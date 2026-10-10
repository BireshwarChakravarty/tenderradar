"""
TenderRadar — email and Telegram delivery, plus the shared message templates
used by alerts.py (new tenders) and daily_digest.py (morning summary).
"""
import html
import json
import logging
import smtplib
import urllib.parse
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import (ALERT_EMAIL_TO, DASHBOARD_URL, EMAIL_ENABLED, SMTP_HOST, SMTP_PASS,
                    SMTP_PORT, SMTP_USER, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED)
from dates import days_until, from_str
from models import Tender

log = logging.getLogger("Notify")

E = html.escape


# ── Formatting ────────────────────────────────────────────────────────

def fmt_inr(v: float | None) -> str:
    if not v:
        return ""
    if v >= 1e7:
        return f"₹{v / 1e7:.2f}".rstrip("0").rstrip(".") + " Cr"
    if v >= 1e5:
        return f"₹{v / 1e5:.2f}".rstrip("0").rstrip(".") + " L"
    return f"₹{v:,.0f}"


def fmt_closing(deadline: str) -> str:
    """'Tue 14 Oct · 4 days left', 'Closes today', 'Deadline not stated'."""
    n = days_until(deadline)
    if n is None:
        return "Deadline not stated"
    dt = from_str(deadline)
    d = f"{dt:%a} {dt.day} {dt:%b}"
    if n < 0:
        return f"Closed {d}"
    if n == 0:
        return f"Closes today ({d})"
    if n == 1:
        return f"Closes tomorrow ({d})"
    return f"{d} · {n} days left"


def title_of(t: Tender) -> str:
    return t.headline or t.title


def where_of(t: Tender) -> str:
    return " · ".join(x for x in (t.authority, t.location) if x)


# ── Email ─────────────────────────────────────────────────────────────

_REC_COLOURS = {"Bid": ("#047857", "#ecfdf5"), "Watch": ("#b45309", "#fffbeb"), "Skip": ("#475569", "#f1f5f9")}


def _chip(text: str, fg: str, bg: str) -> str:
    return (f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
            f'background:{bg};color:{fg};font-size:12px;font-weight:600">{E(text)}</span>')


def email_card(t: Tender) -> str:
    fg, bg = _REC_COLOURS.get(t.recommendation, ("#475569", "#f1f5f9"))
    n = days_until(t.deadline)
    urgent = n is not None and 0 <= n <= 3
    chips = []
    if t.score is not None:
        chips.append(_chip(f"{t.score:.1f}/10 · {t.recommendation or 'Unrated'}", fg, bg))
    chips.append(_chip(fmt_closing(t.deadline), "#b91c1c" if urgent else "#334155",
                       "#fef2f2" if urgent else "#f1f5f9"))
    if t.value_inr:
        chips.append(_chip(fmt_inr(t.value_inr), "#334155", "#f1f5f9"))
    reason = f'<p style="margin:8px 0 0;color:#475569;font-size:13px;line-height:1.5">{E(t.reason)}</p>' if t.reason else ""
    return f"""
      <tr><td style="padding:16px 0;border-bottom:1px solid #e2e8f0">
        <a href="{E(t.url)}" style="color:#0f172a;font-size:15px;font-weight:600;text-decoration:none;line-height:1.4">{E(title_of(t))}</a>
        <div style="color:#64748b;font-size:13px;margin-top:3px">{E(where_of(t)) or "&nbsp;"}</div>
        <div style="margin-top:8px">{" ".join(chips)}</div>
        {reason}
      </td></tr>"""


def email_section(title: str, tenders: list[Tender], note: str = "") -> str:
    if not tenders:
        return ""
    note_html = f'<div style="color:#64748b;font-size:13px;margin-top:2px">{E(note)}</div>' if note else ""
    return f"""
    <tr><td style="padding:24px 28px 0">
      <div style="font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#4338ca">{E(title)}</div>
      {note_html}
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(email_card(t) for t in tenders)}</table>
    </td></tr>"""


def email_page(heading: str, subheading: str, body_rows: str) -> str:
    button = (f'<a href="{E(DASHBOARD_URL)}" style="display:inline-block;background:#4338ca;color:#fff;'
              f'padding:10px 18px;border-radius:8px;font-size:14px;font-weight:600;text-decoration:none">'
              f'Open dashboard</a>') if DASHBOARD_URL else ""
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:24px 12px">
<tr><td align="center">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e2e8f0">
    <tr><td style="background:#0f172a;padding:20px 28px">
      <span style="color:#ffffff;font-size:16px;font-weight:700;letter-spacing:-.01em">TenderRadar</span>
    </td></tr>
    <tr><td style="padding:24px 28px 0">
      <div style="font-size:20px;font-weight:700;color:#0f172a">{E(heading)}</div>
      <div style="color:#64748b;font-size:14px;margin-top:4px">{E(subheading)}</div>
    </td></tr>
    {body_rows}
    <tr><td style="padding:24px 28px 28px">{button}
      <p style="color:#94a3b8;font-size:12px;margin:16px 0 0;line-height:1.5">
        Scores and recommendations are AI estimates against your company profile. Always check the tender document before bidding.
      </p>
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""


def send_email(subject: str, html_body: str) -> bool:
    if not EMAIL_ENABLED:
        log.info("Email not configured — skipping")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"TenderRadar <{SMTP_USER}>"
    msg["To"] = ALERT_EMAIL_TO
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_USER, [a.strip() for a in ALERT_EMAIL_TO.split(",")], msg.as_string())
    except (smtplib.SMTPException, OSError) as e:
        log.error("Email failed: %s", e)
        return False
    log.info("Email sent: %s", subject)
    return True


# ── Telegram ──────────────────────────────────────────────────────────

def telegram_line(t: Tender) -> str:
    score = f"<b>{t.score:.1f}</b> {E(t.recommendation)} · " if t.score is not None else ""
    value = f" · {E(fmt_inr(t.value_inr))}" if t.value_inr else ""
    where = f"\n{E(where_of(t))}" if where_of(t) else ""
    return (f'• <a href="{E(t.url)}">{E(title_of(t)[:110])}</a>{where}\n'
            f"  {score}{E(fmt_closing(t.deadline))}{value}")


def telegram_message(heading: str, sections: list[tuple[str, list[Tender]]], limit: int = 8) -> str:
    parts = [f"<b>{E(heading)}</b>"]
    for title, tenders in sections:
        if not tenders:
            continue
        parts.append(f"\n<b>{E(title)}</b>" if title else "")
        parts += [telegram_line(t) for t in tenders[:limit]]
        if len(tenders) > limit:
            parts.append(f"<i>…and {len(tenders) - limit} more</i>")
    if DASHBOARD_URL:
        parts.append(f'\n<a href="{E(DASHBOARD_URL)}">Open dashboard →</a>')
    text = "\n".join(parts)
    return text if len(text) <= 4000 else text[:3990] + "…"


def send_telegram(text: str) -> bool:
    if not TELEGRAM_ENABLED:
        log.info("Telegram not configured — skipping")
        return False
    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            ok = json.loads(r.read()).get("ok")
    except (OSError, ValueError) as e:
        log.error("Telegram failed: %s", e)
        return False
    if not ok:
        log.error("Telegram API rejected the message")
        return False
    log.info("Telegram message sent")
    return True
