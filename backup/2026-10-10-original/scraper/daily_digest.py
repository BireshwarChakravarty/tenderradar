"""
TenderRadar — Daily Digest
Sends a morning summary of active pipeline tenders + anything closing soon.
Runs every day at 8 AM IST via GitHub Actions (daily_digest.yml).

FIXED BUGS:
  - high_score tenders now appear in BOTH email AND Telegram
  - Telegram message no longer sends a bare header when closing/pipeline are empty
  - Early-exit logic is consistent: nothing is sent if there is truly nothing to report
  - TENDERS_FILE path imported from config (single source of truth)
"""

import json
import logging
import smtplib
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ── Bootstrap path so we can import sibling modules ───────────────────
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    ALERT_EMAIL_TO,
    EMAIL_ENABLED,
    MIN_RELEVANCE_SCORE,
    SMTP_HOST,
    SMTP_PASS,
    SMTP_PORT,
    SMTP_USER,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_ENABLED,
    TENDERS_FILE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("DailyDigest")


# ── Data loading ───────────────────────────────────────────────────────

def load_pipeline_tenders() -> dict[str, list]:
    """
    Reads tenders.json and buckets tenders into three groups:
      closing   — deadline within 7 days, not Won/Lost
      pipeline  — status is Watching or Bid Submitted
      high_score — score >= 8.0 and status is New
    Returns an empty dict if file is missing or malformed.
    """
    if not TENDERS_FILE.exists():
        logger.warning("TENDERS_FILE not found: %s", TENDERS_FILE)
        return {}

    try:
        with open(TENDERS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to read tenders file: %s", exc)
        return {}

    tenders = data.get("tenders", [])
    if not tenders:
        logger.info("tenders.json is empty — nothing to digest.")
        return {}

    today = date.today()

    pipeline: list[dict] = []
    high_score: list[dict] = []
    closing: list[dict] = []

    for t in tenders:
        status = t.get("status", "New")

        # Pipeline board items
        if status in ("Watching", "Bid Submitted"):
            pipeline.append(t)

        # High-fit new tenders
        try:
            score = float(t.get("score", 0))
        except (TypeError, ValueError):
            score = 0.0
        if score >= 8.0 and status == "New":
            high_score.append(t)

        # Closing soon — skip Won/Lost
        if status in ("Won", "Lost"):
            continue
        raw_deadline = t.get("deadline", "")
        if not raw_deadline:
            continue
        try:
            deadline_date = datetime.strptime(raw_deadline, "%Y-%m-%d").date()
            days_left = (deadline_date - today).days
            if 0 <= days_left <= 7:
                t["_days_left"] = days_left
                closing.append(t)
        except ValueError:
            pass  # unparseable deadline — skip

    closing.sort(key=lambda t: t.get("_days_left", 99))

    return {
        "pipeline":   pipeline,
        "high_score": high_score[:5],
        "closing":    closing[:5],
    }


# ── Email builder ──────────────────────────────────────────────────────

def _build_digest_email(groups: dict[str, list]) -> str:
    """Builds the full HTML email body for the daily digest."""

    def section(title: str, tenders: list, color: str) -> str:
        if not tenders:
            return ""
        rows = ""
        for t in tenders:
            days = t.get("_days_left")
            deadline_str = (
                f"{t.get('deadline', '')} ({days}d left)"
                if days is not None
                else t.get("deadline", "N/A")
            )
            score = t.get("score", 0)
            score_html = (
                f'<span style="background:#10b98122;color:#10b981;padding:2px 7px;'
                f'border-radius:10px;font-size:11px;font-weight:700">{score}</span>'
                if score
                else ""
            )
            rows += f"""
            <tr style="border-bottom:1px solid #f1f5f9">
              <td style="padding:10px 8px">
                <div style="font-weight:600;color:#1e293b;font-size:13px">
                  {t.get('title', '')[:90]}
                </div>
                <div style="color:#94a3b8;font-size:11px;margin-top:2px">
                  {t.get('portal', '')} &middot; {t.get('ref_no', '')}
                </div>
              </td>
              <td style="padding:10px 8px;color:#64748b;font-size:12px;white-space:nowrap">
                {t.get('value_str', 'N/A')}
              </td>
              <td style="padding:10px 8px;color:#ef4444;font-size:12px;white-space:nowrap">
                {deadline_str}
              </td>
              <td style="padding:10px 8px">{score_html}</td>
              <td style="padding:10px 8px">
                <span style="background:{color}22;color:{color};padding:2px 8px;
                  border-radius:10px;font-size:11px;font-weight:600">
                  {t.get('status', 'New')}
                </span>
              </td>
            </tr>"""

        return f"""
        <div style="margin-bottom:28px">
          <h2 style="font-size:13px;font-weight:700;color:{color};text-transform:uppercase;
            letter-spacing:.6px;margin:0 0 12px;padding-bottom:8px;
            border-bottom:2px solid {color}22">{title}</h2>
          <table style="width:100%;border-collapse:collapse;font-size:13px">{rows}</table>
        </div>"""

    closing_html    = section("⏰ Closing This Week",        groups.get("closing",    []), "#ef4444")
    pipeline_html   = section("📌 In Pipeline",              groups.get("pipeline",   []), "#8b5cf6")
    high_score_html = section("⭐ High-Fit New Tenders",     groups.get("high_score", []), "#10b981")

    body = closing_html + pipeline_html + high_score_html

    total = sum(len(v) for v in groups.values())
    date_str = datetime.now().strftime("%A, %d %B %Y")

    return f"""<!DOCTYPE html>
<html lang="en">
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
             background:#f8fafc;padding:20px;margin:0">
  <div style="max-width:760px;margin:0 auto;background:white;border-radius:12px;
              overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.1)">

    <!-- Header -->
    <div style="background:#0a0f1e;padding:22px 28px;display:flex;align-items:center;gap:10px">
      <div style="width:10px;height:10px;background:#f59e0b;border-radius:50%;flex-shrink:0"></div>
      <h1 style="color:white;margin:0;font-size:18px;font-weight:700">TenderRadar</h1>
      <span style="color:#64748b;font-size:13px;margin-left:auto">Daily Digest</span>
    </div>

    <!-- Sub-header -->
    <div style="padding:14px 28px;border-bottom:1px solid #e2e8f0;background:#fafafa">
      <p style="color:#475569;font-size:13px;margin:0">
        {date_str} &nbsp;&middot;&nbsp;
        <strong style="color:#0f172a">{total} item(s)</strong> requiring your attention
      </p>
    </div>

    <!-- Body -->
    <div style="padding:24px 28px">
      {body if body else
        '<p style="color:#94a3b8;text-align:center;padding:32px 0;font-size:14px">'
        'No active tenders today — check back tomorrow.</p>'}
    </div>

    <!-- Footer -->
    <div style="background:#f8fafc;padding:14px 28px;border-top:1px solid #e2e8f0">
      <p style="color:#94a3b8;font-size:11px;margin:0">
        TenderRadar &middot; Automated daily digest &middot; Fit scores are AI estimates
      </p>
    </div>

  </div>
</body>
</html>"""


# ── Send functions ─────────────────────────────────────────────────────

def _send_digest_email(groups: dict[str, list]) -> None:
    """Sends the HTML digest via SMTP."""
    html = _build_digest_email(groups)
    total = sum(len(v) for v in groups.values())

    msg = MIMEMultipart("alternative")
    msg["Subject"] = (
        f"TenderRadar Daily Digest — {datetime.now().strftime('%d %b %Y')} "
        f"({total} item{'s' if total != 1 else ''})"
    )
    msg["From"] = f"TenderRadar <{SMTP_USER}>"
    msg["To"]   = ALERT_EMAIL_TO
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, ALERT_EMAIL_TO, msg.as_string())

    logger.info("Digest email sent to %s (%d items).", ALERT_EMAIL_TO, total)


def _send_digest_telegram(groups: dict[str, list]) -> None:
    """
    Sends a concise Telegram digest.
    NOW includes high_score section so the message is never a bare header.
    """
    closing    = groups.get("closing", [])
    pipeline   = groups.get("pipeline", [])
    high_score = groups.get("high_score", [])

    lines: list[str] = [
        f"*📋 TenderRadar — Daily Digest*",
        f"_{datetime.now().strftime('%A, %d %B %Y')}_\n",
    ]

    if closing:
        lines.append("*⏰ Closing this week:*")
        for t in closing:
            days = t.get("_days_left", "?")
            title = t.get("title", "")[:55]
            lines.append(f"• {title}… — {t.get('deadline', '')} ({days}d)")
        lines.append("")

    if pipeline:
        lines.append(f"*📌 In pipeline:* {len(pipeline)} tender(s)")
        for t in pipeline[:3]:
            lines.append(f"  › {t.get('title', '')[:50]}… [{t.get('status', '')}]")
        lines.append("")

    if high_score:
        lines.append("*⭐ High-fit new tenders:*")
        for t in high_score:
            score = t.get("score", "?")
            title = t.get("title", "")[:55]
            lines.append(f"• [{score}] {title}…")
        lines.append("")

    if not closing and not pipeline and not high_score:
        lines.append("_No actionable tenders today._")

    payload = urllib.parse.urlencode(
        {
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       "\n".join(lines),
            "parse_mode": "Markdown",
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        data=payload,
    )
    urllib.request.urlopen(req, timeout=15)
    logger.info("Digest Telegram message sent.")


# ── Orchestrator ───────────────────────────────────────────────────────

def run() -> None:
    logger.info("=" * 55)
    logger.info("TenderRadar Daily Digest — starting")
    logger.info("Reading tenders from: %s", TENDERS_FILE)
    logger.info("=" * 55)

    groups = load_pipeline_tenders()
    total  = sum(len(v) for v in groups.values())

    if total == 0:
        logger.info("Nothing to digest today — skipping all notifications.")
        return

    logger.info(
        "Digest summary: %d closing, %d pipeline, %d high-score",
        len(groups.get("closing", [])),
        len(groups.get("pipeline", [])),
        len(groups.get("high_score", [])),
    )

    # ── Email ──────────────────────────────────────────────────────
    if EMAIL_ENABLED and SMTP_USER and SMTP_PASS and ALERT_EMAIL_TO:
        try:
            _send_digest_email(groups)
        except Exception as exc:
            logger.error("Digest email failed: %s", exc)
    else:
        logger.info("Email disabled or credentials not set — skipping.")

    # ── Telegram ───────────────────────────────────────────────────
    if TELEGRAM_ENABLED and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            _send_digest_telegram(groups)
        except Exception as exc:
            logger.error("Digest Telegram failed: %s", exc)
    else:
        logger.info("Telegram disabled or credentials not set — skipping.")

    logger.info("Daily digest complete.")


if __name__ == "__main__":
    run()
