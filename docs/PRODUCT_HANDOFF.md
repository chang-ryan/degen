# PRODUCT HANDOFF — the Macro-Top Instrumentation Suite ("degen")

> **For:** an agent picking this up to wrap the existing Python gauges in a simple
> visual web panel. **You do not need to design the analytics** — they exist and are
> battle-tested in a daily CLI brief. Your job is to **surface them**. This doc is the
> complete catalog of what's available, what each thing measures, where its data comes
> from, and how the pieces fit the mental model. Tech-stack is deliberately thin
> (FastAPI is the obvious port since everything is already Python) — the value here is
> the **inventory + the framework**, not the plumbing.

---

## 1. What this is (the one-paragraph pitch)

A local instrumentation suite that answers one question: **"is the AI/tech cycle topping,
and if so, when do you de-risk?"** It does **not** try to call the top (nothing can). It
instruments the *transmission mechanism* — the gauges that turn "expensive" into "forced
selling" — so a human operator gets a disciplined, falsifiable read every day instead of
vibes. The output today is a **daily markdown brief** (panels + a hand-written synopsis).
The product ask: turn that brief into a **live visual dashboard.**

### The philosophy (load-bearing — don't lose it in the port)
- **Instrument forced-selling, don't time tops.** Every gauge is about *the mechanism*, not prediction.
- **Gauges, not verdicts.** A panel says "here's what to watch and which band we're in," never "buy/sell."
- **Magnitude vs trigger are different axes.** Some gauges measure *how big* the move will be (froth, positioning); others measure *when* it releases (credit, ROI). Never conflate them.
- **Read internals, not the headline label.** The mechanical "risk-on 0/6" verdict can be misleading while internals rot — the UI must surface internals, not just a summary light.

---

## 2. The mental model — "Two Clocks" (this is the spine of the whole product)

The thesis reduces to a race between two clocks. **Productivity is real and is NOT one of
them** — grant the AI productivity boom fully; it times nothing.

- **Clock A — ROI / demand.** How fast durable, *exogenous* end-demand revenue ramps to
  justify the ~$400B/yr AI capex. Slowed structurally by the K-shape (gains to capital, not
  the consumer demand base). Gauges: `roi_coverage`, `ai_demand`, `consumer_health`, `distribution`.
- **Clock B — credit.** How long the financing holds before it cracks. Slow for the cash-rich
  core (hyperscaler FCF), **fast for the levered edge** (neoclouds, crypto-credit, private-credit
  datacenter SPVs). Gauges: `crypto_credit` (leading edge), HY OAS (corporate backstop, in `regime`).

Two more axes layered on top:
- **Magnitude / "the payload."** How violent the unwind will be when it comes (positioning,
  leverage, froth). Gauges: `retail_froth`, `momentum`, `mag7`, `cta`, + Lee's positioning chart (manual).
- **The kill-switch / posture.** Derived logic, not a single gauge: the **dip-buy window**
  (buy only when *legs basing AND VIX settling AND credit calm*) and the **de-risk triggers**
  (STRC<90 de-risk, STRC<80 cut hard, VIX>22 spike, CTA breach). This is what the dashboard
  should make glanceable: *are we green to buy, or is the window shut?*

> The single most useful visual would be: **two columns (Clock A | Clock B), a magnitude
> strip, and a posture banner** (dip-buy window OPEN/SHUT + active de-risk triggers).

---

## 3. The gauge catalog (the product surface — every analytic available)

All gauges live in `degen.macro` unless noted. Each is a pure function returning a frozen
dataclass — **trivially JSON-serializable**, so each maps 1:1 to a GET endpoint. "Source"
notes the upstream feed; **all are no-API-key except where flagged.**

### A. Regime & environment — the backdrop / style gate
| Gauge | Returns | Measures | Source | Key fields / read |
|---|---|---|---|---|
| `build()` | `Regime` | The 6-gauge stress verdict + trading style | FRED + yfinance | HY OAS (credit), MOVE (rate vol), VIX term-structure, NFCI (financial conditions), 10y TIPS (real rate), RSP/SPY (breadth). Verdict = risk-on/off (n/6 stress) + **style** (convexity vs defined-risk). **HY OAS here = Clock B's corporate backstop.** |
| `fear_greed()` | `FearGreed` | CNN Fear & Greed + 7 sub-indices | CNN F&G API | score + rating; subs (momentum, breadth, put/call, junk-bond, etc.). **Contrarian** — deep fear = constructive. |
| `buffett_indicator()` | `float` | Total market cap / GDP (valuation) | FRED | ~218% of GDP = richly valued. |
| `cross_asset()` | `CrossAsset` | Macro cross-asset tape | yfinance | DXY, Gold, BTC, Copper. |

### B. Clock B — credit (the trigger / leading edge)
| Gauge | Returns | Measures | Source | Key fields / read |
|---|---|---|---|---|
| `crypto_credit()` | `CryptoCredit` | **The leading credit edge** — MSTR/Strategy capital-structure stress as a dress rehearsal for AI-infra leverage | yfinance | `strc` (par 100), `strc_discount`, Strategy pref stack breadth (`pref_below_par`/`pref_total`/`pref_5d`), `mstr_btc_21d` (mNAV compression). **`.stress` (STRC<90) = de-risk-miners trigger. `.band` = crisis<80 / peg-failing<90 / stress-building<95 / normal.** |

### C. Clock A — ROI / demand (does revenue show up before credit cracks)
| Gauge | Returns | Measures | Source | Key fields / read |
|---|---|---|---|---|
| `roi_coverage()` | `RoiCoverage` | Lab ARR vs aggregate capex — the ROI numerator | **hand-entered** `roi_coverage.json` | `coverage` (ARR/capex), `exo_coverage` (strips `circular_pct`), `.closing` (ARR outgrowing capex?). **Honesty check: exogenous vs circular (NVDA→OpenAI→Azure loop inflates ARR).** |
| `ai_demand()` | `AiDemand` | Frontier intelligence $/Mtok — the commoditization / Jevons *denominator* | OpenRouter `/models` | cheapest & median frontier $/Mtok, model counts. Falling = intelligence commoditizing; volume must outrun it. (Module: `degen.ai_demand`.) |
| `consumer_health()` | `ConsumerHealth` | The consumer demand base + the consumer→credit bridge | FRED (8 series, last-good cached) | PCE/DPI `.gap` (spend>income), savings, revolving credit, CC delinquency, **debt-service ratio, initial claims** (labor-migration tell). |
| `distribution()` | `Distribution` | Who captures the productivity boom (the K-shape that *slows* Clock A) | FRED | productivity vs real-pay `.gap` (the wedge), labor share, corp profits, `.to_capital`. |

### D. Magnitude / lateness — "the payload, not the fuse"
| Gauge | Returns | Measures | Source | Key fields / read |
|---|---|---|---|---|
| `retail_froth()` | `RetailFroth` | Leverage + speculation (how big/late) | FRED + yfinance | margin debt + YoY, SPHB/SPLV high-beta, **2x single-stock ETF "casino"** (MSTU/NVDL/TSLL — cratering = spec crowd wrecked). |
| `momentum()` | `Momentum` | 6 leadership legs + the **dip-buy basing read** | yfinance | legs (MTUM/SPY, MAGS/SPY, SMH/SPY, SPHB/SPLV, RSP/SPY, VUG/VTV) with off-63d-high / run63 (fuel) / 5d (basing≥0). + VIX, VVIX. |
| `mag7()` | `Mag7` | Mega-cap concentration (color only, n=7) | yfinance | per-name 1d/21d/vs-50dma; count above 50dma. **Never used as breadth.** |
| `spx_breadth()` | `SpxBreadth` | The load-bearing breadth (n≈500) | yfinance + Wikipedia constituents | % above 50dma / 200dma. |
| `cta()` | `Cta` | Systematic-selling thresholds (the supply trigger) | **hand-entered** `cta_levels.json` | SPX spot vs short/medium/long CTA levels; breach = forced supply ON. Carries `asof` (goes stale). |

### E. Live theme trackers (the active theses)
| Gauge | Returns | Measures | Source | Key fields / read |
|---|---|---|---|---|
| `memory_prices()` | `MemoryPrices` | Memory super-cycle crux — contract-price forecast vs prints | **hand-entered** `memory_prices.json` | Jefferies +40–50% QoQ vs consensus; top marker ~2028; awaiting-print flag. |
| `memory_tape()` | `MemoryTape` | **Live memory-duopoly proxy** — EWY (≈25% Samsung + 10% SK Hynix); leads the contract print + Asia risk canary | yfinance | EWY level, 1d/5d/21d, off-63d-high. |

### F. Pipeline health (for the dashboard's own status bar)
| Tool | Returns | Use |
|---|---|---|
| `fred_health()` | list of (series, status, detail) | pings every FRED series — show which are live/stale. |
| `degen.health` (`health.main`) | exit code + table | **end-to-end liveness** across every source (yfinance/FRED/CNN/OpenRouter/crypto-credit/Wikipedia/EDGAR/X). Run on a schedule; surface as a green/red status pill. |

---

## 4. Per-ticker / options tooling (the pre-trade gate — secondary surface)

The macro suite answers "is the environment right." These answer "is *this trade* right."
Lower priority for a first dashboard, but available:

| Module | Purpose |
|---|---|
| `dashboard.build(ticker)` | Per-ticker options dashboard — IV vs HV, skew, term structure, liquidity, DTE-to-earnings. |
| `data.py` | yfinance wrappers: spot, expiries, option chains, realized vol, derived skew/term-structure/liquidity. |
| `greeks.py` | Black-Scholes price + delta/gamma/vega/theta + implied vol solver. |
| `iv_store.py` | **Daily ATM IV snapshot DB → IV rank / percentile** (the one thing no free API gives you). SQLite. |
| `size.py` | Defined-risk contract sizing + gap-sized shares, per the CONSTITUTION risk rules. |
| `heat.py` | Portfolio heat — sum of open max-losses, correlation-netted, vs a cap %. |

---

## 5. Data integrations (what's wired, and the auth boundary)

| Source | Used for | Auth | Notes |
|---|---|---|---|
| **yfinance** (Yahoo) | all price/vol/ETF/cross-asset | none | delayed, flaky per-call — wrap with retry. |
| **FRED** (fredgraph CSV) | credit, rates, consumer, distribution, valuation | none | per-series can 504; **already last-good-cached** to `data/fred_cache.json`. |
| **CNN Fear & Greed** | sentiment | none | needs browser headers. |
| **OpenRouter** `/models` | `ai_demand` price side | none (key only for token *volume*, not built) | |
| **Wikipedia** | S&P constituents (breadth denominator) | none | |
| **SEC EDGAR** | primary-source filings (`edgar.py`) | none (UA string) | |
| **X syndication** | pull post text for qualitative inputs | none | |
| **Robinhood MCP** | **live book** (positions/quotes/orders) | user session | **read-only by policy — never place orders without explicit instruction.** Book data is private. |
| **E*TRADE** (`etrade.py`) | long-term book positions/balances | OAuth 1.0a | read-only. Private. |
| **Discord ingest** (`ingest/`) | Lee's analyses, call hit-rate ledger, catalyst calendar | bot token | **raw digest is private** (contains real handles + P&L) — synthesize/anonymize only. |

**Manual inputs (no feed exists — the operator hand-enters):** `roi_coverage.json` (lab ARR/capex),
`memory_prices.json` (contract-price prints), `cta_levels.json` (CTA thresholds), and Lee's
combined-positioning SD chart (a paid terminal series). The dashboard should expose simple
edit forms for these, or read the JSON files.

---

## 6. The daily brief (the artifact you're visualizing)

`degen.daily.build_brief(tickers)` assembles the panels in this order, then a human writes the
`## Synopsis` memo on top (the narrative read — **this stays human/LLM-authored, not generated**):

1. **Synopsis** (hand-written memo + 2 one-line stat tags)
2. **What changed** (delta vs prior brief — auto-diffed from a saved snapshot in `data/snapshots/`)
3. Macro regime → Consumer → Distribution → Sentiment & valuation → Momentum/crowding →
   Breadth & systematic flows → Crypto / AI-infra credit → AI-infra demand → **AI ROI coverage (Clock A)** →
   Memory super-cycle → Mag7 concentration → Retail froth → Book (focus + watch tables)
4. **Upcoming catalysts** (countdown from `ingest/catalysts.py`)
5. **Qualitative inputs** (paste area; X-post puller)

Supporting machinery: **delta snapshots** (`data/snapshots/YYYY-MM-DD.json` → the "what changed"
lede), the **health check**, and a **privacy scanner** + pre-commit hook that blocks any live-book
personal number from entering tracked files.

---

## 7. The macro-top thesis (the narrative the gauges serve)

Condensed; full version in `docs/theses/ai-infra-cycle-top.md`. The dashboard's copy/tooltips
should echo this language so the numbers carry meaning:

- **Two clocks** (§2). ROI vs credit; productivity times nothing.
- **K-shape / fallacy of composition.** AI productivity as labor *substitution* expands margins
  for the first mover but, in aggregate, income-caps the consumer demand base (~68% of GDP) the
  capex must sell into. Substitution-ROI creates no net-new value; only an exogenous new market
  (the "gig-economy equivalent") closes the gap — and that historically lags infra by years.
- **Dark fiber.** The 2000 telecom build: the technology won, the *funders* were wiped out,
  the asset enabled the *next* cycle. Cost-down (cheaper tokens) helps demand but *accelerates
  obsolescence* of the sunk capex — bearish for the deployed fleet.
- **Magnitude vs trigger.** Froth/positioning (+5.34 SD combined, per Lee) = max downside fuel,
  NOT a timing signal. Credit (STRC) + ROI = the trigger. "Too early to short" and "the fuse is
  lighting" coexist.
- **The posture that falls out:** **gated-BTFD** — don't short a maxed-but-untimed top (you go
  broke being right), don't chase, keep powder; buy only when the dip-buy window opens; back up
  the truck on a credit-confirmed washout.

---

## 8. The web product (kept deliberately thin)

**Shape, not stack.** FastAPI is the natural port (everything is already Python; dataclasses
serialize for free). The minimum lovable product:

- **Endpoints:** one GET per gauge returning its dataclass as JSON, plus a `/brief` that returns
  the whole assembled set (+ the latest synopsis + the "what changed" delta). Reuse the existing
  functions verbatim — no analytics rewrite.
- **One page, card grid**, organized by the framework (§2): **Clock A column | Clock B column |
  Magnitude strip | Posture banner.** Each card = one panel, **color-coded by the gauge's own
  band/threshold** (e.g. `crypto_credit.band` → red/amber/green; the 3 dip-buy gates → 3 lights;
  `distribution.to_capital` → flag). Synopsis as the hero text; "what changed" as a ticker.
- **Caching is mandatory** — gauges hit slow/flaky endpoints. Server-side cache + scheduled
  refresh (FRED-heavy panels ~1×/day, price-based intraday). The FRED last-good cache already exists;
  mirror that pattern. Show a per-source freshness/health pill from `degen.health`.
- **Hard privacy boundary (do not skip):** the macro gauges are shareable; **the book is not.**
  Never put POSITIONS / P&L / account numbers / raw Discord on any networked surface. The repo
  already has a privacy scanner + gitignored local-only files (`POSITIONS.md`, `JOURNAL.md`,
  `roi_coverage.json`, etc.) — respect that line. A shared dashboard shows *gauges*, never the book.

---

## 9. Honest gaps / not-yet-built (so the next agent doesn't assume completeness)

- **`roi_coverage` token-VOLUME numerator** — only the price side (`ai_demand`) is wired; the
  demand-volume numerator needs an API key / manual rankings. ARR figures are hand-entered estimates.
- **Lee's combined-positioning SD** — paid terminal series; manual input, no feed.
- **CTA levels & memory prints** — hand-entered, go stale; carry `asof` and treat as suspect when old.
- **Congressional / insider-flow gauges** — discussed, not built (Quiver/Capitol Trades are free).
- **No alerting** — the posture/kill-switch logic exists conceptually but isn't a push system;
  a dashboard adding threshold alerts (STRC<80, VIX>22, CTA breach, dip-buy window flip) would be net-new value.
- **`ai_demand` reads the *denominator* only** — the commoditization story is half-instrumented
  until volume lands.

---

## 10. Where to look in the repo

- **Analytics:** `src/degen/macro.py` (all macro gauges), `ai_demand.py`, `health.py`.
- **Assembly:** `src/degen/daily.py` (`build_brief`, render blocks, snapshots).
- **Per-ticker/options:** `dashboard.py`, `data.py`, `greeks.py`, `iv_store.py`, `size.py`, `heat.py`.
- **Integrations:** `edgar.py`, `etrade.py`, `ingest/` (Discord/calls/catalysts).
- **Narrative / framework:** `docs/theses/` (esp. `ai-infra-cycle-top.md`), `docs/daily/` (worked examples),
  `HANDOFF.md` (operating model), `CONSTITUTION.md` (risk rules), `README.md` (run commands).
- **Run it:** `uv run python -m degen.daily` (full brief), `uv run python -m degen.health` (liveness),
  `uv run python -m degen.macro` (regime), `uv run python -m degen.macro fred` (FRED validator).
