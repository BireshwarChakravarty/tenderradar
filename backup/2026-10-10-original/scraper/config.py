"""
TenderRadar — Central configuration
Reads from environment variables (GitHub Secrets in production,
or a local .env file for development).

IMPORTANT PATH NOTE
  Data lives at  docs/data/tenders.json  so that GitHub Pages can
  serve it directly from the /docs folder.  All Python modules must
  use the TENDERS_FILE / ALERT_LOG_FILE constants from this file —
  never hard-code the path anywhere else.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Load .env when running locally ────────────────────────────────────
load_dotenv(Path(__file__).parent.parent / ".env")

# ── Core AI ───────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
COMPANY_PROFILE: str   = os.getenv(
    "COMPANY_PROFILE",
    "Communications and PR agency based in India looking for relevant tenders.",
)
MIN_RELEVANCE_SCORE: float = float(os.getenv("MIN_RELEVANCE_SCORE", "6.0"))

# ── HTTP / scraper settings ───────────────────────────────────────────
REQUEST_DELAY: float = float(os.getenv("REQUEST_DELAY_SECONDS", "3"))
USER_AGENT: str = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
)

# ── Portal toggles ────────────────────────────────────────────────────
SCRAPE_GEM:   bool = os.getenv("SCRAPE_GEM",   "true").lower() == "true"
SCRAPE_CPPP:  bool = os.getenv("SCRAPE_CPPP",  "true").lower() == "true"
SCRAPE_BHEL:  bool = os.getenv("SCRAPE_BHEL",  "true").lower() == "true"
SCRAPE_ONGC:  bool = os.getenv("SCRAPE_ONGC",  "true").lower() == "true"
SCRAPE_NTPC:  bool = os.getenv("SCRAPE_NTPC",  "true").lower() == "true"
SCRAPE_STATE: bool = os.getenv("SCRAPE_STATE", "true").lower() == "true"

# Manual portal override via workflow_dispatch input
_override: str = os.getenv("PORTALS_OVERRIDE", "").strip()
if _override:
    _enabled = {p.strip().lower() for p in _override.split(",")}
    SCRAPE_GEM   = "gem"   in _enabled
    SCRAPE_CPPP  = "cppp"  in _enabled
    SCRAPE_BHEL  = "bhel"  in _enabled
    SCRAPE_ONGC  = "ongc"  in _enabled
    SCRAPE_NTPC  = "ntpc"  in _enabled
    SCRAPE_STATE = "state" in _enabled

# ── Email / SMTP ──────────────────────────────────────────────────────
EMAIL_ENABLED:  bool = os.getenv("EMAIL_ENABLED", "true").lower() == "true"
SMTP_HOST:      str  = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT:      int  = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER:      str  = os.getenv("SMTP_USER", "")
SMTP_PASS:      str  = os.getenv("SMTP_PASS", "")
ALERT_EMAIL_TO: str  = os.getenv("ALERT_EMAIL_TO", "")

# ── Telegram ──────────────────────────────────────────────────────────
TELEGRAM_ENABLED:   bool = bool(os.getenv("TELEGRAM_BOT_TOKEN"))
TELEGRAM_BOT_TOKEN: str  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID:   str  = os.getenv("TELEGRAM_CHAT_ID", "")

# ── File paths ────────────────────────────────────────────────────────
# Root of the repo  →  tenderradar/
ROOT_DIR: Path = Path(__file__).parent.parent

# Data lives inside docs/ so GitHub Pages can serve it
# DO NOT change this to ROOT_DIR / "data" — the scraper writes here
# and the dashboard reads from this same path via raw.githubusercontent.com
DATA_DIR: Path = ROOT_DIR / "docs" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

TENDERS_FILE:   Path = DATA_DIR / "tenders.json"
ALERT_LOG_FILE: Path = DATA_DIR / "alert_log.json"
