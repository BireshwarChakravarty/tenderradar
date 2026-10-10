# TenderRadar

Government tenders for PR and communications agencies — found, filtered, scored and delivered.
Runs entirely on GitHub (Actions + Pages) for the cost of the Claude API calls, a few rupees a day.

```
every 4 hours  GitHub Actions
                 ├─ crawl TenderDetail.com (GeM, CPPP, state portals)   scraper/tenderdetail.py
                 ├─ parse each notice: title, deadline, value, EMD …     scraper/page_parser.py
                 ├─ drop auctions, works, goods, closed tenders          scraper/relevance.py, store.py
                 ├─ Claude scores the rest against your profile          scraper/ai_scorer.py
                 ├─ email + Telegram for new recommended tenders         scraper/alerts.py
                 └─ commit docs/data/tenders.json
8 AM IST       morning digest: closing this week + new since yesterday  scraper/daily_digest.py

GitHub Pages   docs/index.html — the dashboard, reading docs/data/tenders.json
```

## Setup

1. **Pages** — Settings → Pages → Deploy from a branch → `main` / `/docs`.
   The dashboard is then at `https://<you>.github.io/tenderradar/`.
2. **Secrets** — Settings → Secrets and variables → Actions:

   | Secret | What it is | Needed for |
   |---|---|---|
   | `ANTHROPIC_API_KEY` | Claude API key from console.anthropic.com | Scoring (without it tenders are listed but unscored) |
   | `COMPANY_PROFILE` | A paragraph on what you do, who for, typical deal size | Scoring |
   | `MIN_RELEVANCE_SCORE` | Fit score that counts as "recommended" (default `6.0`) | Optional |
   | `SMTP_USER`, `SMTP_PASS`, `ALERT_EMAIL_TO` | Gmail address, Gmail **App Password**, recipient(s) | Email |
   | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | From @BotFather, and your chat ID | Telegram |

3. **First run** — Actions → TenderRadar Scraper → Run workflow. A run takes 10–25 minutes.

Example `COMPANY_PROFILE`:

```
Delhi-based communications agency: public relations, media relations, social media
management, digital campaigns, media monitoring and content for central ministries,
state departments and PSUs. Typical engagements ₹10 L – ₹2 Cr.
```

## How tenders are judged

**Dropped before scoring** (`scraper/relevance.py`) — auctions that *sell* ad space (hoardings, bus
shelters, train wraps), construction and civil works, geotechnical surveys, and goods supply. Titles
that clearly describe agency work (IEC campaigns, publicity, PR) are always kept. These rules were
checked against ~1,000 previously scored tenders: they removed 335, all of which had scored under 4.

**Dropped by the store** (`scraper/store.py`) — tenders already closed when first found; closed
tenders older than 30 days; tenders with no stated deadline not seen for 45 days.

**Scored by Claude** (`scraper/ai_scorer.py`) — a short headline, the issuing authority, the kind of
procurement, a 1–10 fit score, Bid / Watch / Skip, and one-line reasons. A tender is *recommended*
when it scores at or above `MIN_RELEVANCE_SCORE`, isn't Skip, and isn't goods, works or an auction.

**Dates** (`scraper/dates.py`) — every date is an Indian calendar date, and a tender is open
through its closing day. A missing deadline stays missing; nothing is invented. Implausible
dates (e.g. 2018) are discarded. Open tenders closing within 3 days are re-checked each run,
so extended deadlines (corrigenda) are picked up.

## Tuning

| Change | Where |
|---|---|
| Search keywords | `SEARCH_KEYWORDS` in `scraper/relevance.py` |
| Exclusion rules | `EXCLUDE_PATTERNS` / `KEEP_PATTERNS` in `scraper/relevance.py` |
| Recommended threshold | `MIN_RELEVANCE_SCORE` secret |
| Scoring rubric | `SYSTEM_PROMPT` in `scraper/ai_scorer.py` |
| Pages per run, retention | `MAX_DETAIL_PAGES`, `KEEP_CLOSED_DAYS`, `STALE_DAYS` in `scraper/config.py` |
| Schedule | cron lines in `.github/workflows/*.yml` |

## Dashboard

Recommended / All open / Shortlist / Closed views, search, category and state filters, CSV export,
a detail sheet with the AI assessment, and tracking (Shortlisted → Preparing bid → Submitted) with notes.
Tracking lives in your browser; export it from the settings panel to back it up or move devices.
A link to a single tender is `…/#t=td-<number>`.

## When something breaks

- **The run is red with "page layout has probably changed"** — TenderDetail changed its HTML. The
  log prints the text of the first page it couldn't read; update the patterns in
  `scraper/page_parser.py` and add that text as a test case in `scraper/tests/test_parsing.py`.
- **The dashboard says "no update for N hours"** — check the Actions tab. GitHub pauses scheduled
  workflows on repositories with no activity for 60 days; re-enable it there.
- **No email** — the Gmail password must be an App Password; check spam.

## Local development

```bash
pip install -r scraper/requirements.txt && playwright install chromium
cp .env.example .env                                   # fill in your keys
python -m unittest discover -s scraper/tests -t scraper
python scraper/main.py                                 # full run
python -m http.server -d docs                          # dashboard at http://localhost:8000
```

## Restoring the original version

The pre-redesign files are in `backup/2026-10-10-original/` — see `RESTORE.md` there.
