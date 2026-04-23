"""
TenderRadar — TenderDetail.com Scraper
tenderdetail.com is accessible from GitHub Actions and aggregates
tenders from GeM, CPPP, and all state portals.
URL pattern: /Indian-tender/{keyword}-tenders
"""
import re
import time
from datetime import datetime, timedelta
from base_scraper import BaseScraper, Tender


# PR/Comms specific search keywords on tenderdetail.com
# NOTE: "geo-services" removed — it pulls geotechnical/GIS tenders, not PR-relevant
# Added: photography-services, film-production, outdoor-advertising
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
    "photography-services",
    "film-production",
    "outdoor-advertising",
    "brand-promotion",
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

    def _parse_link(self, link) -> "Tender | None":
        try:
            title = link.get_text(strip=True)
            if not title or len(title) < 8:
                return None

            href = link.get("href", "")
            url  = href if href.startswith("http") else (BASE + href)

            parent = link.parent
            for _ in range(4):
                if parent is None:
                    break
                parent = parent.parent

            container_text = parent.get_text(" ", strip=True) if parent else ""

            # Parse due date — try common Indian tender date formats
            date_m = re.search(
                r"Due\s*Date\s*:?\s*([A-Za-z]+\s+\d+,?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
                container_text, re.IGNORECASE
            )
            deadline = self._pd(date_m.group(1)) if date_m else ""

            # Parse value
            val_m = re.search(
                r"([\d,\.]+)\s*(Crore|Lakh|L|Cr)", container_text, re.IGNORECASE
            )
            value_str = f"₹{val_m.group(1)} {val_m.group(2)}" if val_m else "N/A"

            # Extract ref number
            ref_m = re.search(
                r"GEM/\d+/\w/\d+|[\w]+/\d{4}[/-]\w+/\d+", title + " " + url, re.IGNORECASE
            )
            ref = ref_m.group(0) if ref_m else f"TD-{abs(hash(title))%100000}"

            portal = self._detect_portal(title + " " + container_text)

            self.PORTAL_NAME = portal
            return self.make_tender(
                title=title[:250],
                ref_no=ref[:100],
                category=self._cat(title),
                description=title,
                value_raw=0.0,
                value_str=value_str,
                deadline=deadline,
                url=url,
            )
        except Exception as e:
            self.logger.debug(f"TenderDetail parse error: {e}")
            return None

    def _detect_portal(self, text: str) -> str:
        t = text.upper()
        if "GEM/" in t or "GEM/2" in t:  return "GeM"
        if "CPPP" in t:                   return "CPPP"
        if "ONGC" in t:                   return "ONGC"
        if "NTPC" in t:                   return "NTPC"
        if "IRCTC" in t:                  return "IRCTC"
        if "BHEL" in t:                   return "BHEL"
        if "IRCON" in t:                  return "IRCON"
        if "NBCC" in t:                   return "NBCC"
        return "Govt Portal"

    def _pd(self, s: str) -> str:
        """Parse a date string into YYYY-MM-DD. Returns empty string if unparseable."""
        s = s.strip()
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y",
                    "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y"):
            try:
                return datetime.strptime(s[:len(fmt.replace('%Y','0000').replace('%m','00').replace('%d','00').replace('%b','AAA').replace('%B','AAAAAAAA'))], fmt).strftime("%Y-%m-%d")
            except Exception:
                pass
        # Try a simpler approach for edge cases
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
            except Exception:
                pass
        return ""  # empty string — dashboard will show "N/A" cleanly without NaNd

    def _dd(self, d: int) -> str:
        return (datetime.utcnow() + timedelta(days=d)).strftime("%Y-%m-%d")

    def _cat(self, t: str) -> str:
        t = t.lower()
        if any(k in t for k in ["pr ", "public relation", "communication agency", "empanelment",
                                  "media relation", "press release", "spokesperson"]):
            return "PR & Communications"
        if any(k in t for k in ["social media", "digital media management", "facebook",
                                  "instagram", "twitter"]):
            return "Social Media"
        if any(k in t for k in ["campaign", "awareness campaign", "outreach campaign",
                                  "iec campaign", "information education"]):
            return "Campaign Execution"
        if any(k in t for k in ["media monitor", "press clipping", "news monitor",
                                  "sentiment", "media tracking"]):
            return "Media Monitoring"
        if any(k in t for k in ["event", "exhibition", "trade fair", "conference",
                                  "seminar", "ceremony"]):
            return "Event Publicity"
        if any(k in t for k in ["creative", "content", "design", "video", "film",
                                  "photo", "production", "animation"]):
            return "Creative & Content"
        if any(k in t for k in ["website", "web portal", "web development", "seo",
                                  "digital platform"]):
            return "Digital & Web"
        if any(k in t for k in ["advertising", "ad agency", "media buying", "outdoor",
                                  "hoarding", "banner", "flex"]):
            return "Advertising"
        if any(k in t for k in ["reputation", "crisis", "brand management", "brand promotion"]):
            return "Reputation Management"
        if any(k in t for k in ["analytics", "reporting", "dashboard", "measurement"]):
            return "Analytics"
        return "Communication Support"


def scrape_all_aggregators() -> list[Tender]:
    import logging
    log = logging.getLogger("Aggregators")
    try:
        scraper = TenderDetailScraper()
        results = scraper.scrape()
        log.info(f"TenderDetail.com: {len(results)} tenders")
        return results
    except Exception as e:
        log.error(f"TenderDetail.com failed: {e}")
        return []
