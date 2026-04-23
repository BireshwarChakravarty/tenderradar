import hashlib
import time
import logging
from abc import ABC, abstractmethod
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

    def __init__(self):
        self.logger = logging.getLogger(self.PORTAL_NAME)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        })

    def get(self, url: str, **kwargs) -> Optional[BeautifulSoup]:
        for attempt in range(3):
            try:
                time.sleep(REQUEST_DELAY + attempt * 2)
                resp = self.session.get(url, timeout=20, **kwargs)
                resp.raise_for_status()
                return BeautifulSoup(resp.text, "lxml")
            except Exception as e:
                self.logger.warning(f"Attempt {attempt+1} failed for {url}: {e}")
        self.logger.error(f"All retries exhausted for {url}")
        return None

    def make_tender(self, **kwargs) -> Tender:
        t = Tender(
            scraped_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            **kwargs
        )
        t.compute_id()
        return t

    def _pd(self, s: str) -> str:
        """Parse a date string → YYYY-MM-DD. Returns '' on failure."""
        s = s.strip()
        fmts = [
            "%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y",
            "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
            "%d %B %Y", "%d %b %Y",
            "%Y-%m-%d",
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
