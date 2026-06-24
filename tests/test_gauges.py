"""Deterministic logic tests for the gauges — pure computation, no network.

Catches regressions in the transform/threshold logic (the part that breaks
*silently* when refactored). Live-endpoint health is a separate concern, checked
by `degen.health` / `degen.macro fred` — we test math, not I/O (README convention).
"""

from __future__ import annotations

import importlib.util
import pathlib

from degen.ai_demand import _mtok
from degen.macro import (
    _SIGNAL_WEIGHTS,
    ConsumerHealth,
    CreditStress,
    CryptoCredit,
    Distribution,
    FundingStress,
    Labor,
    Makers,
    Neocloud,
    PrivateCredit,
    RoiCoverage,
    _verdict,
)


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
        cc_delinq=None, cc_delinq_chg=None, debt_service=None, debt_service_chg=None,
        claims=None, claims_chg=None, sentiment=None, resolved=0, total=8, stale=(),
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


def _roi(arr_g: float | None, cap_g: float | None) -> RoiCoverage:
    return RoiCoverage(
        asof="2026-06-22", total_arr=54.0, capex=400.0, coverage=0.135,
        exo_coverage=0.088, circular_pct=0.35, arr_growth=arr_g, capex_growth=cap_g,
        vol_growth=None, labs=(("OpenAI", 30.0), ("Anthropic", 24.0)), note=None,
    )


def test_roi_coverage_closing() -> None:
    assert _roi(1.50, 0.60).closing is True  # ARR outgrowing capex → gap closing
    assert _roi(0.20, 0.60).closing is False  # capex outrunning ARR → gap widening
    assert _roi(None, 0.60).closing is None


def _credit(
    ig: float, ccc: float, bdc: float | None, banks: float | None, market: float | None = None
) -> CreditStress:
    return CreditStress(
        ig_oas=ig, bb_oas=1.5, hy_oas=2.6, ccc_oas=ccc, ccc_chg=None, ig_chg=None,
        bdc_offhi=bdc, bdc_5d=None, loans_offhi=-0.01, banks_offhi=banks, stale=(),
        market_offhi=market,
    )


def test_credit_stress_bands() -> None:
    # live read: IG tight, CCC dispersion wide, private credit rolling, banks calm
    leak = _credit(0.74, 9.47, -0.079, 0.0)
    assert round(leak.dispersion, 2) == 8.73
    assert leak.band == "leaking (bottom edge)"
    assert _credit(1.20, 9.47, -0.079, 0.0).band == "spreading (quality/banks)"  # IG widened
    assert _credit(0.74, 9.47, -0.02, -0.10).band == "spreading (quality/banks)"  # banks broke
    assert _credit(0.74, 5.0, -0.01, 0.0).band == "calm"  # tight dispersion, edge fine


def test_credit_stress_debeta() -> None:
    # #1: banks -10% but the whole market is -10% → banks_excess 0 = not bank-specific
    assert _credit(0.74, 5.0, -0.02, -0.10, market=-0.10).band == "calm"
    # banks -10% with SPY flat → -10pp excess = real bank stress (systemic)
    assert _credit(0.74, 5.0, -0.02, -0.10, market=0.0).band == "spreading (quality/banks)"
    # BDC -8% but SPY -6% → only -2pp excess = not a private-credit leak
    assert _credit(0.74, 5.0, -0.08, 0.0, market=-0.06).band == "calm"


def _funding(sofr_iorb: float, rrp: float) -> FundingStress:
    return FundingStress(
        sofr=3.61, iorb=3.61 - sofr_iorb, sofr_iorb=sofr_iorb, rrp=rrp, rrp_chg=None,
        reserves=3033.0, reserves_chg=None, stale=(),
    )


def test_funding_stress_bands() -> None:
    assert _funding(-0.04, 6.5).band == "buffer drained"  # live: RRP gone, no repo stress
    assert _funding(0.08, 6.5).band == "repo stress"  # SOFR firmly over IORB
    assert _funding(-0.04, 400.0).band == "ample"  # buffer intact, repo calm


def _pc(pc_off: float, infra_off: float, market: float | None = None) -> PrivateCredit:
    return PrivateCredit(
        pc_offhi=pc_off, pc_5d=None, pc_n=7, pc_worst=("OWL", pc_off),
        infra_offhi=infra_off, infra_5d=None, infra_n=4, infra_worst=("ORCL", infra_off),
        market_offhi=market,
    )


def test_private_credit_bands() -> None:
    # no market baseline → absolute off-high thresholds (back-compat)
    assert _pc(-0.09, -0.19).band == "cracking"  # live: infra-debt edge cracking
    assert _pc(-0.09, -0.04).band == "stressed"  # PC complex stressed, infra ok
    assert _pc(-0.03, -0.02).band == "calm"


def test_private_credit_debeta() -> None:
    # #1: infra -20% but SPY -14% → only -6pp excess = NOT a standalone crack
    assert _pc(-0.05, -0.20, market=-0.14).band == "stressed"
    # infra -19% with SPY flat → -19pp excess = real cracking
    assert _pc(-0.05, -0.19, market=-0.01).band == "cracking"
    assert _pc(-0.06, -0.06, market=-0.05).band == "calm"  # both ~-1pp vs SPY


def _neo(avg: float, market: float | None = None) -> Neocloud:
    return Neocloud(avg_offhi=avg, avg_5d=None, n=9, n_cracking=2, names=(), market_offhi=market)


def test_neocloud_bands() -> None:
    # no market baseline → absolute off-high thresholds (back-compat)
    assert _neo(-0.16).band == "cracking"
    assert _neo(-0.09).band == "stressed"  # live: bifurcated, avg ~-9%
    assert _neo(-0.03).band == "calm"
    assert Neocloud(None, None, 0, 0, ()).band == "n/a"


def test_neocloud_debeta() -> None:
    # #1: a basket down 16% in a market also down 14% is NOT a Clock-B crack
    n = _neo(-0.16, market=-0.14)
    assert round(n.excess_offhi, 2) == -0.02
    assert n.band == "calm"  # excess only -2pp vs SPY → not idiosyncratic stress
    # but down 16% while SPY is flat = real idiosyncratic cracking
    assert _neo(-0.16, market=-0.01).band == "cracking"  # excess -15pp
    assert _neo(-0.13, market=-0.02).band == "cracking"  # excess -11pp
    assert _neo(-0.09, market=-0.03).band == "stressed"  # excess -6pp


def _labor(sahm: float | None) -> Labor:
    return Labor(
        unrate=4.3, unrate_chg=0.2, payrolls_mom=80.0, quits=1.9, openings=7618.0,
        sahm=sahm, tech_yoy=-0.01, continued_claims=1810000.0, stale=(),
    )


def test_labor_sahm_bands() -> None:
    assert _labor(0.10).band == "firm"  # live
    assert _labor(0.30).band == "softening"
    assert _labor(0.55).band == "recession signal"  # Sahm triggered
    assert _labor(None).band == "firm"  # no signal → not flagged


def test_makers_excess() -> None:
    m = Makers(avg_offhi=-0.10, avg_5d=None, n=7, names=(), market_offhi=-0.06)
    assert round(m.excess_offhi, 2) == -0.04  # 4pp worse than SPY
    assert Makers(-0.10, None, 7, (), None).excess_offhi is None  # no baseline → no excess


def test_regime_verdict_weighting() -> None:
    full = 6.0  # weight sum when all six signals are available
    assert _verdict(0.0, full) == "risk-on"
    # #2: the rate/vol trio alone (0.5*3 = 1.5 → 0.25) must NOT reach defensive
    assert _verdict(1.5, full) == "neutral"
    assert _verdict(2.0, full) == "neutral"  # credit alone (2.0 → 0.33)
    assert _verdict(3.5, full) == "defensive"  # credit + conditions (3.5 → 0.58)
    assert _verdict(0.0, 0) == "no data"
    # the correlated trio cannot outvote the two independent macro signals
    trio = sum(_SIGNAL_WEIGHTS[k] for k in ("ratevol", "equityvol", "realrates"))
    assert trio < _SIGNAL_WEIGHTS["credit"] + _SIGNAL_WEIGHTS["conditions"]


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
