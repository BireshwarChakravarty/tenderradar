"""
TenderRadar — TenderDetail.com Scraper (Playwright edition)

tenderdetail.com is a JS-rendered SPA — requires headless Chromium.

ARCHITECTURE (two-pass):
  Pass 1  — Scrape listing pages to collect TenderNotice URLs
  Pass 2  — Visit each detail page to get real title, submission date, value
            (only for tenders not already in the store)

ROOT CAUSES FIXED:
  1. Value regex used [₹Rs\\.] character class which matched '.' in "Apr. 24"
     → fake ₹24 values. Fixed to explicit (?:₹|Rs\\.?) pattern.
  2. Listing page link text is always "View Notice" — actual title is on detail page.
  3. Listing page shows publication date, not submission date — only detail page has it.
"""
import logging
import os
import random
import re
import time
from datetime import datetime, timedelta

from base_scraper import BaseScraper, Tender
from deduplicator import load_existing

log = logging.getLogger("TenderDetail")

MAX_DETAIL_PAGES = int(os.getenv("MAX_DETAIL_PAGES", "150"))

SEARCH_KEYWORDS = [
    "public-relations",
    "social-media-management",
    "media-monitoring",
    "communication-agency",
    "pr-agency",
    "digital-outreach",
    "advertising-agency",
    "event-publicity",
    "media-buying",
    "content-development",
    "digital-marketing-agency",
    "integrated-communication",
    "website-development",
    "seo-services",
    "geo-services",
]

BASE = "https://www.tenderdetail.com"

CATEGORY_MAP = {
    "public relations":         "Public Relations",
    "pr agency":                "Public Relations",
    "media monitoring":         "Media Monitoring",
    "social media":             "Social Media Management",
    "digital marketing":        "Digital Marketing",
    "digital outreach":         "Digital Marketing",
    "event":                    "Events & Publicity",
    "advertising":              "Campaign Execution",
    "media buying":             "Campaign Execution",
    "integrated communication": "Integrated Communications",
    "communication agency":     "Integrated Communications",
    "content":                  "Creative & Content",
    "website":                  "Digital Marketing",
    "seo":                      "Digital Marketing",
    "geo":                      "Digital Marketing",
}

LINK_SELECTORS = [
    "a[href*='/TenderNotice/']",
    "h2 a[href*='/TenderNotice/']",
    "a[href*='TenderNotice']",
    "h2 a[href*='tender']",
    "a[href*='/tender-detail']",
    ".tender-title a",
    ".bid-title a",
    "h3 a",
    "h2 a",
]


class TenderDetailScraper(BaseScraper):
    PORTAL_NAME = "TenderDetail"

    def scrape(self) -> list[Tender]:
        tenders  = []
        seen_ids = set()
        no_title = 0
        log.info("Starting TenderDetail.com scrape (Playwright two-pass)…")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.error("Playwright not installed")
            return []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox",
                      "--disable-dev-shm-usage", "--disable-gpu"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="en-IN",
            )
            page = context.new_page()

            # ── Warm up ───────────────────────────────────────────
            log.info("Warming up session…")
            try:
                page.goto(BASE, timeout=25000, wait_until="domcontentloaded")
                time.sleep(random.uniform(4, 7))
                log.info("Homepage: %s", page.title()[:60])
            except Exception as e:
                log.warning("Warmup failed (non-fatal): %s", e)

            # ── PASS 1: Collect URLs from listing pages ────────────
            url_keyword_map: dict[str, str] = {}  # url → keyword
            consecutive_failures = 0

            for i, keyword in enumerate(SEARCH_KEYWORDS):
                if i > 0:
                    time.sleep(random.uniform(5, 9))

                listing_url = f"{BASE}/Indian-tender/{keyword}-tenders"
                try:
                    page.goto(listing_url, timeout=35000, wait_until="networkidle")
                    time.sleep(random.uniform(2, 3))

                    title = page.title()
                    log.info("Listing '%s' — %s", keyword, title[:70] if title else "NO TITLE")

                    # Find working selector
                    working_sel = None
                    for sel in LINK_SELECTORS:
                        if page.query_selector_all(sel):
                            working_sel = sel
                            break

                    if not working_sel:
                        all_a = page.query_selector_all("a[href]")
                        log.warning("No selector matched. <a>: %d", len(all_a))
                        consecutive_failures += 1
                        if consecutive_failures >= 3:
                            log.warning("3 failures — backing off 90s")
                            time.sleep(90)
                            consecutive_failures = 0
                        continue

                    consecutive_failures = 0
                    link_els = page.query_selector_all(working_sel)
                    log.info("  '%s' → %d links", working_sel, len(link_els))

                    for el in link_els:
                        try:
                            href = el.get_attribute("href") or ""
                            if not href:
                                continue
                            full_url = href if href.startswith("http") else (BASE + href)
                            # First keyword to find a URL wins (avoids duplicate detail fetches)
                            if full_url not in url_keyword_map:
                                url_keyword_map[full_url] = keyword
                        except Exception as e:
                            log.debug("URL collect error: %s", e)

                    log.info("  Collected %d unique URLs so far", len(url_keyword_map))

                except Exception as e:
                    log.error("Listing '%s': %s", keyword, e)
                    consecutive_failures += 1

            log.info("Pass 1 complete — %d unique tender URLs", len(url_keyword_map))

            # ── PASS 2: Visit each detail page ────────────────────
            # Skip URLs already in the store, and cap the rest so the run
            # finishes (and commits) inside the workflow's 45-minute timeout.
            # Each detail page takes ~6 s; leftovers are picked up next run.
            known = {t.get("url") for t in load_existing().values()}
            pending = [(u, k) for u, k in url_keyword_map.items() if u not in known]
            log.info("Pass 2: %d new URLs (%d already stored), fetching up to %d…",
                     len(pending), len(url_keyword_map) - len(pending), MAX_DETAIL_PAGES)
            pending = pending[:MAX_DETAIL_PAGES]
            processed = 0

            for n, (detail_url, keyword) in enumerate(pending, 1):
                if n % 10 == 0:
                    log.info("  Visited %d / %d detail pages (%d parsed)", n, len(pending), processed)
                try:
                    time.sleep(random.uniform(2, 4))
                    detail = self._fetch_detail(page, detail_url)

                    if not detail.get("title"):
                        no_title += 1
                        if no_title == 1:
                            log.warning("No title parsed from %s — page text starts:\n%s",
                                        detail_url, detail.get("description", "<empty>")[:400])
                        continue

                    t = self._build_tender(
                        title    = detail["title"],
                        url      = detail_url,
                        deadline = detail.get("deadline", self._dd(30)),
                        value_str= detail.get("value_str", "N/A"),
                        portal   = detail.get("portal", "Gov Portal"),
                        keyword  = keyword,
                        description = detail.get("description", ""),
                    )
                    if t and t.id not in seen_ids:
                        seen_ids.add(t.id)
                        tenders.append(t)
                        processed += 1

                except Exception as e:
                    log.error("Detail page '%s': %s", detail_url, e)

            browser.close()

        log.info("TenderDetail total: %d tenders (%d pages without a title)", len(tenders), no_title)
        if no_title and not tenders:
            # Every page fetched but none parsed — the site layout has changed.
            # Fail loudly instead of committing an unchanged store for months.
            raise RuntimeError(
                f"Parsed 0 of {no_title} TenderDetail pages — detail page layout has "
                "probably changed; update the patterns in _parse_detail()"
            )
        return tenders

    # ── Detail page extractor ──────────────────────────────────────

    def _fetch_detail(self, page, url: str) -> dict:
        """
        Navigate to a TenderNotice detail page and extract:
          - title (from Tender Brief section)
          - deadline (Submission Date)
          - value_str (Tender Value)
          - portal (from tendering authority / location text)
          - description (tender brief text)
        """
        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(random.uniform(1.5, 2.5))
            body_text = page.evaluate("() => document.body.innerText || ''")
        except Exception as e:
            log.debug("_fetch_detail error %s: %s", url, e)
            return {}
        return self._parse_detail(body_text)

    def _parse_detail(self, body_text: str) -> dict:
        """
        Extract fields from a detail page's visible text. Handles both layouts:
          - pre-July 2026: "TDR : 55145448 … Tender Brief : <title> … Submission Date …"
          - redesign:      "Closing in 13 days\nTDR #57185957\n<title>\nIssued by …"
        """
        result = {}
        try:
            if not body_text or len(body_text) < 80:
                return result

            result["description"] = body_text[:500]

            # ── Title ──────────────────────────────────────────────
            title_patterns = [
                # Old layout: "Tender Brief : [Corrigendum :] <actual title>"
                r"Tender Brief\s*[:\-]\s*(?:Corrigendum\s*[:\-]\s*)?([A-Za-z][^\n]{20,350})",
                r"(?:Subject|Title|Brief)\s*[:\-]\s*([A-Za-z][^\n]{20,300})",
                # Redesign: no label — the title is the line right after "TDR #<id>"
                r"TDR\s*[#:]\s*\d+\s*\n\s*([A-Za-z][^\n]{20,350})",
            ]
            for pat in title_patterns:
                m = re.search(pat, body_text, re.IGNORECASE)
                if m:
                    t = m.group(1).strip().rstrip(".")
                    if len(t) > 15:
                        result["title"] = t[:280]
                        break

            # ── Submission date ────────────────────────────────────
            # The redesign shows a countdown ("Closing in 13 days"). Prefer it:
            # labelled dates on the new page pick up an unrelated date.
            m = re.search(r"Closing (?:in (\d+) days?|(today)|(tomorrow))", body_text, re.IGNORECASE)
            if m:
                days = int(m.group(1)) if m.group(1) else (0 if m.group(2) else 1)
                result["deadline"] = (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d")

            date_patterns = [
                r"Submission Date\s*[:\-]?\s*(\d{1,2}[-\/]\d{1,2}[-\/]\d{2,4})",
                r"Bid Submission\s*[:\-]?\s*(\d{1,2}[-\/]\d{1,2}[-\/]\d{2,4})",
                r"Last Date\s*[:\-]?\s*(\d{1,2}[-\/]\d{1,2}[-\/]\d{2,4})",
                r"Due Date\s*[:\-]?\s*(\d{1,2}[-\/]\d{1,2}[-\/]\d{2,4})",
                r"Closing Date\s*[:\-]?\s*(\d{1,2}[-\/]\d{1,2}[-\/]\d{2,4})",
                # With month names
                r"Submission Date\s*[:\-]?\s*(\d{1,2}[\s\-\/]\w+[\s\-\/]\d{4})",
            ]
            for pat in date_patterns if "deadline" not in result else []:
                m = re.search(pat, body_text, re.IGNORECASE)
                if m:
                    parsed = self._pd(m.group(1))
                    if parsed:
                        result["deadline"] = parsed
                        break

            # ── Tender value ───────────────────────────────────────
            # FIXED: use explicit (?:₹|Rs\.?) — NOT character class [₹Rs\.]
            # Old regex matched '.' in "Apr. 24" giving fake ₹24 values.
            value_patterns = [
                # Labeled value (most reliable)
                r"Tender Value\s*[:\-]?\s*(?:₹|Rs\.?|INR)?\s*([\d,\.]+)\s*/?\s*-?\s*(Crore|Lakh|L|Cr|K)?",
                # Explicit currency prefix
                r"(?:₹|Rs\.)\s*([\d,\.]+)\s*(Crore|Lakh|L|Cr|K)?",
                # Bare number followed by mandatory unit
                r"([\d,\.]+)\s*/?\s*-?\s*(Crore|Lakh)\b",
            ]
            for pat in value_patterns:
                m = re.search(pat, body_text, re.IGNORECASE)
                if m:
                    try:
                        amount = float(m.group(1).replace(",", ""))
                        if amount <= 0:
                            continue
                        unit = (m.group(2) or "").lower().strip()
                        if "cr" in unit:
                            result["value_str"] = f"₹{amount:.2f} Cr"
                        elif unit in ("l", "lac", "lakh"):
                            result["value_str"] = f"₹{amount:.2f} L"
                        elif unit in ("k",):
                            result["value_str"] = f"₹{amount/100:.2f} L"
                        elif amount > 1000:
                            # Large bare number — likely rupees
                            result["value_str"] = f"₹{amount:,.0f}"
                        else:
                            # Ambiguous small number without unit — skip
                            continue
                        break
                    except Exception:
                        continue

            # ── Portal ─────────────────────────────────────────────
            result["portal"] = self._detect_portal(body_text, "")

        except Exception as e:
            log.debug("_parse_detail error: %s", e)

        return result

    # ── Tender builder ─────────────────────────────────────────────

    def _build_tender(self, title, url, deadline, value_str, portal, keyword, description="") -> "Tender | None":
        try:
            if not title or len(title.strip()) < 8:
                return None
            category = self._categorise(keyword, title)
            ref_no   = self._extract_ref_from_url(url)
            return self.make_tender(
                portal      = portal,
                title       = title.strip()[:300],
                ref_no      = ref_no,
                category    = category,
                description = description[:500],
                value_raw   = 0.0,
                value_str   = value_str or "N/A",
                deadline    = deadline or self._dd(30),
                url         = url,
            )
        except Exception as e:
            self.logger.debug("_build_tender error: %s", e)
            return None

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_ref_from_url(self, url: str) -> str:
        """Extract ref number from TenderNotice URL path."""
        m = re.search(r"/TenderNotice/(\d+)", url)
        return m.group(1) if m else url.split("/")[-1][:30]

    def _detect_portal(self, text: str, title: str) -> str:
        combined = (text[:300] + " " + title).upper()
        if "GEM"         in combined: return "GeM"
        if "CPPP"        in combined: return "CPPP"
        if "MAHARASHTRA" in combined: return "MH Gov"
        if "KARNATAKA"   in combined: return "KA Gov"
        if "RAJASTHAN"   in combined: return "RJ Gov"
        if "GUJARAT"     in combined: return "GJ Gov"
        if "BIHAR"       in combined: return "BR Gov"
        if "MADHYA PRADESH" in combined: return "MP Gov"
        if "UTTAR PRADESH" in combined or ("UP" in combined and "GOVT" in combined):
            return "UP Gov"
        return "Gov Portal"

    def _categorise(self, keyword: str, title: str) -> str:
        kw = keyword.replace("-", " ").lower()
        t  = title.lower()
        for k, cat in CATEGORY_MAP.items():
            if k in kw or k in t:
                return cat
        return "Communication Support"

    def _is_stale(self, date_str: str) -> bool:
        try:
            from datetime import date
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            return (date.today() - d).days > 7
        except Exception:
            return False


def scrape_all_aggregators() -> list[Tender]:
    results = TenderDetailScraper().scrape()
    logging.getLogger("Aggregators").info("TenderDetail.com: %d tenders", len(results))
    return results
