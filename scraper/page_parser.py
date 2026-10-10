"""
TenderRadar: TenderDetail.com page parser.

Pure functions over a detail page's visible text (document.body.innerText),
so they can be tested without a browser. Handles both page layouts:

  before July 2026   "TDR : 55145448 / Tender Notice / 3 Days Left / Jaipur , Rajasthan /
                      Tender Brief : <title> / … Submission Date …"
  since July 2026    "Closing in 13 days / TDR #57185957 / <title> /
                      Issued by <authority> · <city>, <state>"
"""
import re
from datetime import date, timedelta

from dates import parse_date, plausible, to_str, today_ist

STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa",
    "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala",
    "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland",
    "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
    "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman And Nicobar Islands", "Chandigarh", "Dadra And Nagar Haveli And Daman And Diu",
    "Delhi", "Jammu And Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]
_STATE_ALIASES = {"new delhi": "Delhi", "orissa": "Odisha", "pondicherry": "Puducherry",
                  "jammu & kashmir": "Jammu And Kashmir", "uttaranchal": "Uttarakhand"}
_STATE_LOOKUP = {s.lower(): s for s in STATES} | _STATE_ALIASES

# ── Title ─────────────────────────────────────────────────────────────
_TITLE_PATTERNS = [
    # Old layout: "Tender Brief : [Corrigendum :] <title>"
    re.compile(r"Tender Brief\s*[:\-]\s*(?:Corrigendum\s*[:\-]\s*)?([A-Za-z][^\n]{20,400})", re.I),
    re.compile(r"(?:Subject|Title|Brief)\s*[:\-]\s*([A-Za-z][^\n]{20,400})", re.I),
    # New layout: the title is the line right after "TDR #<id>"
    re.compile(r"TDR\s*[#:]\s*\d+\s*\n\s*([A-Za-z][^\n]{20,400})", re.I),
]

# ── Dates ─────────────────────────────────────────────────────────────
_COUNTDOWN = re.compile(
    r"Closing (?:in (\d+) days?|(today)|(tomorrow))|\b(\d+) Days? Left\b|\b(Last Day)\b", re.I)
_CLOSED = re.compile(r"^\s*(?:Expired|Closed|Tender Closed)\s*$", re.I | re.M)
_DEADLINE_LABEL = re.compile(
    r"(?:Bid\s+)?Submission\s+(?:End\s+|Last\s+|Closing\s+)?Date"
    r"|Last\s+Date(?:\s+(?:of|for))?(?:\s+Bid)?(?:\s+Submission)?"
    r"|Bid\s+(?:End|Closing)\s+Date|Closing\s+Date|Due\s+Date", re.I)
_PUBLISHED_LABEL = re.compile(
    r"Publish(?:ed|ing)?(?:\s+(?:Date|On))?|Posted\s+On|Release\s+Date|Tender\s+Date", re.I)

# ── Money ─────────────────────────────────────────────────────────────
_AMOUNT = r"(?:₹|Rs\.?|INR)?[ \t]*\n?[ \t]*(?:₹|Rs\.?|INR)?[ \t]*([\d,]+(?:\.\d+)?)[ \t]*(?:/-)?[ \t]*(crores?|cr\b\.?|lakhs?|lacs?|lakh)?"
_VALUE = re.compile(
    r"(?:Tender\s+Value|Estimated\s+(?:Cost|Value)|Contract\s+Value|Project\s+Cost)\s*[:\-]?[ \t]*" + _AMOUNT, re.I)
_EMD = re.compile(r"\bEMD\b(?:\s+Amount)?\s*[:\-]?[ \t]*" + _AMOUNT, re.I)

# ── Where ─────────────────────────────────────────────────────────────
_ISSUED_BY = re.compile(r"Issued by\s+([^\n·]+?)\s*·\s*([^\n]+)", re.I)
_OLD_LOCATION = re.compile(r"View Tendering Authority\.?\s*\n\s*([^\n]{3,80})", re.I)
# TenderDetail's "Issued by" often names a sector, not the buyer
_SECTOR_LABEL = re.compile(
    r"^(?:government departments?|statutory bodies|boards?\s*/\s*undertakings|cooperatives?|local bodies"
    r"|private organi[sz]ations?|autonomous bodies|central government|state government|public sector"
    r"|banks?\b|educational institutions?|research institutes?)", re.I)


def is_sector_label(s: str) -> bool:
    return bool(_SECTOR_LABEL.match((s or "").strip()))


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip(" .,-:")


def parse_title(text: str) -> str:
    for rx in _TITLE_PATTERNS:
        m = rx.search(text)
        if m:
            t = _clean(m.group(1))
            if len(t) > 15:
                return t[:300]
    return ""


def _labelled_date(text: str, label: re.Pattern) -> date | None:
    """Date within the 40 characters after the first label that has one."""
    for m in label.finditer(text):
        d = parse_date(text[m.end():m.end() + 40])
        if d and plausible(d):
            return d
    return None


def parse_dates(text: str, today: date | None = None) -> dict:
    """
    {"deadline", "published", "closed"}: deadline/published are "YYYY-MM-DD" or "".

    A labelled date ("Submission Date 15-10-2026") is exact, so it wins, unless
    the page also shows a live countdown and the labelled date is already past.
    That combination appeared on the July 2026 layout, where the label picked up
    an unrelated date; the countdown ("Closing in 13 days") is right there.
    """
    today = today or today_ist()
    labelled = _labelled_date(text, _DEADLINE_LABEL)
    published = _labelled_date(text, _PUBLISHED_LABEL)

    countdown = None
    m = _COUNTDOWN.search(text)
    if m:
        n_in, is_today, is_tomorrow, n_left, last_day = m.groups()
        days = int(n_in or n_left) if (n_in or n_left) else (1 if is_tomorrow else 0)
        countdown = today + timedelta(days=days)

    if labelled and (countdown is None or labelled >= today):
        deadline = labelled
    else:
        deadline = countdown

    if published and deadline and published > deadline:
        published = None  # mis-read; a tender can't close before it's published

    closed = bool(_CLOSED.search(text)) and countdown is None
    if deadline and deadline < today:
        closed = True
    return {"deadline": to_str(deadline), "published": to_str(published), "closed": closed}


def to_inr(amount: str, unit: str | None) -> float | None:
    try:
        n = float(amount.replace(",", ""))
    except ValueError:
        return None
    u = (unit or "").lower()
    if u.startswith("cr"):
        n *= 1e7
    elif u.startswith(("lakh", "lac")):
        n *= 1e5
    return round(n) if n >= 1000 else None  # smaller numbers are mis-reads


def parse_money(text: str) -> dict:
    out = {"value_inr": None, "emd_inr": None}
    for key, rx in (("value_inr", _VALUE), ("emd_inr", _EMD)):
        m = rx.search(text)
        if m:
            out[key] = to_inr(m.group(1), m.group(2))
    return out


def split_location(loc: str) -> tuple[str, str]:
    """('Gorakhpur, Uttar Pradesh', 'Uttar Pradesh') from messy text like ' Gorakhpur , Uttar Pradesh'."""
    parts = [p.strip() for p in re.split(r"\s*,\s*", _clean(loc)) if p.strip()]
    parts = [p.title() if p.islower() else p for p in parts]          # "jalandhar" to "Jalandhar"
    seen: set[str] = set()
    parts = [p for p in parts if not (p.lower() in seen or seen.add(p.lower()))]  # "Delhi, Delhi" to "Delhi"
    state = ""
    for p in reversed(parts):
        state = _STATE_LOOKUP.get(p.lower(), "")
        if state:
            break
    return ", ".join(parts), state


def parse_where(text: str) -> dict:
    out = {"authority": "", "location": "", "state": ""}
    m = _ISSUED_BY.search(text)
    if m:
        name = _clean(m.group(1))
        out["authority"] = "" if is_sector_label(name) else name
        out["location"], out["state"] = split_location(m.group(2))
    else:
        m = _OLD_LOCATION.search(text)
        if m:
            out["location"], out["state"] = split_location(m.group(1))
    return out


def detect_portal(text: str) -> str:
    """Only claims a portal when the page says so. (The old check matched "GEM" inside "MANAGEMENT".)"""
    if re.search(r"\bGeM\b|gem\.gov\.in|\bGEM/\d{4}/|Custom Bid For Services", text):
        return "GeM"
    if re.search(r"\bCPPP\b|eprocure\.gov\.in", text):
        return "CPPP"
    return ""


def parse_detail(text: str, today: date | None = None) -> dict:
    """Every field we can read from a detail page. Missing values are "" / None."""
    if not text or len(text) < 80:
        return {}
    return {
        "title": parse_title(text),
        "portal": detect_portal(text),
        **parse_where(text),
        **parse_dates(text, today),
        **parse_money(text),
    }


def ref_from_url(url: str) -> str:
    m = re.search(r"/TenderNotice/(\d+)", url or "")
    return m.group(1) if m else ""
