"""
TenderRadar — TenderDetail.com Scraper
Aggregates tenders from GeM, CPPP, and state portals via tenderdetail.com.
"""
import random
import re
import time
from datetime import datetime, timedelta
from base_scraper import BaseScraper, Tender

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

# All known URL patterns to try for each keyword
# Listed in order of preference — first match wins
URL_PATTERNS = [
    "{base}/Indian-tender/{kw}-tenders",
    "{base}/search-tender?keyword={kw}",
    "{base}/tenders/{kw}",
    "{base}/tender-search?q={kw}",
]

# All known link selectors — first non-empty match wins
LINK_SELECTORS = [
    "h2 a[href*='/TenderNotice/']",
    "a[href*='/TenderNotice/']",
    "a[href*='TenderNotice']",
    "h2 a[href*='/tender/']",
    "a[href*='/tender-detail']",
    "a[href*='/tender/']",
    ".tender-title a",
    ".bid-title a",
    "h3 a[href*='tender']",
    "h2 a",
    "h3 a",
]


class TenderDetailScraper(BaseScraper):
    PORTAL_NAME = "TenderDetail"

    def scrape(self) -> list[Tender]:
        tenders  = []
        seen_ids = set()
        self.logger.info("Starting TenderDetail.com scrape…")

        # Warm up session
        self.logger.info("Warming up session…")
        try:
            r = self.session.get(BASE, timeout=15)
            self.logger.info("Homepage: HTTP %d — %d chars", r.status_code, len(r.text))
        except Exception as e:
            self.logger.warning("Warmup failed: %s", e)
        time.sleep(random.uniform(4, 7))

        # Discover which URL pattern and selector work on the first keyword
        working_url_pattern = None
        working_selector    = None

        self.logger.info("=== SELECTOR DISCOVERY on first keyword ===")
        disc_url, disc_selector, disc_soup = self._discover(SEARCH_KEYWORDS[0])
        if disc_url:
            working_url_pattern = disc_url
            working_selector    = disc_selector
            self.logger.info("✓ URL pattern : %s", disc_url)
            self.logger.info("✓ Selector    : %s", disc_selector)
        else:
            self.logger.error("✗ No working URL+selector found — aborting scrape")
            self.logger.error("  Check the DIAGNOSTIC output above to update selectors")
            return []

        consecutive_failures = 0

        for i, keyword in enumerate(SEARCH_KEYWORDS):
            if i > 0:
                delay = random.uniform(6, 12)
                time.sleep(delay)

            url = working_url_pattern.replace("{kw}", keyword)
            try:
                soup = self.get(url)
                if not soup:
                    consecutive_failures += 1
                    if consecutive_failures >= 3:
                        self.logger.warning("3 consecutive failures — backing off 120s")
                        time.sleep(120)
                        consecutive_failures = 0
                    continue

                consecutive_failures = 0
                links = soup.select(working_selector)

                # Fallback: try all selectors if the working one returns 0
                if not links:
                    for sel in LINK_SELECTORS:
                        links = soup.select(sel)
                        if links:
                            self.logger.info(
                                "Selector updated to '%s' for '%s'", sel, keyword
                            )
                            working_selector = sel
                            break

                found = 0
                for link in links:
                    t = self._parse_link(link, keyword)
                    if t and t.id not in seen_ids:
                        seen_ids.add(t.id)
                        tenders.append(t)
                        found += 1

                self.logger.info("TenderDetail '%s': %d tenders", keyword, found)

            except Exception as e:
                self.logger.error("TenderDetail '%s': %s", keyword, e)
                consecutive_failures += 1

        self.logger.info("TenderDetail total: %d", len(tenders))
        return tenders

    def _discover(self, keyword: str):
        """
        Try every URL pattern × selector combination on one keyword.
        Logs full diagnostics so failures can be debugged.
        Returns (url_template, selector, soup) on first success, or (None,None,None).
        """
        kw = keyword
        for url_tmpl in URL_PATTERNS:
            url = url_tmpl.format(base=BASE, kw=kw)
            self.logger.info("Trying URL: %s", url)
            try:
                time.sleep(random.uniform(3, 6))
                r = self.session.get(url, timeout=25)
                self.logger.info("  → HTTP %d | %d chars", r.status_code, len(r.text))

                if r.status_code != 200:
                    self.logger.warning("  Non-200, skipping")
                    continue

                from bs4 import BeautifulSoup
                soup = BeautifulSoup(r.text, "lxml")

                # Diagnostics regardless of selector outcome
                title = soup.title.string.strip()[:80] if soup.title else "NO TITLE"
                all_a = soup.find_all("a")
                self.logger.info("  Page title : %s", title)
                self.logger.info("  Total <a>  : %d", len(all_a))
                if all_a:
                    # Log first 5 hrefs so we can identify the new pattern
                    hrefs = [a.get("href","")[:70] for a in all_a[:5] if a.get("href")]
                    self.logger.info("  First hrefs: %s", hrefs)

                # Try every selector
                for sel in LINK_SELECTORS:
                    links = soup.select(sel)
                    if links:
                        self.logger.info("  ✓ Selector '%s' → %d links", sel, len(links))
                        return url_tmpl, sel, soup
                    else:
                        self.logger.info("  ✗ '%s' → 0", sel)

                self.logger.warning("  No selector matched on %s", url)

            except Exception as e:
                self.logger.error("  Error: %s", e)

        return None, None, None

    def _parse_link(self, link, keyword: str) -> "Tender | None":
        try:
            title = link.get_text(strip=True)
            if not title or len(title) < 8:
                return None

            href = link.get("href", "")
            url  = href if href.startswith("http") else (BASE + href)

            search_texts = [title]
            node = link
            for _ in range(6):
                node = node.parent
                if node is None:
                    break
                txt = node.get_text(" ", strip=True)
                if txt:
                    search_texts.append(txt)
                if len(txt) > 400:
                    break
            container = " ".join(search_texts)

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
            self.logger.debug("_parse_link error: %s", e)
            return None

    def _extract_deadline(self, text: str) -> str:
        label_patterns = [
            r"(?:Submission|Bid\s+Submission|Last\s+Date|Due\s+Date|Closing\s+Date|End\s+Date)"
            r"\s*[:\-]?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
            r"(?:Submission|Bid\s+Submission|Last\s+Date|Due\s+Date|Closing\s+Date|End\s+Date)"
            r"\s*[:\-]?\s*(\d{1,2}\s+\w+\s+\d{4})",
            r"(?:Submission|Bid\s+Submission|Last\s+Date|Due\s+Date|Closing\s+Date|End\s+Date)"
            r"\s*[:\-]?\s*(\w+\s+\d{1,2},?\s+\d{4})",
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
        if "cr" in unit:                     return f"₹{amount:.2f} Cr"
        if unit in ("l","lac","lakh"):       return f"₹{amount:.2f} L"
        if unit in ("k","thousand"):         return f"₹{amount/100000:.2f} L"
        return f"₹{amount:,.0f}"

    def _detect_portal(self, text: str, title: str) -> str:
        combined = (text + " " + title).upper()
        if "GEM"         in combined: return "GeM"
        if "CPPP"        in combined: return "CPPP"
        if "TENDER.GOV"  in combined: return "CPPP"
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
            r"CPPP[\/\-]\d+",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return m.group(0)[:100]
        slug = re.sub(r"[^A-Za-z0-9]", "", text[:20])
        return f"{portal}-{slug}"


def scrape_all_aggregators() -> list[Tender]:
    import logging
    log = logging.getLogger("Aggregators")
    try:
        results = TenderDetailScraper().scrape()
        log.info("TenderDetail.com: %d tenders", len(results))
        return results
    except Exception as e:
        log.error("TenderDetail.com failed: %s", e)
        return []
