"""
TenderRadar — TenderDetail.com Scraper
Only source that works from GitHub Actions.
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

                links = soup.select("h2 a[href*='/TenderNotice/']")
                if not links:
                    links = soup.select("a[href*='/TenderNotice/']")

                found = 0
                for link in links:
                    t = self._parse_link(link)
                    if t and t.id not in seen_ids:
                        seen_ids.add(t.id)
                        tenders.append(t)
                        found += 1

                self.logger.info(f"TenderDetail '{keyword}': {found} tenders")

            except Exception as e:
                self.logger.error(f"TenderDetail '{keyword}': {e}")

        self.logger.info(f"TenderDetail total: {len(tenders)}")
        return tenders

    def _parse_link(self, link) -> Tender | None:
        try:
            title = link.get_text(strip=True)
            if not title or len(title) < 8:
                return None

            href = link.get("href", "")
            url  = href if href.startswith("http") else (BASE + href)

            # Walk up the DOM to find the container with Due Date
            container_text = ""
            node = link.parent
            for _ in range(8):
                if node is None:
                    break
                text = node.get_text(" ", strip=True)
                if "Due" in text or "due" in text:
                    container_text = text
                    break
                node = node.parent
            if not container_text:
                # Try getting the full page section around this link
                container_text = link.find_parent(["div","tr","li","section"]).get_text(" ", strip=True) if link.find_parent(["div","tr","li","section"]) else ""

            date_m = re.search(r"Due\s*Date\s*:?\s*([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", container_text, re.IGNORECASE)
            deadline = self._pd(date_m.group(1).strip()) if date_m else self._dd(30)

            val_m = re.search(r"([\d,\.]+)\s*(Crore|Lakh|L|Cr)", container_text, re.IGNORECASE)
            value_str = f"₹{val_m.group(1)} {val_m.group(2)}" if val_m else "N/A"

            ref_m = re.search(r"GEM/\d+/\w/\d+|[\w]+/\d{4}[/-]\w+/\d+", title + " " + url, re.IGNORECASE)
            ref = ref_m.group(0) if ref_m else f"TD-{title[:20].replace(' ','')}"

            portal = self._detect_portal(title + container_text)
            self.PORTAL_NAME = portal

            return self.make_tender(
                title=title[:250], ref_no=ref[:100],
                category=self._cat(title), description=title,
                value_raw=0.0, value_str=value_str,
                deadline=deadline, url=url,
            )
        except Exception as e:
            self.logger.debug(f"TenderDetail parse: {e}")
            return None

    def _detect_portal(self, text: str) -> str:
        t = text.upper()
        if "GEM/" in t:   return "GeM"
        if "CPPP" in t:   return "CPPP"
        if "BHEL" in t:   return "BHEL"
        if "ONGC" in t:   return "ONGC"
        if "NTPC" in t:   return "NTPC"
        return "Govt Portal"

    def _pd(self, s: str) -> str:
        s = s.strip().rstrip(".")
        # Remove leading/trailing noise
        import re as _re
        s = _re.sub(r"[Dd]ue\s*[Dd]ate\s*:?\s*", "", s).strip()
        # Try all common formats
        for fmt in ("%b %d, %Y", "%b %d %Y", "%B %d, %Y", "%B %d %Y",
                    "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y",
                    "%d-%m-%y", "%d %b %Y", "%d %B %Y"):
            try:
                parsed = datetime.strptime(s[:15], fmt)
                # Sanity check — must be in 2024-2027
                if 2024 <= parsed.year <= 2027:
                    return parsed.strftime("%Y-%m-%d")
            except: pass
        return self._dd(30)

    def _dd(self, d: int) -> str:
        return (datetime.utcnow() + timedelta(days=d)).strftime("%Y-%m-%d")

    def _cat(self, t: str) -> str:
        t = t.lower()
        if any(k in t for k in ["pr ", "public relation", "communication agency", "empanelment", "media relation"]): return "PR & Communications"
        if any(k in t for k in ["social media", "digital media management"]): return "Social Media"
        if any(k in t for k in ["campaign", "awareness campaign", "outreach campaign"]): return "Campaign Execution"
        if any(k in t for k in ["media monitor", "press clipping", "sentiment"]): return "Media Monitoring"
        if any(k in t for k in ["event", "exhibition", "trade fair", "conference"]): return "Event Publicity"
        if any(k in t for k in ["creative", "content", "design", "film", "video", "photography"]): return "Creative & Content"
        if any(k in t for k in ["reputation", "crisis", "brand management"]): return "Reputation Management"
        if any(k in t for k in ["analytics", "reporting", "dashboard", "measurement"]): return "Analytics"
        if any(k in t for k in ["advertising", "media buying", "ad agency"]): return "Campaign Execution"
        if any(k in t for k in ["website", "web development", "web design", "portal development"]): return "Website Development"
        if any(k in t for k in ["seo", "search engine", "search optimization"]): return "SEO Services"
        if any(k in t for k in ["geo", "geospatial", "gis", "geographic", "location service"]): return "GEO Services"
        return "Communication Support"


def scrape_all_aggregators() -> list[Tender]:
    import logging
    log = logging.getLogger("Aggregators")
    try:
        results = TenderDetailScraper().scrape()
        log.info(f"TenderDetail.com: {len(results)} tenders")
        return results
    except Exception as e:
        log.error(f"TenderDetail.com failed: {e}")
        return []
