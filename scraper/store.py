"""
TenderRadar: the tender store (docs/data/tenders.json).

Keeps one record per TenderDetail notice and applies the house rules:
  - a tender already closed when first found is never stored
  - titles that match the exclusion rules are never stored
  - closed tenders are kept for KEEP_CLOSED_DAYS so recent history stays visible
  - a tender with no stated deadline is dropped once it hasn't been seen
    on the site for STALE_DAYS

Reads the original (v1) file format too and converts it on load.
"""
import json
import logging
import re
from datetime import timedelta

from config import (ALERT_LOG_FILE, KEEP_CLOSED_DAYS, MIN_RELEVANCE_SCORE, REJECTED_FILE, STALE_DAYS,
                    TENDERS_FILE)
from dates import from_str, iso_now, plausible, today_ist
from models import SCHEMA_VERSION, Tender, plain, tender_id
from page_parser import detect_portal, is_sector_label, parse_where, ref_from_url, split_location
from relevance import categorise, exclusion_reason

log = logging.getLogger("Store")


# ── Load / save ───────────────────────────────────────────────────────

def load() -> tuple[dict[str, Tender], dict]:
    """({id: Tender}, meta). Converts v1 files transparently."""
    if not TENDERS_FILE.exists():
        return {}, {}
    try:
        data = json.loads(TENDERS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.error("Could not read %s: %s", TENDERS_FILE, e)
        raise
    meta = data.get("meta", {})
    rows = data.get("tenders", [])
    if meta.get("schema", 1) < 2:
        return _from_v1(rows), {}
    store = {r["id"]: Tender.from_dict(r) for r in rows if r.get("id")}
    for t in store.values():
        if is_sector_label(t.authority):
            t.authority = ""  # stored before sector labels were recognised
        if t.location:
            t.location = split_location(t.location)[0]
        for f in ("title", "headline", "authority", "fit", "reason", "eligibility"):
            setattr(t, f, plain(getattr(t, f)))
    return store, meta


def save(tenders: dict[str, Tender], run: dict | None = None) -> None:
    today = today_ist()
    rows = sorted(tenders.values(), key=lambda t: (t.first_seen, t.id), reverse=True)
    open_n = sum(1 for t in rows if not t.deadline or from_str(t.deadline) >= today)
    meta = {
        "schema": SCHEMA_VERSION,
        "last_updated": iso_now(),
        "total": len(rows),
        "open": open_n,
        "min_score": MIN_RELEVANCE_SCORE,   # the dashboard's "Recommended" threshold
        "keep_closed_days": KEEP_CLOSED_DAYS,
    }
    if run:
        meta["last_run"] = run
    TENDERS_FILE.write_text(
        json.dumps({"meta": meta, "tenders": [t.to_dict() for t in rows]},
                   indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    log.info("Saved %d tenders (%d open) to %s", len(rows), open_n, TENDERS_FILE)


# ── Merge a scrape into the store ─────────────────────────────────────

_BOILERPLATE = re.compile(r"\b(?:corrigendum|tender for|tender|bids are invited for|notice inviting|nit)\b|[^a-z0-9 ]", re.I)


def dupe_key(t: Tender) -> str:
    """
    The same tender is often listed several times: the original notice plus each
    corrigendum gets its own TenderDetail number. Same wording + same deadline = same tender.
    """
    words = _BOILERPLATE.sub(" ", t.title.lower()).split()
    return " ".join(words) + "|" + t.deadline


def merge(store: dict[str, Tender], scraped: list[Tender]) -> dict:
    """
    Add new tenders and refresh known ones in place.
    Returns counts plus "new_ids" for the scorer.
    """
    today = today_ist()
    stats = {"new": 0, "updated": 0, "excluded": 0, "closed_on_arrival": 0, "duplicates": 0,
             "new_ids": [], "rejected_ids": []}
    seen = {dupe_key(t) for t in store.values()}
    for t in scraped:
        known = store.get(t.id)
        if known:
            # Refresh what the source may have changed (corrigenda extend deadlines)
            for f in ("deadline", "published", "value_inr", "emd_inr", "authority",
                      "location", "state", "portal"):
                v = getattr(t, f)
                if v not in ("", None):
                    setattr(known, f, v)
            known.last_seen = t.last_seen
            stats["updated"] += 1
            continue
        if exclusion_reason(t.title):
            stats["excluded"] += 1
            stats["rejected_ids"].append(t.id)
            continue
        d = from_str(t.deadline)
        if d and d < today:
            stats["closed_on_arrival"] += 1
            stats["rejected_ids"].append(t.id)
            continue
        if dupe_key(t) in seen:
            stats["duplicates"] += 1
            stats["rejected_ids"].append(t.id)
            continue
        seen.add(dupe_key(t))
        store[t.id] = t
        stats["new"] += 1
        stats["new_ids"].append(t.id)
    return stats


def prune(store: dict[str, Tender]) -> int:
    """Remove long-closed and stale tenders. Returns how many were removed."""
    today = today_ist()
    closed_cutoff = today - timedelta(days=KEEP_CLOSED_DAYS)
    stale_cutoff = (today - timedelta(days=STALE_DAYS)).isoformat()
    doomed = []
    for tid, t in store.items():
        d = from_str(t.deadline)
        if d and d < closed_cutoff:
            doomed.append(tid)
        elif not d and t.last_seen[:10] < stale_cutoff:
            doomed.append(tid)
        elif exclusion_reason(t.title):  # rules may have been tightened since it was stored
            doomed.append(tid)
    # Collapse duplicates already in the store, keeping the first one found. Two keys:
    # the source wording, and the AI headline (catches corrigenda worded differently).
    first: dict[str, str] = {}
    for t in sorted(store.values(), key=lambda t: (t.first_seen, t.id)):
        keys = [dupe_key(t)]
        if t.headline and t.deadline:
            keys.append("h|" + re.sub(r"[^a-z0-9]+", " ", t.headline.lower()).strip() + "|" + t.deadline + "|" + t.state)
        if any(k in first for k in keys) and t.id not in doomed:
            doomed.append(t.id)
        for k in keys:
            first.setdefault(k, t.id)
    for tid in doomed:
        del store[tid]
    return len(doomed)


# ── Rejected notices ──────────────────────────────────────────────────
# {id: date} for notices turned down, so the crawler doesn't fetch them every run.
# Entries expire after 60 days, by which time the tender has closed anyway.

def load_rejected() -> dict[str, str]:
    try:
        return json.loads(REJECTED_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_rejected(rejected: dict[str, str]) -> None:
    cutoff = (today_ist() - timedelta(days=60)).isoformat()
    keep = {k: v for k, v in rejected.items() if v >= cutoff}
    REJECTED_FILE.write_text(json.dumps(dict(sorted(keep.items())), indent=0) + "\n")


# ── Alert log ─────────────────────────────────────────────────────────

def load_alerted() -> set[str]:
    try:
        return set(json.loads(ALERT_LOG_FILE.read_text())["alerted_ids"])
    except (OSError, ValueError, KeyError):
        return set()


def save_alerted(ids: set[str]) -> None:
    ALERT_LOG_FILE.write_text(json.dumps(
        {"alerted_ids": sorted(ids), "updated_at": iso_now()}, indent=1) + "\n")


# ── v1 → v2 conversion ────────────────────────────────────────────────

def _v1_value(s: str) -> float | None:
    m = re.match(r"₹\s*([\d,.]+)\s*(Cr|L)?", s or "")
    if not m:
        return None
    n = float(m.group(1).replace(",", "")) * {"Cr": 1e7, "L": 1e5}.get(m.group(2) or "", 1)
    return round(n) if n >= 1000 else None


def _v1_summary(s: str) -> dict:
    def grab(label):
        m = re.search(rf"\*\*{label}:\*\*\s*(.+?)(?:\n\n|$)", s or "", re.S)
        return m.group(1).strip() if m else ""
    rec = grab("Recommendation").split()[:1]
    return {"fit": grab("Fit"), "reason": grab("Opportunity"),
            "recommendation": rec[0] if rec and rec[0] in ("Bid", "Watch", "Skip") else ""}


def _from_v1(rows: list[dict]) -> dict[str, Tender]:
    """
    Convert the original format. Dates are kept as stored (re-parsing the saved
    page snippet would compute countdowns against today, not the scrape date),
    except implausible ones (e.g. 2018), which become "".
    """
    out: dict[str, Tender] = {}
    dropped = 0
    for r in rows:
        ref = ref_from_url(r.get("url", "")) or r.get("ref_no", "")
        if not ref:
            dropped += 1
            continue
        seen = r.get("scraped_at", "")
        dl = from_str(r.get("deadline", ""))
        if dl and seen and dl < from_str(seen):
            dropped += 1  # was already closed when scraped
            continue
        desc = r.get("description", "")
        t = Tender(
            id=tender_id(ref), ref_no=ref, url=r.get("url", ""), title=r.get("title", ""),
            portal=detect_portal(desc), category=categorise(r.get("title", "")),
            value_inr=_v1_value(r.get("value_str", "")),
            deadline=dl.isoformat() if plausible(dl) else "",
            first_seen=seen, last_seen=seen,
            score=r.get("score") or None,
            scored_at=seen if r.get("score") else "",
            **parse_where(desc), **_v1_summary(r.get("summary", "")),
        )
        if t.id in out and out[t.id].last_seen >= t.last_seen:
            continue  # the same notice stored twice under different titles
        out[t.id] = t
    log.info("Converted v1 store: %d records kept, %d dropped", len(out), dropped)
    return out
