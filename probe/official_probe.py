"""One-off, read-only probe (pass 3): CPPP terms of use, robots, pagination and corrigendum/cancelled lists."""
import base64, re, ssl, time, urllib.request
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
def get(u):
    t0 = time.time()
    r = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=40, context=CTX)
    return r.status, r.read().decode("utf-8", "replace"), time.time() - t0
def text(html): return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style).*?</\1>", " ", html)))
BASE = "https://eprocure.gov.in/cppp/"
for path in ["robots.txt"]:
    try:
        st, h, _ = get(BASE.rsplit("/cppp/", 1)[0] + "/robots.txt"); print("robots:", st, h[:400])
    except Exception as e: print("robots:", e)
st, h, dt = get(BASE + "latestactivetendersnew/cpppdata"); print("list page 1:", st, f"{dt:.1f}s", len(h), "bytes")
links = re.findall(r'href="([^"]+)"', h)
terms = [l for l in links if re.search(r"terms|copyright|policy|disclaimer|hyperlink", l, re.I)]
print("policy links:", sorted(set(terms))[:10])
for l in sorted(set(terms))[:6]:
    u = l if l.startswith("http") else "https://eprocure.gov.in" + l
    try:
        st, th, _ = get(u); tt = text(th)
        for m in list(re.finditer(r"reproduc|copyright|hyperlink|automated|crawl|scrap|permission|robot", tt, re.I))[:5]:
            print(f"  [{u.split('/')[-1]}] ...", tt[max(0, m.start()-160):m.start()+260], "...")
    except Exception as e: print("  ", u, e)
for n in [2, 50, 500]:
    u = BASE + "latestactivetendersnew/cpppdata?url=" + base64.b64encode(f"{BASE}latestactivetendersnew/cpppdata?page={n}".encode()).decode()
    st, h, dt = get(u); t = text(h); k = t.find(" 1. ") if " 1. " in t else t.find("1.")
    rows = re.findall(r"\b\d{1,2}-[A-Z][a-z]{2}-20\d\d \d\d:\d\d [AP]M", t)
    print(f"page {n}: {st} {dt:.1f}s dates={len(rows)} first={t[t.find('Sl.No'):t.find('Sl.No')+30]!r} sample={rows[:3]}")
    time.sleep(1)
for name in ["activecorrigendums", "cancelledtenders", "tenderclosingtoday"]:
    for cand in [f"{name}", f"{name}/cpppdata", f"{name}new/cpppdata"]:
        try:
            st, h, dt = get(BASE + cand); t = text(h)
            rows = re.findall(r"\b\d{1,2}-[A-Z][a-z]{2}-20\d\d \d\d:\d\d [AP]M", t)
            tot = re.search(r"Total [A-Za-z ]*: ?\d+", t)
            print(f"{cand}: {st} {dt:.1f}s dates={len(rows)} {tot.group(0) if tot else ''} cap={'captcha' in t.lower()}")
            i = t.find("Sl.No"); print("   ", t[i:i+500] if i >= 0 else t[:200])
            break
        except Exception as e:
            print(f"{cand}: {type(e).__name__} {str(e)[:80]}")
    time.sleep(1)
menu = sorted(set(l for l in links if "/cppp/" in l and not l.endswith((".pdf", ".png"))))
print("menu links:", menu[:60])
