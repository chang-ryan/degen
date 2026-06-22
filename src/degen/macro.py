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


def _verdict(stress_count: int, available: int) -> str:
    if available == 0:
        return "no data"
    frac = stress_count / available
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
    stress_count = sum(1 for s in available if s.stress)
    return Regime(
        asof=date.today().isoformat(),
        signals=tuple(signals),
        verdict=_verdict(stress_count, len(available)),
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

    Wilshire 5000 full-cap index (≈ market value in $B) over GDP ($B SAAR). A
    slow quarterly valuation gauge — historically ~75% (cheap) to ~200%+ (frothy).
    """
    try:
        w = _fred_series("WILL5000PRFC")
        g = _fred_series("GDP")
        return float(w.iloc[-1] / g.iloc[-1] * 100)
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
    """`uv run python -m degen.macro`"""
    print(build())


if __name__ == "__main__":
    main()
