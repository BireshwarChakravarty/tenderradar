"""
TenderRadar — TenderDetail.com Scraper (Playwright edition)
tenderdetail.com is a JS-rendered SPA — requires headless Chromium.
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
        log.info("Starting TenderDetail.com scrape (Playwright)…")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.error("Playwright not installed")
            return []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox","--disable-setuid-sandbox",
                      "--disable-dev-shm-usage","--disable-gpu"],
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

            # Warm up
            log.info("Warming up session…")
            try:
                page.goto(BASE, timeout=25000, wait_until="domcontentloaded")
                time.sleep(random.uniform(4, 7))
                log.info("Homepage: %s", page.title()[:60])
            except Exception as e:
                log.warning("Warmup failed (non-fatal): %s", e)

            consecutive_failures = 0

            for i, keyword in enumerate(SEARCH_KEYWORDS):
                if i > 0:
                    time.sleep(random.uniform(6, 11))

                url = f"{BASE}/Indian-tender/{keyword}-tenders"
                try:
                    page.goto(url, timeout=35000, wait_until="networkidle")
                    time.sleep(random.uniform(2, 4))

                    title = page.title()
                    log.info("'%s' — %s", keyword, title[:70] if title else "NO TITLE")

                    # Find the working link selector
                    working_sel = None
                    for sel in LINK_SELECTORS:
                        if page.query_selector_all(sel):
                            working_sel = sel
                            break

                    if not working_sel:
                        all_a = page.query_selector_all("a[href]")
                        log.warning("No selector matched. <a> count: %d", len(all_a))
                        if all_a:
                            sample = [el.get_attribute("href")[:60] for el in all_a[:5]]
                            log.warning("Sample hrefs: %s", sample)
                        consecutive_failures += 1
                        if consecutive_failures >= 3:
                            log.warning("3+ failures — backing off 90s")
                            time.sleep(90)
                            consecutive_failures = 0
                        continue

                    consecutive_failures = 0
                    link_els = page.query_selector_all(working_sel)
                    log.info("  Selector '%s' → %d links", working_sel, len(link_els))

                    found = 0
                    for el in link_els:
                        try:
                            href       = el.get_attribute("href") or ""
                            link_text  = (el.inner_text() or "").strip()

                            if not href or not link_text or len(link_text) < 8:
                                continue

                            full_url = href if href.startswith("http") else (BASE + href)

                            # ── Extract surrounding card text for deadline/value ──
                            # Walk up the DOM to find the card container
                            container_text = link_text
                            try:
                                # Try to get the parent card element text
                                for _ in range(5):
                                    parent = el.evaluate("el => el.parentElement")
                                    if parent:
                                        card_text = el.evaluate(
                                            """el => {
                                                let node = el;
                                                for(let i=0; i<5; i++){
                                                    node = node.parentElement;
                                                    if(!node) break;
                                                    const t = node.innerText || '';
                                                    if(t.length > 50 && t.length < 800) return t;
                                                }
                                                return '';
                                            }"""
                                        )
                                        if card_text and len(card_text) > 50:
                                            container_text = card_text
                                            break
                            except Exception:
                                pass

                            t = self._build_tender(
                                title=link_text,
                                url=full_url,
                                container=container_text,
                                keyword=keyword,
                            )
                            if t and t.id not in seen_ids:
                                seen_ids.add(t.id)
                                tenders.append(t)
                                found += 1

                        except Exception as e:
                            log.debug("Link parse error: %s", e)

                    log.info("TenderDetail '%s': %d tenders", keyword, found)

                except Exception as e:
                    log.error("TenderDetail '%s': %s", keyword, e)
                    consecutive_failures += 1

            browser.close()

        log.info("TenderDetail total: %d", len(tenders))
        return tenders

    def _build_tender(self, title, url, container, keyword):
        try:
            if not title or len(title) < 8:
                return None
            deadline  = self._extract_deadline(container)
            value_str = self._extract_value(container)
            portal    = self._detect_portal(container, title)
            category  = self._categorise(keyword, title)
            ref_no    = self._extract_ref(container, portal)
            return self.make_tender(
                portal=portal, title=title[:300], ref_no=ref_no,
                category=category, description=container[:500],
                value_raw=0.0, value_str=value_str,
                deadline=deadline, url=url,
            )
        except Exception as e:
            self.logger.debug("_build_tender error: %s", e)
            return None

    def _extract_deadline(self, text: str) -> str:
        label_patterns = [
            r"(?:Submission|Bid\s+Submission|Last\s+Date|Due\s+Date|Closing\s+Date|End\s+Date|Closing)"
            r"\s*[:\-]?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
            r"(?:Submission|Bid\s+Submission|Last\s+Date|Due\s+Date|Closing\s+Date|End\s+Date|Closing)"
            r"\s*[:\-]?\s*(\d{1,2}\s+\w+\s+\d{4})",
            r"(?:Submission|Bid\s+Submission|Last\s+Date|Due\s+Date|Closing\s+Date|End\s+Date|Closing)"
            r"\s*[:\-]?\s*(\w+\s+\d{1,2},?\s+\d{4})",
        ]
        for pattern in label_patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                parsed = self._pd(m.group(1))
                if parsed and not self._is_stale(parsed):
                    return parsed
        # Fallback: last date-like string
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
        for p in [r"[A-Z]{2,}/\d{4}[\/\-]\w+", r"\d{4,}/\w+/\d{2,4}", r"GEM[\/\-]\w+[\/\-]\w+"]:
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
