"""One-off, read-only probe: which official tender sources can the scraper read from GitHub?"""
import re, urllib.request, ssl
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
NIC = "/app?page=FrontEndLatestActiveTenders&service=page"
SOURCES = {
    "GeM all bids": "https://bidplus.gem.gov.in/all-bids",
    "CPPP latest": "https://eprocure.gov.in/cppp/latestactivetendersnew/cpppdata",
    "CPPP home": "https://eprocure.gov.in/cppp/",
    "Central NIC (eprocure)": "https://eprocure.gov.in/eprocure" + NIC,
    "etenders.gov.in (central PSUs)": "https://etenders.gov.in/eprocure" + NIC,
    "Maharashtra": "https://mahatenders.gov.in/nicgep" + NIC,
    "Uttar Pradesh": "https://etender.up.nic.in/nicgep" + NIC,
    "Rajasthan": "https://eproc.rajasthan.gov.in/nicgep" + NIC,
    "West Bengal": "https://wbtenders.gov.in/nicgep" + NIC,
    "Tamil Nadu": "https://tntenders.gov.in/nicgep" + NIC,
    "Delhi": "https://govtprocurement.delhi.gov.in/nicgep" + NIC,
    "Haryana": "https://etenders.hry.nic.in/nicgep" + NIC,
    "Madhya Pradesh": "https://mptenders.gov.in/nicgep" + NIC,
    "Odisha": "https://tendersodisha.gov.in/nicgep" + NIC,
    "Defence (defproc)": "https://defproc.gov.in/nicgep" + NIC,
    "TenderDetail (control)": "https://www.tenderdetail.com/Indian-tender/public-relations-tenders",
}
BOT = re.compile(r"Performing security verification|not a bot|Verify you are human|Just a moment|Access Denied|Request Rejected|403 Forbidden", re.I)
CAPTCHA = re.compile(r"captcha", re.I)
DATE = re.compile(r"\b\d{1,2}[-/ ](?:\d{1,2}|[A-Za-z]{3})[-/ ]20\d\d\b")

def robots(url):
    root = "/".join(url.split("/")[:3])
    try:
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        r = urllib.request.urlopen(urllib.request.Request(root + "/robots.txt", headers={"User-Agent": UA}), timeout=15, context=ctx)
        body = r.read().decode("utf-8", "replace")
        dis = [l.strip() for l in body.splitlines() if l.lower().startswith("disallow")][:6]
        return f"{r.status} {dis}"
    except Exception as e:
        return f"n/a ({type(e).__name__})"

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = b.new_context(user_agent=UA, locale="en-IN", ignore_https_errors=True, viewport={"width": 1366, "height": 900})
    for name, url in SOURCES.items():
        p = ctx.new_page()
        try:
            resp = p.goto(url, timeout=45000, wait_until="domcontentloaded")
            p.wait_for_timeout(4000)
            t = p.evaluate("() => document.body ? document.body.innerText : ''")
            rows = p.evaluate("() => document.querySelectorAll('table tr').length")
            verdict = ("BOT-CHECK" if BOT.search(t[:3000]) else "OK")
            print(f"\n######## {name}\n{url}\nstatus={resp.status if resp else '?'} final={p.url}\ntitle={p.title()!r} verdict={verdict} "
                  f"captcha_on_page={bool(CAPTCHA.search(t))} dates={len(DATE.findall(t))} table_rows={rows} chars={len(t)}")
            print("robots:", robots(url))
            print("text:", re.sub(r"\s+", " ", t)[:900])
        except Exception as e:
            print(f"\n######## {name}\n{url}\nFAILED: {type(e).__name__}: {str(e)[:200]}")
            print("robots:", robots(url))
        p.close()
    b.close()
