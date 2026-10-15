"""
TenderRadar: CPPP collector (Central Public Procurement Portal, eprocure.gov.in).

CPPP is the Government of India's national tender portal (Ministry of Finance
and NIC). Its public "Latest Active Tenders" list covers the central NIC
e-procurement portals, central PSUs and state portals, newest first, ten
tenders a page, with the e-published date, bid submission closing date,
opening date, title, reference, tender ID and organisation. No captcha is
needed to read it; its search forms do use one and are never touched.

Two ways to read it:
  incremental  newest pages until tenders older than the last run's newest
               (every scrape run, a few minutes)
  sweep        every page (nightly, about an hour); this is the daily
               re-verification, and tenders no longer listed are withdrawn

Requests are plain HTTP, paced, with a few workers at most. Material is
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
_TOTAL = re.compile(r"Total\s+Tenders\s*:\s*([\d,]+)", re.I)
_DT_FORMATS = ("%d-%b-%Y %I:%M %p", "%d-%b-%Y %H:%M", "%d-%b-%Y")
_CTX = ssl.create_default_context()


class SourceUnavailable(RuntimeError):
    """CPPP could not be read (down, blocked or changed)."""


@dataclass
class Row:
    tender_id: str
    title: str
    ref: str
    organisation: str
    published: str        # YYYY-MM-DD
    closing: str          # YYYY-MM-DD
    corrigendum: bool


@dataclass
class CrawlResult:
    tenders: list[Tender] = field(default_factory=list)
    listed_ids: set[str] = field(default_factory=set)     # every candidate ID seen this run
    seen_rows: int = 0
    pages: int = 0
    unparsed: int = 0
    closed_on_arrival: int = 0
    closed_ids: set[str] = field(default_factory=set)
    backlog: int = 0
    blocked: int = 0
    complete_sweep: bool = False
    newest_published: str = ""


def page_url(n: int) -> str:
    if n <= 1:
        return LIST
    target = f"{LIST}?page={n}".encode()
    return LIST + "?url=" + urllib.parse.quote(base64.b64encode(target).decode(), safe="")


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _date(s: str) -> str:
    s = _text(s)
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
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
        published, closing = _date(cells[1]), _date(cells[2])
        if not (published and closing):
            continue
        text = _text(cells[4])
        ref = tid = ""
        m = _HREF.search(cells[4])
        if m:
            parts = _link_parts(html.unescape(m.group(1)))
            if len(parts) >= 2:
                ref, tid = parts[-2].strip(), parts[-1].strip()
        if not tid:
            tid = text.rsplit("/", 1)[-1].strip()
        title = text
        for tail in (f"/{ref}/{tid}" if ref else None, f"/{tid}"):
            if tail and title.endswith(tail):
                title = title[: -len(tail)]
                break
        title = title.strip(" ./")
        if not tid or len(title) < 8:
            continue
        rows.append(Row(tender_id=tid, title=title, ref=ref, organisation=_text(cells[5]),
                        published=published, closing=closing,
                        corrigendum=len(cells) > 6 and _text(cells[6]) not in ("", "--", "-")))
    return rows


def total_tenders(page_html: str) -> int:
    m = _TOTAL.search(_text(page_html))
    return int(m.group(1).replace(",", "")) if m else 0


def fetch(url: str, attempts: int = 3) -> str:
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-IN,en"})
            with urllib.request.urlopen(req, timeout=60, context=_CTX) as r:
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


def tender_id(tid: str) -> str:
    return f"cppp-{tid}"


def to_tender(r: Row, now: str) -> Tender:
    return Tender(
        id=tender_id(r.tender_id), ref_no=r.tender_id, url=LOOKUP, title=r.title,
        source=SOURCE, portal=SOURCE, authority=r.organisation,
        category=categorise(r.title), published=r.published, deadline=r.closing,
        deadline_source="stated", first_seen=now, last_seen=now, verified_at=now,
    )


def _collect(res: CrawlResult, rows: list[Row], today: str, now: str) -> None:
    for r in rows:
        res.seen_rows += 1
        res.newest_published = max(res.newest_published, r.published)
        if not is_candidate(r.title):
            continue
        tid = tender_id(r.tender_id)
        res.listed_ids.add(tid)
        if r.closing < today:
            res.closed_on_arrival += 1
            res.closed_ids.add(tid)
            continue
        res.tenders.append(to_tender(r, now))


def crawl(mode: str, since_published: str = "", max_pages: int = 80, workers: int = 3,
          budget_min: int = 150, pause: float = 1.0) -> CrawlResult:
    """Read CPPP. `since_published` is the newest e-published date seen by the last run."""
    from dates import today_ist

    res, today, now = CrawlResult(), today_ist().isoformat(), iso_now()
    first = fetch(LIST)
    res.pages = 1
    total = total_tenders(first)
    rows = parse_list(first)
    if not rows:
        raise SourceUnavailable("CPPP's tender list could not be read; its page layout may have changed")
    _collect(res, rows, today, now)
    last_page = max(1, -(-total // 10)) if total else 1
    log.info("CPPP lists %d active tenders (%d pages); mode %s", total, last_page, mode)
    started = time.monotonic()

    if mode == "sweep":
        pages = list(range(2, last_page + 1))

        def get(n: int):
            if time.monotonic() - started > budget_min * 60:
                return n, None
            time.sleep(pause)
            try:
                return n, parse_list(fetch(page_url(n)))
            except SourceUnavailable as e:
                log.warning("Page %d failed: %s", n, e)
                return n, []

        failed = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i, (n, got) in enumerate(pool.map(get, pages), 2):
                if got is None:
                    res.backlog += 1
                    continue
                res.pages += 1
                if not got:
                    failed += 1
                    res.unparsed += 1
                _collect(res, got, today, now)
                if i % 250 == 0:
                    log.info("  %d / %d pages, %d candidate tenders so far", i, last_page, len(res.listed_ids))
        res.complete_sweep = res.backlog == 0 and failed <= max(3, last_page // 200)
    else:
        for n in range(2, min(last_page, max_pages) + 1):
            time.sleep(pause)
            got = parse_list(fetch(page_url(n)))
            res.pages += 1
            if not got:
                res.unparsed += 1
                continue
            _collect(res, got, today, now)
            # Newest first: stop a page after reaching what the last run already read
            if since_published and max(r.published for r in got) < since_published:
                break
        else:
            if last_page > max_pages:
                log.info("Read %d newest pages (cap); older pages are covered by the nightly sweep", max_pages)

    log.info("CPPP: %d pages, %d rows, %d candidates (%d open, %d closed), %d unreadable, sweep complete: %s",
             res.pages, res.seen_rows, len(res.listed_ids), len(res.tenders), res.closed_on_arrival,
             res.unparsed, res.complete_sweep)
    if res.pages > 3 and res.seen_rows == 0:
        raise SourceUnavailable("Read CPPP pages but found no tenders; its page layout may have changed")
    return res
