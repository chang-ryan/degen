"""Per-ticker options dashboard. The input to the pre-trade gate.

Answers, in one block:
  - Where is the stock?               (spot, 30d HV)
  - Is vol cheap or crowded?           (ATM IV, IV rank, IV/HV ratio)
  - Where is the crowd paying up?      (25Δ skew, term-structure slope)
  - Can I actually trade it?           (liquidity grade on the nearest expiry)
  - What's the catalyst clock?         (days to next earnings)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from degen.data import (
    atm_iv,
    expiries,
    liquid_chain,
    next_earnings,
    realized_vol,
    skew_25d,
    spot,
    term_structure,
)
from degen.iv_store import iv_rank


@dataclass(frozen=True, slots=True)
class Dashboard:
    ticker: str
    spot: float
    hv_30d: float
    target_expiry: str
    target_dte: int
    atm_iv_target: float
    iv_rank: float | None
    iv_over_hv: float
    skew_25d_target: float | None
    term_slope: float | None  # last - first ATM IV across the surface
    liquid_strikes_target: int
    days_to_earnings: int | None

    def __str__(self) -> str:
        return format_dashboard(self)


def _pick_expiry(ticker: str, target_dte: int) -> str:
    """Pick the closest expiry on/after target_dte; falls back to the longest available."""
    from datetime import datetime

    today = date.today()
    candidates = []
    for exp in expiries(ticker):
        dte = (datetime.strptime(exp, "%Y-%m-%d").date() - today).days
        candidates.append((dte, exp))
    eligible = [c for c in candidates if c[0] >= target_dte]
    return min(eligible, key=lambda c: c[0])[1] if eligible else candidates[-1][1]


def build(ticker: str, target_dte: int = 120) -> Dashboard:
    s = spot(ticker)
    hv = realized_vol(ticker, 30)
    target = _pick_expiry(ticker, target_dte)
    from datetime import datetime

    dte = (datetime.strptime(target, "%Y-%m-%d").date() - date.today()).days
    iv_t = atm_iv(ticker, target)

    try:
        sk = skew_25d(ticker, target)
    except Exception:  # noqa: BLE001
        sk = None

    ts = term_structure(ticker, max_expiries=10)
    slope = float(ts["atm_iv"].iloc[-1] - ts["atm_iv"].iloc[0]) if len(ts) >= 2 else None

    lc = liquid_chain(ticker, target)
    liquid_n = len(lc.calls) + len(lc.puts)

    earn = next_earnings(ticker)
    dte_earn = (earn - date.today()).days if earn else None

    return Dashboard(
        ticker=ticker,
        spot=s,
        hv_30d=hv,
        target_expiry=target,
        target_dte=dte,
        atm_iv_target=iv_t,
        iv_rank=iv_rank(ticker),
        iv_over_hv=iv_t / hv if hv > 0 else float("nan"),
        skew_25d_target=sk,
        term_slope=slope,
        liquid_strikes_target=liquid_n,
        days_to_earnings=dte_earn,
    )


def _fmt(x: float | None, fmt: str = ".2f", na: str = "n/a") -> str:
    return format(x, fmt) if x is not None else na


def format_dashboard(d: Dashboard) -> str:
    rank_pct = f"{d.iv_rank:.0%}" if d.iv_rank is not None else "n/a (build history)"
    iv_verdict = _iv_verdict(d.iv_rank, d.iv_over_hv)
    skew_verdict = _skew_verdict(d.skew_25d_target)
    return "\n".join(
        [
            f"=== {d.ticker} @ ${d.spot:,.2f} ===",
            f"  Target expiry  : {d.target_expiry}  ({d.target_dte} DTE)",
            f"  HV 30d         : {d.hv_30d:.1%}",
            f"  ATM IV (target): {d.atm_iv_target:.1%}    IV/HV {_fmt(d.iv_over_hv)}",
            f"  IV rank (252d) : {rank_pct}    [{iv_verdict}]",
            f"  25Δ skew       : {_fmt(d.skew_25d_target, '.3f')}    [{skew_verdict}]",
            f"  Term slope     : {_fmt(d.term_slope, '+.3f')}   "
            "(longest − shortest; +=contango, −=event/stress)",
            f"  Liquid strikes : {d.liquid_strikes_target}  (target expiry, after OI/vol/spread filter)",
            f"  Next earnings  : {_fmt(d.days_to_earnings, 'd')} days",
        ]
    )


def _iv_verdict(rank: float | None, iv_hv: float) -> str:
    if rank is None:
        return "no history — build the store"
    if rank < 0.30 and iv_hv < 1.2:
        return "cheap convexity — favor long premium"
    if rank > 0.70 or iv_hv > 1.8:
        return "vol crowded — favor spreads / selling premium"
    return "neutral"


def _skew_verdict(sk: float | None) -> str:
    if sk is None:
        return "n/a"
    if sk > 0.08:
        return "rich downside — puts expensive"
    if sk < 0.02:
        return "flat/inverted — unusual; watch"
    return "normal"


def main() -> None:
    """`uv run python -m degen.dashboard NVDA CRM`"""
    import sys

    for t in sys.argv[1:]:
        print(build(t))
        print()


if __name__ == "__main__":
    main()
