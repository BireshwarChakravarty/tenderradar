import json, logging, smtplib, urllib.request, urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from config import (
    EMAIL_ENABLED, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, ALERT_EMAIL_TO,
    TELEGRAM_ENABLED, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    ALERT_LOG_FILE, TENDERS_FILE, MIN_RELEVANCE_SCORE
)
logger = logging.getLogger("Alerts")

def load_alert_log() -> set:
    if not ALERT_LOG_FILE.exists():
        return set()
    try:
        with open(ALERT_LOG_FILE) as f:
            return set(json.load(f).get("alerted_ids", []))
    except Exception:
        return set()

def save_alert_log(alerted_ids: set) -> None:
    with open(ALERT_LOG_FILE, "w") as f:
        json.dump({"alerted_ids": list(alerted_ids), "updated_at": datetime.utcnow().isoformat()}, f, indent=2)

def load_new_tenders() -> list:
    if not TENDERS_FILE.exists():
        return []
    try:
        with open(TENDERS_FILE) as f:
            data = json.load(f)
        alerted = load_alert_log()
        return [
            t for t in data.get("tenders", [])
            if t.get("id") not in alerted
            and float(t.get("score", 0)) >= MIN_RELEVANCE_SCORE
        ]
    except Exception as e:
        logger.error(f"Failed to load tenders: {e}")
        return []

def run_alerts():
    new_tenders = load_new_tenders()
    if not new_tenders:
        logger.info("No new tenders to alert.")
        return
    logger.info(f"Alerting on {len(new_tenders)} new tenders...")
    alerted = load_alert_log()
    if EMAIL_ENABLED and SMTP_USER and ALERT_EMAIL_TO:
        try:
            _send_email(new_tenders)
            logger.info("Email alert sent.")
        except Exception as e:
            logger.error(f"Email failed: {e}")
    if TELEGRAM_ENABLED and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        for t in new_tenders:
            try:
                _send_telegram(t)
            except Exception as e:
                logger.error(f"Telegram failed for {t.get('id')}: {e}")
    for t in new_tenders:
        alerted.add(t["id"])
    save_alert_log(alerted)
    logger.info(f"Marked {len(new_tenders)} tenders as alerted.")

def _send_email(tenders: list) -> None:
    subject = f"TenderRadar — {len(tenders)} new relevant tender(s) found"
    body_html = _build_email_html(tenders)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"TenderRadar <{SMTP_USER}>"
    msg["To"]      = ALERT_EMAIL_TO
    msg.attach(MIMEText(body_html, "html"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, ALERT_EMAIL_TO, msg.as_string())

def _build_email_html(tenders: list) -> str:
    rows = ""
    for t in tenders:
        score_color = "#10b981" if float(t.get("score", 0)) >= 8 else "#f59e0b" if float(t.get("score", 0)) >= 6 else "#ef4444"
        deadline = t.get("deadline","N/A")
        rows += f"""<tr><td>{t.get('title','')[:100]}</td><td>{t.get('category','')}</td>
          <td>{t.get('value_str','N/A')}</td><td>{deadline}</td>
          <td>{t.get('score',0)}</td><td><a href="{t.get('url','#')}">View</a></td></tr>"""
    return f"<html><body><table>{rows}</table></body></html>"

def _send_telegram(tender: dict) -> None:
    score = tender.get("score", 0)
    score_emoji = "🟢" if score >= 8 else "🟡" if score >= 6 else "🔴"
    text = (
        f"*📋 New Tender — TenderRadar*\n\n"
        f"*{tender.get('title','')[:120]}*\n\n"
        f"🏛 Portal: `{tender.get('portal','')}`\n"
        f"📁 Category: {tender.get('category','')}\n"
        f"💰 Value: {tender.get('value_str', 'N/A')}\n"
        f"⏰ Deadline: {tender.get('deadline', 'N/A')}\n"
        f"{score_emoji} Score: *{score}/10*\n\n"
        f"[View Tender]({tender.get('url','#')})"
    )
    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID, "text": text,
        "parse_mode": "Markdown", "disable_web_page_preview": "true"
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
        if not result.get("ok"):
            raise Exception(f"Telegram API error: {result}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_alerts()
