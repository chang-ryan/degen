"""Deterministic logic tests for the gauges — pure computation, no network.

Catches regressions in the transform/threshold logic (the part that breaks
*silently* when refactored). Live-endpoint health is a separate concern, checked
by `degen.health` / `degen.macro fred` — we test math, not I/O (README convention).
"""

from __future__ import annotations

import importlib.util
import pathlib

from degen.ai_demand import _mtok
from degen.macro import ConsumerHealth, CryptoCredit, Distribution


def _cc(strc: float | None) -> CryptoCredit:
    return CryptoCredit(
        strc=strc, strc_discount=None, pref_below_par=0, pref_total=4,
        pref_5d=None, mstr_btc_21d=None, btc=None, mstr=None,
    )


def test_crypto_band_thresholds() -> None:
    assert _cc(75).band == "crisis"
    assert _cc(85).band == "peg failing"
    assert _cc(92).band == "stress building"
    assert _cc(99).band == "normal"
    assert _cc(None).band == "n/a"


def test_crypto_stress_trigger() -> None:
    assert _cc(85).stress is True  # < 90 = de-risk trigger
    assert _cc(95).stress is False
    assert _cc(None).stress is False


def _consumer(pce: float | None, dpi: float | None) -> ConsumerHealth:
    return ConsumerHealth(
        pce_yoy=pce, dpi_yoy=dpi, savings=None, revolving_yoy=None,
        cc_delinq=None, cc_delinq_chg=None, sentiment=None, resolved=0, total=6, stale=(),
    )


def test_consumer_gap() -> None:
    assert round(_consumer(0.021, -0.011).gap, 3) == 0.032  # spending outruns income
    assert _consumer(0.01, 0.03).gap < 0  # income outruns spending
    assert _consumer(None, 0.02).gap is None


def _dist(prod: float | None, comp: float | None, ls_yoy: float | None) -> Distribution:
    return Distribution(
        labor_share=95.0, labor_share_yoy=ls_yoy, productivity_yoy=prod,
        real_comp_yoy=comp, profits_yoy=None, stale=(),
    )


def test_distribution_wedge_and_capital() -> None:
    d = _dist(0.028, 0.006, -0.029)  # the live read: boom escaping labor
    assert round(d.gap, 3) == 0.022  # productivity outruns pay by 2.2pp
    assert d.to_capital is True  # wedge>0 AND labor share falling
    assert _dist(0.01, 0.03, 0.01).gap < 0  # pay outruns productivity
    assert _dist(0.03, 0.01, 0.02).to_capital is False  # wedge>0 but labor share rising
    assert _dist(None, 0.01, -0.02).gap is None


def test_mtok_pricing_conversion() -> None:
    assert _mtok({"completion": "0.000003"}, "completion") == 3.0  # $/token -> $/Mtok
    assert _mtok({"completion": "0"}, "completion") is None  # zero -> None
    assert _mtok({}, "completion") is None


def _load_privacy_scan() -> object:
    p = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "privacy_scan.py"
    spec = importlib.util.spec_from_file_location("privacy_scan", p)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_privacy_scan_flags_leaks() -> None:
    ps = _load_privacy_scan()
    leaks = ["+$1,739 (+32%)", "net worth is now", "I'm up 1700% on SNDK", "up 389% on my WDC"]
    for s in leaks:
        assert any(rx.search(s) for rx, _ in ps._COMPILED), f"missed leak: {s!r}"


def test_privacy_scan_ignores_market_data() -> None:
    ps = _load_privacy_scan()
    clean = ["SMH up 7.7% on the week", "memory +40% QoQ", "1% of port", "VIX 18", "STRC 89.65"]
    for s in clean:
        assert not any(rx.search(s) for rx, _ in ps._COMPILED), f"false positive: {s!r}"
