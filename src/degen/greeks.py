"""Black-Scholes pricing and Greeks. No dividend yield; add `q` if you need it later."""

from __future__ import annotations

from typing import Literal

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm

Kind = Literal["call", "put"]


def _d1_d2(s: float, k: float, t: float, r: float, sigma: float) -> tuple[float, float]:
    d1 = (np.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * np.sqrt(t))
    d2 = d1 - sigma * np.sqrt(t)
    return d1, d2


def bs_price(s: float, k: float, t: float, r: float, sigma: float, kind: Kind) -> float:
    """Black-Scholes price. t in years, r and sigma as decimals (0.05, not 5)."""
    if t <= 0 or sigma <= 0:
        intrinsic = max(s - k, 0.0) if kind == "call" else max(k - s, 0.0)
        return intrinsic
    d1, d2 = _d1_d2(s, k, t, r, sigma)
    if kind == "call":
        return s * norm.cdf(d1) - k * np.exp(-r * t) * norm.cdf(d2)
    return k * np.exp(-r * t) * norm.cdf(-d2) - s * norm.cdf(-d1)


def delta(s: float, k: float, t: float, r: float, sigma: float, kind: Kind) -> float:
    d1, _ = _d1_d2(s, k, t, r, sigma)
    return norm.cdf(d1) if kind == "call" else norm.cdf(d1) - 1.0


def gamma(s: float, k: float, t: float, r: float, sigma: float) -> float:
    d1, _ = _d1_d2(s, k, t, r, sigma)
    return norm.pdf(d1) / (s * sigma * np.sqrt(t))


def vega(s: float, k: float, t: float, r: float, sigma: float) -> float:
    """Per 1.00 change in vol (i.e. 100 vol points). Divide by 100 for per-vol-point."""
    d1, _ = _d1_d2(s, k, t, r, sigma)
    return s * norm.pdf(d1) * np.sqrt(t)


def theta(s: float, k: float, t: float, r: float, sigma: float, kind: Kind) -> float:
    """Per year. Divide by 365 for per-calendar-day."""
    d1, d2 = _d1_d2(s, k, t, r, sigma)
    first = -(s * norm.pdf(d1) * sigma) / (2 * np.sqrt(t))
    if kind == "call":
        return first - r * k * np.exp(-r * t) * norm.cdf(d2)
    return first + r * k * np.exp(-r * t) * norm.cdf(-d2)


def implied_vol(
    price: float,
    s: float,
    k: float,
    t: float,
    r: float,
    kind: Kind,
    lo: float = 1e-4,
    hi: float = 5.0,
) -> float:
    """Solve for sigma given an observed option price. Raises if no root in [lo, hi]."""

    def f(sigma: float) -> float:
        return bs_price(s, k, t, r, sigma, kind) - price

    return float(brentq(f, lo, hi))
