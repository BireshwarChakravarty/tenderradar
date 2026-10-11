# TenderRadar

Government tenders for PR and communications agencies: found, filtered, scored and delivered.
Runs entirely on GitHub (Actions + Pages) for the cost of the Claude API calls, a few rupees a day.

```
every 4 hours  GitHub Actions
                 ├─ crawl TenderDetail.com (GeM, CPPP, state portals)   scraper/tenderdetail.py
                 │  and re-read every open tender from its source daily
                 ├─ parse each notice: title, deadline, value, EMD …     scraper/page_parser.py
                 ├─ drop auctions, works, goods, closed tenders          scraper/relevance.py, store.py
                 ├─ Claude scores the rest against your profile          scraper/ai_scorer.py
                 ├─ publish gate: only verified, open, 2026 tenders      scraper/integrity.py
                 ├─ email + Telegram for new recommended tenders         scraper/alerts.py
                 └─ commit data/store.json and docs/data/tenders.json
8 AM IST       morning digest: closing this week + new since yesterday  scraper/daily_digest.py
03:47 IST      audit: every published date re-checked against source  scraper/verify_dates.py

GitHub Pages   docs/index.html: the dashboard, reading docs/data/tenders.json
```

## Setup

1. **Pages**: Settings → Pages → Deploy from a branch → `main` / `/docs`.
   The dashboard is then at `https://<you>.github.io/tenderradar/`.
2. **Secrets**: Settings → Secrets and variables → Actions:

   | Secret | What it is | Needed for |
   |---|---|---|
   | `ANTHROPIC_API_KEY` | Claude API key from console.anthropic.com | Scoring (without it tenders are listed but unscored) |
   | `COMPANY_KNOWLEDGE` | Private company notes: turnover, contract sizes, empanelments, named clients, bids in progress | Scoring (recommended) |
   | `COMPANY_PROFILE` | Any extra notes for the scorer | Optional |
   | `MIN_RELEVANCE_SCORE` | Fit score that counts as "recommended" (default `6.0`) | Optional |
   | `SMTP_USER`, `SMTP_PASS`, `ALERT_EMAIL_TO` | Gmail address, Gmail **App Password**, recipient(s) | Email |
   | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | From @BotFather, and your chat ID | Telegram |

3. **First run**: Actions → TenderRadar Scraper → Run workflow. A run takes 10–25 minutes.

**Company profile.** The scorer reads `scraper/knowledge/profile.md` (public: services, target
buyers and the scoring guide) and then the `COMPANY_KNOWLEDGE` secret (private: anything you
wouldn't put in a public repo). Paste a whole Markdown file into the secret; it can be up to 48 KB.
After changing either, bump `SCORING_VERSION` in `scraper/ai_scorer.py` to re-score open tenders.

## How tenders are judged

**Dropped before scoring** (`scraper/relevance.py`): auctions that *sell* ad space (hoardings, bus
shelters, train wraps), construction and civil works, geotechnical surveys, and goods supply. Titles
that clearly describe agency work (IEC campaigns, publicity, PR) are always kept. These rules were
checked against ~1,000 previously scored tenders: they removed 335, all of which had scored under 4.

**Dropped by the store** (`scraper/store.py`): tenders already closed when first found; notices
published before 2026; corrigenda of a tender already listed (same wording and deadline). Closed
tenders stay in the working store for 30 days (to recognise duplicates) but are never published;
tenders with no stated deadline are dropped once not seen for 45 days. Rejected notices are remembered in
`docs/data/rejected.json` for 60 days so they aren't fetched again.

**Scored by Claude** (`scraper/ai_scorer.py`): a short headline, the issuing authority, the kind of
procurement, a 1–10 fit score, Bid / Watch / Skip, and one-line reasons. A tender is *recommended*
when it scores at or above `MIN_RELEVANCE_SCORE`, isn't Skip, and isn't goods, works or an auction. Goods,
works, auctions and anything scoring under 3 are not published at all; they stay in the working
store and are re-checked like everything else.

**Dates** (`scraper/dates.py`, `scraper/page_parser.py`): every date is an Indian calendar date,
and a tender is open through its closing day. The closing date is the one the source page prints;
a missing deadline stays missing and nothing is invented. Every open tender is re-read daily, so
extended deadlines (corrigenda) and closures are picked up. See *Data integrity* below.

## Data integrity

Nothing reaches the website, the alerts or the digest unless it passes every check. The scraper
keeps its working copy in `data/store.json`; only tenders that pass the publish gate
(`scraper/integrity.py`) are written to `docs/data/tenders.json`.

1. **Every open tender is re-read from its source page at least daily** (`REVERIFY_HOURS`, 18 by
   default), oldest check first, so extensions, cancellations and closures are picked up.
2. **The closing date is the one the page states**: the "BID SUBMISSION" box, then "LAST DATE".
   A countdown is only used when no date is printed. TenderDetail shows "Closing in 0 days" on
   every expired tender, so a zero countdown never keeps a tender open.
3. **The publish gate** shows a tender only if: the source states a closing date; it is today or
   later (IST); it is within a year; it was published in 2026 or later (when a publish date is
   given); its page was re-read within the last 36 hours; its link matches its reference; and the
   AI has assessed it as relevant (not goods, works or an auction, fit 3 or more).
   Contradictory values (an EMD above the tender value, a publish date in the future) are cleared,
   and AI text that mentions private names or internal process is wiped and re-scored.
   `data/quality.json` lists everything held back or corrected, with the reason.
4. **The dashboard** hides anything past its closing date even before the next sync.
5. **A daily audit** (`Audit published tenders` workflow, 03:47 IST) re-opens every published
   tender and compares its closing date with the source page. Any mismatch fails the run, and
   GitHub emails the repo owner.

## Tuning

| Change | Where |
|---|---|
| Search keywords | `SEARCH_KEYWORDS` in `scraper/relevance.py` |
| Exclusion rules | `EXCLUDE_PATTERNS` / `KEEP_PATTERNS` in `scraper/relevance.py` |
| Recommended threshold | `MIN_RELEVANCE_SCORE` secret |
| Scoring rubric | `SYSTEM_PROMPT` in `scraper/ai_scorer.py` |
| Pages and time per run | `MAX_DETAIL_PAGES`, `CRAWL_BUDGET_MIN` in `scraper/config.py` |
| Re-verification, retention | `REVERIFY_HOURS`, `KEEP_CLOSED_DAYS`, `STALE_DAYS` in `scraper/config.py` |
| Publish rules | `MIN_PUBLISHED`, `MAX_VERIFY_AGE_HOURS` in `scraper/integrity.py` |
| Schedule | cron lines in `.github/workflows/*.yml` |

## Dashboard

Recommended / All open / Shortlist views (open, relevant tenders only), search, category and state filters, CSV export,
a detail sheet with the AI assessment, and tracking (Shortlisted → Preparing bid → Submitted) with notes.
Tracking lives in your browser; export it from the settings panel to back it up or move devices.
A link to a single tender is `…/#t=td-<number>`.

## When something breaks

- **The run is red with "page layout has probably changed"**: TenderDetail changed its HTML. The
  log prints the text of the first page it couldn't read; update the patterns in
  `scraper/page_parser.py` and add that text as a test case in `scraper/tests/test_parsing.py`.
- **The dashboard says "no update for N hours"**: check the Actions tab. GitHub pauses scheduled
  workflows on repositories with no activity for 60 days; re-enable it there.
- **No email**: the Gmail password must be an App Password; check spam.

## Local development

```bash
pip install -r scraper/requirements.txt && playwright install chromium
cp .env.example .env                                   # fill in your keys
python -m unittest discover -s scraper/tests -t scraper
python scraper/main.py                                 # full run
python -m http.server -d docs                          # dashboard at http://localhost:8000
```

## Restoring the original version

The pre-redesign files are in `backup/2026-10-10-original/`. See `RESTORE.md` there.

---

Designed and built by Bireshwar Chakravarty. © 2026 Bireshwar Chakravarty. All rights reserved.
See [LICENSE](LICENSE).
