#!/usr/bin/env python3
"""
Gap Alert v1.0
Scans top 50 US stocks (market cap >$100B) for today's gap.
  Gap-down > 4%  OR  Gap-up > 1.5%  → email alert with top 3 news per stock.
Schedule: 4 PM CST (22:00 UTC) on weekdays via GitHub Actions.

Gap definition (High/Low based):
  Gap-down: today_high < prev_low  → pct = (prev_low  - today_high) / prev_low  * 100
  Gap-up:   today_low  > prev_high → pct = (today_low  - prev_high) / prev_high * 100
"""

import os
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

import yfinance as yf
import pandas as pd

# ── Thresholds ──────────────────────────────────────────────────────────────
DOWN_THRESHOLD = 4.0    # gap-down must exceed this %
UP_THRESHOLD   = 1.5    # gap-up must exceed this %
MIN_MARKET_CAP = 100e9  # $100 billion
TOP_N          = 50

# ── Email (override via env vars / GitHub Secrets) ───────────────────────────
EMAIL_FROM     = os.environ.get('EMAIL_FROM', '')
EMAIL_PASSWORD = os.environ.get('EMAIL_APP_PASSWORD', '')
EMAIL_TO       = os.environ.get('EMAIL_TO', 'avin.khurana18@gmail.com')

# ── Broad candidate universe (~110 stocks); market cap check narrows to top 50 ──
CANDIDATES = [
    # Mega-cap tech / growth
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "COST", "NFLX",
    # Semiconductors / software
    "AMD",  "QCOM", "TXN",  "INTU", "ADBE",  "PANW", "CRWD", "MRVL", "AMAT", "MU",
    # EDA & equipment
    "SNPS", "CDNS", "KLAC", "LRCX", "ADI",
    # Healthcare / biotech
    "LLY",  "UNH",  "JNJ",  "ABBV", "MRK",   "AMGN", "ISRG", "VRTX", "REGN", "TMO",
    # Healthcare — diversified
    "ABT",  "DHR",  "SYK",  "MDT",  "GILD",  "ZTS",  "BMY",  "ELV",  "HCA",  "CI",
    # Financials
    "JPM",  "BAC",  "WFC",  "GS",   "MS",    "AXP",  "BLK",  "SCHW", "C",    "PNC",
    # Payments / diversified finance
    "COF",  "BRK-B","SPGI", "MMC",  "V",     "MA",
    # Consumer discretionary / retail
    "WMT",  "HD",   "MCD",  "NKE",  "LOW",   "TGT",  "TJX",  "BKNG", "UBER", "ABNB",
    "CMG",
    # Energy
    "XOM",  "CVX",
    # Industrials / infrastructure
    "GE",   "CAT",  "HON",  "RTX",  "DE",    "UPS",  "WM",   "APH",  "EQIX", "AMT",
    # Enterprise tech / cloud
    "CRM",  "ORCL", "IBM",  "NOW",  "FTNT",
    # Telecom / utilities
    "TMUS", "NEE",  "DUK",  "SO",
    # Consumer staples / materials / services
    "PG",   "KO",   "PEP",  "LIN",  "ACN",   "PFE",
    # High-growth large-cap
    "PLTR", "SNOW", "ARM",
]

BAR = "─" * 70


# ── Step 1: Build market-cap universe ────────────────────────────────────────

def build_universe():
    """
    Fetches market cap for every candidate via fast_info and returns
    the top TOP_N tickers with market cap > MIN_MARKET_CAP, sorted desc.
    """
    print(f"  Fetching market caps for {len(CANDIDATES)} candidates...")
    cap_map = {}

    for i, ticker in enumerate(CANDIDATES):
        try:
            t = yf.Ticker(ticker)
            # fast_info is significantly faster than .info for a single value
            mc = None
            try:
                mc = t.fast_info.market_cap
            except AttributeError:
                mc = t.info.get('marketCap')

            if mc and mc > MIN_MARKET_CAP:
                cap_map[ticker] = mc
                print(f"    [{i+1:3d}/{len(CANDIDATES)}] {ticker:<6}  ${mc/1e9:,.0f}B  ✓")
            else:
                print(f"    [{i+1:3d}/{len(CANDIDATES)}] {ticker:<6}  (< $100B, skipped)")
        except Exception as e:
            print(f"    [{i+1:3d}/{len(CANDIDATES)}] {ticker:<6}  ERR: {e}")

        time.sleep(0.1)

    universe = sorted(cap_map, key=cap_map.get, reverse=True)[:TOP_N]
    print(f"\n  Universe built: {len(universe)} stocks with market cap > $100B\n")
    return universe, cap_map


# ── Step 2: Detect today's gap ───────────────────────────────────────────────

def detect_today_gap(ticker):
    """
    Downloads last 5 trading days and checks the final two rows.
    Uses High/Low definition (same as gap_scanner.py).
    Returns a gap dict or None.
    """
    try:
        df = yf.download(ticker, period='5d', auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if len(df) < 2:
            return None

        prev = df.iloc[-2]
        curr = df.iloc[-1]

        prev_low  = float(prev['Low'])
        prev_high = float(prev['High'])
        curr_low  = float(curr['Low'])
        curr_high = float(curr['High'])

        # Gap-down: today's entire range is below yesterday's low
        if curr_high < prev_low:
            gap_pct = (prev_low - curr_high) / prev_low * 100
            if gap_pct > DOWN_THRESHOLD:
                return dict(
                    ticker=ticker,
                    date=df.index[-1].date(),
                    type='GAP-DOWN',
                    gap_pct=round(gap_pct, 2),
                    prev_ref=round(prev_low, 2),
                    day_ref=round(curr_high, 2),
                    open=round(float(curr['Open']), 2),
                    close=round(float(curr['Close']), 2),
                )

        # Gap-up: today's entire range is above yesterday's high
        elif curr_low > prev_high:
            gap_pct = (curr_low - prev_high) / prev_high * 100
            if gap_pct > UP_THRESHOLD:
                return dict(
                    ticker=ticker,
                    date=df.index[-1].date(),
                    type='GAP-UP',
                    gap_pct=round(gap_pct, 2),
                    prev_ref=round(prev_high, 2),
                    day_ref=round(curr_low, 2),
                    open=round(float(curr['Open']), 2),
                    close=round(float(curr['Close']), 2),
                )

    except Exception as e:
        print(f"    ERROR {ticker}: {e}")

    return None


# ── Step 3: Fetch news ───────────────────────────────────────────────────────

def get_news(ticker, n=3):
    """
    Returns up to n Yahoo Finance headlines via yfinance.
    Handles both the legacy flat format and the newer nested 'content' format
    introduced in yfinance ≥0.2.51.
    """
    try:
        items = yf.Ticker(ticker).news or []
        results = []
        for item in items:
            if len(results) >= n:
                break
            # New format wraps fields inside a 'content' key
            inner = item.get('content', item)
            title = inner.get('title') or item.get('title', '')
            pub   = (inner.get('provider', {}).get('displayName') or
                     item.get('publisher', ''))
            link  = (inner.get('canonicalUrl', {}).get('url') or
                     item.get('link', '#'))
            if title:
                results.append({'title': title, 'publisher': pub, 'link': link})
        return results
    except Exception:
        return []


# ── HTML email ───────────────────────────────────────────────────────────────

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#c9d1d9;font-family:'Courier New',monospace;
     font-size:14px;padding:24px;max-width:900px;margin:0 auto}
h1{color:#58a6ff;border-bottom:2px solid #21262d;padding-bottom:12px;
   margin-bottom:24px;font-size:20px}
.env{background:#161b22;border:1px solid #30363d;border-radius:8px;
     padding:16px 20px;margin-bottom:24px;font-size:14px;line-height:1.8}
.card{border:1px solid #30363d;border-radius:8px;padding:20px;
      margin-bottom:16px;background:#161b22}
.card.down{border-left:4px solid #f85149}
.card.up{border-left:4px solid #3fb950}
.hdr{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px}
.ticker{font-size:22px;font-weight:bold}
.badge{padding:4px 14px;border-radius:12px;font-size:12px;font-weight:bold;color:#000}
.badge.down{background:#f85149}
.badge.up{background:#3fb950}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:16px}
.met{background:#0d1117;padding:10px 14px;border-radius:6px}
.met-l{color:#8b949e;font-size:11px;text-transform:uppercase;margin-bottom:4px}
.met-v{font-size:17px;font-weight:bold}
.news-box{background:#0d1117;border:1px solid #21262d;border-radius:6px;padding:14px}
.news-title{color:#8b949e;font-size:11px;text-transform:uppercase;
            letter-spacing:1px;margin-bottom:10px}
.news-item{margin-bottom:10px;font-size:13px;line-height:1.6}
.news-item a{color:#58a6ff;text-decoration:none}
.pub{color:#8b949e;font-size:11px}
.no-gap{text-align:center;color:#8b949e;padding:40px;font-size:15px}
.foot{color:#8b949e;font-size:12px;text-align:center;margin-top:32px;
      padding-top:16px;border-top:1px solid #21262d}
.pos{color:#3fb950}
.neg{color:#f85149}
"""


def build_email_html(gaps, run_date, universe_size, cap_map):
    no_gap = '<div class="no-gap">No qualifying gaps today — scanner ran successfully.</div>'

    cards = ""
    for g in gaps:
        is_down = g['type'] == 'GAP-DOWN'
        cls     = 'down' if is_down else 'up'
        sign    = '-' if is_down else '+'
        mc      = cap_map.get(g['ticker'], 0)
        mc_str  = f"${mc/1e9:,.0f}B" if mc else "—"

        prev_label = 'Prev Low'  if is_down else 'Prev High'
        day_label  = 'Today High' if is_down else 'Today Low'

        news_html = "".join(
            f'<div class="news-item">'
            f'{i+1}. <a href="{n["link"]}" target="_blank">{n["title"]}</a>'
            + (f'<br><span class="pub">{n["publisher"]}</span>' if n.get('publisher') else '')
            + '</div>'
            for i, n in enumerate(g.get('news', []))
        ) or '<div class="news-item" style="color:#8b949e">No news available at this time.</div>'

        cards += f"""
<div class="card {cls}">
  <div class="hdr">
    <div>
      <span class="ticker">{g['ticker']}</span>
      &nbsp;<span style="color:#8b949e;font-size:13px">Mkt Cap: {mc_str}
      &nbsp;·&nbsp; {g['date']}</span>
    </div>
    <span class="badge {cls}">{g['type']} &nbsp;{sign}{g['gap_pct']:.2f}%</span>
  </div>
  <div class="metrics">
    <div class="met">
      <div class="met-l">Gap Size</div>
      <div class="met-v {'neg' if is_down else 'pos'}">{sign}{g['gap_pct']:.2f}%</div>
    </div>
    <div class="met">
      <div class="met-l">{prev_label}</div>
      <div class="met-v">${g['prev_ref']:,.2f}</div>
    </div>
    <div class="met">
      <div class="met-l">{day_label}</div>
      <div class="met-v">${g['day_ref']:,.2f}</div>
    </div>
    <div class="met">
      <div class="met-l">Day Close</div>
      <div class="met-v">${g['close']:,.2f}</div>
    </div>
  </div>
  <div class="news-box">
    <div class="news-title">Top 3 News — Why the Gap?</div>
    {news_html}
  </div>
</div>"""

    threshold_note = (f"Gap-Down &gt; {DOWN_THRESHOLD}% &nbsp;|&nbsp; "
                      f"Gap-Up &gt; {UP_THRESHOLD}% &nbsp;|&nbsp; "
                      f"Universe: top {universe_size} US stocks by market cap &gt;$100B")

    gap_count_color = '#f85149' if gaps else '#8b949e'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Gap Alert — {run_date}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>Gap Alert &nbsp;<small style="color:#8b949e;font-size:14px">{run_date}</small></h1>
<div class="env">
  <b style="color:{gap_count_color}">{len(gaps)} qualifying gap{'s' if len(gaps) != 1 else ''} today</b>
  &nbsp;&nbsp;{threshold_note}
</div>
{cards if cards else no_gap}
<div class="foot">
  Gap Alert v1.0 &nbsp;|&nbsp; {run_date} &nbsp;|&nbsp;
  Data: Yahoo Finance &nbsp;|&nbsp; Not financial advice.
</div>
</body>
</html>"""


# ── Email delivery ────────────────────────────────────────────────────────────

def send_email(subject, html_body):
    if not EMAIL_FROM or not EMAIL_PASSWORD:
        print("  Email skipped — EMAIL_FROM or EMAIL_APP_PASSWORD not set.")
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = EMAIL_FROM
        msg["To"]      = EMAIL_TO
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(EMAIL_FROM, EMAIL_PASSWORD)
            s.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"  Email sent → {EMAIL_TO}")
    except Exception as e:
        print(f"  Email error: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    run_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{BAR}")
    print(f"  GAP ALERT SCANNER v1.0  —  {run_date}")
    print(f"  Thresholds:  Gap-Down > {DOWN_THRESHOLD}%  |  Gap-Up > {UP_THRESHOLD}%")
    print(f"  Universe:    top {TOP_N} US stocks with market cap > $100B (dynamic)")
    print(f"{BAR}\n")

    # ── 1. Build universe ───────────────────────────────────────────────────
    universe, cap_map = build_universe()

    # ── 2. Scan each ticker for today's gap ─────────────────────────────────
    print(f"\n{BAR}")
    print(f"  SCANNING {len(universe)} TICKERS FOR TODAY'S GAP")
    print(BAR)

    gaps = []
    for i, ticker in enumerate(universe):
        print(f"  [{i+1:2d}/{len(universe)}] {ticker:<6} ...", end=" ", flush=True)
        g = detect_today_gap(ticker)
        if g:
            sign = '-' if g['type'] == 'GAP-DOWN' else '+'
            print(f"*** {g['type']}  {sign}{g['gap_pct']:.2f}% ***")
            gaps.append(g)
        else:
            print("no gap")
        time.sleep(0.1)

    # ── 3. Fetch news for qualifying gaps ───────────────────────────────────
    if gaps:
        print(f"\n  Fetching news for {len(gaps)} qualifying stock(s)...")
        for g in gaps:
            g['news'] = get_news(g['ticker'])
            print(f"    {g['ticker']}: {len(g['news'])} headline(s)")
            time.sleep(0.3)

    # ── 4. Console summary ──────────────────────────────────────────────────
    print(f"\n{BAR}")
    print(f"  RESULTS: {len(gaps)} qualifying gap(s) of {len(universe)} scanned")
    print(BAR)
    if gaps:
        for g in gaps:
            sign = '-' if g['type'] == 'GAP-DOWN' else '+'
            print(f"  {g['ticker']:<6}  {g['type']:<9}  {sign}{g['gap_pct']:.2f}%"
                  f"  open={g['open']:.2f}  close={g['close']:.2f}")
    else:
        print("  No stocks exceeded the gap thresholds today.")

    # ── 5. Build and send email ─────────────────────────────────────────────
    html = build_email_html(gaps, run_date, len(universe), cap_map)

    if gaps:
        summary = ", ".join(
            f"{g['ticker']} ({'↓' if g['type'] == 'GAP-DOWN' else '↑'}{g['gap_pct']:.1f}%)"
            for g in gaps
        )
        subject = f"Gap Alert {run_date} — {len(gaps)} gap(s): {summary}"
    else:
        subject = f"Gap Alert {run_date} — No qualifying gaps today"

    send_email(subject, html)

    # ── 6. Save HTML artifact ────────────────────────────────────────────────
    fname = f"gap_alert_{datetime.now().strftime('%Y-%m-%d')}.html"
    with open(fname, 'w') as f:
        f.write(html)
    print(f"\n  Saved → {fname}")
    print(f"\n{BAR}\n")


if __name__ == "__main__":
    main()
