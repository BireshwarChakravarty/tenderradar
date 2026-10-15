"""
TenderRadar: publish gate.

The scraper keeps everything it knows in data/store.json. Only tenders that
pass every check below are written to docs/data/tenders.json, the file the
website, alerts and digest read. Anything that fails is held back with a
reason in data/quality.json, never shown.

A tender is published only when:
  - the source states a closing date, and it is today or later (IST)
  - the closing date is within a year (anything later is a mis-read)
  - it was published in 2026 or later, when the source states a publish date
  - its page was re-read from the source within MAX_VERIFY_AGE_HOURS
  - its link and reference number point to the same TenderDetail notice
  - the AI has assessed it and judged it relevant: not goods, works or an
    auction, and a fit score of 3 or more

Some values are corrected rather than blocked: a publish date in the future,
or after the closing date, is cleared; money values that contradict each
other are cleared; AI text that mentions private names or internal process
is wiped so the tender is re-scored.
"""
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dates import from_str, today_ist
from models import Tender

MIN_PUBLISHED = date(2026, 1, 1)
# Normally 36. Raised temporarily with the MAX_VERIFY_AGE_HOURS variable in
# scrape.yml when the source can't be re-read; closing dates are still enforced.
MAX_VERIFY_AGE_HOURS = int(os.getenv("MAX_VERIFY_AGE_HOURS") or 36)
MAX_DAYS_AHEAD = 365

_URL = re.compile(r"^https://www\.tenderdetail\.com/[^ ]*TenderNotice/(\d+)")
_BANNED = re.compile(r"bid tracker|bid pipeline|in the pipeline|already bid|internal tracker|"
                     r"company_knowledge|private notes", re.I)
# Acronyms and abbreviations that are fine anywhere
_COMMON = {
    "AI", "AEO", "APAC", "BCC", "BOC", "CA", "CBC", "CMS", "CSR", "CTC", "CV", "CVs", "DAVP", "EMD",
    "EOI", "GA4", "GEO", "GeM", "GIGW", "GST", "HQ", "IEC", "INR", "IT", "LLP", "MSE", "MSME", "NIT",
    "OBD", "OK", "ORM", "OSINT", "PR", "PSU", "PSUs", "QCBS", "QR", "RFP", "SEO", "SMM", "SMS", "TOR",
    "UI", "URL", "USD", "UX", "CPPP",
}
_TOKEN = re.compile(r"\b[A-Za-z]*[A-Z][A-Za-z]*[A-Z][A-Za-z0-9]*\b")


def _private_terms() -> set[str]:
    """Acronyms from the private notes (client and bid names) that the public guide doesn't use."""
    private = os.getenv("COMPANY_KNOWLEDGE", "")
    if not private:
        return set()
    guide = Path(__file__).resolve().parent / "knowledge" / "profile.md"
    public = set(_TOKEN.findall(guide.read_text(encoding="utf-8"))) if guide.exists() else set()
    return {w for w in _TOKEN.findall(private) if 2 <= len(w) <= 10} - public - _COMMON


PRIVATE_TERMS = _private_terms()


def _hours_since(ts: str) -> float | None:
    try:
        then = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600


def fix_fields(t: Tender, today: date) -> list[str]:
    """Clear values that can't be right. Returns what was changed."""
    fixed = []
    pub, dl = from_str(t.published), from_str(t.deadline)
    if pub and (pub > today or (dl and pub > dl)):
        t.published = ""
        fixed.append("publish date cleared (after today or after closing)")
    if t.value_inr is not None and not (1_000 <= t.value_inr <= 1e11):
        t.value_inr = None
        fixed.append("value cleared (out of range)")
    if t.emd_inr is not None and (t.emd_inr < 100 or (t.value_inr and t.emd_inr > t.value_inr)):
        t.emd_inr = None
        fixed.append("EMD cleared (out of range or above the value)")
    return fixed


def ai_problem(t: Tender) -> str:
    """Why the AI text can't be published, or ""."""
    text = " ".join((t.headline, t.fit, t.reason, t.eligibility))
    if not text.strip():
        return ""
    if "\u2014" in text:  # em dash (house style: none anywhere)
        return "em dash"
    if _BANNED.search(text):
        return "mentions internal process"
    own = " ".join((t.title, t.authority, t.location))
    for w in PRIVATE_TERMS:
        if re.search(rf"\b{re.escape(w)}\b", text) and not re.search(rf"\b{re.escape(w)}\b", own, re.I):
            return f"mentions a private name ({w})"
    return ""


def reset_assessment(t: Tender) -> None:
    t.headline = t.fit = t.reason = t.eligibility = t.recommendation = t.kind = ""
    t.score = None
    t.scored_at = ""
    t.scoring_version = 0


def blockers(t: Tender, today: date) -> list[str]:
    """Reasons this tender can't be published. Empty means it can."""
    out = []
    dl = from_str(t.deadline)
    if not dl:
        out.append("no closing date stated")
    elif dl < today:
        out.append("closed")
    elif dl > today + timedelta(days=MAX_DAYS_AHEAD):
        out.append("closing date more than a year away")
    pub = from_str(t.published)
    if pub and pub < MIN_PUBLISHED:
        out.append("published before 2026")
    age = _hours_since(t.verified_at)
    if age is None:
        out.append("never verified against the source")
    elif age > MAX_VERIFY_AGE_HOURS:
        out.append(f"not re-verified for {age:.0f} hours")
    m = _URL.match(t.url or "")
    if not m or f"td-{m.group(1)}" != t.id or m.group(1) != t.ref_no:
        out.append("source link doesn't match the reference")
    if len((t.title or "").strip()) < 15:
        out.append("title missing")
    return out


NOT_RELEVANT_KINDS = ("goods", "works", "auction")
MIN_PUBLISHED_SCORE = 3.0


def relevance_blockers(t: Tender) -> list[str]:
    """The site lists only tenders the AI has judged relevant to the company."""
    if t.score is None:
        return ["not yet assessed"]
    if t.kind in NOT_RELEVANT_KINDS:
        return ["not relevant (goods, works or auction)"]
    if t.score < MIN_PUBLISHED_SCORE:
        return ["not relevant (fit under 3)"]
    return []


def publish_blockers(t: Tender, today: date) -> list[str]:
    """Everything that keeps a tender off the site: source checks, then relevance."""
    return blockers(t, today) + relevance_blockers(t)


def gate(store: dict[str, Tender], today: date | None = None) -> tuple[list[Tender], dict]:
    """(publishable tenders, quality report). Fixes fields in place."""
    today = today or today_ist()
    published, held, fixes, ai_resets = [], [], [], []
    for t in store.values():
        for f in fix_fields(t, today):
            fixes.append({"id": t.id, "fix": f})
        problem = ai_problem(t)
        if problem:
            reset_assessment(t)
            ai_resets.append({"id": t.id, "problem": problem})
        reasons = publish_blockers(t, today)
        if reasons:
            held.append({"id": t.id, "title": t.title[:120], "deadline": t.deadline, "reasons": reasons})
        else:
            published.append(t)
    counts: dict[str, int] = {}
    for h in held:
        for r in h["reasons"]:
            key = "not re-verified recently" if r.startswith("not re-verified") else r
            counts[key] = counts.get(key, 0) + 1
    report = {"published": len(published), "held_back": len(held), "held_reasons": counts,
              "fields_fixed": len(fixes), "ai_text_reset": len(ai_resets),
              "held": held, "fixes": fixes, "ai_resets": ai_resets}
    return published, report
