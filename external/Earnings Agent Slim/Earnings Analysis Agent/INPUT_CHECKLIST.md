# Earnings Preview — Input Checklist

**Use:** When the agent triggers `prep earnings for [TICKER]`, it presents this checklist. Drop the items you have; mark "skip" on what you don't.

---

## Required (workflow blocks if missing)

- [ ] **Pre-earnings decision:** BUY / SELL / HOLD / TRIM + price triggers
  - Example: "TRIM $225 scaling to $250, half off at $250"
- [ ] **Recommended position size** ($ amount or % of portfolio)
- [ ] **Earnings preview score** (1-5 composite, where 1 = high-conviction bullish, 3 = neutral, 5 = high-conviction bearish)

## Recommended (degrades quality if absent)

- [ ] **Pre-print thoughts** (free-form 2-5 sentences on what you expect, key drivers, risks)
- [ ] **Bull case framing** — what would drive the upside scenario
- [ ] **Bear case / risk framing** — what would drive the down-print scenario
- [ ] **Deltas to consensus** you want flagged (free-form — only needed if your view differs from what's recorded)

## High-value optional (Tier-1 — most impactful for tactical analysis)

- [ ] **Short interest detail** — for squeeze risk + positioning
- [ ] **Implied move / historical reaction** — for implied move + historical reaction asymmetry
- [ ] **Vol surface — vol table + skew chart** — for the options-market read

## Optional (Tier-2 — color and refinement)

- [ ] **Sell-side research PDFs** — drop in `/Earnings Analysis Agent/Reference Files/`
  - Naming convention: `YYYYMMDD_BrokerName_TICKER_topic.pdf`
- [ ] **Desk / sales commentary** — paste into chat
- [ ] **Whisper number** (if any)
- [ ] **Macro alt data** — tax refund tracking, consumer confidence, anything sector-relevant
- [ ] **Borrow rate / utilization** — for pair short feasibility on micro-caps
- [ ] **Position data** — drop `workspace/{TICKER}/position.json` (direction, shares, $-invested, %-weight). OPTIONAL; if absent, position size shows "not provided".

## Per-ticker config (one-time setup, then maintained)

If this is the first time running on this ticker, the agent needs:

- [ ] **Sector ETF** for beta computation (e.g., XLV for healthcare, XLF for financials)
- [ ] **Comp set** (3-5 tickers): direct competitor, adjacent, distributor/supplier
- [ ] **Key metrics list** to populate KPI tables (segment revenues, volume metrics, etc.)
- [ ] **Whisper culture flag** (does this name have whisper number tracking?)
- [ ] **Desk-commentary culture flag** (crowded names yes; mid-caps no)

Saved to `workspace/{TICKER}/config.yaml` for reuse.

---

## What the agent auto-pulls (no action) — free sources only

For reference, here's what you don't need to provide because the agent pulls it:

**From the company IR site / latest 8-K:**
- Print date (AMC/BMO)
- Headline KPIs from the most recent results

**From your manually-entered consensus (`consensus.csv`):**
- Consensus estimates (rev, EPS, EBITDA, segment metrics) for current Q + Q+1 + FY + FY+1
- Cons EPS dispersion stats (CV, # estimators, revision skew) computed from the CSV

**From SEC EDGAR (free fetcher):**
- `python scripts/edgar_fetch.py --ticker {TICKER}` writes 10-K/10-Q/8-K extracts to `workspace/{TICKER}/filings/`
- Full-text from filings for revenue-recognition footnotes, MD&A, risk factors
- Historical surprise (last 8 Q) and price reactions from filings / IR history

**From the stock-reaction helper:**
- Daily prices for ticker + comp set (for correlations, beta, vol) via Yahoo Finance

**Sequencing & local:**
- Comp earnings dates for sequencing analysis (from peer IR calendars)
- Local thesis_current.md if present
- Local prior outputs, Reference Files, position.json, research_notes/

**For sector-specific KPIs** (e.g., health insurers' quarterly MLR / SG&A ratio / membership): the agent ALSO pulls the last 4 quarterly 10-Qs via the EDGAR fetcher to extract these at quarterly granularity.

---

## How to send inputs

Paste / drop files into the chat. The agent will inventory them at workflow step [1] and ask for what's still missing.

For data that needs to live on disk (PDFs, model files), drop in:
- Model file: `/Earnings Analysis Agent/Reference Files/{TICKER}/models/{TICKER}_model_{YYYY_MMDD}.xlsx`
- Sell-side PDFs: `/Earnings Analysis Agent/Reference Files/{TICKER}/sell_side_notes/{YYYYMMDD}_{Broker}_{TICKER}_{topic}.pdf`
- Screenshots / positioning: paste into chat or save to `workspace/{TICKER}/positioning/`

---

## Default behavior if items skipped

If you skip an item:

| Skipped | Effect |
|---|---|
| Pre-earnings decision | Workflow halts. This is required. |
| Position size | Workflow halts. Required. |
| Preview score | Workflow halts. Required. |
| Pre-print thoughts | Agent uses research_notes/ + thesis_current.md + cons as narrative anchor; output reads less personal |
| Short interest detail | Squeeze risk section reads "data not provided" |
| Implied move / reaction | Marked "data not provided" |
| Vol surface | Appendix A.1 (Options Surface) marked "supporting data not provided" but plain-English read still attempted if implied move available |
| Sell-side PDFs | Alt data table populated from research_notes/ only; sell-side row left out |
| Desk commentary | Buy-side bar omits desk-color subsection |
| Whisper | Whisper line omitted |
| position.json | Position size shows "not provided" — never fabricate a placeholder |
| research_notes/ empty | Note that this is genuinely first-time research |
