"""
TenderRadar — Base scraper
Shared HTTP session, retry logic, and Tender dataclass.
"""
import hashlib
import random
import time
import logging
from abc import ABC
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional
import re
import requests
from bs4 import BeautifulSoup
from config import USER_AGENT, REQUEST_DELAY


@dataclass
class Tender:
    id:          str   = ""
    portal:      str   = ""
    title:       str   = ""
    ref_no:      str   = ""
    category:    str   = ""
    description: str   = ""
    value_raw:   float = 0.0
    value_str:   str   = ""
    deadline:    str   = ""
    url:         str   = ""
    status:      str   = "New"
    score:       float = 0.0
    summary:     str   = ""
    scraped_at:  str   = ""
    alerted:     bool  = False

    def compute_id(self):
        raw = f"{self.portal}|{self.ref_no}|{self.title}".lower().strip()
        self.id = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return self

    def to_dict(self):
        return asdict(self)


class BaseScraper(ABC):
    PORTAL_NAME: str = ""

    # Extra headers that make requests look like a real browser
    _HEADERS = {
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-IN,en-GB;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control":   "max-age=0",
    }

    def __init__(self):
        self.logger = logging.getLogger(self.PORTAL_NAME)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            **self._HEADERS,
        })

    def get(self, url: str, **kwargs) -> Optional[BeautifulSoup]:
        """
        GET with smart retry + exponential back-off.
        - 503 / 429: wait 45 s then 90 s before retrying (server is throttling)
        - Timeout / other: wait 5 s then 12 s
        - Returns None after 3 failed attempts.
        """
        for attempt in range(3):
            try:
                # Jittered delay: base delay + random 0-3 s so requests don't
                # look metronomic to the server
                delay = REQUEST_DELAY + random.uniform(0, 3)
                if attempt > 0:
                    delay += attempt * 2          # extra back-off on retries
                time.sleep(delay)

                resp = self.session.get(url, timeout=25, **kwargs)

                # Rate-limit / service unavailable — long back-off
                if resp.status_code in (429, 503):
                    wait = 45 * (attempt + 1)     # 45 s, then 90 s
                    self.logger.warning(
                        "HTTP %d on attempt %d — backing off %ds: %s",
                        resp.status_code, attempt + 1, wait, url
                    )
                    time.sleep(wait)
                    continue                       # retry without raising

                resp.raise_for_status()
                return BeautifulSoup(resp.text, "lxml")

            except requests.exceptions.Timeout:
                self.logger.warning("Timeout attempt %d: %s", attempt + 1, url)
                time.sleep(8 + attempt * 4)
            except requests.exceptions.RequestException as e:
                self.logger.warning("Attempt %d failed: %s — %s", attempt + 1, url, e)
                time.sleep(5 + attempt * 3)

        self.logger.error("All retries exhausted: %s", url)
        return None

    def make_tender(self, **kwargs) -> Tender:
        t = Tender(
            scraped_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            **kwargs,
        )
        t.compute_id()
        return t

    def _pd(self, s: str) -> str:
        """Parse a date string → YYYY-MM-DD. Returns '' on failure."""
        s = s.strip()
        fmts = [
            "%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y",
            "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
            "%d %B %Y",  "%d %b %Y",  "%Y-%m-%d",
        ]
        for fmt in fmts:
            try:
                return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return ""

    def _dd(self, days: int = 30) -> str:
        """Default deadline = today + N days."""
        return (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d")
