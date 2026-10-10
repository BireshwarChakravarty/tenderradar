# 📡 TenderRadar

> Free, automated tender monitoring across GeM, CPPP, BHEL, ONGC, NTPC, and State portals.
> Runs entirely on GitHub — zero hosting cost.

---

## How It Works

```
GitHub Actions (cron every 4 hrs)
    → runs scrapers
    → scores new tenders with Claude AI
    → commits updated data/tenders.json back to repo
    → sends Email + Telegram alerts

GitHub Pages (docs/index.html)
    → reads data/tenders.json directly from your repo
    → shows live dashboard with filters, pipeline board, AI scoring
```

**Total cost: ₹0/month** (GitHub free tier is more than enough)

---

## Setup — Step by Step

### Step 1 — Create the GitHub repo

1. Go to [github.com](https://github.com) → **New repository**
2. Name it `tenderradar` (or anything you like)
3. Set visibility to **Private** (recommended) or Public
4. **Do not** initialise with README
5. Click **Create repository**

---

### Step 2 — Upload the files

**Option A — GitHub web UI (easiest)**
1. Extract the `tenderradar.zip` you downloaded
2. In your new repo, click **uploading an existing file**
3. Drag the entire extracted folder contents in
4. Commit directly to `main`

**Option B — Git CLI**
```bash
cd tenderradar          # the extracted folder
git init
git remote add origin https://github.com/YOUR_USERNAME/tenderradar.git
git add .
git commit -m "Initial commit"
git branch -M main
git push -u origin main
```

---

### Step 3 — Enable GitHub Pages

1. In your repo → **Settings** → **Pages**
2. Source: **Deploy from a branch**
3. Branch: `main` / folder: `/docs`
4. Click **Save**
5. Your dashboard will be live at:
   `https://YOUR_USERNAME.github.io/tenderradar/`

---

### Step 4 — Add GitHub Secrets

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these one by one:

| Secret Name | Value | Required? |
|---|---|---|
| `ANTHROPIC_API_KEY` | Your Claude API key from [console.anthropic.com](https://console.anthropic.com) | ✅ Yes |
| `COMPANY_PROFILE` | Description of your company & what tenders you want (see example below) | ✅ Yes |
| `SMTP_USER` | Your Gmail address | For email alerts |
| `SMTP_PASS` | Gmail App Password (not your login password — see Step 5) | For email alerts |
| `ALERT_EMAIL_TO` | Email to receive alerts | For email alerts |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token (see Step 6) | For Telegram alerts |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID (see Step 6) | For Telegram alerts |
| `MIN_RELEVANCE_SCORE` | e.g. `6.5` — only alert on tenders above this score | Optional (default: 6.0) |

**Example COMPANY_PROFILE:**
```
IT services company based in Delhi NCR specialising in hardware supply
(laptops, servers, networking equipment), IT infrastructure projects,
data centre AMC, cloud solutions and system integration.
Typical bid size Rs 5L to Rs 2Cr. Strong track record in central
government ministries and PSU sector.
```

---

### Step 5 — Gmail App Password (for email alerts)

Regular Gmail password won't work — you need an App Password:

1. Go to your Google Account → **Security**
2. Enable **2-Step Verification** if not already on
3. Search for **App passwords** → Select app: **Mail** → Device: **Other** → type "TenderRadar"
4. Copy the 16-character password → paste as `SMTP_PASS` secret

---

### Step 6 — Telegram Bot Setup (free, takes 2 minutes)

1. Open Telegram → search **@BotFather** → start chat
2. Send `/newbot` → follow prompts → copy the **token** → paste as `TELEGRAM_BOT_TOKEN`
3. Start a chat with your new bot (click the t.me link BotFather gives you → Start)
4. Open [https://api.telegram.org/bot**YOUR_TOKEN**/getUpdates](https://api.telegram.org/bot/getUpdates)
5. Send any message to your bot, then refresh the URL above
6. Find `"chat":{"id":XXXXXXXXX}` → that number is your `TELEGRAM_CHAT_ID`

---

### Step 7 — Run the first scrape manually

1. In your repo → **Actions** tab
2. Click **TenderRadar Scraper** → **Run workflow** → **Run workflow**
3. Watch the logs — first run takes ~5–10 minutes
4. After it finishes, check `data/tenders.json` — it should have tenders
5. Open your GitHub Pages URL — the dashboard will show live data

---

### Step 8 — Customise the dashboard URL

Open `docs/index.html` in your editor and find this line near the bottom:

```javascript
const repoBase = `https://raw.githubusercontent.com/${parts[0]}/${parts[1]}/main/data/tenders.json`;
```

This auto-detects your repo from the GitHub Pages URL, so it should work without changes.
If it doesn't, open your dashboard → **Settings tab** → enter your repo as `username/tenderradar`.

---

## Cron Schedule

| Workflow | Schedule | What it does |
|---|---|---|
| TenderRadar Scraper | Every 4 hours | Scrapes all portals, scores new tenders, sends instant alerts |
| TenderRadar Daily Digest | Daily at 8 AM IST | Sends a morning summary of pipeline + closing deadlines |

To change the schedule, edit `.github/workflows/scrape.yml` and modify the cron expression.
A good reference: [crontab.guru](https://crontab.guru)

---

## Adding More Portals

Each portal is a separate file in `scraper/`. To add a new one:

1. Copy `scraper/bhel_scraper.py` as a template
2. Set `PORTAL_NAME` and `BASE_URL`
3. Adjust the CSS selectors in `_parse_row()` to match the new portal's HTML
4. Import and call it in `scraper/main.py`
5. Add a toggle in `scraper/config.py` and `.env.example`

Portals easy to add next: **IRCON, NBCC, CPWD, IREPS, HAL, BEL, Coal India, GAIL**

---

## File Structure

```
tenderradar/
├── .github/
│   └── workflows/
│       ├── scrape.yml          ← runs scrapers every 4 hrs
│       └── daily_digest.yml    ← morning summary at 8 AM IST
├── scraper/
│   ├── main.py                 ← orchestrator (runs all scrapers)
│   ├── config.py               ← reads env vars / GitHub Secrets
│   ├── base_scraper.py         ← shared scraper base class
│   ├── gem_scraper.py          ← GeM portal
│   ├── cppp_scraper.py         ← CPPP / eProcure
│   ├── bhel_scraper.py         ← BHEL
│   ├── psu_scrapers.py         ← ONGC + NTPC
│   ├── state_scrapers.py       ← UP, Maharashtra, Karnataka
│   ├── deduplicator.py         ← prevents duplicate alerts
│   ├── ai_scorer.py            ← Claude relevance scoring
│   ├── alerts.py               ← email + Telegram notifications
│   ├── daily_digest.py         ← morning digest
│   └── requirements.txt
├── data/
│   ├── tenders.json            ← live database (auto-updated by Actions)
│   └── alert_log.json          ← tracks which tenders have been alerted
├── docs/
│   └── index.html              ← full dashboard (GitHub Pages)
└── .env.example                ← copy to .env for local dev
```

---

## Local Development

```bash
cd tenderradar
pip install -r scraper/requirements.txt
playwright install chromium

# Copy and fill in your credentials
cp .env.example .env
# Edit .env with your API keys

# Run one portal manually
cd scraper
python gem_scraper.py

# Run full pipeline
python main.py

# Run alerts manually
python alerts.py

# Open dashboard locally
# Just open docs/index.html in your browser
# Go to Settings tab → set JSON URL to: ../data/tenders.json
```

---

## Troubleshooting

**Dashboard shows demo data / no tenders**
→ Check that `data/tenders.json` in your repo has content (not empty `[]`)
→ In dashboard Settings tab, set your repo as `username/tenderradar`
→ Make sure GitHub Pages is enabled from `/docs`

**Scraper workflow fails**
→ Go to Actions → click the failed run → expand the failing step for the error
→ Most common: missing secrets (ANTHROPIC_API_KEY not set), or a portal changed its HTML

**No email received**
→ Check Gmail App Password is correct (16 chars, no spaces)
→ Check spam folder
→ Verify `ALERT_EMAIL_TO` secret is set

**Telegram not working**
→ Make sure you started a chat with your bot first
→ Double-check the Chat ID (it should be a plain number, no spaces)

**Portal returning 0 tenders**
→ The portal may have changed its HTML structure
→ Open the portal in your browser → inspect the tender listing table
→ Update the CSS selector in the relevant scraper file

---

## GitHub Actions Free Tier Usage

| Metric | Your usage | Free limit |
|---|---|---|
| Workflow minutes/month | ~900 min (6 runs/day × 30 × 5 min) | 2,000 min (private) / Unlimited (public) |
| Storage | < 10 MB (JSON data) | 500 MB |
| API calls | ~50 Claude calls/day | Pay-per-use (very cheap — ~₹2/day) |

---

*Built with Python + GitHub Actions + GitHub Pages. Zero infrastructure, zero monthly cost.*
