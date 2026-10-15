"""One-off, read-only probe (pass 2): what exactly is readable on CPPP and a NIC portal without a captcha?"""
import re
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
def txt(p): return p.evaluate("() => document.body ? document.body.innerText : ''")
def links(p): return p.evaluate("() => [...document.querySelectorAll('a[href]')].map(a => [a.href, a.innerText.trim().replace(/\\s+/g,' ').slice(0,90)])")
def show(t, s, n): print(f"\n----- {t} -----\n" + re.sub(r"\n{3,}", "\n\n", s)[:n])

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    p = b.new_context(user_agent=UA, locale="en-IN", ignore_https_errors=True, viewport={"width": 1366, "height": 900}).new_page()
    def go(u):
        r = p.goto(u, timeout=60000, wait_until="domcontentloaded"); p.wait_for_timeout(4000); return r

    # ---- CPPP latest active tenders
    r = go("https://eprocure.gov.in/cppp/latestactivetendersnew/cpppdata")
    t = txt(p); i = t.find("Bid Submission"); 
    show(f"CPPP list ({r.status}) final {p.url}", t[max(0, i-400):] if i >= 0 else t, 4500)
    L = links(p)
    print("\nCPPP pagination-ish:", [h for h, s in L if re.search(r"page=|/\d+$|next|›|»", h + s, re.I)][:10])
    det = [h for h, s in L if re.search(r"tendersfullview|tenderdetails|cpppdata/|/viewtender|DirectLink", h, re.I)][:6]
    print("CPPP detail-ish links:", det)
    print("CPPP forms:", p.evaluate("() => [...document.forms].map(f => [f.action, f.method, [...f.elements].map(e => e.name).filter(Boolean).slice(0,12)])"))
    for d in det[:2]:
        r = go(d); dt = txt(p)
        show(f"CPPP detail ({r.status}) {p.url}", dt, 3000)
        print("captcha on detail:", bool(re.search(r"captcha", dt, re.I)))
    # page 2
    for u in ["https://eprocure.gov.in/cppp/latestactivetendersnew/cpppdata?page=2",
              "https://eprocure.gov.in/cppp/latestactivetendersnew/cpppdata/page/2"]:
        r = go(u); t2 = txt(p)
        k = t2.find("1.")
        first = re.sub(r"\s+", " ", t2[k:k + 250]) if k >= 0 else "n/a"
        print(f"\n{u} -> {r.status} final {p.url} | first row: {first}")

    # ---- NIC central portal: latest active tenders + by organisation + a detail
    base = "https://eprocure.gov.in/eprocure/app"
    r = go(base + "?page=FrontEndLatestActiveTenders&service=page"); t = txt(p)
    i = t.find("Latest Tenders") if "Latest Tenders" in t else t.find("Tender Title")
    show(f"NIC latest ({r.status})", t[max(0, i-200):] if i >= 0 else t, 3500)
    L = links(p)
    det = [h for h, s in L if re.search(r"DirectLink|component=%24DirectLink|FrontEndViewTender|sp=", h)][:5]
    print("NIC detail-ish links:", det[:5])
    for d in det[:1]:
        r = go(d); dt = txt(p)
        show(f"NIC detail ({r.status}) {p.url[:150]}", dt, 3500)
        print("captcha on detail:", bool(re.search(r"captcha", dt, re.I)))
    r = go(base + "?page=FrontEndTendersByOrganisation&service=page"); t = txt(p)
    show(f"NIC by organisation ({r.status})", t, 1500)
    print("captcha on by-org:", bool(re.search(r"captcha", t, re.I)))
    org = [h for h, s in links(p) if re.search(r"DirectLink", h)][:2]
    for o in org[:1]:
        r = go(o); ot = txt(p)
        show(f"NIC org list ({r.status})", ot, 2500)
        print("captcha on org list:", bool(re.search(r"captcha", ot, re.I)))
    b.close()
