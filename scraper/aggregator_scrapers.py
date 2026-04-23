"""
TenderRadar — TenderDetail.com Scraper (Playwright edition)
tenderdetail.com migrated to a JS-rendered SPA — requires a real browser
to execute JavaScript before the DOM contains any tender links.
"""
import logging
import random
import re
import time
from datetime import datetime, timedelta

from base_scraper import BaseScraper, Tender

log = logging.getLogger("TenderDetail")

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

# Link selectors to try after JS has rendered the page
LINK_SELECTORS = [
    "h2 a[href*='/TenderNotice/']",
    "a[href*='/TenderNotice/']",
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
        log.info("Starting TenderDetail.com scrape (Playwright)…")

        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        except ImportError:
            log.error("Playwright not installed — run: playwright install chromium --with-deps")
            return []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
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

            # Warm up — visit homepage first to set cookies / bypass checks
            log.info("Warming up session…")
            try:
                page.goto(BASE, timeout=20000, wait_until="domcontentloaded")
                time.sleep(random.uniform(3, 5))
                log.info("Homepage loaded — title: %s", page.title()[:60])
            except Exception as e:
                log.warning("Warmup failed (non-fatal): %s", e)

            consecutive_failures = 0

            for i, keyword in enumerate(SEARCH_KEYWORDS):
                if i > 0:
                    time.sleep(random.uniform(5, 10))

                url = f"{BASE}/Indian-tender/{keyword}-tenders"
                try:
                    page.goto(url, timeout=30000, wait_until="networkidle")
                    # Give JS a moment to finish rendering
                    time.sleep(random.uniform(2, 4))

                    title = page.title()
                    log.info("'%s' — title: %s", keyword, title[:60] if title else "NO TITLE")

                    # Try selectors until one returns links
                    links_data = []
                    for sel in LINK_SELECTORS:
                        els = page.query_selector_all(sel)
                        if els:
                            log.info("  Selector '%s' → %d links", sel, len(els))
                            for el in els:
                                href = el.get_attribute("href") or ""
                                text = (el.inner_text() or "").strip()
                                if href and text:
                                    links_data.append((href, text))
                            break

                    if not links_data:
                        # Last resort: log all hrefs so we can debug
                        all_links = page.query_selector_all("a[href]")
                        log.warning(
                            "  No selector matched. Total <a>: %d", len(all_links)
                        )
                        if all_links:
                            sample = [el.get_attribute("href")[:60] for el in all_links[:5]]
                            log.warning("  Sample hrefs: %s", sample)
                        consecutive_failures += 1
                        if consecutive_failures >= 3:
                            log.warning("3+ failures — backing off 60s")
                            time.sleep(60)
                            consecutive_failures = 0
                        continue

                    consecutive_failures = 0
                    found = 0

                    for href, title_text in links_data:
                        # Get the full URL
                        full_url = href if href.startswith("http") else (BASE + href)
                        # Get surrounding text for date/value extraction
                        container = title_text  # minimal — expand if needed

                        t = self._build_tender(
                            title=title_text,
                            url=full_url,
                            container=container,
                            keyword=keyword,
                        )
                        if t and t.id not in seen_ids:
                            seen_ids.add(t.id)
                            tenders.append(t)
                            found += 1

                    log.info("TenderDetail '%s': %d tenders", keyword, found)

                except Exception as e:
                    log.error("TenderDetail '%s': %s", keyword, e)
                    consecutive_failures += 1

            browser.close()

        log.info("TenderDetail total: %d", len(tenders))
        return tenders

    def _build_tender(self, title: str, url: str, container: str, keyword: str) -> "Tender | None":
        try:
            if not title or len(title) < 8:
                return None
            deadline  = self._extract_deadline(container)
            value_str = self._extract_value(container)
            portal    = self._detect_portal(container, title)
            category  = self._categorise(keyword, title)
            ref_no    = self._extract_ref(container, portal)
            return self.make_tender(
                portal=portal,
                title=title[:300],
                ref_no=ref_no,
                category=category,
                description=container[:500],
                value_raw=0.0,
                value_str=value_str,
                deadline=deadline,
                url=url,
            )
        except Exception as e:
            self.logger.debug("_build_tender error: %s", e)
            return None

    def _extract_deadline(self, text: str) -> str:
        label_patterns = [
            r"(?:Submission|Bid\s+Submission|Last\s+Date|Due\s+Date|Closing\s+Date|End\s+Date)"
            r"\s*[:\-]?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
            r"(?:Submission|Bid\s+Submission|Last\s+Date|Due\s+Date|Closing\s+Date|End\s+Date)"
            r"\s*[:\-]?\s*(\d{1,2}\s+\w+\s+\d{4})",
        ]
        for pattern in label_patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                parsed = self._pd(m.group(1))
                if parsed and not self._is_stale(parsed):
                    return parsed
        all_dates = re.findall(r"\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})\b", text)
        for raw in reversed(all_dates):
            parsed = self._pd(raw)
            if parsed and not self._is_stale(parsed):
                return parsed
        return self._dd(30)

    def _is_stale(self, date_str: str) -> bool:
        try:
            from datetime import date
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            return (date.today() - d).days > 7
        except Exception:
            return False

    def _extract_value(self, text: str) -> str:
        m = re.search(
            r"[₹Rs\.]+\s*([\d,\.]+)\s*(Cr|Crore|L|Lac|Lakh|K|Thousand)?",
            text, re.IGNORECASE,
        )
        if not m:
            return "N/A"
        amount = float(m.group(1).replace(",", ""))
        unit   = (m.group(2) or "").lower()
        if "cr" in unit:                   return f"₹{amount:.2f} Cr"
        if unit in ("l","lac","lakh"):     return f"₹{amount:.2f} L"
        if unit in ("k","thousand"):       return f"₹{amount/100000:.2f} L"
        return f"₹{amount:,.0f}"

    def _detect_portal(self, text: str, title: str) -> str:
        combined = (text + " " + title).upper()
        if "GEM"         in combined: return "GeM"
        if "CPPP"        in combined: return "CPPP"
        if "MAHARASHTRA" in combined: return "MH Gov"
        if "KARNATAKA"   in combined: return "KA Gov"
        if "RAJASTHAN"   in combined: return "RJ Gov"
        if "GUJARAT"     in combined: return "GJ Gov"
        if "UP" in combined and "GOVERNMENT" in combined: return "UP Gov"
        return "Gov Portal"

    def _categorise(self, keyword: str, title: str) -> str:
        kw = keyword.replace("-", " ").lower()
        t  = title.lower()
        for k, cat in CATEGORY_MAP.items():
            if k in kw or k in t:
                return cat
        return "Communication Support"

    def _extract_ref(self, text: str, portal: str) -> str:
        patterns = [
            r"[A-Z]{2,}/\d{4}[\/\-]\w+",
            r"\d{4,}/\w+/\d{2,4}",
            r"GEM[\/\-]\w+[\/\-]\w+",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return m.group(0)[:100]
        slug = re.sub(r"[^A-Za-z0-9]", "", text[:20])
        return f"{portal}-{slug}"


def scrape_all_aggregators() -> list[Tender]:
    try:
        results = TenderDetailScraper().scrape()
        logging.getLogger("Aggregators").info("TenderDetail.com: %d tenders", len(results))
        return results
    except Exception as e:
        logging.getLogger("Aggregators").error("TenderDetail.com failed: %s", e)
        return []
