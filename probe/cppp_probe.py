"""Temporary, read-only check of the CPPP collector against the live portal (pass 2)."""
import os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scraper"))
import cppp
from relevance import is_candidate

# 1. How often do communications tenders appear? Every 25th page across the list, 3 workers
first = cppp.fetch(cppp.LIST)
last = -(-cppp.total_tenders(first) // 10)
pages = list(range(2, last + 1, 25))
t0 = time.time()
def get(n):
    time.sleep(0.5)
    try:
        return n, cppp.parse_list(cppp.fetch(cppp.page_url(n)))
    except Exception as e:
        return n, e
rows, errors = [], 0
with ThreadPoolExecutor(3) as pool:
    for n, got in pool.map(get, pages):
        if isinstance(got, Exception):
            errors += 1; print("ERR", n, got); continue
        rows += [(n, r) for r in got]
dt = time.time() - t0
print(f"SAMPLE {len(pages)} pages in {dt:.0f}s ({dt/len(pages):.1f}s/page with 3 workers), {len(rows)} rows, {errors} errors")
cands = [(n, r) for n, r in rows if is_candidate(r.title)]
print(f"CANDIDATES {len(cands)} of {len(rows)} rows ({100*len(cands)/max(1,len(rows)):.1f}%) -> est. {len(cands)*25} across the list")
for n, r in cands:
    print(f"  p{n} {r.tender_id} | {r.published} -> {r.closing} | {r.organisation[:35]} | {r.title[:120]}")
skipped_noref = 0
for tr in cppp._ROW.findall(first):
    pass
# 2. Rows with short IDs or reference-only titles, raw
html2 = cppp.fetch(cppp.page_url(2))
for tr in cppp._ROW.findall(html2)[:3]:
    print("RAW p2:", re.sub(r"\s+", " ", tr)[:1200])
# 3. Other public lists
for name in ["gemtender", "latestactivecorrigendumsnew", "latestactivecorrigendumsnew/cpppdata", "highvaluetenders", "highvaluetenders/cpppdata"]:
    try:
        t0 = time.time(); h = cppp.fetch(cppp.BASE + name); t = cppp._text(re.sub(r"(?s)<(script|style).*?</\1>", " ", h))
        tot = re.search(r"Total [A-Za-z ]*:\s*[\d,]+", t)
        print(f"LIST {name}: {time.time()-t0:.1f}s {len(h)}b {tot.group(0) if tot else ''} captcha={'captcha' in t.lower()} rows={len(cppp.parse_list(h))}")
        i = t.find("Sl.No"); print("   ", t[i:i+900] if i >= 0 else t[1500:2300])
        trs = [x for x in cppp._ROW.findall(h) if len(cppp._CELL.findall(x)) >= 5]
        if trs: print("    RAW:", re.sub(r"\s+", " ", trs[0])[:1500])
    except Exception as e:
        print(f"LIST {name}: {type(e).__name__} {str(e)[:100]}")
    time.sleep(1)
