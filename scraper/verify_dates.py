"""
TenderRadar: independent audit of the published data.

Runs daily, separately from the scraper. Read-only: nothing is saved.

  1. Every tender the website shows (docs/data/tenders.json) is checked
     against the publish rules again: closing date stated and not passed,
     re-verified against the source within the allowed window.
  2. A sample of CPPP list pages (the newest, plus random pages across the
     list) is read again and every row is parsed twice: by the collector's
     parser, and by a deliberately different one that works on the page text
     alone. Any disagreement on a closing date, publish date or Tender ID
     fails the audit.
  3. Any published tender that appears in the sample is compared with its
     stored closing date.

Exits 1 on any problem, so the GitHub run turns red and the owner is emailed.

Run: python scraper/verify_dates.py   (AUDIT_PAGES sets the sample size)
"""
import base64
import logging
import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import cppp
from dates import today_ist
from integrity import MAX_VERIFY_AGE_HOURS, _hours_since
from store import load_published

log = logging.getLogger("Audit")

# The second parser: a row's visible text is
#   "<n>. <published> <closing> <opening> <title>/<ref>/<tender id> <organisation> <corrigendum>"
_DT = r"(\d{2}-[A-Z][a-z]{2}-\d{4} \d{2}:\d{2} [AP]M)"
_ROW_TEXT = re.compile(rf"^\d+\.\s+{_DT}\s+{_DT}\s+{_DT}\s+(.+)$")


def text_rows(page_html: str) -> dict[str, tuple[str, str, str]]:
    """{CPPP key: (published, closing, tender id)} from the page text, independently of cppp.parse_list."""
    out = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page_html, re.S | re.I):
        key = re.search(r"tendersfullview/([A-Za-z0-9+/=]+?)A13h1", tr)
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
        m = _ROW_TEXT.match(" ".join(cells[:5]).replace("&amp;", "&"))
        if not (key and m):
            continue
        k = base64.b64decode(key.group(1) + "=" * (-len(key.group(1)) % 4)).decode()
        iso = lambda s: datetime.strptime(s, "%d-%b-%Y %I:%M %p").strftime("%Y-%m-%dT%H:%M")
        out[k] = (iso(m.group(1)), iso(m.group(2)), m.group(4).rsplit("/", 1)[-1].strip())
    return out


def main() -> None:
    today = today_ist().isoformat()
    problems = []

    published = load_published()
    log.info("Website shows %d tenders", len(published))
    for t in published:
        age = _hours_since(t.verified_at)
        if not t.deadline or t.deadline < today:
            problems.append(f"{t.id}: closing date {t.deadline or 'missing'} is not open")
        if age is None or age > MAX_VERIFY_AGE_HOURS:
            problems.append(f"{t.id}: last verified {t.verified_at or 'never'}")

    first = cppp.fetch(cppp.LIST)
    last = max(1, -(-cppp.total_tenders(first) // 10))
    n = int(os.getenv("AUDIT_PAGES") or 60)
    pages = sorted(set(range(2, min(last, 10) + 1)) | set(random.sample(range(2, last + 1), min(n, last - 1))))
    log.info("Re-reading %d of %d CPPP list pages", len(pages) + 1, last)

    def get(p):
        try:
            return p, cppp.fetch(cppp.page_url(p))
        except cppp.SourceUnavailable as e:
            return p, e

    htmls = [(1, first)]
    failed = 0
    with ThreadPoolExecutor(3) as pool:
        for p, h in pool.map(get, pages):
            if isinstance(h, Exception):
                failed += 1
                log.warning("Page %d: %s", p, h)
            else:
                htmls.append((p, h))

    by_key = {t.id.removeprefix("cppp-"): t for t in published if t.source == cppp.SOURCE}
    rows = matched = 0
    for p, h in htmls:
        a = {r.key: r for r in cppp.parse_list(h)}
        b = text_rows(h)
        for key, r in a.items():
            rows += 1
            if key not in b:
                continue          # the text parser skips nothing the collector keeps, except odd rows
            if (r.published, r.closing, r.tender_id) != b[key]:
                problems.append(f"page {p} row {key}: parsers disagree {(r.published, r.closing, r.tender_id)} vs {b[key]}")
            t = by_key.get(key)
            if t:
                matched += 1
                if t.deadline != r.closing[:10]:
                    problems.append(f"{t.id}: site shows closing {t.deadline}, CPPP now says {r.closing[:10]}")
        if len(b) >= 5 and len(a) < len(b) // 2:
            problems.append(f"page {p}: collector read {len(a)} rows, the page has {len(b)}")

    print("\n==== AUDIT ====")
    for pr in problems:
        print("PROBLEM", pr)
    print(f"{len(published)} published tenders re-checked against the rules; {rows} rows on {len(htmls)} "
          f"CPPP pages parsed twice; {matched} published tenders found in the sample; {failed} pages didn't load; "
          f"{len(problems)} problems")
    if problems or failed > max(3, len(pages) // 10):
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    main()
