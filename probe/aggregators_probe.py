"""One-off, read-only probe: which tender aggregators are readable from GitHub, and what do their terms say?"""
import re, ssl, urllib.request
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
SITES = {
    "BidAssist": "https://bidassist.com/all-tenders/active?filter=KEYWORD:public%20relations",
    "Tender247": "https://www.tender247.com/keyword/public+relations+tenders",
    "TenderTiger": "https://www.tendertiger.com/tenders/public-relations-tenders",
    "TendersOnTime": "https://www.tendersontime.com/india/public-relations-tenders/",
    "BidDetail": "https://www.biddetail.com/india/public-relations-tenders",
    "TendersNet (tenders.net)": "https://www.tenders.net/",
    "IndianTenders (indiantenders.in)": "https://www.indiantenders.in/",
    "TenderShark": "https://www.tendershark.com/",
    "eTenders India (etender.co.in)": "https://www.etender.co.in/",
    "TenderNews": "https://www.tendernews.com/",
    "Global Tenders India": "https://www.globaltenders.com/government-tenders-india.php",
    "TenderDetail (control)": "https://www.tenderdetail.com/Indian-tender/public-relations-tenders",
}
BOT = re.compile(r"Performing security verification|not a bot|Verify you are human|Just a moment|Access Denied|"
                 r"Request Rejected|403 Forbidden|Attention Required|unusual traffic|Pardon Our Interruption", re.I)
PAY = re.compile(r"login to view|sign in to view|subscribe to view|upgrade|premium|paid plan|buy now|free trial", re.I)
DATE = re.compile(r"\b\d{1,2}(?:st|nd|rd|th)?[-/ ](?:\d{1,2}|[A-Za-z]{3,9})[-/ ,]+20\d\d\b")
TERMS_RX = re.compile(r"scrap|crawl|robot|spider|automated|harvest|data mining|bot\b|systematic(?:ally)? (?:retriev|download|extract)", re.I)

def fetch(url):
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20, context=ctx)
    return r.status, r.read().decode("utf-8", "replace")

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = b.new_context(user_agent=UA, locale="en-IN", ignore_https_errors=True, viewport={"width": 1366, "height": 900})
    for name, url in SITES.items():
        root = "/".join(url.split("/")[:3])
        print(f"\n######## {name}\n{url}")
        try:
            st, body = fetch(root + "/robots.txt")
            ua_all = re.split(r"(?im)^user-agent:\s*", body)
            star = next((blk for blk in ua_all if blk.startswith("*")), "")
            dis = [l.strip() for l in star.splitlines() if l.lower().startswith("disallow")]
            print(f"robots ({st}): {'DISALLOW ALL' if any(d.rstrip() == 'Disallow: /' for d in dis) else dis[:8]}")
        except Exception as e:
            print(f"robots: n/a ({type(e).__name__})")
        p = ctx.new_page()
        try:
            resp = p.goto(url, timeout=45000, wait_until="domcontentloaded"); p.wait_for_timeout(5000)
            t = p.evaluate("() => document.body ? document.body.innerText : ''")
            print(f"status={resp.status if resp else '?'} final={p.url} title={p.title()[:90]!r}")
            print(f"verdict={'BOT-CHECK' if BOT.search(t[:3000]) else 'OK'} paywall_words={sorted(set(m.lower() for m in PAY.findall(t)))[:6]} dates={len(DATE.findall(t))} chars={len(t)}")
            print("text:", re.sub(r"\s+", " ", t)[:700])
            links = p.evaluate("() => [...document.querySelectorAll('a[href]')].map(a => [a.href, a.innerText.trim().toLowerCase()])")
            terms = next((h for h, s in links if re.search(r"terms|conditions|tos|legal", s) and h.startswith("http")), None)
            if terms:
                p.goto(terms, timeout=45000, wait_until="domcontentloaded"); p.wait_for_timeout(2500)
                tt = p.evaluate("() => document.body ? document.body.innerText : ''")
                hits = [re.sub(r"\s+", " ", tt[max(0, m.start()-150):m.start()+200]) for m in TERMS_RX.finditer(tt)]
                print(f"terms page {terms}: {len(tt)} chars, {len(hits)} automated-access mentions")
                for h in hits[:4]: print("   TERMS ...", h, "...")
            else:
                print("terms page: not found on landing page")
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {str(e)[:200]}")
        p.close()
    b.close()
