# TenderRadar

**Government tender intelligence for communications agencies.**

TenderRadar finds public tenders for PR, communications, social media, digital, creative and
website work across Indian government procurement, assesses each one against the company's
capabilities, verifies it against its source, and delivers the ones worth pursuing to a private
dashboard, email and Telegram.

---

## What it does

- **Discovers** new tenders on the Central Public Procurement Portal (CPPP), which lists open
  tenders from central ministries, PSUs and state e-procurement portals, several times a day.
- **Screens out** what is never a fit, such as goods supply, civil works and auctions.
- **Assesses** every remaining tender with AI: a plain-English headline, a fit score, a
  Bid / Watch / Skip recommendation, and notes on fit, risk and eligibility.
- **Verifies** every published tender against the source twice a day, and publishes only tenders
  that are open, current and confirmed. A tender the source stops listing is taken down.
- **Alerts** the team when a strong new match appears, and sends a morning digest of what is
  closing this week.
- **Tracks** bids from shortlist to submission on the dashboard, with notes and CSV export.

## Data integrity

Accuracy comes first. A tender appears on the dashboard, in an alert or in the digest only if:

- its source states a closing date, and that date has not passed;
- it was published in 2026 or later;
- the source was re-read within the last 36 hours and still lists it;
- it has been assessed and judged relevant.

Anything that fails a check is held back, never shown. Contradictory values are removed rather
than displayed, and the dashboard hides any tender that passes its closing date between updates.

An independent audit runs every night. It re-opens every published tender and compares its
closing date with the source. If a single date disagrees, the audit fails and the repository
owner is notified by email.

## Architecture

```
GitHub Actions   every 4 hours   discover, verify, assess, publish, alert
                                 (every listing re-read twice a day)
                 08:00 IST       morning digest
                 03:47 IST       independent audit of published data
GitHub Pages     dashboard (docs/), reading only the published data
```

| Path | Contents |
|---|---|
| `scraper/` | Collection, verification, assessment, publishing and notifications |
| `scraper/tests/` | Unit tests, run before every update |
| `docs/` | The dashboard and the published data it reads |
| `data/` | Working store and quality reports (not served by the website) |
| `.github/workflows/` | Schedules |

## Setup

1. **GitHub Pages:** Settings, Pages, deploy from branch `main`, folder `/docs`.
2. **Secrets:** Settings, Secrets and variables, Actions.

   | Secret | Purpose | Required |
   |---|---|---|
   | `ANTHROPIC_API_KEY` | AI assessment | Yes |
   | `COMPANY_KNOWLEDGE` | Private company profile used for assessment | Yes |
   | `SMTP_USER`, `SMTP_PASS`, `ALERT_EMAIL_TO` | Email alerts and digest (Gmail App Password) | For email |
   | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram alerts | For Telegram |
   | `MIN_RELEVANCE_SCORE` | Score treated as recommended (default 6.0) | No |

3. **First run:** Actions, TenderRadar Scraper, Run workflow. The first run reads every listing
   and takes about an hour; later runs take a few minutes, and a full re-read twice a day takes
   about an hour.

## Operations

| Signal | Meaning | Action |
|---|---|---|
| Scraper run fails | The source could not be read or understood | Check the run log in Actions |
| Audit run fails | A published date no longer matches its source | Usually corrected by the next update; check the audit log |
| Dashboard says an update didn't finish | The latest run stopped early | Data shown is still verified; check Actions |
| No email | Gmail rejected the login | Use an App Password; check spam |

GitHub pauses scheduled workflows in repositories with no activity for 60 days. Re-enable them
from the Actions tab if that happens.

## Local development

```bash
pip install -r scraper/requirements.txt
cp .env.example .env                                   # add keys
python -m unittest discover -s scraper/tests -t scraper
python scraper/main.py
python -m http.server -d docs                          # dashboard at http://localhost:8000
```

## Data source

Tender data comes from the Central Public Procurement Portal (eprocure.gov.in), Government of
India, and is shown with the source acknowledged. Only its public tender list is read, at a
measured pace; search forms and anything behind a captcha are never used.

---

Designed and built by Bireshwar Chakravarty. © 2026 Bireshwar Chakravarty. All rights reserved.
See [LICENSE](LICENSE).
