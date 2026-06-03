"""Sanity checks for Black-Scholes math. Reference values from Hull, 9e."""

from __future__ import annotations

import math

import pytest

from degen.greeks import bs_price, delta, gamma, implied_vol, theta, vega


def test_atm_call_put_parity():
    s, k, t, r, sigma = 100.0, 100.0, 1.0, 0.05, 0.2
    c = bs_price(s, k, t, r, sigma, "call")
    p = bs_price(s, k, t, r, sigma, "put")
    # C - P = S - K * e^-rT
    assert math.isclose(c - p, s - k * math.exp(-r * t), abs_tol=1e-6)


def test_hull_example_13_6():
    # Hull 9e Ex 13.6: S=42, K=40, T=0.5, r=0.10, σ=0.20 → C≈4.76
    price = bs_price(42, 40, 0.5, 0.10, 0.20, "call")
    assert math.isclose(price, 4.7594, abs_tol=1e-3)


def test_implied_vol_round_trip():
    true_sigma = 0.35
    price = bs_price(100, 105, 0.25, 0.04, true_sigma, "put")
    assert math.isclose(implied_vol(price, 100, 105, 0.25, 0.04, "put"), true_sigma, abs_tol=1e-6)


def test_call_delta_bounds():
    assert 0.0 <= delta(100, 100, 0.5, 0.05, 0.3, "call") <= 1.0


def test_put_delta_bounds():
    assert -1.0 <= delta(100, 100, 0.5, 0.05, 0.3, "put") <= 0.0


def test_gamma_vega_positive():
    assert gamma(100, 100, 0.5, 0.05, 0.3) > 0
    assert vega(100, 100, 0.5, 0.05, 0.3) > 0


@pytest.mark.parametrize("kind", ["call", "put"])
def test_theta_negative_for_long_options(kind):
    # Long options bleed time value (theta convention here: per year, signed).
    assert theta(100, 100, 0.5, 0.05, 0.3, kind) < 0
