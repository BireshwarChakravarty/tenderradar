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


class TenderDetailScraper(BaseScraper):
    PORTAL_NAME = "TenderDetail"

    def scrape(self) -> list[Tender]:
        tenders  = []
        seen_ids = set()
        self.logger.info("Starting TenderDetail.com scrape…")

        # Warm up the session with the homepage first — reduces 503 likelihood
        self.logger.info("Warming up session…")
        self.session.get(BASE, timeout=15)
        time.sleep(random.uniform(4, 7))

        consecutive_failures = 0

        for i, keyword in enumerate(SEARCH_KEYWORDS):
            url = f"{BASE}/Indian-tender/{keyword}-tenders"
            try:
                # Longer inter-keyword delay to avoid rate-limiting
                # Randomised so it doesn't look metronomic
                if i > 0:
                    delay = random.uniform(6, 12)
                    self.logger.debug("Sleeping %.1fs before next keyword…", delay)
                    time.sleep(delay)

                soup = self.get(url)

                if not soup:
                    consecutive_failures += 1
                    self.logger.warning(
                        "No response for '%s' (%d consecutive failures)",
                        keyword, consecutive_failures
                    )
                    # If 3+ keywords in a row fail, the site is likely blocking
                    # this run — back off heavily then continue
                    if consecutive_failures >= 3:
                        self.logger.warning(
                            "3+ consecutive failures — backing off 120s before continuing"
                        )
                        time.sleep(120)
                        consecutive_failures = 0
                    continue

                consecutive_failures = 0  # reset on success

                links = (
                    soup.select("h2 a[href*='/TenderNotice/']")
                    or soup.select("a[href*='/TenderNotice/']")
                )

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

    def _parse_link(self, link, keyword: str) -> "Tender | None":
        try:
            title = link.get_text(strip=True)
            if not title or len(title) < 8:
                return None

            href = link.get("href", "")
            url  = href if href.startswith("http") else (BASE + href)

            # Collect context text from surrounding DOM
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

        # Fallback: last date-like string in text that isn't in the past > 7 days
        all_dates = re.findall(r"\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})\b", text)
        for raw in reversed(all_dates):
            parsed = self._pd(raw)
            if parsed and not self._is_stale(parsed):
                return parsed

        return self._dd(30)

    def _is_stale(self, date_str: str) -> bool:
        """Returns True if the date is more than 7 days in the past."""
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
        if "cr" in unit:                        return f"₹{amount:.2f} Cr"
        if unit in ("l", "lac", "lakh"):        return f"₹{amount:.2f} L"
        if unit in ("k", "thousand"):           return f"₹{amount / 100000:.2f} L"
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
