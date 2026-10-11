"""
TenderRadar: deadline verification.

Re-opens each stored open tender on TenderDetail and checks the stored
deadline against what the page actually says. Read-only: nothing is saved.

Each tender lands in one bucket:
  ok          explicit closing date on the page, in the future, equals the stored one
  changed     explicit future date on the page differs from the stored one
  countdown   no explicit date; the deadline comes only from "Closing in N days" style text
  override    the page states a closing date that has already passed, but a
              countdown phrase made the parser treat it as still open
  no_date     the page states no date and no countdown
  failed      the page didn't load

Run: python scraper/verify_dates.py   (VERIFY_LIMIT caps how many are checked)
"""
import json
import logging
import os
import re
import sys
from collections import Counter, defaultdict

from config import USER_AGENT
from dates import parse_date, plausible, today_ist
from page_parser import _COUNTDOWN, _DEADLINE_LABEL, _PUBLISHED_LABEL, parse_dates
from store import load
from tenderdetail import _read_page

log = logging.getLogger("Verify")


def _ctx(text: str, start: int, end: int, before: int = 50, after: int = 60) -> str:
    return re.sub(r"\s+", " ", text[max(0, start - before):end + after]).strip()


def inspect(text: str) -> dict:
    today = today_ist()
    labelled = []
    for m in _DEADLINE_LABEL.finditer(text):
        d = parse_date(text[m.end():m.end() + 40])
        if d and plausible(d):
            labelled.append({"date": d.isoformat(), "at": m.start(), "ctx": _ctx(text, m.start(), m.end())})
    countdowns = [{"match": m.group(0), "at": m.start(), "ctx": _ctx(text, m.start(), m.end(), 80, 80)}
                  for m in _COUNTDOWN.finditer(text)]
    published = []
    for m in _PUBLISHED_LABEL.finditer(text):
        d = parse_date(text[m.end():m.end() + 40])
        if d and plausible(d):
            published.append({"date": d.isoformat(), "ctx": _ctx(text, m.start(), m.end())})
            break
    first_label = labelled[0]["date"] if labelled else ""
    return {"fresh": parse_dates(text), "labelled": labelled, "countdowns": countdowns,
            "published": published, "first_label": first_label, "today": today.isoformat(),
            "length": len(text)}


def bucket(stored: str, info: dict) -> str:
    fresh = info["fresh"]["deadline"]
    label = info["first_label"]
    today = info["today"]
    if label and label < today and info["countdowns"] and fresh >= today:
        return "override"
    if label and label >= today:
        return "ok" if label == stored else "changed"
    if info["countdowns"]:
        return "countdown"
    return "no_date"


def main() -> None:
    from playwright.sync_api import sync_playwright

    tenders, _ = load()
    today = today_ist().isoformat()
    todo = sorted((t for t in tenders.values() if not t.deadline or t.deadline >= today),
                  key=lambda t: t.deadline or "9999")
    limit = int(os.getenv("VERIFY_LIMIT") or 400)
    todo = todo[:limit]
    log.info("Checking %d open tenders against their pages (today %s)", len(todo), today)

    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_context(user_agent=USER_AGENT, viewport={"width": 1280, "height": 800},
                                   locale="en-IN").new_page()
        for i, t in enumerate(todo, 1):
            text = _read_page(page, t.url)
            if not text:
                rows.append({"id": t.id, "stored": t.deadline, "bucket": "failed", "title": t.title})
                continue
            info = inspect(text)
            b = bucket(t.deadline, info)
            rows.append({"id": t.id, "url": t.url, "title": t.title[:90], "stored": t.deadline,
                         "stored_published": t.published, "bucket": b, "excerpt": text[:2500], **info})
            log.info("[%d/%d] %-9s stored=%-10s page=%-10s countdown=%s  %s", i, len(todo), b,
                     t.deadline or "-", info["first_label"] or "-",
                     ",".join(c["match"] for c in info["countdowns"]) or "-", t.title[:60])
        browser.close()

    counts = Counter(r["bucket"] for r in rows)
    print("\n==== SUMMARY ====")
    print(f"checked {len(rows)}  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    by = defaultdict(list)
    for r in rows:
        by[r["bucket"]].append(r)
    for b in ("override", "changed", "countdown", "no_date", "failed", "ok"):
        if not by[b]:
            continue
        print(f"\n==== {b.upper()} ({len(by[b])}) ====")
        for r in by[b][:40]:
            print(f"- {r['id']} stored={r['stored'] or '-'} page_label={r.get('first_label') or '-'} "
                  f"fresh={r.get('fresh', {}).get('deadline') or '-'} | {r['title']}")
            for lab in r.get("labelled", [])[:2]:
                print(f"    label: {lab['ctx']}")
            for c in r.get("countdowns", [])[:3]:
                print(f"    countdown @{c['at']}/{r.get('length')}: {c['ctx']}")
    # A few full page excerpts so the layout can be checked by eye
    print("\n==== PAGE EXCERPTS ====")
    for b in ("override", "countdown", "ok"):
        for r in by[b][:2]:
            print(f"\n--- {b} {r['id']} {r.get('url')}")
            print(r.get("excerpt", ""))
    with open("verify_dates.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    main()
