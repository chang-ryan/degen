# degen — technical stack

Local Python toolkit for sizing, portfolio heat, and pre-trade math on a
speculative options book. The trading system itself — rules, worldview,
positions, journal — lives in the markdown files (`HANDOFF.md` is the entry
point). This README is the engineering side: how the code is laid out, what
runs it, and how to add to it.

---

## Stack

| Concern | Choice | Why |
|---|---|---|
| Python version | **3.12** (pinned via `.python-version`) | Modern type syntax, `slots=True` dataclasses, broad package support. |
| Env + deps | **[uv](https://docs.astral.sh/uv/)** | Single tool for Python install, venv, lockfile. ~10–100× faster than pip/poetry. |
| Packaging | **hatchling** + src layout | Standard PEP 621 build backend; src layout avoids import shadowing. |
| Lint + format | **ruff** | Replaces black + isort + flake8. One tool, fast. |
| Type checker | **mypy** (strict) | Catches sizing/Greeks bugs before they hit a live position. |
| Tests | **pytest** | BS math is tested against Hull reference values. |
| Market data | **yfinance** | Free, no API key, ~15-min delayed. Sufficient for a 2–6mo horizon. |
| Macro data | **FRED** (public CSV endpoint) | Free, no API key. Credit spreads, financial conditions, real rates for the regime dashboard. |
| Math | **numpy + scipy** | `scipy.stats.norm` for BS, `scipy.optimize.brentq` for implied vol. |
| Tabular | **pandas** | yfinance returns DataFrames; we stay in them. |

Deliberately **not** in the stack: real-time feeds, paid options data, broker
APIs, backtesting frameworks, ORMs. Add only when a specific trade decision
required them and didn't have them.

---

## Layout

```
degen/
├── CONSTITUTION.md          # risk rules (the guardrail)
├── HANDOFF.md               # trading system overview — start here for context
├── MACRO.md                 # working worldview, updated weekly
├── POSITIONS.md             # open + proposed trades
├── WATCHLIST.md             # candidates with triggers
├── JOURNAL.md               # closed-trade log + edge measurement
│
├── pyproject.toml           # deps, ruff/mypy/pytest config
├── .python-version          # 3.12
├── uv.lock                  # reproducible env (committed)
│
├── src/degen/
│   ├── greeks.py            # Black-Scholes + Greeks + IV solver
│   ├── data.py              # yfinance wrappers (spot, chain, history, RV, skew, earnings)
│   ├── size.py              # CONSTITUTION sizing rules as functions
│   ├── heat.py              # portfolio heat with correlation netting
│   ├── iv_store.py          # SQLite IV snapshots → IV rank/percentile (self-built history)
│   ├── dashboard.py         # per-ticker pre-trade dashboard (the gate input)
│   └── macro.py             # portfolio-wide regime dashboard (sits above the gate)
│
└── tests/
    └── test_greeks.py       # BS sanity vs Hull reference values
```

---

## Setup (one time)

```bash
# install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# from the repo root: install Python 3.12, create .venv, install deps
uv sync
```

That's it. No `pip install`, no manual venv, no `activate`.

---

## Day-to-day commands

```bash
uv run pytest                    # run tests
uv run ruff check . && uv run ruff format .   # lint + format
uv run mypy                      # type-check

uv run python -m degen.heat      # ad-hoc script invocation
uv run python -m degen.dashboard CRM TEAM   # per-ticker pre-trade dashboard(s)
uv run python -m degen.macro     # portfolio-wide macro regime read
uv run python -m degen.iv_store snapshot     # append today's IV snapshot to the store
uv run python                    # REPL with the package importable

uv add <pkg>                     # add a runtime dep
uv add --dev <pkg>               # add a dev dep
uv lock --upgrade                # bump lockfile
```

`uv run` executes inside the project venv without activating it. If you prefer
an activated shell: `source .venv/bin/activate`.

---

## Module reference

### `degen.greeks`
Black-Scholes pricing and Greeks. No dividend yield (add `q` if needed).

```python
from degen.greeks import bs_price, delta, implied_vol

bs_price(s=100, k=105, t=0.25, r=0.04, sigma=0.30, kind="call")  # → price
delta(s=100, k=105, t=0.25, r=0.04, sigma=0.30, kind="put")      # → Δ
implied_vol(price=4.20, s=100, k=105, t=0.25, r=0.04, kind="call")
```

Conventions: `t` in years, `r` and `sigma` as decimals (0.04 not 4). `vega` is
per 1.00 vol change (divide by 100 for per-vol-point). `theta` is per year
(divide by 365 for per-calendar-day).

### `degen.data`
yfinance wrappers. Delayed ~15 min; no key needed.

```python
from degen.data import spot, expiries, chain, history, realized_vol

spot("NVDA")                       # last price
expiries("NVDA")                   # ['2026-06-13', '2026-06-20', ...]
ch = chain("NVDA", "2026-09-19")   # Chain(expiry, calls, puts)
realized_vol("NVDA", lookback_days=30)  # annualized
```

Yahoo's IV column is fine for triage; recompute with `greeks.implied_vol` if a
sizing decision depends on the number.

### `degen.size`
The CONSTITUTION sizing rules as code.

```python
from degen.size import defined_risk_contracts, gap_sized_shares

# Defined-risk: long options / debit spreads
defined_risk_contracts(
    port_value=100_000,
    premium_per_contract=350,   # debit × 100
    risk_pct=0.01,              # 1% until edge proven
)

# Naked / margin / LETF: size to 2–3σ overnight gap ≤ 5%
gap_sized_shares(
    port_value=100_000,
    underlying_price=180,
    annual_vol=0.45,
    sigmas=2.5,
    max_gap_pct=0.05,
)
```

### `degen.heat`
Portfolio heat with correlation groups netted.

```python
from degen.heat import Position, heat_report

positions = [
    Position("CRM",   max_loss=1_000, group="saas-phoenix"),
    Position("TEAM",  max_loss=  800, group="saas-phoenix"),
    Position("SMH",   max_loss=1_200, group="ai-semis-hedge"),
    Position("USO",   max_loss=  500, group="oil"),
]
print(heat_report(positions, port_value=100_000, cap_pct=0.08))
```

### `degen.iv_store`
SQLite store of ~30-DTE constant-maturity ATM IV snapshots — the one input no
free API gives you. Append one snapshot per day; after ~20 observations
`iv_rank` / `iv_percentile` become meaningful (252-day lookback).

```python
from degen.iv_store import snapshot, iv_rank

snapshot(["NVDA", "CRM"])   # append today's reading to data/iv_snapshots.db
iv_rank("CRM")              # 0..1, or None until enough history accrues
```

CLI: `uv run python -m degen.iv_store snapshot` (reads `tickers.txt`) is wired to
a daily launchd job in `scripts/`.

### `degen.dashboard`
Per-ticker pre-trade dashboard — the input to the gate. One block per ticker:
spot + 30d HV, ATM IV / IV rank / IV-over-HV, 25Δ skew, term-structure slope,
liquid-strike count, and days-to-earnings, each with a plain-language verdict.

```python
from degen.dashboard import build

print(build("CRM", target_dte=120))
```

CLI: `uv run python -m degen.dashboard CRM TEAM`

### `degen.macro`
Portfolio-wide **regime** dashboard — sits *above* the per-ticker gate. It does
not time tops; it instruments the transmission mechanism that turns "expensive"
into forced selling, and prints one verdict — **risk-on / neutral / defensive** —
that maps to position style (e.g. defensive → defined-risk spreads, not naked
longs). This is the CONSTITUTION's vol rule lifted from one ticker to the book.

Six signals, all no-API-key (FRED CSV + yfinance):

| Signal | Source | Reads stress when |
|---|---|---|
| Credit (HY OAS) | FRED | spreads in top 30% of 1y range or widening ≥30bp/mo |
| Rate vol (MOVE) | yfinance | top 30% of 1y range |
| Equity-vol term structure (VIX/VIX3M) | yfinance | backwardated (front > 3M) |
| Financial conditions (NFCI) | FRED | tighter than average (> 0) |
| Real rate (10y TIPS) | FRED | rising ≥25bp/mo |
| Breadth (RSP/SPY) | yfinance | equal-weight lagging cap-weight > 2% over 50d |

```python
from degen.macro import build

print(build())   # → Regime(verdict=..., signals=...)
```

CLI: `uv run python -m degen.macro`

Each feed is wrapped: any single series can time out or go empty without taking
the dashboard down — it reads `unavailable` and drops out of the verdict
denominator. FRED's CSV endpoint degrades per-series (some series hang while
others return instantly), so partial reads are normal; re-run later for the full
set.

---

## Conventions

- **Type hints everywhere.** `mypy --strict` is on.
- **Sizes in dollars, not %.** Convert at the boundary. % is for display only.
- **No hidden state.** Functions take all inputs explicitly; no module-level
  config or singleton clients.
- **yfinance is the boundary.** If Yahoo breaks, only `data.py` needs to change.
- **Tests for math, not for I/O.** `greeks.py` is tested against published
  reference values. `data.py` is a smoke test at most.

---

## Known sharp edges

- **yfinance breaks occasionally** when Yahoo changes their site. Symptom:
  empty DataFrames. Fix: `uv lock --upgrade-package yfinance`.
- **Options IV from Yahoo can be stale or zero** for illiquid strikes. Filter
  by OI/volume before trusting.
- **Risk-free rate is passed in, not fetched.** Hardcoding `r=0.04` is fine
  for 2026; revisit if the Fed moves materially.
- **FRED's CSV endpoint degrades per-series.** Some series return in <1s while
  others hang (504 or stalled socket). `macro.py` guards every fetch with a 10s
  timeout and degrades to a partial read rather than hanging — a partial macro
  verdict is expected behavior, not a bug. Re-run later for the full six signals.
- **No live broker connection.** Positions are reconciled from Robinhood CSV
  exports (see HANDOFF §2). The code never trades.

---

## What this toolkit is not

- Not a backtester. The horizon is 2–6 months and `n` is small; the JOURNAL
  is the feedback loop, not a vectorized backtest.
- Not an execution system. Orders are placed manually in Robinhood.
- Not a signal generator. It sizes and stress-tests *your* ideas; it doesn't
  produce them.
