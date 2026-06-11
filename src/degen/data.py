"""yfinance wrappers + derived options metrics (skew, term structure, liquidity).

Delayed ~15min, no API key. Yahoo's endpoints occasionally break; pin yfinance
and upgrade when calls start returning empty frames. For options, IV is Yahoo's
implied vol — fine for a sanity check but recompute with `greeks.implied_vol`
if a sizing decision depends on the number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
import yfinance as yf

from degen.greeks import delta as bs_delta

DEFAULT_R = 0.04  # 2026 risk-free; revisit if the Fed moves materially


@dataclass(frozen=True, slots=True)
class Chain:
    expiry: str
    calls: pd.DataFrame
    puts: pd.DataFrame


def spot(ticker: str) -> float:
    """Last trade price for the underlying. Falls back to most recent close."""
    t = yf.Ticker(ticker)
    fi = t.fast_info
    for key in ("lastPrice", "last_price", "regularMarketPrice"):
        px = fi.get(key) if hasattr(fi, "get") else getattr(fi, key, None)
        if px:
            return float(px)
    h = t.history(period="5d")
    if not h.empty:
        return float(h["Close"].iloc[-1])
    raise RuntimeError(f"no price for {ticker}")


def expiries(ticker: str) -> list[str]:
    """ISO-formatted expiry strings, sorted ascending."""
    return list(yf.Ticker(ticker).options)


def chain(ticker: str, expiry: str | None = None) -> Chain:
    """Full options chain for a single expiry. Defaults to nearest expiry."""
    t = yf.Ticker(ticker)
    exp = expiry or t.options[0]
    ch = t.option_chain(exp)
    return Chain(expiry=exp, calls=ch.calls, puts=ch.puts)


def history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """OHLCV. `period` ∈ {1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max}."""
    return yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)


def realized_vol(ticker: str, lookback_days: int = 30) -> float:
    """Annualized realized vol from close-to-close log returns."""
    h = history(ticker, period="6mo")
    rets = (h["Close"] / h["Close"].shift(1)).apply("log").dropna().tail(lookback_days)
    return float(rets.std() * (252**0.5))


# ---------- derived options metrics ----------


def _years_to_expiry(expiry: str, today: date | None = None) -> float:
    today = today or date.today()
    exp = datetime.strptime(expiry, "%Y-%m-%d").date()
    return max((exp - today).days, 1) / 365.0


def atm_iv(ticker: str, expiry: str | None = None) -> float:
    """Average of nearest-strike call IV and put IV. Yahoo's IV — flaky on illiquid strikes."""
    s = spot(ticker)
    ch = chain(ticker, expiry)
    c = ch.calls.iloc[(ch.calls["strike"] - s).abs().argsort().iloc[0]]
    p = ch.puts.iloc[(ch.puts["strike"] - s).abs().argsort().iloc[0]]
    return float((c["impliedVolatility"] + p["impliedVolatility"]) / 2)


DEFAULT_DTE_LADDER = (14, 30, 60, 90, 120, 180, 365)


def term_structure(
    ticker: str,
    dte_ladder: tuple[int, ...] = DEFAULT_DTE_LADDER,
) -> pd.DataFrame:
    """ATM IV sampled across a DTE ladder. Picks the closest available expiry to
    each target DTE so slope reflects real term structure, not weekly noise.
    Columns: expiry, dte, atm_iv.
    """
    today = date.today()
    exps = [(datetime.strptime(e, "%Y-%m-%d").date(), e) for e in expiries(ticker)]
    chosen: dict[str, int] = {}  # expiry -> dte (deduped)
    for target in dte_ladder:
        if not exps:
            break
        d, e = min(exps, key=lambda x: abs((x[0] - today).days - target))
        chosen[e] = (d - today).days
    rows = []
    for exp, dte in sorted(chosen.items(), key=lambda kv: kv[1]):
        try:
            iv = atm_iv(ticker, exp)
        except Exception:  # noqa: BLE001 — yfinance can return empty chains
            continue
        rows.append({"expiry": exp, "dte": dte, "atm_iv": iv})
    return pd.DataFrame(rows)


def skew_25d(ticker: str, expiry: str | None = None, r: float = DEFAULT_R) -> float:
    """25Δ put IV minus 25Δ call IV. Positive = downside priced richer than upside (typical).

    Finds the strike whose computed delta is closest to ±0.25 on each side, returns the
    IV gap. Cheap proxy for the skew slope.
    """
    s = spot(ticker)
    ch = chain(ticker, expiry)
    t = _years_to_expiry(ch.expiry)

    def closest_iv(df: pd.DataFrame, target_delta: float, kind: str) -> float:
        df = df[df["impliedVolatility"] > 0].copy()
        df["delta"] = df.apply(
            lambda row: bs_delta(s, row["strike"], t, r, row["impliedVolatility"], kind),  # type: ignore[arg-type]
            axis=1,
        )
        idx = (df["delta"] - target_delta).abs().idxmin()
        return float(df.loc[idx, "impliedVolatility"])

    return closest_iv(ch.puts, -0.25, "put") - closest_iv(ch.calls, 0.25, "call")


def liquid_chain(
    ticker: str,
    expiry: str | None = None,
    min_oi: int = 200,
    min_volume: int = 0,
    max_spread_pct: float = 0.10,
    abs_spread_floor: float = 0.10,
) -> Chain:
    """Filter a chain to contracts you can actually trade.

    Defaults tuned for *monthly/LEAP* chains: OI is the real liquidity signal,
    daily volume is near-zero for back-month strikes by design, and absolute
    spread is meaningless on a $30 LEAP. We accept the wider of
    `abs_spread_floor` or `max_spread_pct × mid`.
    """
    ch = chain(ticker, expiry)

    def f(df: pd.DataFrame) -> pd.DataFrame:
        mid = (df["bid"] + df["ask"]) / 2
        spread = df["ask"] - df["bid"]
        allowed_spread = (mid * max_spread_pct).clip(lower=abs_spread_floor)
        keep = (
            (df["openInterest"] >= min_oi)
            & (df["volume"] >= min_volume)
            & (df["bid"] > 0)
            & (spread <= allowed_spread)
        )
        return df[keep].reset_index(drop=True)

    return Chain(expiry=ch.expiry, calls=f(ch.calls), puts=f(ch.puts))


def next_earnings(ticker: str) -> date | None:
    """Next upcoming earnings date. Uses yfinance's full history table (more
    reliable than the `.calendar` field, which returns None for many tickers).
    """
    try:
        df = yf.Ticker(ticker).get_earnings_dates(limit=8)
    except Exception:  # noqa: BLE001 — lxml missing, network, etc.
        return None
    if df is None or df.empty:
        return None
    today = date.today()
    upcoming = [idx.date() for idx in df.index if idx.date() >= today]
    return min(upcoming) if upcoming else None


def last_earnings(ticker: str, limit: int = 8) -> pd.DataFrame | None:
    """Recent earnings table: date, EPS estimate, reported EPS, surprise %.
    None on failure."""
    try:
        df = yf.Ticker(ticker).get_earnings_dates(limit=limit)
    except Exception:  # noqa: BLE001
        return None
    if df is None or df.empty:
        return None
    return df
