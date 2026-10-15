"""
TenderRadar: CPPP collector (Central Public Procurement Portal, eprocure.gov.in).

CPPP is the Government of India's national tender portal (Ministry of Finance
and NIC). Its public "Latest Active Tenders" list covers the central NIC
e-procurement portals, central PSUs and state portals, newest first, ten
tenders a page, with the e-published date, bid submission closing date,
opening date, title, reference, tender ID and organisation. No captcha is
needed to read it; its search forms do use one and are never touched.

Each run reads the newest pages (back to what the last run saw), then the
next third of the list, so every listing is re-read every 12 hours at the
4-hourly schedule. A tender is re-verified each time its row is read; one the
portal stops listing (closed, withdrawn or cancelled) is no longer re-verified
and drops off the website once its last check is 36 hours old.

Requests are plain HTTP, paced, with three workers at most. Material is
shown with the source acknowledged, per the portal's copyright policy.
"""
import base64
import html
import logging
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

from config import USER_AGENT
from dates import iso_now
from models import Tender
from page_parser import is_bot_check
from relevance import categorise, is_candidate

log = logging.getLogger("CPPP")

BASE = "https://eprocure.gov.in/cppp/"
LIST = BASE + "latestactivetendersnew/cpppdata"
LOOKUP = LIST                     # where people can look a tender up by its Tender ID
SOURCE = "CPPP"

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_HREF = re.compile(r'href="([^"]*tendersfullview/[^"]+)"', re.I)
_ANCHOR = re.compile(r"<a\b[^>]*>(.*?)</a>", re.S | re.I)
_TOTAL = re.compile(r"Total\s+(?:Tenders|Bid\(s\)|Bids)\s*:\s*([\d,]+)", re.I)
_DT_FORMATS = ("%d-%b-%Y %I:%M %p", "%d-%b-%Y %H:%M", "%d-%b-%Y")
_CTX = ssl.create_default_context()


class SourceUnavailable(RuntimeError):
    """CPPP could not be read (down, blocked or changed)."""


@dataclass
class Row:
    key: str              # CPPP's own number for the listing (first link segment); stable and unique
    tender_id: str        # the Tender ID people search for on the portal
    title: str
    ref: str
    organisation: str
    published: str        # YYYY-MM-DDTHH:MM, IST
    closing: str          # YYYY-MM-DDTHH:MM, IST
    corrigendum: bool


@dataclass
class CrawlResult:
    tenders: list[Tender] = field(default_factory=list)
    listed_ids: set[str] = field(default_factory=set)     # every candidate seen this run
    seen_rows: int = 0
    pages: int = 0
    last_page: int = 0
    unparsed: int = 0
    closed_on_arrival: int = 0
    closed_ids: set[str] = field(default_factory=set)
    backlog: int = 0                                       # pages left for the next run
    next_cursor: int = 0
    newest_published: str = ""                             # YYYY-MM-DDTHH:MM, IST


def page_url(n: int, base: str = LIST) -> str:
    """CPPP pages its lists with the target URL base64-encoded in ?url= (?page=1 is the first page)."""
    if n <= 1:
        return base
    target = f"{base}?page={n}".encode()
    return base + "?url=" + urllib.parse.quote(base64.b64encode(target).decode(), safe="")


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _when(s: str) -> str:
    """"15-Oct-2026 10:49 AM" as "2026-10-15T10:49" (IST), or ""."""
    s = _text(s)
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            continue
    return ""


def _link_parts(href: str) -> list[str]:
    """The detail link carries base64 segments joined by 'A13h1'; the last two are ref and tender ID."""
    seg = href.rsplit("/", 1)[-1]
    out = []
    for part in seg.split("A13h1"):
        try:
            out.append(base64.b64decode(part + "=" * (-len(part) % 4)).decode("utf-8", "replace"))
        except Exception:
            out.append("")
    return out


def parse_list(page_html: str) -> list[Row]:
    rows = []
    for tr in _ROW.findall(page_html):
        cells = _CELL.findall(tr)
        if len(cells) < 6:
            continue
        published, closing = _when(cells[1]), _when(cells[2])
        if not (published and closing):
            continue
        m = _HREF.search(cells[4])
        if not m:
            continue
        parts = _link_parts(html.unescape(m.group(1)))
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        key, ref, tid = parts[0], parts[-2].strip(), parts[-1].strip()
        a = _ANCHOR.search(cells[4])
        title = _text(a.group(1)) if a else ""
        if not title:
            title = _text(cells[4])
            for tail in (f"/{ref}/{tid}", f"/{tid}"):
                if title.endswith(tail):
                    title = title[: -len(tail)]
                    break
        title = title.strip(" ./")
        # Some portals list only the reference number, with no title to screen
        if not tid or len(title) < 8 or title == ref:
            continue
        rows.append(Row(key=key, tender_id=tid, title=title, ref=ref, organisation=_text(cells[5]),
                        published=published, closing=closing,
                        corrigendum=len(cells) > 6 and _text(cells[6]) not in ("", "--", "-")))
    return rows


_GEM_BID = re.compile(r"(GEM/\d{4}/[A-Z]/(\d+))")


def parse_gem(page_html: str) -> list[Row]:
    """CPPP's copy of the GeM bid list: start, end, bid number, item or service, organisation, department."""
    rows = []
    for tr in _ROW.findall(page_html):
        cells = _CELL.findall(tr)
        if len(cells) < 6:
            continue
        published, closing = _when(cells[1]), _when(cells[2])
        m = _GEM_BID.search(_text(cells[3]))
        title = _text(cells[4])
        if not (published and closing and m) or len(title) < 8:
            continue
        org = ", ".join(x for x in (_text(cells[5]), _text(cells[6]) if len(cells) > 6 else "") if x)
        rows.append(Row(key="gem-" + m.group(2), tender_id=m.group(1), title=title, ref=m.group(1),
                        organisation=org, published=published, closing=closing, corrigendum=False))
    return rows


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    parse: object
    portal: str
    lookup: str              # where people find the tender by its ID
    newest_first: bool       # sorted by publish time, so new tenders are on the first pages
    budget_min: float        # time allowed per run


FEEDS = {
    "cppp": Feed("CPPP tenders", LIST, parse_list, "CPPP", LOOKUP, True, 35),
    # GeM bids as republished on CPPP (sorted by closing date, so read in full over the cycle)
    "gem": Feed("GeM bids", BASE + "gemtender", parse_gem, "GeM", "https://bidplus.gem.gov.in/all-bids", False, 60),
}


def total_tenders(page_html: str) -> int:
    m = _TOTAL.search(_text(page_html))
    return int(m.group(1).replace(",", "")) if m else 0


def fetch(url: str, attempts: int = 3) -> str:
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-IN,en"})
            with urllib.request.urlopen(req, timeout=90, context=_CTX) as r:
                body = r.read().decode("utf-8", "replace")
            if is_bot_check(_text(body[:20000])):
                raise SourceUnavailable("CPPP answered with a bot-protection check")
            return body
        except SourceUnavailable:
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = e
            time.sleep(4 * (i + 1))
    raise SourceUnavailable(f"CPPP could not be read: {last}")


def tender_id(key: str) -> str:
    return f"cppp-{key}"


def to_tender(r: Row, now: str, feed: Feed | None = None) -> Tender:
    feed = feed or FEEDS["cppp"]
    return Tender(
        id=tender_id(r.key), ref_no=r.tender_id, url=feed.lookup, title=r.title,
        source=SOURCE, portal=feed.portal, authority=r.organisation,
        category=categorise(r.title), published=r.published[:10], deadline=r.closing[:10],
        deadline_source="stated", first_seen=now, last_seen=now, verified_at=now,
    )


def _collect(res: CrawlResult, rows: list[Row], today: str, now: str, feed: Feed | None = None) -> None:
    for r in rows:
        res.seen_rows += 1
        res.newest_published = max(res.newest_published, r.published)
        if not is_candidate(r.title):
            continue
        tid = tender_id(r.key)
        res.listed_ids.add(tid)
        if r.closing[:10] < today:
            res.closed_on_arrival += 1
            res.closed_ids.add(tid)
            continue
        res.tenders.append(to_tender(r, now, feed))


def plan(last_page: int, newest_end: int, cursor: int, chunk: int, full: bool) -> list[int]:
    """
    Pages to read after the newest ones: the next slice of the list, starting a
    little before where the last run stopped (rows shift between runs as tenders
    are added and closed), wrapping to the start at the end. `full` reads the rest.
    """
    first = newest_end + 1
    if first > last_page:
        return []
    if full:
        return list(range(first, last_page + 1))
    start = max(first, cursor - OVERLAP_PAGES)
    if start > last_page:
        start = first
    return list(range(start, min(last_page, start + chunk - 1) + 1))


OVERLAP_PAGES = 40
MAX_NEWEST_PAGES = 200


def crawl(feed: Feed | str = "cppp", since_published: str = "", cursor: int = 0, cycle_runs: int = 6,
          full: bool = False, workers: int = 3, budget_min: float | None = None,
          pause: float = 0.5) -> CrawlResult:
    """
    One run over one list: for a newest-first list, the newest pages back to
    `since_published` (the newest e-published time the last run saw); then the
    next 1/cycle_runs of the list from `cursor`, so every listing is re-read
    every `cycle_runs` runs. `full` reads the rest of the list, time allowing.
    """
    from dates import today_ist

    feed = FEEDS[feed] if isinstance(feed, str) else feed
    budget = budget_min if budget_min is not None else feed.budget_min
    res, today, now = CrawlResult(), today_ist().isoformat(), iso_now()
    started = time.monotonic()
    first = fetch(feed.url)
    res.pages = 1
    total = total_tenders(first)
    rows = feed.parse(first)
    if not rows:
        raise SourceUnavailable(f"The {feed.name} list could not be read; its page layout may have changed")
    _collect(res, rows, today, now, feed)
    res.last_page = last_page = max(1, -(-total // 10)) if total else 1
    log.info("%s: %d listed (%d pages)", feed.name, total, last_page)

    # Newest first, until a page holds only tenders the last run already saw
    n = 1
    while feed.newest_first and since_published and n < min(last_page, MAX_NEWEST_PAGES) and \
            max(r.published for r in rows) >= since_published:
        n += 1
        time.sleep(pause)
        rows = feed.parse(fetch(page_url(n, feed.url)))
        res.pages += 1
        if not rows:
            res.unparsed += 1
            break
        _collect(res, rows, today, now, feed)
    newest_end = n

    chunk = -(-last_page // max(1, cycle_runs)) + OVERLAP_PAGES
    todo = plan(last_page, newest_end, cursor, chunk, full)
    log.info("%s: newest %d pages; re-reading pages %s to %s", feed.name, newest_end,
             todo[0] if todo else "-", todo[-1] if todo else "-")

    def get(p: int):
        if time.monotonic() - started > budget * 60:
            return p, None
        time.sleep(pause)
        try:
            return p, feed.parse(fetch(page_url(p, feed.url)))
        except SourceUnavailable as e:
            log.warning("%s page %d failed: %s", feed.name, p, e)
            return p, []

    unread = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (p, got) in enumerate(pool.map(get, todo), 1):
            if got is None:
                unread.append(p)
                continue
            res.pages += 1
            if not got:
                res.unparsed += 1
            _collect(res, got, today, now, feed)
            if i % 100 == 0:
                log.info("  %d / %d pages, %d candidates so far", i, len(todo), len(res.listed_ids))
    res.backlog = len(unread)
    if unread:
        res.next_cursor = unread[0]
    elif todo and todo[-1] < last_page:
        res.next_cursor = todo[-1] + 1
    else:
        res.next_cursor = 0                     # wrapped: the next run starts again from the top

    log.info("%s: %d pages, %d rows, %d candidates (%d open, %d closed), %d unreadable, %d left",
             feed.name, res.pages, res.seen_rows, len(res.listed_ids), len(res.tenders),
             res.closed_on_arrival, res.unparsed, res.backlog)
    if res.pages > 5 and res.unparsed > res.pages // 2:
        raise SourceUnavailable(f"The {feed.name} list returned {res.unparsed} of {res.pages} pages without "
                                f"readable rows; CPPP may be down or its layout may have changed")
    return res
