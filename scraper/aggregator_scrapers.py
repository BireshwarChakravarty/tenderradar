"""
TenderRadar — TenderDetail.com Scraper
Structure per tender on listing page:
  <h2>location info</h2>
  <a href="/TenderNotice/...">title</a>
  "Due Date : Apr 11, 2026"   ← plain text sibling after the link
  "Tender Value : ..."
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

                # Each tender: h2 (location) > sibling a (link) > sibling text (Due Date)
                # Find all TenderNotice links
                links = soup.select("a[href*='/TenderNotice/']")
                # Exclude "View Notice" duplicates — keep only the descriptive ones
                links = [l for l in links if len(l.get_text(strip=True)) > 15]

                found = 0
                for link in links:
                    t = self._parse_tender(link)
                    if t and t.id not in seen_ids:
                        seen_ids.add(t.id)
                        tenders.append(t)
                        found += 1

                self.logger.info(f"TenderDetail '{keyword}': {found} tenders")

            except Exception as e:
                self.logger.error(f"TenderDetail '{keyword}': {e}")

        self.logger.info(f"TenderDetail total: {len(tenders)}")
        return tenders

    def _parse_tender(self, link) -> Tender | None:
        try:
            title = link.get_text(strip=True)
            if not title or len(title) < 8:
                return None

            href = link.get("href", "")
            url  = href if href.startswith("http") else (BASE + href)

            # ── Get Due Date ─────────────────────────────────────
            # The due date is a text node that appears AFTER the link element
            # at the same level (sibling). We scan next siblings for it.
            deadline = self._dd(30)  # fallback

            # Method 1: check next siblings of the link itself
            for sibling in link.next_siblings:
                text = sibling.get_text(strip=True) if hasattr(sibling, 'get_text') else str(sibling).strip()
                if not text:
                    continue
                if "Due Date" in text or "due date" in text.lower():
                    m = re.search(r"[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}", text)
                    if m:
                        deadline = self._pd(m.group(0))
                        break
                    m2 = re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", text)
                    if m2:
                        deadline = self._pd(m2.group(0))
                        break
                # Stop if we hit another tender link
                if hasattr(sibling, 'find') and sibling.find("a", href=lambda h: h and "/TenderNotice/" in h):
                    break

            # Method 2: if not found, check parent's text for Due Date
            if deadline == self._dd(30):
                parent = link.parent
                if parent:
                    parent_text = parent.get_text(" ", strip=True)
                    m = re.search(r"Due\s*Date\s*:?\s*([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", parent_text, re.IGNORECASE)
                    if m:
                        deadline = self._pd(m.group(1).strip())

            # Method 3: check grandparent container
            if deadline == self._dd(30):
                gp = link.parent.parent if link.parent else None
                if gp:
                    gp_text = gp.get_text(" ", strip=True)
                    m = re.search(r"Due\s*Date\s*:?\s*([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", gp_text, re.IGNORECASE)
                    if m:
                        deadline = self._pd(m.group(1).strip())

            # ── Get Value ─────────────────────────────────────────
            value_str = "N/A"
            for sibling in link.next_siblings:
                text = sibling.get_text(strip=True) if hasattr(sibling, 'get_text') else str(sibling).strip()
                if not text:
                    continue
                m = re.search(r"([\d,\.]+)\s*(Crore|Lakh|L\b|Cr\b)", text, re.IGNORECASE)
                if m:
                    value_str = f"₹{m.group(1)} {m.group(2)}"
                    break
                if "Tender Value" in text:
                    break

            # ── Ref number ────────────────────────────────────────
            # Extract from link title attribute or URL
            title_attr = link.get("title", "")
            ref_m = re.search(r"GEM/\d+/\w/\d+|[\w]+/\d{4}[-/]\w+|[\w/\-]{5,}/\d{4}", title_attr or url, re.IGNORECASE)
            ref = ref_m.group(0)[:100] if ref_m else f"TD-{title[:20].replace(' ','')}"

            # ── Portal from ref ───────────────────────────────────
            portal = self._detect_portal(title_attr + " " + title)
            self.PORTAL_NAME = portal

            return self.make_tender(
                title=title[:250],
                ref_no=ref,
                category=self._cat(title),
                description=title,
                value_raw=0.0,
                value_str=value_str,
                deadline=deadline,
                url=url,
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
        for fmt in ("%b %d, %Y", "%b %d %Y", "%B %d, %Y", "%B %d %Y",
                    "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y",
                    "%d-%m-%y", "%d %b %Y", "%d %B %Y"):
            try:
                parsed = datetime.strptime(s[:20], fmt)
                if 2024 <= parsed.year <= 2028:
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
        if any(k in t for k in ["geo", "geospatial", "gis", "geographic"]): return "GEO Services"
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
