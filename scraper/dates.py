"""
TenderRadar: date handling.

Every date in the store is a plain calendar date ("YYYY-MM-DD") in India
Standard Time, or "" when the source doesn't state one. Nothing here ever
invents a date: a missing deadline stays missing.
"""
import re
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

_MONTHS = {
    m: i for i, names in enumerate(
        [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
         ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
         ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
         ("dec", "december")], start=1)
    for m in names
}

# 14-10-2026, 14/10/26, 14.10.2026. Indian sites are always day-first
_NUMERIC = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b")
# 2026-10-14
_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
# 14 Oct 2026, 14-Oct-2026, 14th October, 2026
_DAY_MONTH = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-/]+([A-Za-z]{3,9})\.?,?[\s\-/]+(\d{2,4})\b")
# October 14, 2026
_MONTH_DAY = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> date:
    return now_ist().date()


def iso_now() -> str:
    """Timestamp for first_seen / last_seen, in UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _year(y: str) -> int:
    n = int(y)
    return 2000 + n if n < 100 else n


def _make(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(text: str) -> date | None:
    """First date found in `text`, or None. Accepts the formats Indian tender sites use."""
    if not text:
        return None
    for rx, order in ((_ISO, "ymd"), (_NUMERIC, "dmy")):
        m = rx.search(text)
        if m:
            a, b, c = m.groups()
            if order == "ymd":
                return _make(int(a), int(b), int(c))
            return _make(_year(c), int(b), int(a))
    m = _DAY_MONTH.search(text)
    if m and m.group(2).lower() in _MONTHS:
        return _make(_year(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
    m = _MONTH_DAY.search(text)
    if m and m.group(1).lower() in _MONTHS:
        return _make(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
    return None


def plausible(d: date | None, today: date | None = None) -> bool:
    """Reject garbage such as 2018 deadlines or dates years in the future."""
    if d is None:
        return False
    today = today or today_ist()
    return today - timedelta(days=3 * 365) <= d <= today + timedelta(days=2 * 365)


def to_str(d: date | None) -> str:
    return d.isoformat() if d else ""


def from_str(s: str) -> date | None:
    try:
        return date.fromisoformat(s[:10]) if s else None
    except ValueError:
        return None


def days_until(deadline: str, today: date | None = None) -> int | None:
    """Whole days from today (IST) to the deadline; 0 = closes today, negative = closed."""
    d = from_str(deadline)
    if d is None:
        return None
    return (d - (today or today_ist())).days


def is_open(deadline: str, today: date | None = None) -> bool | None:
    """True/False, or None when the deadline is unknown. A tender is open through its closing day."""
    n = days_until(deadline, today)
    return None if n is None else n >= 0
