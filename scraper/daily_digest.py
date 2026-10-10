"""
TenderRadar: morning digest (8 AM IST).

  Closing this week   recommended tenders with a deadline in the next 7 days
  New since yesterday recommended tenders first seen in the last 24 hours
  Still open          a count of every other recommended open tender

Nothing is sent when there is nothing in the first two sections.
"""
import logging
import sys
from datetime import datetime, timedelta, timezone

from dates import days_until, is_open, now_ist
from notify import email_page, email_section, send_email, send_telegram, telegram_message
from relevance import is_recommended
from store import load

log = logging.getLogger("Digest")


def build() -> dict:
    tenders, _ = load()
    rec = [t for t in tenders.values() if is_recommended(t) and is_open(t.deadline) is not False]
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")

    closing = sorted((t for t in rec if (n := days_until(t.deadline)) is not None and n <= 7),
                     key=lambda t: t.deadline)
    closing_ids = {t.id for t in closing}
    new = sorted((t for t in rec if t.first_seen >= since and t.id not in closing_ids),
                 key=lambda t: -(t.score or 0))
    return {"closing": closing, "new": new, "open": len(rec)}


def run() -> None:
    g = build()
    if not g["closing"] and not g["new"]:
        log.info("Nothing closing this week and nothing new; no digest today.")
        return

    date_str = f"{now_ist():%A}, {now_ist().day} {now_ist():%B}"
    summary = f"{len(g['closing'])} closing this week · {len(g['new'])} new · {g['open']} open in total"
    log.info("Digest: %s", summary)

    body = (email_section("Closing this week", g["closing"], "Deadlines in the next 7 days")
            + email_section("New since yesterday", g["new"]))
    send_email(f"TenderRadar digest, {now_ist().day} {now_ist():%b}: {summary}",
               email_page("Your morning digest", f"{date_str} · {summary}", body))
    send_telegram(telegram_message(f"☀️ TenderRadar · {date_str}\n{summary}",
                                   [("⏰ Closing this week", g["closing"]),
                                    ("✨ New since yesterday", g["new"])]))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    run()
