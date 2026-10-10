"""
TenderRadar: configuration.

Everything comes from environment variables: GitHub Secrets in Actions, or a
local .env file during development. Defaults are sensible for a PR and
communications agency.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _float(name: str, default: float) -> float:
    return float(os.getenv(name) or default)


def _int(name: str, default: int) -> int:
    return int(os.getenv(name) or default)


# ── AI scoring ────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL          = os.getenv("AI_MODEL") or "claude-haiku-5-5"
COMPANY_PROFILE   = os.getenv("COMPANY_PROFILE") or (
    "Communications and PR agency based in India: public relations, media relations, "
    "social media management, digital marketing, media monitoring, content and campaigns "
    "for government and PSU clients."
)
# Tenders scoring at least this (and not recommended "Skip") are "relevant":
# they trigger alerts and appear in the dashboard's Recommended view.
MIN_RELEVANCE_SCORE = _float("MIN_RELEVANCE_SCORE", 6.0)

# ── Scraping ──────────────────────────────────────────────────────────
# Detail pages take ~6 s each; this keeps a run well inside the 45-minute
# job limit. Anything left over is picked up on the next run.
MAX_DETAIL_PAGES = _int("MAX_DETAIL_PAGES", 150)
# Re-check open tenders this often, to catch extended deadlines (corrigenda)
REFRESH_DAYS     = _int("REFRESH_DAYS", 3)
USER_AGENT = os.getenv("USER_AGENT") or (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ── Retention ─────────────────────────────────────────────────────────
KEEP_CLOSED_DAYS = _int("KEEP_CLOSED_DAYS", 30)   # closed tenders stay visible this long
STALE_DAYS       = _int("STALE_DAYS", 45)         # no-deadline tenders not seen for this long are dropped

# ── Notifications ─────────────────────────────────────────────────────
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "")

SMTP_HOST      = os.getenv("SMTP_HOST") or "smtp.gmail.com"
SMTP_PORT      = _int("SMTP_PORT", 587)
SMTP_USER      = os.getenv("SMTP_USER", "")
SMTP_PASS      = os.getenv("SMTP_PASS", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")
EMAIL_ENABLED  = bool(SMTP_USER and SMTP_PASS and ALERT_EMAIL_TO)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED   = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

# ── Files ─────────────────────────────────────────────────────────────
# Data lives inside docs/ so GitHub Pages serves it next to the dashboard.
DATA_DIR = ROOT_DIR / "docs" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TENDERS_FILE   = DATA_DIR / "tenders.json"
ALERT_LOG_FILE = DATA_DIR / "alert_log.json"
REJECTED_FILE  = DATA_DIR / "rejected.json"   # notices not worth storing, so they aren't re-fetched
