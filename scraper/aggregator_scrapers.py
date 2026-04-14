"""
TenderRadar — TenderDetail.com Scraper
Date fix: anchor by tender ID (numeric prefix) not full title text,
since get_text() adds spaces that break exact title matching.
"""
import re
import time
from datetime import datetime, timedelta
from base_scraper import BaseScraper, Tender

SEARCH_KEYWORDS = [
    "public-relations", "social-media-management", "media-monitoring",
    "communication-agency", "pr-agency", "digital-outreach",
    "advertising-agency", "event-publicity", "media-buying",
    "content-development", "digital-marketing-agency", "integrated-communication",
    "website-development", "seo-services", "geo-services",
]

BASE = "https://www.tenderdetail.com"
DATE_PATTERN = re.compile(
    r"(Due|Submission|Closing|Last|Bid|Opening)\s*(Date|Datetime)\s*:?\s*([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
    re.IGNORECASE
)
ID_PATTERN = re.compile(r"^\d{6,10}")


class TenderDetailScraper(BaseScraper):
    PORTAL_NAME = "TenderDetail"

    def scrape(self) -> list[Tender]:
        tenders = []
        seen_ids = set()
        self.logger.info("Starting TenderDetail.com scrape…")

        for keyword in SEARCH_KEYWORDS:
            url = f"{BASE}/Indian-tender/{keyword}-tenders"
            try:
                time.sleep(3)
                soup = self.get(url)
                if not soup:
                    continue

                full_text = soup.get_text(" ")

                # All Due Date positions in page text
                date_hits = [
                    (m.start(), m.group(3).strip())
                    for m in DATE_PATTERN.finditer(full_text)
                ]
                self.logger.debug(f"  Found {len(date_hits)} date markers on page")

                links = [
                    l for l in soup.select("a[href*='/TenderNotice/']")
                    if len(l.get_text(strip=True)) > 15
                ]

                found = 0
                for link in links:
                    title = link.get_text(strip=True)
                    href  = link.get("href", "")
                    url_t = href if href.startswith("http") else (BASE + href)

                    # ── Anchor by numeric tender ID, not full title ────
                    # e.g. "55047660tender for..." → anchor = "55047660"
                    id_match = ID_PATTERN.match(title)
                    anchor = id_match.group(0) if id_match else title[:30]

                    anchor_pos = full_text.find(anchor)

                    # Find nearest Due Date AFTER the anchor position
                    deadline = self._dd(30)
                    if anchor_pos != -1:
                        for pos, date_str in date_hits:
                            if pos > anchor_pos:
                                parsed = self._pd(date_str)
                                if parsed != self._dd(30):
                                    deadline = parsed
                                break

                    # Value — scan 600 chars after anchor
                    value_str = "N/A"
                    if anchor_pos != -1:
                        snippet = full_text[anchor_pos:anchor_pos + 600]
                        val_m = re.search(
                            r"([\d,\.]+)\s*(Crore|Lakh|L\b|Cr\b)",
                            snippet, re.IGNORECASE
                        )
                        if val_m:
                            value_str = f"₹{val_m.group(1)} {val_m.group(2)}"

                    # Ref from link title attribute
                    title_attr = link.get("title", "")
                    ref_m = re.search(
                        r"GEM/\d+/\w/\d+|[\w]+/\d{4}[-/]\w+|[\w/\-]{5,}/\d{4}",
                        title_attr or url_t, re.IGNORECASE
                    )
                    ref = ref_m.group(0)[:100] if ref_m else f"TD-{title[:20].replace(' ','')}"

                    portal = self._detect_portal(title_attr + " " + title)
                    self.PORTAL_NAME = portal

                    t = self.make_tender(
                        title=title[:250], ref_no=ref,
                        category=self._cat(title), description=title,
                        value_raw=0.0, value_str=value_str,
                        deadline=deadline, url=url_t,
                    )
                    if t and t.id not in seen_ids:
                        seen_ids.add(t.id)
                        tenders.append(t)
                        found += 1

                self.logger.info(f"TenderDetail '{keyword}': {found} tenders")

            except Exception as e:
                self.logger.error(f"TenderDetail '{keyword}': {e}")

        self.logger.info(f"TenderDetail total: {len(tenders)}")
        return tenders

    def _detect_portal(self, text):
        t = text.upper()
        if "GEM/" in t:   return "GeM"
        if "CPPP" in t:   return "CPPP"
        if "ONGC" in t:   return "ONGC"
        if "NTPC" in t:   return "NTPC"
        return "Govt Portal"

    def _pd(self, s):
        s = s.strip().rstrip(".")
        for fmt in ("%b %d, %Y", "%b %d %Y", "%B %d, %Y", "%B %d %Y",
                    "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y",
                    "%d.%m.%Y", "%d %b %Y", "%d %B %Y"):
            try:
                parsed = datetime.strptime(s[:20], fmt)
                if 2024 <= parsed.year <= 2028:
                    return parsed.strftime("%Y-%m-%d")
            except: pass
        return self._dd(30)

    def _dd(self, d):
        return (datetime.utcnow() + timedelta(days=d)).strftime("%Y-%m-%d")

    def _cat(self, t):
        t = t.lower()
        if any(k in t for k in ["pr ", "public relation", "communication agency", "empanelment", "media relation"]): return "PR & Communications"
        if any(k in t for k in ["social media", "digital media management"]): return "Social Media"
        if any(k in t for k in ["campaign", "awareness", "outreach campaign"]): return "Campaign Execution"
        if any(k in t for k in ["media monitor", "press clipping", "sentiment"]): return "Media Monitoring"
        if any(k in t for k in ["event", "exhibition", "trade fair", "conference"]): return "Event Publicity"
        if any(k in t for k in ["creative", "content", "design", "film", "video", "photography"]): return "Creative & Content"
        if any(k in t for k in ["reputation", "crisis", "brand management"]): return "Reputation Management"
        if any(k in t for k in ["analytics", "reporting", "dashboard", "measurement"]): return "Analytics"
        if any(k in t for k in ["advertising", "media buying", "ad agency"]): return "Campaign Execution"
        if any(k in t for k in ["website", "web development", "web design", "portal development"]): return "Website Development"
        if any(k in t for k in ["seo", "search engine", "search optimization"]): return "SEO Services"
        if any(k in t for k in ["geo", "geospatial", "gis", "geographic"]): return "GEO Services"
        return "Communication Support"


def scrape_all_aggregators():
    import logging
    log = logging.getLogger("Aggregators")
    try:
        results = TenderDetailScraper().scrape()
        log.info(f"TenderDetail.com: {len(results)} tenders")
        return results
    except Exception as e:
        log.error(f"TenderDetail.com failed: {e}")
        return []
