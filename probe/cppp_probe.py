"""Temporary, read-only check of the CPPP collector against the live portal."""
import os, re, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scraper"))
import cppp
from relevance import is_candidate

t0 = time.time()
first = cppp.fetch(cppp.LIST)
print(f"page 1: {len(first)} bytes in {time.time()-t0:.1f}s (TLS verified), total={cppp.total_tenders(first)}")
trs = cppp._ROW.findall(first)
print("rows <tr>:", len(trs))
shown = 0
for tr in trs:
    if len(cppp._CELL.findall(tr)) >= 6:
        print("RAW ROW:", re.sub(r"\s+", " ", tr)[:2500]); shown += 1
        if shown == 2: break
for r in cppp.parse_list(first)[:10]:
    print("ROW", r)
links = []
for n in (2, 3, 300, 1500):
    t0 = time.time(); rows = cppp.parse_list(cppp.fetch(cppp.page_url(n)))
    print(f"page {n}: {len(rows)} rows in {time.time()-t0:.1f}s; first: {rows[0] if rows else None}")
    time.sleep(1)
# A small incremental crawl, then a peek at the candidates
res = cppp.crawl("incremental", max_pages=40, pause=0.5)
print(f"incremental 40 pages: rows={res.seen_rows} candidates={len(res.listed_ids)} open={len(res.tenders)} unparsed={res.unparsed} newest={res.newest_published}")
for t in res.tenders[:60]:
    print(f"  CAND {t.ref_no} | {t.published} -> {t.deadline} | {t.authority[:40]} | {t.title[:110]}")
# Does a detail link open without a captcha?
m = cppp._HREF.search(first)
if m:
    href = m.group(1).replace("&amp;", "&")
    url = href if href.startswith("http") else "https://eprocure.gov.in" + href
    print("detail link:", url[:300])
    try:
        body = cppp.fetch(url)
        txt = cppp._text(re.sub(r"(?s)<(script|style).*?</\1>", " ", body))
        print("detail: captcha" if "captcha" in txt.lower() else "detail: no captcha", len(txt))
        print("detail text:", txt[:2500])
    except Exception as e:
        print("detail failed:", e)
