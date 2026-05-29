# Gap Alert Scanner

Scans the **top 50 US large-cap stocks** (market cap > $100B) for significant gap events over the last 3 trading days and sends an HTML email alert with the qualifying stocks and the top 3 news headlines explaining why the gap happened.

Runs automatically at **4 PM CST every weekday** via GitHub Actions.

---

## What Is a Gap?

A gap occurs when a stock's opening range does not overlap with the previous day's range.

**Gap-Down** — today's HIGH is below yesterday's LOW:
```
Yesterday:        ──────────────  (Low: $100)
Today:   ──────────────           (High: $95)
         ↑ Gap of $5 = 5%
```

**Gap-Up** — today's LOW is above yesterday's HIGH:
```
Yesterday:  ──────────────        (High: $100)
Today:                ──────────  (Low: $106)
                      ↑ Gap of $6 = 6%
```

---

## Trigger Thresholds

| Direction | Threshold | Rationale |
|-----------|-----------|-----------|
| Gap-Down  | > **4.0%** | Only fires on significant sell-offs in mega-cap stocks |
| Gap-Up    | > **1.5%** | Catches meaningful upside momentum moves |

These are asymmetric by design — large-caps rarely gap down 4%+ without a major catalyst, while 1.5% gap-ups are tradeable momentum signals.

---

## Universe — How the Top 50 Is Built

The script does **not** use a hardcoded list. Every run it:

1. Starts with ~110 large-cap candidate tickers
2. Calls `yf.Ticker(ticker).fast_info.market_cap` for each
3. Filters to those with market cap **> $100 billion**
4. Sorts by market cap descending
5. Takes the **top 50**

This means the universe automatically reflects current market realities — a stock that drops below $100B is dropped, a newly qualifying stock is added.

---

## How the Script Works — Step by Step

```
┌─────────────────────────────────────────────────────────────┐
│  Step 1: Build Universe                                      │
│  ~110 candidates → fast_info market cap fetch →             │
│  filter >$100B → sort desc → top 50                         │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  Step 2: Scan for Gaps (last 3 trading days)                 │
│  For each of the 50 tickers:                                 │
│    • Download last 10 trading days of OHLC via yfinance      │
│    • Slice to last 4 rows (covers 3 day-over-day comparisons)│
│    • Check each consecutive pair:                            │
│        Gap-Down: curr_high < prev_low  AND pct > 4.0%        │
│        Gap-Up:   curr_low  > prev_high AND pct > 1.5%        │
│    • Collect all qualifying gaps as a list                   │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  Step 3: Fetch News                                          │
│  For each qualifying stock:                                  │
│    • Call yf.Ticker(ticker).news                             │
│    • Extract top 3 headlines (title, publisher, link)        │
│    • Handles both legacy and new yfinance news formats       │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  Step 4: Send Email                                          │
│  • Builds dark-theme HTML report                             │
│  • One card per gap: ticker, gap %, price levels, news       │
│  • Sends via Gmail SMTP SSL (port 465)                       │
│  • Also saves gap_alert_YYYY-MM-DD.html as a local artifact  │
└─────────────────────────────────────────────────────────────┘
```

---

## Gap Calculation Formula

**Gap-Down %**
```
gap_pct = (prev_low - today_high) / prev_low × 100
```

**Gap-Up %**
```
gap_pct = (today_low - prev_high) / prev_high × 100
```

This is a **strict gap** definition — the entire day's range must be outside the previous day's range. A stock that merely opens lower but trades back into yesterday's range does **not** qualify.

---

## Email Format

Each qualifying stock gets a card in the email showing:

- Ticker + market cap
- Gap type (GAP-UP / GAP-DOWN) and gap %
- Previous reference price (prev Low for down, prev High for up)
- Today's reference price (today High for down, today Low for up)
- Day close price
- **Top 3 news headlines** with publisher and link

Subject line example:
```
Gap Alert 2026-05-28 14:00 — 3 gap(s): MU (↑5.1%), ARM (↑2.5%), WMT (↓4.2%)
```

If no gaps qualify, a confirmation email is still sent so you know the scanner ran successfully.

---

## GitHub Actions Schedule

```yaml
cron: '0 22 * * 1-5'   # 22:00 UTC = 4:00 PM CST / 5:00 PM CDT
```

Runs Monday–Friday after market close. Can also be triggered manually from the **Actions** tab → **Gap Alert Scanner** → **Run workflow**.

---

## Configuration

### Thresholds (gap_alert.py)

```python
DOWN_THRESHOLD = 4.0    # gap-down must exceed this %
UP_THRESHOLD   = 1.5    # gap-up must exceed this %
LOOKBACK_DAYS  = 3      # number of recent trading days to scan
MIN_MARKET_CAP = 100e9  # minimum market cap ($100 billion)
TOP_N          = 50     # number of stocks in the universe
```

### GitHub Secrets Required

| Secret | Value |
|--------|-------|
| `EMAIL_FROM` | Gmail address used as the sender |
| `EMAIL_APP_PASSWORD` | Gmail App Password (16-char, generated at myaccount.google.com/apppasswords) |

The recipient (`avin.khurana18@gmail.com`) is hardcoded in the workflow. Change `EMAIL_TO` in the workflow env or script to redirect alerts.

### Running Locally

```bash
pip install -r requirements.txt

export EMAIL_FROM="youraddress@gmail.com"
export EMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"

python gap_alert.py
```

---

## Data Source

All data is sourced from **Yahoo Finance via yfinance** — fully open source, no paid subscription required.

- Price data: `yf.download()` with `auto_adjust=True`
- Market cap: `yf.Ticker().fast_info.market_cap`
- News: `yf.Ticker().news`

---

## File Structure

```
GAPGIT/
├── gap_alert.py              # main scanner script
├── requirements.txt          # yfinance, pandas, requests
└── .github/
    └── workflows/
        └── gap_alert.yml     # GitHub Actions schedule
```

---

## 60-Day Backtest Results (Mar–May 2026)

Running with current thresholds (Down >4%, Up >1.5%) against the last 60 trading days produced **62 signals** across 50 stocks:

- **59 gap-ups**, **3 gap-downs** — reflecting the bullish market trend in this period
- Most active gappers: **MU** (7×), **AMD** (5×), **ARM** (4×), **TXN** (3×), **CAT** (3×)
- Largest gap-up: AMD +11.81% on May 6
- Largest gap-down: NFLX -7.39% on Apr 17
- Notable cluster: 17 stocks gapped up simultaneously on Apr 8 (macro reversal day)
