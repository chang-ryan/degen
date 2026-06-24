"""Portfolio-wide regime dashboard. The input *above* the per-ticker gate.

The per-ticker dashboard answers "is THIS vol cheap." This answers the upstream
question: "is the environment one where long-premium convexity is even the right
style right now." It does not time tops — nothing does. It instruments the
*transmission mechanism* that turns "expensive" into "forced selling": credit,
funding/rate vol, equity-vol term structure, financial conditions, real rates,
and market breadth. When those deteriorate together, you shift from naked
convexity to defined-risk and cut gross — which is the CONSTITUTION's vol rule
lifted from one ticker to the whole book.

Sources, all no-API-key:
  - FRED via the public fredgraph CSV endpoint (credit, conditions, rates)
  - yfinance for cross-asset vol (^VIX/^VIX3M, ^MOVE) and breadth (RSP/SPY)

Every feed is wrapped: any single series can 504 or go empty without taking the
whole dashboard down — that signal just reads `unavailable` and drops out of the
verdict denominator.

Measurement principles (distilled from team review, 2026-06-10):
  1. Breadth needs a representative sample. A breadth measure is only as robust
     as its denominator — n=503 (spx_breadth) is load-bearing; n=7 (mag7) is
     not. The Mag7 count is a *concentration* gauge for the AI-capex complex,
     never a market-breadth input, and nothing downstream may depend on it.
     RSP/SPY is the continuous breadth proxy inside the regime verdict;
     spx_breadth() is the explicit %-above-MA read.
  2. Pair ratios are indicative, not pure. MTUM holds only the *long* leg of
     the momentum factor, so MTUM/SPY isolates momo-vs-beta, not market-neutral
     momentum (that needs long/short custom baskets we can't build from ETFs).
     MAGS is ~equal-weight vs SPY's cap-weight, so that ratio mixes a weighting
     effect into the leadership read. Use the legs for direction and turn
     (basing), not as precise factor returns.
  3. Sentiment indices are contrarian inputs. Fear & Greed deep in fear is
     *constructive* for buyers, not a warning — but it stays interpretive color
     (n=1 composite), never a mechanical gate.
  4. Know each number's provenance. Everything here is pulled from exchange-
     derived or institutional endpoints (yfinance/Yahoo quotes, FRED, CNN's own
     F&G API, SEC EDGAR) — not web-searched figures. Hand-entered levels (e.g.
     cta_levels.json) carry an `asof` and must be treated as stale once the
     market has moved away from their reference close.
"""

from __future__ import annotations

import io
import json
import time
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf

from degen.data import history

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.cnn.com/markets/fear-and-greed",
    "Origin": "https://www.cnn.com",
}

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
FRED_TIMEOUT = 10  # seconds; urllib has no default timeout and will hang on a stalled socket
PCTILE_WINDOW = 252  # ~1y trading days; matches the IV-rank convention


@dataclass(frozen=True, slots=True)
class Signal:
    key: str
    label: str
    value: float | None
    display: str  # preformatted value + context for the report
    stress: bool
    note: str
    available: bool = True


@dataclass(frozen=True, slots=True)
class Regime:
    asof: str
    signals: tuple[Signal, ...]
    verdict: str  # risk-on | neutral | defensive
    stress_count: int
    available_count: int
    curve_note: str

    def __str__(self) -> str:
        return format_regime(self)


# ---------- fetch helpers ----------


def _fred_series(series_id: str, retries: int = 3) -> pd.Series:
    """Full history for a FRED series via the no-key CSV endpoint.

    fredgraph intermittently 504s on individual series; retry quick failures with
    a short backoff, but do NOT retry a timeout — it already waited the full
    budget, and a series that's hanging will just hang again (FRED degrades
    per-series, so other signals can still resolve). Missing observations are
    encoded as '.' and coerced to NaN, then dropped.
    """
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(FRED_CSV.format(series_id), timeout=FRED_TIMEOUT) as resp:
                raw = resp.read()
            df = pd.read_csv(io.BytesIO(raw))
            break
        except TimeoutError:  # already waited FRED_TIMEOUT; don't double the stall
            raise
        except Exception:  # transient HTTP (fredgraph 504s); retry with backoff
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))
    df.columns = ["date", "value"]
    s = pd.to_numeric(df["value"], errors="coerce")
    s.index = pd.to_datetime(df["date"])
    return s.dropna()


def _close(ticker: str, period: str = "1y") -> pd.Series:
    h = history(ticker, period=period)
    return h["Close"].dropna()


def _market_offhi() -> float | None:
    """SPY's own off-63d-high — the beta baseline netted out of the basket gauges (#1).

    Every basket gauge (neocloud, private_credit, makers, the credit levered edge) is
    'avg % off 63d high', which is dominated by market beta: in a selloff they all
    flash together and *look* like N independent Clock-B cracks when it's really one
    factor. Subtracting this isolates the idiosyncratic (excess) stress — a basket
    down only as much as SPY is NOT a confirmation; down more than SPY is.
    """
    try:
        s = _close("SPY", "6mo").dropna()
        return float(s.iloc[-1] / s.tail(63).max() - 1)
    except Exception:
        return None


def _pctile(s: pd.Series, window: int = PCTILE_WINDOW) -> tuple[float, float]:
    """(current value, its percentile within the trailing window)."""
    tail = s.tail(window)
    cur = float(tail.iloc[-1])
    rank = float((tail <= cur).mean())
    return cur, rank


def _change_1m(s: pd.Series, obs: int = 22) -> float:
    """Change vs ~1 month ago, in the series' native units."""
    return float(s.iloc[-1] - s.tail(obs).iloc[0])


# ---------- individual signals ----------


def _sig_credit() -> Signal:
    s = _fred_series("BAMLH0A0HYM2")  # HY OAS, in percent (2.75 = 275bp)
    cur, pct = _pctile(s)
    chg = _change_1m(s)
    stress = pct > 0.70 or chg >= 0.30
    direction = "widening" if chg > 0.05 else "tightening" if chg < -0.05 else "flat"
    return Signal(
        key="credit",
        label="Credit (HY OAS)",
        value=cur,
        display=f"{cur:.2f}%  (252d pctile {pct:.0%}, 1m {chg:+.2f}pp, {direction})",
        stress=stress,
        note="credit cracks before equity — the cleanest forced-selling canary",
    )


def _sig_ratevol() -> Signal:
    m = _close("^MOVE")
    cur, pct = _pctile(m)
    stress = pct > 0.70
    return Signal(
        key="ratevol",
        label="Rate vol (MOVE)",
        value=cur,
        display=f"{cur:.0f}  (252d pctile {pct:.0%})",
        stress=stress,
        note="funding-stress tell; leverage gets margin-called on rate vol",
    )


def _sig_equityvol() -> Signal:
    vix = float(_close("^VIX").iloc[-1])
    vix3m = float(_close("^VIX3M").iloc[-1])
    backwardated = vix > vix3m
    shape = "BACKWARDATED" if backwardated else "contango"
    return Signal(
        key="equityvol",
        label="Equity vol (VIX TS)",
        value=vix,
        display=f"VIX {vix:.1f} / 3M {vix3m:.1f} → {shape}",
        stress=backwardated,
        note="front>3M = acute near-term fear; contango = calm",
    )


def _sig_conditions() -> Signal:
    s = _fred_series("NFCI")  # Chicago Fed financial conditions; >0 = tighter than avg
    cur = float(s.iloc[-1])
    stress = cur > 0
    return Signal(
        key="conditions",
        label="Fin. conditions (NFCI)",
        value=cur,
        display=f"{cur:+.2f}  ({'tighter' if cur > 0 else 'looser'} than average)",
        stress=stress,
        note="composite; one number for whether conditions are tightening",
    )


def _sig_realrates() -> Signal:
    s = _fred_series("DFII10")  # 10y TIPS yield = real rate
    cur, _ = _pctile(s)
    chg = _change_1m(s)
    stress = chg >= 0.25
    return Signal(
        key="realrates",
        label="Real rate (10y TIPS)",
        value=cur,
        display=f"{cur:.2f}%  (1m {chg:+.2f}pp)",
        stress=stress,
        note="rising real rates compress long-duration / AI-growth multiples",
    )


def _sig_breadth() -> Signal:
    rsp = _close("RSP")
    spy = _close("SPY")
    df = pd.concat([rsp, spy], axis=1).dropna()
    ratio = df.iloc[:, 0] / df.iloc[:, 1]
    chg = float(ratio.iloc[-1] / ratio.iloc[-50] - 1)
    stress = chg < -0.02
    return Signal(
        key="breadth",
        label="Breadth (RSP/SPY)",
        value=chg,
        display=f"50d {chg:+.1%}  ({'narrowing' if chg < 0 else 'broadening'})",
        stress=stress,
        note="equal- vs cap-weight; narrowing = index held up by a few names = fragile",
    )


_BUILDERS: tuple[tuple[str, str, object], ...] = (
    ("credit", "Credit (HY OAS)", _sig_credit),
    ("ratevol", "Rate vol (MOVE)", _sig_ratevol),
    ("equityvol", "Equity vol (VIX TS)", _sig_equityvol),
    ("conditions", "Fin. conditions (NFCI)", _sig_conditions),
    ("realrates", "Real rate (10y TIPS)", _sig_realrates),
    ("breadth", "Breadth (RSP/SPY)", _sig_breadth),
)


def _curve_note() -> str:
    """10y-2y slope as context only — a slow recession signal, not a 2-6mo timing tool."""
    try:
        s = _fred_series("T10Y2Y")
        cur = float(s.iloc[-1])
        return f"{cur:+.2f}pp ({'inverted' if cur < 0 else 'positive'})"
    except Exception:  # context line only; never block the verdict
        return "n/a"


# The verdict weights signals so correlated ones can't gang up (#2). The rate/vol
# trio (ratevol, equityvol, realrates) is largely ONE factor — a single bond-market
# move can fire all three — so each gets 0.5 (≈1.5 together, not 3.0). Credit is the
# canary the whole module is built around, so it outweighs the trio on its own.
_SIGNAL_WEIGHTS = {
    "credit": 2.0,  # the cleanest forced-selling canary
    "conditions": 1.5,  # NFCI composite (independent of the vol trio)
    "breadth": 1.0,
    "ratevol": 0.5,
    "equityvol": 0.5,
    "realrates": 0.5,
}


def _verdict(stress: float, available: float) -> str:
    """Weighted stress fraction → regime. Inputs are summed signal *weights*, not counts."""
    if available == 0:
        return "no data"
    frac = stress / available
    if frac <= 0.20:
        return "risk-on"
    if frac <= 0.50:
        return "neutral"
    return "defensive"


def build() -> Regime:
    signals: list[Signal] = []
    for key, label, fn in _BUILDERS:
        try:
            signals.append(fn())  # type: ignore[operator]
        except Exception as e:  # degrade gracefully per-feed
            signals.append(
                Signal(
                    key=key,
                    label=label,
                    value=None,
                    display=f"unavailable ({type(e).__name__})",
                    stress=False,
                    note="",
                    available=False,
                )
            )
    available = [s for s in signals if s.available]
    stress_count = sum(1 for s in available if s.stress)  # raw count, for display honesty
    w_avail = sum(_SIGNAL_WEIGHTS.get(s.key, 1.0) for s in available)
    w_stress = sum(_SIGNAL_WEIGHTS.get(s.key, 1.0) for s in available if s.stress)
    return Regime(
        asof=date.today().isoformat(),
        signals=tuple(signals),
        verdict=_verdict(w_stress, w_avail),  # weighted, so credit/conditions lead
        stress_count=stress_count,
        available_count=len(available),
        curve_note=_curve_note(),
    )


# ---------- sentiment, valuation, cross-asset (context, not stress votes) ----------


@dataclass(frozen=True, slots=True)
class FearGreed:
    score: float
    rating: str
    asof: str
    subs: tuple[tuple[str, str], ...]  # (label, rating) for the 7 components


# CNN's seven canonical components, mapped to short labels.
_FG_SUBS = (
    ("market_momentum_sp125", "Momentum"),
    ("stock_price_strength", "Strength"),
    ("stock_price_breadth", "Breadth"),
    ("put_call_options", "Put/Call"),
    ("market_volatility_vix", "Volatility"),
    ("safe_haven_demand", "Safe-haven"),
    ("junk_bond_demand", "Junk-bond"),
)


def fear_greed() -> FearGreed | None:
    """CNN Fear & Greed headline + the 7 sub-indicators. None on failure.

    Pulled from CNN's public dataviz endpoint (needs full browser headers or it
    429/418s). The headline often hides a split — the sub-indicators are the
    signal (e.g. greedy momentum over fearful breadth = narrow leadership).
    """
    try:
        req = urllib.request.Request(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers=_BROWSER_HEADERS,
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        fg = d["fear_and_greed"]
        subs = tuple(
            (label, d[key]["rating"])
            for key, label in _FG_SUBS
            if isinstance(d.get(key), dict) and "rating" in d[key]
        )
        return FearGreed(
            score=float(fg["score"]), rating=str(fg["rating"]), asof=str(fg["timestamp"]), subs=subs
        )
    except Exception:  # endpoint blocked/changed; brief degrades to n/a
        return None


def buffett_indicator() -> float | None:
    """Total US market cap / GDP, as a percent. None when FRED is unavailable.

    Numerator: Fed Z.1 nonfinancial corporate equities (NCBEILQ027S, $millions) —
    the standard Buffett-indicator series after FRED retired the WILL5000* family.
    Denominator: GDP ($B SAAR). Slow quarterly valuation gauge — historically ~75%
    (cheap) to ~200%+ (frothy).
    """
    try:
        mktcap = _fred_series("NCBEILQ027S")  # $ millions
        g = _fred_series("GDP")  # $ billions SAAR
        return float((mktcap.iloc[-1] / 1000) / g.iloc[-1] * 100)
    except Exception:
        return None


@dataclass(frozen=True, slots=True)
class CrossAsset:
    dxy: float | None
    gold: float | None
    btc: float | None
    copper: float | None
    skew: float | None
    skew_pctile: float | None
    copper_gold: float | None  # growth proxy; relative, watch the trend not the level


def cross_asset() -> CrossAsset:
    """Risk-appetite / safe-haven / tail-pricing read across asset classes."""

    def last(ticker: str) -> float | None:
        try:
            return float(_close(ticker, "1y").iloc[-1])
        except Exception:
            return None

    dxy, gold, btc, copper = last("DX-Y.NYB"), last("GC=F"), last("BTC-USD"), last("HG=F")
    skew = skew_pct = None
    try:
        s = _close("^SKEW", "1y")
        skew, (_, skew_pct) = float(s.iloc[-1]), _pctile(s)
    except Exception:
        pass
    cg = (copper / gold) if (copper and gold) else None
    return CrossAsset(dxy, gold, btc, copper, skew, skew_pct, cg)


# ---------- momentum / crowding (context, not stress votes) ----------


@dataclass(frozen=True, slots=True)
class MomoLeg:
    label: str
    pair: str  # "MTUM/SPY"
    dd63: float | None  # ratio drawdown from its 63d high (<=0); how far the unwind has run
    run63: float | None  # numerator's 63d return; the crowding "fuel" still in the trade
    d5: float | None  # 5d change in the ratio; <0 still unwinding, >=0 basing/turning


@dataclass(frozen=True, slots=True)
class Momentum:
    legs: tuple[MomoLeg, ...]
    vix: float | None
    vvix: float | None  # vol-of-vol; >~100 = traders bidding up VIX options = stress brewing


# Leadership pairs: a crowded sleeve / its benchmark. A rolling-over ratio is the
# unwind; the numerator's own run is how much air is still underneath it.
# Indicative, not pure (module principle #2): MTUM is long-leg-only momentum,
# MAGS is ~equal-weight vs SPY's cap-weight. Read direction and turn, not levels.
_MOMO_PAIRS = (
    ("MTUM", "SPY", "Momentum factor"),
    ("MAGS", "SPY", "Mag7 mega-cap"),
    ("SMH", "SPY", "Semis"),
    ("SPHB", "SPLV", "High-beta/low-vol"),
    ("RSP", "SPY", "Breadth (eq/cap)"),
    ("VUG", "VTV", "Growth/value"),
)


def _momo_leg(num: str, den: str, label: str) -> MomoLeg:
    a = _close(num, "6mo")
    b = _close(den, "6mo")
    df = pd.concat([a, b], axis=1).dropna()
    df.columns = ["a", "b"]
    r = df["a"] / df["b"]
    dd63 = float(r.iloc[-1] / r.tail(63).max() - 1)
    d5 = float(r.iloc[-1] / r.iloc[-6] - 1) if len(r) > 5 else None
    run63 = float(df["a"].iloc[-1] / df["a"].iloc[-64] - 1) if len(df) > 63 else None
    return MomoLeg(label, f"{num}/{den}", dd63, run63, d5)


def momentum() -> Momentum:
    """Leadership/crowding panel: how far the momentum unwind has run, and the fuel left.

    `dd63` (ratio off its 63d high) measures how much the crowded trade has already
    unwound; `run63` (the winner's own 63d return) is the air still underneath it; a
    negative `d5` means the ratio is still making lower lows (not yet basing). VIX/VVIX
    flag whether vol is confirming — the dip-buy window is legs basing while vol settles.
    """
    legs: list[MomoLeg] = []
    for num, den, label in _MOMO_PAIRS:
        try:
            legs.append(_momo_leg(num, den, label))
        except Exception:  # one sleeve degrades to dashes, panel still renders
            legs.append(MomoLeg(label, f"{num}/{den}", None, None, None))

    def last(ticker: str) -> float | None:
        try:
            return float(_close(ticker, "1y").iloc[-1])
        except Exception:
            return None

    return Momentum(tuple(legs), last("^VIX"), last("^VVIX"))


# ---------- Mag7 concentration (context, not stress votes) ----------


@dataclass(frozen=True, slots=True)
class Mag7Name:
    ticker: str
    last: float | None
    chg_1d: float | None
    chg_21d: float | None
    above_50dma: bool | None


@dataclass(frozen=True, slots=True)
class Mag7:
    names: tuple[Mag7Name, ...]
    above_50: int  # concentration gauge — NOT breadth (n=7; see module principles)
    total: int  # how many resolved (guards against a flaky feed skewing the count)


# The mega-caps whose AI-capex flows circle back into each other's revenue — the
# index *is* these names, so their internal breadth is a concentration health check.
_MAG7 = ("AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA")


def mag7() -> Mag7:
    """Per-name Mag7 read + concentration count (n above 50dma).

    Concentration color only — with n=7 this is not a breadth measure and nothing
    may depend on it (module principle #1). What it's for: 7/7 = the AI-capex
    complex is holding up the cap-weighted tape; a slide toward 3/7 means the
    leaders are rolling even while the index looks fine. Market breadth lives in
    spx_breadth() and the RSP/SPY regime signal.
    """
    rows: list[Mag7Name] = []
    breadth = total = 0
    for t in _MAG7:
        try:
            h = _close(t, "6mo")
            last = float(h.iloc[-1])
            ma50 = float(h.tail(50).mean())
            c1 = float(h.iloc[-1] / h.iloc[-2] - 1)
            c21 = float(h.iloc[-1] / h.iloc[-22] - 1) if len(h) > 22 else None
            above = last > ma50
            breadth += int(above)
            total += 1
            rows.append(Mag7Name(t, last, c1, c21, above))
        except Exception:  # one name degrades to dashes, doesn't skew breadth
            rows.append(Mag7Name(t, None, None, None, None))
    return Mag7(tuple(rows), breadth, total)


# ---------- SPX breadth (the load-bearing breadth measure) ----------


_WIKI_SPX = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


@dataclass(frozen=True, slots=True)
class SpxBreadth:
    above_50: int
    above_200: int
    total: int

    @property
    def pct_50(self) -> float:
        return self.above_50 / self.total

    @property
    def pct_200(self) -> float:
        return self.above_200 / self.total


def _spx_symbols() -> list[str]:
    req = urllib.request.Request(_WIKI_SPX, headers=_BROWSER_HEADERS)
    html = urllib.request.urlopen(req, timeout=30).read().decode()
    table = pd.read_html(io.StringIO(html))[0]
    return [str(s).replace(".", "-") for s in table["Symbol"]]


def spx_breadth() -> SpxBreadth | None:
    """% of S&P 500 members above their 50/200dma — index-wide breadth.

    Breadth over the full membership (n≈503) is the load-bearing measure; Mag7
    internal breadth (n=7) stays in the brief as concentration color only. One
    batch download, ~30-60s; any name without enough history just drops out.
    """
    try:
        syms = _spx_symbols()
        px = yf.download(syms, period="1y", auto_adjust=True, progress=False)["Close"]
        a50 = a200 = total = 0
        for col in px.columns:
            s = px[col].dropna()
            if len(s) < 60:
                continue
            last = float(s.iloc[-1])
            total += 1
            a50 += int(last > float(s.tail(50).mean()))
            a200 += int(len(s) >= 200 and last > float(s.tail(200).mean()))
        return SpxBreadth(a50, a200, total) if total else None
    except Exception:
        return None


# ---------- CTA thresholds (manual levels from team/sellside notes) ----------


_CTA_FILE = Path("cta_levels.json")


@dataclass(frozen=True, slots=True)
class CtaLevel:
    name: str  # "short" | "medium" | "long"
    level: float  # absolute SPX index level
    dist: float  # spot/level - 1; negative = breached, supply is flowing


@dataclass(frozen=True, slots=True)
class Cta:
    asof: str  # date the levels were quoted — they drift, treat stale ones with suspicion
    source: str
    spot: float
    levels: tuple[CtaLevel, ...]


def cta() -> Cta | None:
    """Distance from SPX to the CTA systematic-selling thresholds.

    Levels are hand-entered into `cta_levels.json` whenever the team/sellside
    shares fresh ones — they can't be derived from free feeds. A breach turns
    systematic supply ON, which is exactly the forced-selling phase this module
    exists to instrument; supply flowing into *calm credit* is the entry setup.
    """
    try:
        cfg = json.loads(_CTA_FILE.read_text())
        spot = float(_close("^GSPC", "1mo").iloc[-1])
        levels = tuple(
            CtaLevel(k, float(cfg[k]), spot / float(cfg[k]) - 1)
            for k in ("short", "medium", "long")
            if cfg.get(k) is not None
        )
        if not levels:
            return None
        return Cta(str(cfg.get("asof", "?")), str(cfg.get("source", "")), spot, levels)
    except Exception:
        return None


# ---------- memory super-cycle price tracker (hand-entered, like cta) ----------
# The crux gauge for the memory thesis: are DRAM/NAND contract prices tracking the
# super-bull forecast (Jefferies: +40-50% QoQ 3Q26 >> consensus) or consensus? Prints
# above = cycle real, top ~2028; at/below = top sooner. Free feeds can't see contract
# prices, so you hand-enter prints into memory_prices.json. See docs/theses/memory-supercycle.md.

_MEMORY_FILE = Path("memory_prices.json")


@dataclass(frozen=True, slots=True)
class MemoryPrices:
    source: str
    fc_3q: tuple[float, float] | None  # forecast 3Q QoQ % range (bull)
    consensus_3q: tuple[float, float] | None
    top_marker: str
    latest: dict | None  # most recent observed print carrying a DRAM/NAND number
    awaiting: bool  # True until a numeric print lands


def memory_prices() -> MemoryPrices | None:
    """Memory contract-price prints vs the super-cycle forecast (hand-entered)."""
    try:
        cfg = json.loads(_MEMORY_FILE.read_text())
        fc = cfg.get("forecast", {})
        obs = cfg.get("observed", [])

        latest = None
        for o in reversed(obs):
            if o.get("dram_qoq_pct") is not None or o.get("nand_qoq_pct") is not None:
                latest = o
                break

        def _rng(v: object) -> tuple[float, float] | None:
            return (float(v[0]), float(v[1])) if isinstance(v, list) and len(v) == 2 else None

        return MemoryPrices(
            source=str(fc.get("source", "")),
            fc_3q=_rng(fc.get("3Q_qoq_pct")),
            consensus_3q=_rng(fc.get("consensus_3q_qoq_pct")),
            top_marker=str(fc.get("top_marker", "")),
            latest=latest,
            awaiting=latest is None,
        )
    except Exception:
        return None


# ---------- Korea-beta canary (memory tilt — NOT the memory duopoly) ----------
# HONEST SCOPE: EWY (iShares MSCI South Korea) is a BROAD Korea fund (banks, autos,
# Samsung ~20-25%, SK Hynix ~5-8%) — so this tape is a Korea-beta/risk canary with a
# memory TILT, not a clean memory read. For direct memory exposure use makers()
# (005930.KS / 000660.KS). Kept because Korea (KOSPI) led the early-June momo unwind,
# so it's a useful Asia-risk tape that happens to lean memory; read it as such.


@dataclass(frozen=True, slots=True)
class MemoryTape:
    ewy: float | None  # EWY level
    d1: float | None  # 1d change
    d5: float | None  # 5d change
    d21: float | None  # 21d change
    off_hi: float | None  # off its 63d high (the unwind-so-far)


def memory_tape() -> MemoryTape:
    """Korea-beta canary via EWY (broad Korea, memory tilt — direct makers in makers())."""
    try:
        s = _close("EWY", "6mo").dropna()
        return MemoryTape(
            ewy=float(s.iloc[-1]),
            d1=float(s.iloc[-1] / s.iloc[-2] - 1) if len(s) > 1 else None,
            d5=float(s.iloc[-1] / s.iloc[-6] - 1) if len(s) > 5 else None,
            d21=float(s.iloc[-1] / s.iloc[-22] - 1) if len(s) > 21 else None,
            off_hi=float(s.iloc[-1] / s.tail(63).max() - 1),
        )
    except Exception:
        return MemoryTape(None, None, None, None, None)


# ---------- semicap & memory complex (equity-beta health of the supply oligopoly) ----------
# The supply side of the AI-infra stack: the oligopoly leaders at the binding
# constraints (memory HBM, CoWoS packaging, EUV litho, power semis). HONEST SCOPE:
# this measures their *stock drawdown* (equity beta), NOT supply tightness/pricing
# power — it can't see CoWoS lead times or HBM allocation (no free feed). So it's a
# complex-health read, de-beta'd vs SPY; the bottleneck-tightness it's named for
# would need a hand-entered gauge. Foreign-listed where there's no clean US line
# (Samsung/Hynix on .KS in local currency; off-high/5d is currency-neutral).
_MAKERS = {
    "MU": "Micron — US memory pure-play (HBM/DRAM/NAND)",
    "005930.KS": "Samsung — HBM/DRAM/NAND + foundry (KRW)",
    "000660.KS": "SK Hynix — HBM leader (KRW)",
    "285A.T": "Kioxia — NAND (JPY)",
    "TSM": "TSMC — CoWoS packaging + logic foundry",
    "ASML": "ASML — EUV litho monopoly",
    "IFNNY": "Infineon — power-semi leader (ADR)",
}


@dataclass(frozen=True, slots=True)
class Makers:
    avg_offhi: float | None
    avg_5d: float | None
    n: int
    names: tuple[tuple[str, float, float | None], ...]  # (ticker, off-hi, 5d), worst-first
    market_offhi: float | None = None  # SPY off-63d-high — for the de-beta'd excess (#1)

    @property
    def excess_offhi(self) -> float | None:
        """Complex drawdown beyond the market's — the idiosyncratic (de-beta'd) read."""
        if self.avg_offhi is None or self.market_offhi is None:
            return None
        return self.avg_offhi - self.market_offhi


def makers() -> Makers:
    """The semicap/memory supply oligopoly — equity-beta health (de-beta'd vs SPY)."""
    rows: list[tuple[str, float, float | None]] = []
    for t in _MAKERS:
        try:
            s = _close(t, "6mo").dropna()
            off = float(s.iloc[-1] / s.tail(63).max() - 1)
            d5 = float(s.iloc[-1] / s.iloc[-6] - 1) if len(s) > 5 else None
            rows.append((t, off, d5))
        except Exception:
            continue
    rows.sort(key=lambda r: r[1])
    offs = [o for _, o, _ in rows]
    d5s = [d for _, _, d in rows if d is not None]
    return Makers(
        avg_offhi=(sum(offs) / len(offs)) if offs else None,
        avg_5d=(sum(d5s) / len(d5s)) if d5s else None,
        n=len(rows),
        names=tuple(rows),
        market_offhi=_market_offhi(),
    )


# ---------- AI ROI coverage (the Clock-A numerator) ----------
# The blind spot: ai_demand() tracks the PRICE side (intelligence commoditizing —
# the Jevons denominator). This tracks the REVENUE side — lab ARR run-rates vs
# aggregate hyperscaler capex — the thing that answers "is paid demand catching the
# spend before credit cracks (Clock B)." Free feeds can't see ARR/capex, so it's
# hand-entered (roi_coverage.json). The honesty check is exogenous-vs-circular:
# circular ARR (NVDA->OpenAI->Azure->NVDA, vendor-financed) inflates the numerator
# without anchoring it in end-customer value. See ai-infra-cycle-top.md (two clocks).

_ROI_FILE = Path("roi_coverage.json")


@dataclass(frozen=True, slots=True)
class RoiCoverage:
    asof: str | None
    total_arr: float | None  # $B, sum of lab run-rates
    capex: float | None  # $B, aggregate annual
    coverage: float | None  # total_arr / capex
    exo_coverage: float | None  # exogenous-only coverage (strips circular_pct)
    circular_pct: float | None  # est. share of ARR that's AI-internal/vendor-financed
    arr_growth: float | None  # ARR growth vs prior period
    capex_growth: float | None  # capex growth vs prior period
    vol_growth: float | None  # token-volume growth (Jevons numerator), optional
    labs: tuple[tuple[str, float], ...]  # (name, arr_b) for display
    note: str | None

    @property
    def closing(self) -> bool | None:
        """Is the coverage *ratio* rising? ARR outgrowing capex = Clock A catching up.

        Mathematically correct for ratio direction, but DELIBERATELY magnitude-blind:
        0.135 -> 0.140 reads True while the gap is still a chasm. Always read it next
        to `coverage` and `gap_x` — direction without distance is falsely reassuring.
        """
        if self.arr_growth is None or self.capex_growth is None:
            return None
        return self.arr_growth > self.capex_growth

    @property
    def gap_x(self) -> float | None:
        """Distance to 1.0x coverage (1 - coverage); how far paid demand is from funding capex."""
        return (1.0 - self.coverage) if self.coverage is not None else None


def roi_coverage() -> RoiCoverage | None:
    """Lab ARR vs aggregate capex — the AI-ROI coverage gauge (hand-entered)."""

    def _growth(latest: float | None, prior: float | None) -> float | None:
        return (latest / prior - 1) if (latest and prior) else None

    try:
        cfg = json.loads(_ROI_FILE.read_text())
        capex = cfg.get("capex", {})
        labs_raw = cfg.get("labs", [])

        labs = [
            (str(la.get("name", "?")), float(la["arr_b"])) for la in labs_raw if la.get("arr_b")
        ]
        total_arr = sum(a for _, a in labs) or None
        prior_arr = (
            sum(float(la["prior_arr_b"]) for la in labs_raw if la.get("prior_arr_b")) or None
        )

        cap = float(capex["annual_b"]) if capex.get("annual_b") else None
        prior_cap = float(capex["prior_annual_b"]) if capex.get("prior_annual_b") else None

        circ = cfg.get("circular_pct")
        circ = float(circ) if circ is not None else None
        coverage = (total_arr / cap) if (total_arr and cap) else None
        exo = (total_arr * (1 - circ) / cap) if (total_arr and cap and circ is not None) else None

        vol = cfg.get("token_volume", {})
        return RoiCoverage(
            asof=cfg.get("asof"),
            total_arr=total_arr,
            capex=cap,
            coverage=coverage,
            exo_coverage=exo,
            circular_pct=circ,
            arr_growth=_growth(total_arr, prior_arr),
            capex_growth=_growth(cap, prior_cap),
            vol_growth=_growth(vol.get("idx"), vol.get("prior_idx")),
            labs=tuple(labs),
            note=cfg.get("note"),
        )
    except Exception:
        return None


# ---------- crypto / AI-infra credit gauge ----------
# The MSTR/Strategy capital structure is the leverage node of the BTC-treasury
# complex and a *dress rehearsal* for AI-infra leverage (leverage against volatile
# collateral — BTC there, GPUs/contracts in the neoclouds). STRC is engineered to
# trade at $100 par via monthly dividend resets; its discount to par is a live
# funding-stress gauge that LEADS the miners and rhymes with the private-credit
# unwind risk under the whole AI buildout. Credit cracking here = the 2008-side of
# the unwind taxonomy. See docs/theses/mstr-strc-contagion.md + ai-infra-cycle-top.md.

_STRATEGY_PREFS = ("STRC", "STRK", "STRF", "STRD")  # the Strategy preferred stack


@dataclass(frozen=True, slots=True)
class CryptoCredit:
    strc: float | None  # STRC price (par = 100)
    strc_discount: float | None  # strc/100 - 1; negative = below par = funding stress
    pref_below_par: int  # how many of the 4 prefs trade below 100
    pref_total: int  # how many resolved
    pref_5d: float | None  # avg 5d change across the stack (deeply negative = stress)
    mstr_btc_21d: float | None  # MSTR 21d return minus BTC 21d; <0 = mNAV compressing
    btc: float | None
    mstr: float | None

    @property
    def stress(self) -> bool:
        """The de-risk trigger: STRC peg failing (<~$90)."""
        return self.strc is not None and self.strc < 90

    @property
    def band(self) -> str:
        if self.strc is None:
            return "n/a"
        if self.strc < 80:
            return "crisis"
        if self.strc < 90:
            return "peg failing"
        if self.strc < 95:
            return "stress building"
        return "normal"


def crypto_credit() -> CryptoCredit:
    """Strategy (MSTR) capital-structure stress — the crypto-credit leading gauge.

    STRC's discount to its $100 par, the whole-pref-stack breadth (cracking
    together = credit not idiosyncratic), and MSTR-vs-BTC (the mNAV-compression
    proxy — MSTR falling faster than BTC = the equity-funding window closing).
    """

    def series(t: str) -> pd.Series | None:
        try:
            s = _close(t, "6mo")
            return s if not s.empty else None
        except Exception:
            return None

    prefs = {t: series(t) for t in _STRATEGY_PREFS}
    strc_s = prefs["STRC"]
    strc = float(strc_s.iloc[-1]) if strc_s is not None else None

    below = total = 0
    d5s: list[float] = []
    for s in prefs.values():
        if s is None:
            continue
        total += 1
        below += int(float(s.iloc[-1]) < 100)
        if len(s) > 5:
            d5s.append(float(s.iloc[-1] / s.iloc[-6] - 1))
    pref_5d = sum(d5s) / len(d5s) if d5s else None

    mstr_s, btc_s = series("MSTR"), series("BTC-USD")

    def r21(s: pd.Series | None) -> float | None:
        return float(s.iloc[-1] / s.iloc[-22] - 1) if s is not None and len(s) > 22 else None

    m21, b21 = r21(mstr_s), r21(btc_s)
    mstr_btc = (m21 - b21) if (m21 is not None and b21 is not None) else None

    return CryptoCredit(
        strc=strc,
        strc_discount=(strc / 100 - 1) if strc is not None else None,
        pref_below_par=below,
        pref_total=total,
        pref_5d=pref_5d,
        mstr_btc_21d=mstr_btc,
        btc=float(btc_s.iloc[-1]) if btc_s is not None else None,
        mstr=float(mstr_s.iloc[-1]) if mstr_s is not None else None,
    )


# ---------- credit stress (Clock B — the quality ladder + the levered edge) ----------
# crypto_credit is ONE edge; this is the broad Clock B. The single HY OAS number
# (in the regime panel) hides where cracks show first: (1) the quality ladder —
# CCC (the marginal borrower) blows out before IG, so CCC-vs-IG *dispersion* leads
# the index; (2) the levered/shadow-bank edge — private-credit/BDCs, leveraged
# loans, regional banks — where this cycle's AI-infra/datacenter leverage sits.
# Confined to the bottom (CCC + private credit cracking, IG + banks calm) = early.
# IG widening or banks breaking = stress reaching quality = systemic. FRED + yfinance.

_CREDIT_LADDER = {
    "ig": ("BAMLC0A0CM", 21),  # investment-grade OAS — the "quality" rung
    "bb": ("BAMLH0A1HYBB", 21),  # BB (top of junk)
    "hy": ("BAMLH0A0HYM2", 21),  # broad HY OAS (also the regime credit vote)
    "ccc": ("BAMLH0A3HYC", 21),  # CCC & lower — the marginal borrower, cracks first
}
_LEVERED_EDGE = ("BIZD", "BKLN", "KRE")  # private-credit/BDC · leveraged loans · regional banks


@dataclass(frozen=True, slots=True)
class CreditStress:
    ig_oas: float | None  # %
    bb_oas: float | None
    hy_oas: float | None
    ccc_oas: float | None
    ccc_chg: float | None  # CCC change vs ~1mo, pp (rising = bottom cracking)
    ig_chg: float | None  # IG change vs ~1mo, pp (rising = stress reaching quality)
    bdc_offhi: float | None  # BIZD off 63d high (private-credit / BDC)
    bdc_5d: float | None
    loans_offhi: float | None  # BKLN (leveraged loans)
    banks_offhi: float | None  # KRE (regional banks)
    stale: tuple[str, ...]
    market_offhi: float | None = None  # SPY off-63d-high — netted out of the equity edges (#1)

    @property
    def dispersion(self) -> float | None:
        """CCC minus IG (pp). Wide = stress concentrated at the bottom (early crack)."""
        if self.ccc_oas is None or self.ig_oas is None:
            return None
        return self.ccc_oas - self.ig_oas

    def _excess(self, offhi: float | None) -> float | None:
        """An equity edge's drawdown beyond the market's — strips beta so a broad
        selloff doesn't masquerade as bank/private-credit-specific stress."""
        if offhi is None:
            return None
        return offhi - self.market_offhi if self.market_offhi is not None else offhi

    @property
    def band(self) -> str:
        banks_ex, bdc_ex = self._excess(self.banks_offhi), self._excess(self.bdc_offhi)
        # systemic: stress reached quality (IG, spread-based) or the banks (KRE, de-beta'd)
        if (self.ig_oas is not None and self.ig_oas > 1.0) or (
            banks_ex is not None and banks_ex < -0.08
        ):
            return "spreading (quality/banks)"
        # bottom-edge leak: private credit (de-beta'd) or the CCC tier while the top is calm
        disp = self.dispersion
        if (bdc_ex is not None and bdc_ex < -0.05) or (disp is not None and disp > 7):
            return "leaking (bottom edge)"
        return "calm"


def credit_stress() -> CreditStress:
    """Broad Clock B — corporate quality ladder (FRED) + the levered/shadow-bank edge."""
    vals: dict[str, tuple[float | None, float | None]] = {}
    stale: list[str] = []
    for key, (sid, per) in _CREDIT_LADDER.items():
        latest, prior, is_stale = _fred_metric(sid, per)
        vals[key] = (latest, prior)
        if is_stale:
            stale.append(sid)

    def _chg(key: str) -> float | None:
        latest, prior = vals[key]
        return (latest - prior) if (latest is not None and prior is not None) else None

    def _edge(ticker: str) -> tuple[float | None, float | None]:
        try:
            s = _close(ticker, "6mo").dropna()
            offhi = float(s.iloc[-1] / s.tail(63).max() - 1)
            d5 = float(s.iloc[-1] / s.iloc[-6] - 1) if len(s) > 5 else None
            return offhi, d5
        except Exception:
            return None, None

    bdc_offhi, bdc_5d = _edge("BIZD")
    loans_offhi, _ = _edge("BKLN")
    banks_offhi, _ = _edge("KRE")

    return CreditStress(
        ig_oas=vals["ig"][0],
        bb_oas=vals["bb"][0],
        hy_oas=vals["hy"][0],
        ccc_oas=vals["ccc"][0],
        ccc_chg=_chg("ccc"),
        ig_chg=_chg("ig"),
        bdc_offhi=bdc_offhi,
        bdc_5d=bdc_5d,
        loans_offhi=loans_offhi,
        banks_offhi=banks_offhi,
        stale=tuple(stale),
        market_offhi=_market_offhi(),
    )


# ---------- funding plumbing (Clock B — the repo / liquidity channel) ----------
# A different failure mode than credit spreads: the money-market plumbing. SOFR
# spiking above IORB = repo stress (the Sept-2019 blowup). RRP near zero = the
# liquidity buffer that's absorbed QT is exhausted, so further tightening drains
# *reserves* directly; reserves toward the ~$3T "scarcity zone" = funding gets
# tight. Slow/systemic, all free FRED — the classic place a systemic crack shows.

_FUNDING_SERIES = {
    "sofr": ("SOFR", 21),  # secured overnight financing rate, %
    "iorb": ("IORB", 21),  # interest on reserve balances, % (the floor)
    "rrp": ("RRPONTSYD", 21),  # overnight reverse repo, $B (the buffer)
    "reserves": ("WRESBAL", 4),  # bank reserves, $millions (weekly)
}


@dataclass(frozen=True, slots=True)
class FundingStress:
    sofr: float | None  # %
    iorb: float | None  # %
    sofr_iorb: float | None  # SOFR minus IORB, pp (>0 = repo paying up = stress)
    rrp: float | None  # $B (near 0 = buffer drained)
    rrp_chg: float | None  # vs ~1mo, $B
    reserves: float | None  # $B
    reserves_chg: float | None  # vs ~1mo, $B (draining = tightening)
    stale: tuple[str, ...]

    @property
    def band(self) -> str:
        if self.sofr_iorb is not None and self.sofr_iorb > 0.05:  # SOFR >5bp over IORB
            return "repo stress"
        if self.rrp is not None and self.rrp < 50:  # buffer effectively gone
            return "buffer drained"
        return "ample"


def funding_stress() -> FundingStress:
    """Money-market plumbing — repo (SOFR-IORB) + the RRP/reserves liquidity buffer."""
    vals: dict[str, tuple[float | None, float | None]] = {}
    stale: list[str] = []
    for key, (sid, per) in _FUNDING_SERIES.items():
        latest, prior, is_stale = _fred_metric(sid, per)
        vals[key] = (latest, prior)
        if is_stale:
            stale.append(sid)

    sofr, iorb = vals["sofr"][0], vals["iorb"][0]
    sofr_iorb = (sofr - iorb) if (sofr is not None and iorb is not None) else None
    rrp_latest, rrp_prior = vals["rrp"]
    res_latest, res_prior = vals["reserves"]
    res_b = (res_latest / 1000) if res_latest is not None else None  # $millions → $B
    res_chg = ((res_latest - res_prior) / 1000) if (res_latest and res_prior) else None

    return FundingStress(
        sofr=sofr,
        iorb=iorb,
        sofr_iorb=sofr_iorb,
        rrp=rrp_latest,
        rrp_chg=(rrp_latest - rrp_prior) if (rrp_latest and rrp_prior) else None,
        reserves=res_b,
        reserves_chg=res_chg,
        stale=tuple(stale),
    )


# ---------- private credit (Clock B — shadow-bank equity proxy, de-beta'd) ----------
# The free *approximation* of the bomb the thesis keeps naming: the cleanest signals
# (CDS, CLO spreads, BDC NAV discounts) are paywalled, so we proxy with equities,
# de-beta'd vs SPY (#1). Two baskets: (1) the private-credit complex — direct-lending
# BDCs + PC-heavy alt managers (Ares/Blue Owl); excess off-highs ≈ discounts widening.
# (2) the AI-infra EQUITY edge — ORCL/VRT/DLR. HONEST SCOPE: ORCL especially is a
# tech-MULTIPLE move, not a debt-stress read — its stock off-high says tech derated,
# not that its datacenter bonds are wobbling. Confirmation of the spread/funding
# leaks, never a standalone trigger.

_PC_COMPLEX = ("ARCC", "BXSL", "FSK", "BIZD", "OBDC", "ARES", "OWL")  # BDCs + PC sponsors
_INFRA_DEBT = ("ORCL", "VRT", "DLR")  # debt-funded build: Oracle + power/datacenter REIT


@dataclass(frozen=True, slots=True)
class PrivateCredit:
    pc_offhi: float | None  # avg off-63d-high, private-credit complex
    pc_5d: float | None
    pc_n: int
    pc_worst: tuple[str, float] | None  # most-stressed single name (ticker, off-hi)
    infra_offhi: float | None  # avg off-high, AI-infra equity edge (ORCL/VRT/DLR)
    infra_5d: float | None
    infra_n: int
    infra_worst: tuple[str, float] | None
    market_offhi: float | None = None  # SPY off-63d-high — for the de-beta'd excess (#1)

    @property
    def pc_excess(self) -> float | None:
        if self.pc_offhi is None or self.market_offhi is None:
            return None
        return self.pc_offhi - self.market_offhi

    @property
    def infra_excess(self) -> float | None:
        if self.infra_offhi is None or self.market_offhi is None:
            return None
        return self.infra_offhi - self.market_offhi

    @property
    def band(self) -> str:
        # prefer the de-beta'd excess; fall back to absolute off-high if no SPY baseline
        ex = [v for v in (self.pc_excess, self.infra_excess) if v is not None]
        if ex:
            worst, crack, stress = min(ex), -0.10, -0.05
        else:
            raw = [v for v in (self.pc_offhi, self.infra_offhi) if v is not None]
            worst, crack, stress = (min(raw) if raw else 0.0), -0.15, -0.07
        if worst <= crack:
            return "cracking"
        if worst <= stress:
            return "stressed"
        return "calm"


def _basket_stress(
    tickers: tuple[str, ...],
) -> tuple[float | None, float | None, int, tuple[str, float] | None]:
    """(avg off-63d-high, avg 5d, n resolved, worst (ticker, off-hi)) for a basket."""
    offs: list[tuple[str, float]] = []
    d5s: list[float] = []
    for t in tickers:
        try:
            s = _close(t, "6mo").dropna()
            offs.append((t, float(s.iloc[-1] / s.tail(63).max() - 1)))
            if len(s) > 5:
                d5s.append(float(s.iloc[-1] / s.iloc[-6] - 1))
        except Exception:
            continue
    if not offs:
        return None, None, 0, None
    avg_off = sum(o for _, o in offs) / len(offs)
    avg_5d = (sum(d5s) / len(d5s)) if d5s else None
    return avg_off, avg_5d, len(offs), min(offs, key=lambda x: x[1])


def private_credit() -> PrivateCredit:
    """The shadow-bank / AI-infra-debt edge (equity proxy — free approximation)."""
    pc_off, pc_5d, pc_n, pc_worst = _basket_stress(_PC_COMPLEX)
    inf_off, inf_5d, inf_n, inf_worst = _basket_stress(_INFRA_DEBT)
    return PrivateCredit(
        pc_offhi=pc_off,
        pc_5d=pc_5d,
        pc_n=pc_n,
        pc_worst=pc_worst,
        infra_offhi=inf_off,
        infra_5d=inf_5d,
        infra_n=inf_n,
        infra_worst=inf_worst,
        market_offhi=_market_offhi(),
    )


# ---------- neocloud watch (Clock B — the sharpest, most faith-dependent edge) ----------
# The levered GPU-cloud operators: pure neoclouds (CRWV/NBIS/BRUN) + the BTC miners
# pivoting to AI compute (IREN/WULF/CORZ/APLD/CIFR/HUT). The purest 2000-telecom
# analog — debt/equity-financed compute capacity betting demand shows up. The *first*
# place the AI-capex-ROI question bites. Bifurcation (some wrecked, holders fine) =
# name-specific stress, not yet a complex meltdown. Equity proxy; `macro neocloud` = full table.
_NEOCLOUDS = {
    "CRWV": "CoreWeave — flagship GPU cloud",
    "NBIS": "Nebius — Amsterdam AI cloud (ex-Yandex)",
    "BRUN": "Boost Run — micro neocloud (founded 2025, 3 employees)",
    "IREN": "IREN — BTC miner → AI compute",
    "WULF": "TeraWulf — miner → AI compute",
    "CORZ": "Core Scientific — hosts CoreWeave",
    "APLD": "Applied Digital — AI/HPC hosting",
    "CIFR": "Cipher — miner → AI compute",
    "HUT": "Hut 8 — miner → AI compute",
}


@dataclass(frozen=True, slots=True)
class Neocloud:
    avg_offhi: float | None  # basket avg off-63d-high
    avg_5d: float | None
    n: int
    n_cracking: int  # how many are >15% off their high
    names: tuple[tuple[str, float, float | None], ...]  # (ticker, off-hi, 5d), worst-first
    market_offhi: float | None = None  # SPY off-63d-high — netted out for the band (#1)

    @property
    def excess_offhi(self) -> float | None:
        """Basket drawdown beyond the market's — the idiosyncratic Clock-B stress."""
        if self.avg_offhi is None or self.market_offhi is None:
            return None
        return self.avg_offhi - self.market_offhi

    @property
    def band(self) -> str:
        # prefer the de-beta'd excess; tighter thresholds than the absolute fallback
        ex = self.excess_offhi
        v = ex if ex is not None else self.avg_offhi
        if v is None:
            return "n/a"
        crack, stress = (-0.10, -0.05) if ex is not None else (-0.15, -0.07)
        if v <= crack:
            return "cracking"
        if v <= stress:
            return "stressed"
        return "calm"


def neocloud() -> Neocloud:
    """The levered AI-compute operators — the sharpest, most faith-dependent Clock-B edge."""
    rows: list[tuple[str, float, float | None]] = []
    for t in _NEOCLOUDS:
        try:
            s = _close(t, "6mo").dropna()
            off = float(s.iloc[-1] / s.tail(63).max() - 1)
            d5 = float(s.iloc[-1] / s.iloc[-6] - 1) if len(s) > 5 else None
            rows.append((t, off, d5))
        except Exception:
            continue
    rows.sort(key=lambda r: r[1])  # worst off-high first
    offs = [o for _, o, _ in rows]
    d5s = [d for _, _, d in rows if d is not None]
    return Neocloud(
        avg_offhi=(sum(offs) / len(offs)) if offs else None,
        avg_5d=(sum(d5s) / len(d5s)) if d5s else None,
        n=len(rows),
        n_cracking=sum(1 for o in offs if o <= -0.15),
        names=tuple(rows),
        market_offhi=_market_offhi(),
    )


# ---------- consumer health (the demand base that ultimately funds AI) ----------
# Almost every AI-funding dollar traces back to the consumer (ad rev, retail) or to
# capital markets (the untethered, fragile part). This panel instruments the consumer
# leg: is spending real (income-driven) or borrowed (credit + falling savings), and is
# the credit cracking. FRED is per-series flaky, so each metric is independently guarded
# AND last-good-cached (data/fred_cache.json) — a transient FRED failure shows the cached
# value flagged stale, not n/a.

_FRED_CACHE = Path("data/fred_cache.json")

# key -> (FRED series id, periods-ago for the YoY/Δ: 12 monthly, 4 quarterly)
_CONSUMER_SERIES = {
    "real_pce": ("PCEC96", 12),  # real personal consumption — the spending leg
    "real_dpi": ("DSPIC96", 12),  # real disposable income — the income leg
    "savings": ("PSAVERT", 12),  # personal saving rate (%) — the stretch
    "revolving": ("REVOLSL", 12),  # revolving consumer credit — the borrowing
    "cc_delinq": ("DRCCLACBS", 4),  # credit-card delinquency rate (%, quarterly) — the crack
    "debt_service": ("TDSP", 4),  # household debt-service ratio (% of DPI, quarterly) — the stretch
    "claims": ("ICSA", 13),  # initial jobless claims (weekly) — the labor-migration tell
    "sentiment": ("UMCSENT", 12),  # UMich consumer sentiment — the soft leading read
}


@dataclass(frozen=True, slots=True)
class ConsumerHealth:
    pce_yoy: float | None  # real consumption growth YoY
    dpi_yoy: float | None  # real disposable income growth YoY
    savings: float | None  # saving rate, %
    revolving_yoy: float | None  # revolving credit growth YoY
    cc_delinq: float | None  # credit-card delinquency rate, %
    cc_delinq_chg: float | None  # delinquency change vs ~1yr ago, pp (rising = cracking)
    debt_service: float | None  # household debt-service ratio, % of DPI (the stretch)
    debt_service_chg: float | None  # change vs ~1yr ago, pp (rising = more income to debt)
    claims: float | None  # initial jobless claims, weekly level (the labor-migration tell)
    claims_chg: float | None  # change vs ~13 weeks ago (rising = bottom-half stress → labor)
    sentiment: float | None
    resolved: int  # FRED series that fetched live (pipeline health)
    total: int
    stale: tuple[str, ...]  # series served from cache (FRED hiccup)

    @property
    def gap(self) -> float | None:
        """PCE YoY minus DPI YoY; >0 = spending outrunning income (credit-funded)."""
        if self.pce_yoy is None or self.dpi_yoy is None:
            return None
        return self.pce_yoy - self.dpi_yoy


def _fred_metric(series_id: str, periods: int) -> tuple[float | None, float | None, bool]:
    """(latest, value `periods` ago, stale). Last-good cached; falls back on FRED failure."""
    try:
        cache = json.loads(_FRED_CACHE.read_text())
    except Exception:
        cache = {}
    try:
        s = _fred_series(series_id).dropna()
        latest = float(s.iloc[-1])
        prior = float(s.iloc[-1 - periods]) if len(s) > periods else None
        cache[series_id] = {"latest": latest, "prior": prior, "asof": str(s.index[-1].date())}
        _FRED_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _FRED_CACHE.write_text(json.dumps(cache, indent=2))
        return latest, prior, False
    except Exception:
        c = cache.get(series_id)
        if c:
            return c.get("latest"), c.get("prior"), True
        return None, None, False


def consumer_health() -> ConsumerHealth:
    """The consumer demand base — instrumented from FRED, cached against FRED's flakiness."""

    def _yoy(latest: float | None, prior: float | None) -> float | None:
        if latest is None or prior is None or prior == 0:
            return None
        return latest / prior - 1

    vals: dict[str, tuple[float | None, float | None]] = {}
    resolved = total = 0
    stale: list[str] = []
    for key, (sid, per) in _CONSUMER_SERIES.items():
        total += 1
        latest, prior, is_stale = _fred_metric(sid, per)
        if latest is not None:
            resolved += 1
        if is_stale:
            stale.append(sid)
        vals[key] = (latest, prior)

    def _diff(pair: tuple[float | None, float | None]) -> float | None:
        latest, prior = pair
        return (latest - prior) if (latest is not None and prior is not None) else None

    cc_latest, _ = vals["cc_delinq"]
    return ConsumerHealth(
        pce_yoy=_yoy(*vals["real_pce"]),
        dpi_yoy=_yoy(*vals["real_dpi"]),
        savings=vals["savings"][0],
        revolving_yoy=_yoy(*vals["revolving"]),
        cc_delinq=cc_latest,
        cc_delinq_chg=_diff(vals["cc_delinq"]),
        debt_service=vals["debt_service"][0],
        debt_service_chg=_diff(vals["debt_service"]),
        claims=vals["claims"][0],
        claims_chg=_diff(vals["claims"]),
        sentiment=vals["sentiment"][0],
        resolved=resolved,
        total=total,
        stale=tuple(stale),
    )


# ---------- distribution (who gets the productivity gains) ----------
# The missing link between the AI-ROI thesis and the consumer panel. A real
# productivity boom only ROIs if the gains reach the demand base. If productivity
# outruns pay and labor share falls, the margin stays with capital (the K-shape) —
# the capex's own future customers get income-capped, which *slows Clock A* (ROI)
# even as Clock B (credit) keeps ticking. "Is this boom feeding its customers or
# eating them?" See ai-infra-cycle-top.md (fallacy-of-composition / two clocks).
_DIST_SERIES = {
    "labor_share": ("PRS85006173", 4),  # nonfarm-biz labor share, index 2017=100
    "productivity": ("OPHNFB", 4),  # output per hour — the real boom
    "real_comp": ("COMPRNFB", 4),  # real compensation per hour — labor's cut
    "profits": ("CP", 4),  # corporate profits after tax — capital's cut
}


@dataclass(frozen=True, slots=True)
class Distribution:
    labor_share: float | None  # index, 2017=100 (<100 = below baseline)
    labor_share_yoy: float | None  # falling = gains shifting to capital
    productivity_yoy: float | None  # output/hr growth — the boom
    real_comp_yoy: float | None  # real pay growth — labor's participation
    profits_yoy: float | None  # corp profits growth — capital's participation
    stale: tuple[str, ...]

    @property
    def gap(self) -> float | None:
        """Productivity growth minus real-pay growth; >0 = the wedge escaping labor."""
        if self.productivity_yoy is None or self.real_comp_yoy is None:
            return None
        return self.productivity_yoy - self.real_comp_yoy

    @property
    def to_capital(self) -> bool:
        """Gains accruing to capital: productivity outruns pay AND labor share falling."""
        g = self.gap
        return bool(g is not None and g > 0 and (self.labor_share_yoy or 0) < 0)


def distribution() -> Distribution:
    """Who captures the productivity boom — labor or capital — from FRED, cached."""

    def _yoy(latest: float | None, prior: float | None) -> float | None:
        if latest is None or prior is None or prior == 0:
            return None
        return latest / prior - 1

    vals: dict[str, tuple[float | None, float | None]] = {}
    stale: list[str] = []
    for key, (sid, per) in _DIST_SERIES.items():
        latest, prior, is_stale = _fred_metric(sid, per)
        if is_stale:
            stale.append(sid)
        vals[key] = (latest, prior)

    return Distribution(
        labor_share=vals["labor_share"][0],
        labor_share_yoy=_yoy(*vals["labor_share"]),
        productivity_yoy=_yoy(*vals["productivity"]),
        real_comp_yoy=_yoy(*vals["real_comp"]),
        profits_yoy=_yoy(*vals["profits"]),
        stale=tuple(stale),
    )


# ---------- labor (jobs — the consumer's income engine + the AI-substitution tell) ----------
# Jobs are where two threads meet: (1) the consumer demand base (Clock A) runs on
# wage income, so a softening labor market erodes it; (2) tech hiring, where an AI
# substitution effect would eventually surface. The Sahm rule is the cleanest
# recession trigger (unemployment momentum); JOLTS quits = worker confidence.
# HONEST SCOPE on "tech": CES6054150001 is computer-systems-DESIGN-and-services
# employment (IT services/consulting), so a decline is a substitution *hint* at
# best — indistinguishable from offshoring or a plain tech-capex slowdown. Free FRED.
_LABOR_SERIES = {
    "unrate": ("UNRATE", 12),  # unemployment rate, %
    "payems": ("PAYEMS", 1),  # nonfarm payrolls level (MoM diff = job adds)
    "claims": ("CCSA", 4),  # continued claims (level)
    "openings": ("JTSJOL", 12),  # job openings (JOLTS), thousands
    "quits": ("JTSQUR", 12),  # quits rate (JOLTS), %
    "sahm": ("SAHMREALTIME", 1),  # Sahm-rule recession indicator
    "tech": ("CES6054150001", 12),  # computer-systems-design employment (tech proxy)
}


@dataclass(frozen=True, slots=True)
class Labor:
    unrate: float | None  # %
    unrate_chg: float | None  # vs ~1yr, pp
    payrolls_mom: float | None  # MoM change in payrolls, thousands
    quits: float | None  # quits rate, %
    openings: float | None  # job openings, thousands
    sahm: float | None  # Sahm-rule value (triggers recession call at >=0.5)
    tech_yoy: float | None  # IT-services employment YoY (substitution *hint*, not proof)
    continued_claims: float | None  # level
    stale: tuple[str, ...]

    @property
    def band(self) -> str:
        if self.sahm is not None and self.sahm >= 0.50:
            return "recession signal"
        if self.sahm is not None and self.sahm >= 0.30:
            return "softening"
        return "firm"


def labor() -> Labor:
    """The labor market — Sahm trigger, JOLTS, tech-employment — from FRED, cached."""
    vals: dict[str, tuple[float | None, float | None]] = {}
    stale: list[str] = []
    for key, (sid, per) in _LABOR_SERIES.items():
        latest, prior, is_stale = _fred_metric(sid, per)
        vals[key] = (latest, prior)
        if is_stale:
            stale.append(sid)

    def _diff(key: str) -> float | None:
        latest, prior = vals[key]
        return (latest - prior) if (latest is not None and prior is not None) else None

    def _yoy(key: str) -> float | None:
        latest, prior = vals[key]
        return (latest / prior - 1) if (latest and prior) else None

    return Labor(
        unrate=vals["unrate"][0],
        unrate_chg=_diff("unrate"),
        payrolls_mom=_diff("payems"),
        quits=vals["quits"][0],
        openings=vals["openings"][0],
        sahm=vals["sahm"][0],
        tech_yoy=_yoy("tech"),
        continued_claims=vals["claims"][0],
        stale=tuple(stale),
    )


def fred_health() -> list[tuple[str, str, str]]:
    """Ping every FRED series the brief depends on; (series_id, status, detail). The
    pipeline validator — `uv run python -m degen.macro fred`."""
    ids = {
        "BAMLH0A0HYM2": "HY OAS (credit)",
        "NFCI": "financial conditions",
        "DFII10": "10y TIPS (real rate)",
        "NCBEILQ027S": "corp equities (Buffett num.)",
        "GDP": "GDP (Buffett denom.)",
        **{sid: key for key, (sid, _) in _CONSUMER_SERIES.items()},
    }
    out: list[tuple[str, str, str]] = []
    for sid, name in ids.items():
        try:
            s = _fred_series(sid).dropna()
            out.append((sid, "ok", f"{name}: {float(s.iloc[-1]):.2f} @ {s.index[-1].date()}"))
        except Exception as e:
            out.append((sid, "FAIL", f"{name}: {type(e).__name__}"))
    return out


# ---------- retail froth (the payload size, not the fuse) ----------
# Retail flooding in is fuel + amplifier, NOT the trigger (credit + ROI are). This
# instruments *how late / how big*: leverage (margin debt), speculative appetite
# (high-beta vs low-vol), and the leveraged single-stock ETF "casino" — ripping =
# froth on, cratering = the speculative crowd getting wrecked. Pairs with the F&G
# put/call sub (retail options). See ai-infra-cycle-top.md (box #4).

_LEVERED_SINGLE = ("MSTU", "NVDL", "TSLL")  # 2x single-stock ETFs — the casino tell


@dataclass(frozen=True, slots=True)
class RetailFroth:
    margin_debt: float | None  # $B (FRED Z.1 households margin, quarterly)
    margin_yoy: float | None  # leverage growth YoY
    high_beta_offhi: float | None  # SPHB/SPLV off its 63d high
    high_beta_5d: float | None  # 5d change in the high-beta/low-vol ratio
    casino_5d: float | None  # avg 5d of the levered single-stock ETF basket
    casino_offhi: float | None  # avg off-63d-high (deeply negative = casino unwinding)
    casino_n: int  # how many levered ETFs resolved
    market_offhi: float | None = None  # SPY off-63d-high — for the de-beta'd excess (#1)

    @property
    def casino_excess(self) -> float | None:
        """Casino drawdown beyond the market's — spec-crowd damage stripped of beta."""
        if self.casino_offhi is None or self.market_offhi is None:
            return None
        return self.casino_offhi - self.market_offhi


def _ratio_read(num: str, den: str) -> tuple[float | None, float | None]:
    """(off-63d-high, 5d change) for a num/den price ratio. None on failure."""
    try:
        df = pd.concat([_close(num, "6mo"), _close(den, "6mo")], axis=1).dropna()
        df.columns = ["a", "b"]
        r = df["a"] / df["b"]
        offhi = float(r.iloc[-1] / r.tail(63).max() - 1)
        d5 = float(r.iloc[-1] / r.iloc[-6] - 1) if len(r) > 5 else None
        return offhi, d5
    except Exception:
        return None, None


def retail_froth() -> RetailFroth:
    """How late / how big the retail flood is — leverage + speculation, price-based + 1 FRED."""
    md_latest, md_prior, _ = _fred_metric("BOGZ1FL663067003Q", 4)  # quarterly → YoY = 4 obs
    margin_debt = (md_latest / 1000) if md_latest is not None else None  # $millions → $B
    margin_yoy = (md_latest / md_prior - 1) if (md_latest and md_prior) else None

    hb_offhi, hb_5d = _ratio_read("SPHB", "SPLV")

    offhis: list[float] = []
    d5s: list[float] = []
    for t in _LEVERED_SINGLE:
        try:
            s = _close(t, "6mo")
            offhis.append(float(s.iloc[-1] / s.tail(63).max() - 1))
            if len(s) > 5:
                d5s.append(float(s.iloc[-1] / s.iloc[-6] - 1))
        except Exception:
            continue

    return RetailFroth(
        margin_debt=margin_debt,
        margin_yoy=margin_yoy,
        high_beta_offhi=hb_offhi,
        high_beta_5d=hb_5d,
        casino_5d=(sum(d5s) / len(d5s)) if d5s else None,
        casino_offhi=(sum(offhis) / len(offhis)) if offhis else None,
        casino_n=len(offhis),
        market_offhi=_market_offhi(),
    )


# ---------- retail attention (search + social — the froth's "who's showing up") ----------
# A magnitude/lateness proxy (same axis as retail_froth, NOT a trigger): is the
# non-trader public flooding in? Two cheap, slow-moving feeds, refreshed ~1-2x/month
# (the data doesn't change day-to-day): Google Trends (hand-entered search interest
# for a retail-attention basket) + WSB mention velocity (ApeWisdom, free/no-key).
# Reads retail_attention.json; refresh the WSB half with refresh_retail_attention().

_RETAIL_ATTENTION_FILE = Path("retail_attention.json")
_APEWISDOM_URL = "https://apewisdom.io/api/v1.0/filter/wallstreetbets/page/1"


@dataclass(frozen=True, slots=True)
class RetailAttention:
    asof: str | None
    trends_index: float | None  # avg Google-Trends search interest across the basket (0-100)
    trends_chg: float | None  # avg change vs prior pull (pp)
    terms: tuple[tuple[str, float], ...]  # (term, level) for display
    wsb_total: int | None  # total mentions across the tracked top names
    wsb_chg: float | None  # vs ~24h-ago total (mention velocity)
    wsb_top: tuple[tuple[str, int, int], ...]  # (ticker, mentions, mentions_24h_ago)
    note: str | None


def retail_attention() -> RetailAttention | None:
    """Retail-attention proxy (Google Trends basket + WSB mentions), from cache."""
    try:
        cfg = json.loads(_RETAIL_ATTENTION_FILE.read_text())
        gt = cfg.get("google_trends", {})
        terms = gt.get("terms", {}) or {}
        prior = gt.get("prior", {}) or {}
        items = [(k, float(v)) for k, v in terms.items() if v is not None]
        idx = (sum(v for _, v in items) / len(items)) if items else None
        chgs = [
            float(terms[k]) - float(prior[k])
            for k in terms
            if terms.get(k) is not None and prior.get(k) is not None
        ]
        trends_chg = (sum(chgs) / len(chgs)) if chgs else None

        wsb = cfg.get("wsb", {})
        top = tuple(
            (str(t[0]), int(t[1]), int(t[2])) for t in wsb.get("top", []) if len(t) >= 3
        )
        wsb_total = sum(m for _, m, _ in top) or None
        prior_total = sum(p for _, _, p in top) or None
        wsb_chg = (wsb_total / prior_total - 1) if (wsb_total and prior_total) else None

        return RetailAttention(
            asof=cfg.get("asof"),
            trends_index=idx,
            trends_chg=trends_chg,
            terms=tuple(items),
            wsb_total=wsb_total,
            wsb_chg=wsb_chg,
            wsb_top=top,
            note=cfg.get("note"),
        )
    except Exception:
        return None


def refresh_retail_attention(top_n: int = 15) -> RetailAttention | None:
    """Pull WSB mentions (ApeWisdom, free) into retail_attention.json. Run ~1-2x/month.

    Preserves the hand-entered google_trends block; only refreshes the wsb half.
    """
    try:
        cfg = json.loads(_RETAIL_ATTENTION_FILE.read_text())
    except Exception:
        cfg = {}
    req = urllib.request.Request(_APEWISDOM_URL, headers=_BROWSER_HEADERS)
    data = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
    rows = data.get("results", [])[:top_n]
    top = [
        [r.get("ticker"), int(r.get("mentions") or 0), int(r.get("mentions_24h_ago") or 0)]
        for r in rows
    ]
    cfg["wsb"] = {
        "asof": date.today().isoformat(),
        "source": "ApeWisdom / r/wallstreetbets",
        "top": top,
    }
    cfg.setdefault(
        "google_trends",
        {"source": "trends.google.com US 12m — hand-entered 0-100", "terms": {}, "prior": {}},
    )
    cfg["asof"] = date.today().isoformat()
    _RETAIL_ATTENTION_FILE.write_text(json.dumps(cfg, indent=2))
    return retail_attention()


# ---------- formatting ----------

_STYLE = {
    "risk-on": "convexity favored — naked longs acceptable within sizing; spreads optional",
    "neutral": "mixed — prefer defined-risk spreads; trim naked premium",
    "defensive": "credit/vol/breadth deteriorating — defined-risk only, cut gross, favor hedges",
    "no data": "no feeds available — do not infer a regime",
}


def format_regime(r: Regime) -> str:
    head = (
        f"=== MACRO REGIME {r.asof} ===   "
        f"{r.verdict.upper()}  ({r.stress_count}/{r.available_count} stress)"
    )
    lines = [head]
    for s in r.signals:
        if not s.available:
            mark = " n/a  "
        elif s.stress:
            mark = "STRESS"
        else:
            mark = "  ok  "
        lines.append(f"  [{mark}] {s.label:<22}: {s.display}")
    lines.append(f"  {'(context)':<8} {'10y-2y curve':<22}: {r.curve_note}")
    lines.append(f"  → Style: {_STYLE.get(r.verdict, '')}")
    return "\n".join(lines)


def main() -> None:
    """`uv run python -m degen.macro` (regime) · `... macro fred` (FRED pipeline check)."""
    import sys

    if "fred" in sys.argv[1:]:
        print("=== FRED pipeline health ===")
        rows = fred_health()
        for sid, status, detail in rows:
            mark = "ok  " if status == "ok" else "FAIL"
            print(f"  [{mark}] {sid:14} {detail}")
        ok = sum(1 for _, s, _ in rows if s == "ok")
        print(f"  → {ok}/{len(rows)} series live")
        return
    if "makers" in sys.argv[1:]:
        m = makers()
        avg = f"{m.avg_offhi:+.1%}" if m.avg_offhi is not None else "—"
        ex = f"  excess {m.excess_offhi:+.1%} vs SPY" if m.excess_offhi is not None else ""
        print(f"=== semicap & memory complex  avg {avg} off-hi (n={m.n}){ex} ===")
        for t, off, d5 in m.names:
            d5s = f"{d5:+6.1%}" if d5 is not None else "   —  "
            print(f"  {t:11} off-hi {off:+6.1%}  5d {d5s}   {_MAKERS.get(t, '')}")
        return
    if "neocloud" in sys.argv[1:]:
        nc = neocloud()
        avg = f"{nc.avg_offhi:+.1%}" if nc.avg_offhi is not None else "—"
        ex = f" (excess {nc.excess_offhi:+.1%} vs SPY)" if nc.excess_offhi is not None else ""
        print(f"=== neocloud [{nc.band}] avg {avg} off-hi{ex} · {nc.n_cracking}/{nc.n} crack ===")
        for t, off, d5 in nc.names:
            d5s = f"{d5:+6.1%}" if d5 is not None else "   —  "
            print(f"  {t:5} off-hi {off:+6.1%}  5d {d5s}   {_NEOCLOUDS.get(t, '')}")
        return
    if "attention" in sys.argv[1:]:
        print("=== refreshing retail attention (WSB via ApeWisdom) ===")
        ra = refresh_retail_attention()
        if ra and ra.wsb_top:
            print(f"  WSB top: {', '.join(f'{t}({m})' for t, m, _ in ra.wsb_top[:8])}")
            print(f"  wrote {_RETAIL_ATTENTION_FILE} (asof {ra.asof}); fill google_trends by hand")
        else:
            print("  refresh failed")
        return
    print(build())


if __name__ == "__main__":
    main()
