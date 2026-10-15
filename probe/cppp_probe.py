"""Temporary, read-only check of CPPP's GeM bid list (pass 3)."""
import base64, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scraper"))
import cppp
from relevance import is_candidate

URL = cppp.BASE + "gemtender"
t0 = time.time(); h = cppp.fetch(URL); print(f"gemtender p1: {time.time()-t0:.1f}s {len(h)} bytes")
t = cppp._text(re.sub(r"(?s)<(script|style).*?</\1>", " ", h))
for m in re.finditer(r"Total[^:]{0,30}:\s*[\d,]+", t): print("TOTAL", m.group(0))
hrefs = sorted(set(re.findall(r'href="([^"]*gemtender[^"]*)"', h)))
print("pager hrefs:", hrefs[:15])
for x in hrefs[:6]:
    q = x.split("url=", 1)[-1] if "url=" in x else ""
    if q:
        try: print("  decoded:", base64.b64decode(q + "=" * (-len(q) % 4)).decode())
        except Exception as e: print("  decode fail", e)
rows = []
for tr in cppp._ROW.findall(h):
    cells = [cppp._text(c) for c in cppp._CELL.findall(tr)]
    if len(cells) >= 6 and re.match(r"\d+\.$", cells[0]): rows.append(cells)
print("rows on page 1:", len(rows))
for c in rows[:5]: print("  ", c[:7])
cands = [c for c in rows if is_candidate(c[4])]
print(f"page-1 candidates {len(cands)}/{len(rows)}")
for c in cands[:40]: print("  CAND", c[1], "->", c[2], "|", c[3], "|", c[4][:100], "|", c[5][:40])
# order of rows: by start date or end date?
print("start dates sample:", [c[1] for c in rows[:3]], "...", [c[1] for c in rows[-3:]])
print("end dates sample:", [c[2] for c in rows[:3]], "...", [c[2] for c in rows[-3:]])
# Try page 2 the CPPP way
for cand in [URL + "?page=1", URL + "?url=" + base64.b64encode(f"{URL}?page=1".encode()).decode(), URL + "?url=" + base64.b64encode(f"{URL}?page=50".encode()).decode()]:
    try:
        t0 = time.time(); h2 = cppp.fetch(cand)
        r2 = [cppp._text(c) for tr in cppp._ROW.findall(h2) for c in cppp._CELL.findall(tr)[3:4]]
        print(f"PAGE {cand[-40:]}: {time.time()-t0:.1f}s first bids {r2[:2]}")
    except Exception as e: print("PAGE fail", cand[-40:], e)
    time.sleep(1)
# Category words across page 1 for a feel of services
cats = {}
for c in rows: cats[c[4][:60]] = cats.get(c[4][:60], 0) + 1
print("top categories:", sorted(cats.items(), key=lambda x: -x[1])[:40])
svc = [c[4] for c in rows if re.search(r"servic|hiring|agency|manpower", c[4], re.I)]
print(f"service-like rows {len(svc)}:", svc[:60])
