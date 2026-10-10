"""
TenderRadar: TenderDetail.com crawler.

TenderDetail aggregates GeM, CPPP and state portals, which block GitHub's IP
ranges directly. The site renders with JavaScript, so this drives headless
Chromium through Playwright:

  1. Listing pages: one per search keyword, collecting notice URLs.
  2. Detail pages:  new notices first, then known ones closing within
                    REFRESH_DAYS (to pick up extended deadlines), capped at
                    MAX_DETAIL_PAGES per run.

Field extraction lives in page_parser.py so it can be tested without a browser.
"""
import logging
import random
import time
from dataclasses import dataclass, field

from config import MAX_DETAIL_PAGES, REFRESH_DAYS, USER_AGENT
from dates import days_until, iso_now
from models import Tender, tender_id
from page_parser import parse_detail, ref_from_url
from relevance import SEARCH_KEYWORDS, categorise

log = logging.getLogger("TenderDetail")

BASE = "https://www.tenderdetail.com"
NOTICE_LINKS = "a[href*='/TenderNotice/']"


class LayoutChanged(RuntimeError):
    """Pages loaded but nothing could be parsed; the site's HTML has changed."""


@dataclass
class CrawlResult:
    tenders: list[Tender] = field(default_factory=list)
    listed_ids: set[str] = field(default_factory=set)   # every notice seen on a listing page
    pages: int = 0
    unparsed: int = 0
    closed_on_arrival: int = 0
    closed_ids: set[str] = field(default_factory=set)
    backlog: int = 0                                    # new notices left for the next run


def _pause(lo: float, hi: float) -> None:
    time.sleep(random.uniform(lo, hi))


def _collect_listing_urls(page) -> dict[str, str]:
    """{notice_url: keyword} across all search keywords."""
    found: dict[str, str] = {}
    for i, kw in enumerate(SEARCH_KEYWORDS):
        if i:
            _pause(4, 7)
        url = f"{BASE}/Indian-tender/{kw}-tenders"
        try:
            page.goto(url, timeout=35000, wait_until="networkidle")
            _pause(1.5, 2.5)
            links = page.query_selector_all(NOTICE_LINKS)
        except Exception as e:
            log.warning("Listing %-26s failed: %s", kw, e)
            continue
        before = len(found)
        for el in links:
            href = (el.get_attribute("href") or "").split("?")[0].split("#")[0]
            if not ref_from_url(href):
                continue
            full = href if href.startswith("http") else BASE + href
            found.setdefault(full, kw)
        log.info("Listing %-26s %3d links, %3d new", kw, len(links), len(found) - before)
    return found


def _read_page(page, url: str) -> str:
    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        _pause(1.5, 2.5)
        return page.evaluate("() => document.body.innerText || ''")
    except Exception as e:
        log.debug("Detail %s failed: %s", url, e)
        return ""


def crawl(store: dict[str, Tender], rejected: set[str] = frozenset()) -> CrawlResult:
    """`rejected`: ids already turned down (excluded, duplicate, closed), never fetched again."""
    from playwright.sync_api import sync_playwright

    res = CrawlResult()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        page = browser.new_context(
            user_agent=USER_AGENT, viewport={"width": 1280, "height": 800}, locale="en-IN",
        ).new_page()

        try:
            page.goto(BASE, timeout=25000, wait_until="domcontentloaded")
            _pause(3, 5)
        except Exception as e:
            log.warning("Warm-up failed (continuing): %s", e)

        listed = _collect_listing_urls(page)
        res.listed_ids = {tender_id(ref_from_url(u)) for u in listed}

        new = [(u, k) for u, k in listed.items()
               if (tid := tender_id(ref_from_url(u))) not in store and tid not in rejected]
        refresh = [
            (u, k) for u, k in listed.items()
            if (t := store.get(tender_id(ref_from_url(u))))
            and (n := days_until(t.deadline)) is not None and 0 <= n <= REFRESH_DAYS
        ]
        queue = (new + refresh)[:MAX_DETAIL_PAGES]
        res.backlog = max(0, len(new) - MAX_DETAIL_PAGES)
        log.info("%d notices listed: %d new, %d to re-check, fetching %d",
                 len(listed), len(new), len(refresh), len(queue))

        for n, (url, kw) in enumerate(queue, 1):
            if n % 10 == 0:
                log.info("  %d / %d detail pages", n, len(queue))
            _pause(2, 4)
            text = _read_page(page, url)
            res.pages += 1
            p = parse_detail(text)
            if not p.get("title"):
                res.unparsed += 1
                if res.unparsed == 1:
                    log.warning("Could not parse %s, page text starts:\n%s", url, text[:500])
                continue
            tid = tender_id(ref_from_url(url))
            if p["closed"] and tid not in store:
                res.closed_on_arrival += 1
                res.closed_ids.add(tid)
                continue
            now = iso_now()
            res.tenders.append(Tender(
                id=tid, ref_no=ref_from_url(url), url=url, title=p["title"],
                portal=p["portal"], authority=p["authority"], location=p["location"],
                state=p["state"], category=categorise(p["title"], kw),
                value_inr=p["value_inr"], emd_inr=p["emd_inr"],
                published=p["published"], deadline=p["deadline"],
                first_seen=now, last_seen=now,
            ))
        browser.close()

    log.info("Fetched %d pages: %d parsed, %d closed on arrival, %d unparsed",
             res.pages, len(res.tenders), res.closed_on_arrival, res.unparsed)
    if res.unparsed and not res.tenders and not res.closed_on_arrival:
        raise LayoutChanged(
            f"Parsed 0 of {res.unparsed} TenderDetail pages, the page layout has probably "
            "changed. Update the patterns in scraper/page_parser.py.")
    return res
