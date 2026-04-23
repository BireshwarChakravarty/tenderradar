"""
TenderRadar — TenderDetail.com Scraper
Aggregates tenders from GeM, CPPP, and state portals.
URL pattern: https://www.tenderdetail.com/Indian-tender/{keyword}-tenders
"""
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
    "public relations":        "Public Relations",
    "pr agency":               "Public Relations",
    "media monitoring":        "Media Monitoring",
    "social media":            "Social Media Management",
    "digital marketing":       "Digital Marketing",
    "digital outreach":        "Digital Marketing",
    "event":                   "Events & Publicity",
    "advertising":             "Campaign Execution",
    "media buying":            "Campaign Execution",
    "integrated communication":"Integrated Communications",
    "communication agency":    "Integrated Communications",
    "content":                 "Creative & Content",
    "website":                 "Digital Marketing",
    "seo":                     "Digital Marketing",
    "geo":                     "Digital Marketing",
}


class TenderDetailScraper(BaseScraper):
    PORTAL_NAME = "TenderDetail"

    def scrape(self) -> list[Tender]:
        tenders  = []
        seen_ids = set()
        self.logger.info("Starting TenderDetail.com scrape…")

        for keyword in SEARCH_KEYWORDS:
            url = f"{BASE}/Indian-tender/{keyword}-tenders"
            try:
                time.sleep(3)
                soup = self.get(url)
                if not soup:
                    continue
                links = soup.select("h2 a[href*='/TenderNotice/']") or \
                        soup.select("a[href*='/TenderNotice/']")
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

        self.logger.info("TenderDetail total: %d", len(tenders))
        return tenders

    def _parse_link(self, link, keyword: str) -> "Tender | None":
        try:
            title = link.get_text(strip=True)
            if not title or len(title) < 8:
                return None

            href = link.get("href", "")
            url  = href if href.startswith("http") else (BASE + href)

            # Collect text from surrounding DOM for date/value/portal
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

            deadline = self._extract_deadline(container)
            value_str = self._extract_value(container)
            portal = self._detect_portal(container, title)
            category = self._categorise(keyword, title)
            ref_no = self._extract_ref(container, portal)

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
        """
        Tries multiple date label patterns.
        Falls back to a 30-day default if nothing found.
        """
        # Labels that precede the submission/closing date
        label_patterns = [
            r"(?:Submission|Bid\s+Submission|Last\s+Date|Due\s+Date|Closing\s+Date|End\s+Date)"
            r"\s*[:\-]?\s*"
            r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
            r"(?:Submission|Bid\s+Submission|Last\s+Date|Due\s+Date|Closing\s+Date|End\s+Date)"
            r"\s*[:\-]?\s*"
            r"(\d{1,2}\s+\w+\s+\d{4})",
            r"(?:Submission|Bid\s+Submission|Last\s+Date|Due\s+Date|Closing\s+Date|End\s+Date)"
            r"\s*[:\-]?\s*"
            r"(\w+\s+\d{1,2},?\s+\d{4})",
        ]
        for pattern in label_patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                parsed = self._pd(m.group(1))
                if parsed:
                    # Reject obviously wrong dates (in the past by more than 1 yr)
                    try:
                        from datetime import date
                        d = datetime.strptime(parsed, "%Y-%m-%d").date()
                        if (date.today() - d).days > 365:
                            continue
                    except Exception:
                        pass
                    return parsed

        # Generic date anywhere in text — take the LAST one found (most likely closing)
        all_dates = re.findall(
            r"\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})\b", text
        )
        for raw in reversed(all_dates):
            parsed = self._pd(raw)
            if parsed:
                try:
                    from datetime import date
                    d = datetime.strptime(parsed, "%Y-%m-%d").date()
                    # Only accept future dates (or within the last 7 days)
                    if (date.today() - d).days <= 7:
                        return parsed
                except Exception:
                    pass

        return self._dd(30)

    def _extract_value(self, text: str) -> str:
        m = re.search(
            r"[₹Rs\.]+\s*([\d,\.]+)\s*(Cr|Crore|L|Lac|Lakh|K|Thousand)?",
            text, re.IGNORECASE
        )
        if not m:
            return "N/A"
        amount = float(m.group(1).replace(",", ""))
        unit   = (m.group(2) or "").lower()
        if "cr" in unit:    return f"₹{amount:.2f} Cr"
        if unit in ("l","lac","lakh"): return f"₹{amount:.2f} L"
        if unit in ("k","thousand"):   return f"₹{amount/100000:.2f} L"
        return f"₹{amount:,.0f}"

    def _detect_portal(self, text: str, title: str) -> str:
        combined = (text + " " + title).upper()
        if "GEM"  in combined: return "GeM"
        if "CPPP" in combined: return "CPPP"
        if "TENDER.GOV" in combined: return "CPPP"
        if "UP"   in combined and "GOVERNMENT" in combined: return "UP Gov"
        if "MAHARASHTRA" in combined: return "MH Gov"
        if "KARNATAKA"   in combined: return "KA Gov"
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
