"""Position sizing per CONSTITUTION.md.

Two regimes:
  - Defined-risk (long options, debit spreads): max loss = premium paid.
    Size so premium is `risk_pct` of port (1% default, 2% cap until edge proven).
  - Naked / margin / leveraged-ETF: loss not capped. Size so a `sigmas`-σ adverse
    overnight gap stays ≤ `max_gap_pct` of port.
"""

from __future__ import annotations

import math


def defined_risk_contracts(
    port_value: float,
    premium_per_contract: float,
    risk_pct: float = 0.01,
) -> int:
    """Contracts to buy such that total premium ≤ risk_pct of port.

    `premium_per_contract` is the per-share debit × 100 (one contract = 100 shares).
    Floors to whole contracts; returns 0 if even one contract breaches the budget.
    """
    if premium_per_contract <= 0:
        raise ValueError("premium_per_contract must be > 0")
    budget = port_value * risk_pct
    return max(0, math.floor(budget / premium_per_contract))


def gap_sized_shares(
    port_value: float,
    underlying_price: float,
    annual_vol: float,
    sigmas: float = 2.5,
    max_gap_pct: float = 0.05,
    horizon_days: float = 1.0,
) -> int:
    """Shares of an uncapped-risk position such that an adverse `sigmas`-σ move
    over `horizon_days` stays inside `max_gap_pct` of port.

    annual_vol: e.g. 0.40 for 40% annualized.
    """
    if underlying_price <= 0 or annual_vol <= 0:
        raise ValueError("underlying_price and annual_vol must be > 0")
    daily_sigma = annual_vol * math.sqrt(horizon_days / 252)
    adverse_pct = sigmas * daily_sigma  # fractional move against you
    max_dollar_loss = port_value * max_gap_pct
    shares = max_dollar_loss / (underlying_price * adverse_pct)
    return max(0, math.floor(shares))
