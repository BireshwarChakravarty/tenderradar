"""
TenderRadar — instant alerts.

Runs after each scrape. Sends one email and one Telegram message listing the
recommended open tenders that haven't been alerted yet, best fit first.
"""
import logging
import sys

from config import EMAIL_ENABLED, TELEGRAM_ENABLED
from dates import is_open
from notify import email_page, email_section, send_email, send_telegram, telegram_message
from relevance import is_recommended
from store import load, load_alerted, save_alerted

log = logging.getLogger("Alerts")


def run() -> None:
    tenders, _ = load()
    alerted = load_alerted()
    fresh = [t for t in tenders.values()
             if t.id not in alerted and is_recommended(t) and is_open(t.deadline) is not False]
    if not fresh:
        log.info("No new recommended tenders to alert on.")
        return
    fresh.sort(key=lambda t: (-(t.score or 0), t.deadline or "9999"))

    n = len(fresh)
    noun = "tender" if n == 1 else "tenders"
    subject = f"TenderRadar: {n} new {noun} worth a look"
    best = fresh[0]
    sub = f"Best match: {best.headline or best.title}"[:140]

    sent_email = send_email(subject, email_page(f"{n} new {noun} worth a look", sub,
                                                email_section("New matches", fresh)))
    sent_tg = send_telegram(telegram_message(f"🔔 {n} new {noun} worth a look", [("", fresh)]))

    # Mark as alerted only if something actually went out (or nothing is configured,
    # so we don't pile up a backlog that floods the first message once it is).
    if sent_email or sent_tg or not (EMAIL_ENABLED or TELEGRAM_ENABLED):
        save_alerted(alerted | {t.id for t in fresh})
        log.info("Marked %d tenders as alerted.", n)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    run()
