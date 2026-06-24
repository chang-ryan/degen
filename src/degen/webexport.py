"""Export the live macro gauges to the dashboard DB (web/data/briefs.db).

Runs the same gauge functions the daily brief uses, maps each frozen dataclass to
the normalized *panel* shape the Nuxt frontend consumes, derives the posture
banner from gauge fields, and upserts one row per day. The synopsis is left as a
placeholder — it is hand/LLM-authored and privacy-scanned in a separate step.

    uv run python -m degen.webexport

This is the real replacement for web/scripts/seed.mjs. The frontend never changes;
it only ever sees the panel JSON. Swap SQLite for Postgres by changing `_write`.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, TypeVar

from dotenv import load_dotenv

from degen import daily, macro
from degen.ai_demand import AiDemand, ai_demand

T = TypeVar("T")

DB_PATH = Path(__file__).resolve().parents[2] / "web" / "data" / "briefs.db"

# Placeholder synopsis. The real memo is hand/LLM-authored and attached by a separate
# publish step — so webexport must PRESERVE an existing non-stub synopsis, never clobber it.
_SYNOPSIS_STUB = (
    "_Auto-generated gauge snapshot — synopsis is authored separately "
    "(privacy-scanned) and attached via the publish-synopsis step._"
)


# ---------- small formatting guards (mirror daily.py conventions) ----------


def _f(x: float | None, fmt: str, na: str = "—") -> str:
    return format(x, fmt) if x is not None else na


def _split_display(disp: str) -> tuple[str, str | None]:
    """Regime signal `display` is 'value  (context...)' — split for headline/row."""
    if "(" in disp:
        head, rest = disp.split("(", 1)
        return head.strip(), rest.rstrip(") ").strip()
    return disp.strip(), None


def _na_card(key: str, title: str, group: str) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "group": group,
        "kind": "metric",
        "status": "neutral",
        "headline": {"value": "n/a", "label": "feed unavailable", "sub": ""},
        "rows": [],
        "note": "Gauge returned no data this run (flaky upstream).",
    }


# ---------- per-gauge panel builders (each guards its own None) ----------


def _regime_panel(r: macro.Regime | None) -> dict[str, Any]:
    if r is None:
        return _na_card("regime", "Macro regime", "header")
    rows = []
    for s in r.signals:
        val, ctx = _split_display(s.display)
        rows.append(
            {
                "label": s.label,
                "value": val,
                "delta": ctx,
                "state": "bad" if s.stress else ("neutral" if not s.available else "good"),
            }
        )
    return {
        "key": "regime",
        "title": "Macro regime",
        "group": "header",
        "kind": "stress",
        "status": "bad" if r.stress_count >= 3 else "warn",
        "headline": {
            "value": f"{r.stress_count}/{r.available_count}",
            "label": "stress signals",
            "sub": r.verdict,
        },
        "extra": {"stress": r.stress_count, "available": r.available_count},
        "rows": rows,
        "note": (
            "Mechanical label can mislead while internals rot — read the signals, "
            "not the headline."
        ),
    }


def _fear_greed_panel(fg: macro.FearGreed | None) -> dict[str, Any]:
    if fg is None:
        return _na_card("fear_greed", "Fear & Greed", "header")
    return {
        "key": "fear_greed",
        "title": "Fear & Greed",
        "group": "header",
        "kind": "dial",
        "status": "neutral",
        "headline": {"value": str(round(fg.score)), "label": fg.rating, "sub": "contrarian"},
        "extra": {"score": fg.score, "rating": fg.rating, "subs": [list(s) for s in fg.subs]},
        "note": "Contrarian — deep fear is constructive for buyers.",
    }


def _roi_panel(r: macro.RoiCoverage | None) -> dict[str, Any]:
    if r is None:
        return _na_card("roi_coverage", "AI ROI coverage", "clockA")
    rows = [
        {
            "label": "Lab ARR",
            "value": f"${r.total_arr:.0f}B" if r.total_arr is not None else "—",
            "delta": _f(r.arr_growth, "+.0%"),
            "state": "good",
        },
        {
            "label": "vs capex",
            "value": f"${_f(r.capex, '.0f')}B/yr",
            "delta": _f(r.capex_growth, "+.0%"),
        },
        {"label": "Exogenous", "value": _f(r.exo_coverage, ".0%"), "state": "warn"},
        {
            "label": "Circular (NVDA→OpenAI→Azure)",
            "value": f"~{_f(r.circular_pct, '.0%')}",
            "state": "bad",
        },
    ]
    return {
        "key": "roi_coverage",
        "title": "AI ROI coverage",
        "group": "clockA",
        "kind": "metric",
        "status": "bad" if r.closing is False else "warn",
        "headline": {
            "value": _f(r.coverage, ".0%"),
            "label": "of capex covered",
            "sub": f"exogenous {_f(r.exo_coverage, '.0%')} · ~{_f(r.circular_pct, '.0%')} circular",
        },
        "rows": rows,
        "note": (
            "ARR vs capex is Clock A's numerator. Exogenous-vs-circular is the "
            f"honesty check. asof {r.asof}."
        ),
    }


def _ai_demand_panel(d: AiDemand | None) -> dict[str, Any]:
    if d is None:
        return _na_card("ai_demand", "AI-infra demand", "clockA")
    return {
        "key": "ai_demand",
        "title": "AI-infra demand",
        "group": "clockA",
        "kind": "metric",
        "status": "warn",
        "headline": {
            "value": f"${_f(d.frontier_cheapest, '.2f')}",
            "label": "cheapest frontier $/Mtok",
            "sub": f"median ${_f(d.frontier_median, '.2f')}",
        },
        "rows": [
            {"label": "Cheapest frontier", "value": f"${_f(d.frontier_cheapest, '.2f')}/Mtok"},
            {"label": "Median frontier", "value": f"${_f(d.frontier_median, '.2f')}/Mtok"},
            {"label": "Frontier-class models", "value": str(d.frontier_count)},
            {"label": "Total models", "value": str(d.model_count)},
        ],
        "note": (
            "Price (the Jevons denominator) only. Falling = intelligence "
            "commoditizing; volume must outrun it."
        ),
    }


def _consumer_panel(c: macro.ConsumerHealth | None) -> dict[str, Any]:
    if c is None:
        return _na_card("consumer", "Consumer (the demand base)", "clockA")
    claims_k = c.claims / 1000 if c.claims is not None else None
    claims_chg_k = c.claims_chg / 1000 if c.claims_chg is not None else None
    rows = [
        {"label": "Real PCE YoY", "value": _f(c.pce_yoy, "+.1%")},
        {
            "label": "Real DPI YoY",
            "value": _f(c.dpi_yoy, "+.1%"),
            "state": "bad" if (c.dpi_yoy or 0) < 0 else None,
        },
        {"label": "Gap (spend - income)", "value": _f(c.gap, "+.1%"), "state": "warn"},
        {"label": "Savings rate", "value": f"{_f(c.savings, '.1f')}%", "state": "warn"},
        {"label": "Revolving credit YoY", "value": _f(c.revolving_yoy, "+.1%")},
        {
            "label": "CC delinquency",
            "value": f"{_f(c.cc_delinq, '.2f')}%",
            "delta": f"{_f(c.cc_delinq_chg, '+.2f')}pp/yr",
        },
        {
            "label": "Debt service / DPI",
            "value": f"{_f(c.debt_service, '.1f')}%",
            "delta": f"{_f(c.debt_service_chg, '+.2f')}pp/yr",
        },
        {
            "label": "Initial claims",
            "value": f"{_f(claims_k, '.0f')}k",
            "delta": f"{_f(claims_chg_k, '+.0f')}k/qtr",
            "state": "warn",
        },
    ]
    return {
        "key": "consumer",
        "title": "Consumer (the demand base)",
        "group": "clockA",
        "kind": "metric",
        "status": "bad" if (c.gap or 0) > 0.02 else "warn",
        "headline": {
            "value": _f(c.gap, "+.1%"),
            "label": "spend-over-income gap",
            "sub": f"savings {_f(c.savings, '.1f')}%",
        },
        "rows": rows,
        "note": (
            "Spend>income + low savings + rising debt-service = the "
            "consumer-funded leg is stretched."
        ),
    }


def _distribution_panel(d: macro.Distribution | None) -> dict[str, Any]:
    if d is None:
        return _na_card("distribution", "Distribution (K-shape)", "clockA")
    return {
        "key": "distribution",
        "title": "Distribution (K-shape)",
        "group": "clockA",
        "kind": "metric",
        "status": "bad" if d.to_capital else "warn",
        "headline": {
            "value": _f(d.gap, "+.1%"),
            "label": "productivity-pay wedge → capital",
            "sub": f"labor share {_f(d.labor_share_yoy, '+.1%')} YoY",
        },
        "rows": [
            {"label": "Productivity YoY", "value": _f(d.productivity_yoy, "+.1%"), "state": "good"},
            {"label": "Real pay YoY", "value": _f(d.real_comp_yoy, "+.1%"), "state": "bad"},
            {"label": "Wedge → capital", "value": _f(d.gap, "+.1%"), "state": "bad"},
            {
                "label": "Labor share (2017=100)",
                "value": _f(d.labor_share, ".1f"),
                "delta": f"{_f(d.labor_share_yoy, '+.1%')} YoY",
                "state": "bad",
            },
            {"label": "Corp profits YoY", "value": _f(d.profits_yoy, "+.1%")},
        ],
        "note": "Gains to capital income-cap the demand base. The K-shape slows Clock A (ROI).",
    }


def _crypto_credit_panel(c: macro.CryptoCredit | None) -> dict[str, Any]:
    if c is None:
        return _na_card("crypto_credit", "Crypto / AI-infra credit", "clockB")
    band = c.band
    status = {
        "crisis": "bad",
        "peg failing": "bad",
        "stress building": "warn",
        "normal": "good",
    }.get(band, "neutral")
    return {
        "key": "crypto_credit",
        "title": "Crypto / AI-infra credit",
        "group": "clockB",
        "kind": "metric",
        "status": status,
        "headline": {
            "value": f"${_f(c.strc, '.2f')}",
            "label": "STRC (par 100)",
            "sub": f"{_f(c.strc_discount, '+.1%')} vs par · {band}",
        },
        "rows": [
            {"label": "STRC discount", "value": _f(c.strc_discount, "+.1%"), "state": "bad"},
            {
                "label": "Strategy prefs",
                "value": f"{c.pref_below_par}/{c.pref_total} below par",
                "delta": f"{_f(c.pref_5d, '+.1%')} 5d",
                "state": "bad" if (c.pref_5d or 0) < -0.03 else "warn",
            },
            {
                "label": "MSTR vs BTC (21d)",
                "value": _f(c.mstr_btc_21d, "+.1%"),
                "state": "bad" if (c.mstr_btc_21d or 0) < -0.15 else "warn",
            },
            {"label": "BTC", "value": f"${_f(c.btc, ',.0f')}"},
            {"label": "MSTR", "value": f"${_f(c.mstr, ',.2f')}"},
        ],
        "note": (
            "The leading credit edge. STRC<90 falling = de-risk; <80 = cut hard. "
            "Dress rehearsal for AI-infra credit."
        ),
    }


def _pct(x: float | None) -> str:
    return f"{x:.2f}%" if x is not None else "—"


def _credit_stress_panel(c: macro.CreditStress | None) -> dict[str, Any]:
    """The corporate quality ladder (IG→CCC) + the levered/private-credit edge."""
    if c is None:
        return _na_card("credit_stress", "Credit quality ladder", "clockB")
    status = {
        "spreading (quality/banks)": "bad",
        "leaking (bottom edge)": "warn",
        "calm": "good",
    }.get(c.band, "neutral")
    disp = f"{c.dispersion:.1f}pp" if c.dispersion is not None else "—"
    return {
        "key": "credit_stress",
        "title": "Credit quality ladder",
        "group": "clockB",
        "kind": "metric",
        "status": status,
        "headline": {"value": disp, "label": "CCC-IG dispersion", "sub": c.band},
        "rows": [
            {
                "label": "IG OAS",
                "value": _pct(c.ig_oas),
                "delta": f"{_f(c.ig_chg, '+.2f')}pp/mo",
                "state": "bad" if (c.ig_oas or 0) > 1.0 else "good",
            },
            {"label": "BB OAS", "value": _pct(c.bb_oas)},
            {"label": "HY OAS", "value": _pct(c.hy_oas)},
            {
                "label": "CCC OAS",
                "value": _pct(c.ccc_oas),
                "delta": f"{_f(c.ccc_chg, '+.2f')}pp/mo",
                "state": "bad",
            },
            {
                "label": "Private-credit / BDC",
                "value": f"{_f(c.bdc_offhi, '+.1%')} off-hi",
                "delta": f"{_f(c.bdc_5d, '+.1%')} 5d",
                "state": "bad" if (c.bdc_offhi or 0) < -0.05 else "warn",
            },
            {"label": "Lev loans (BKLN)", "value": f"{_f(c.loans_offhi, '+.1%')} off-hi"},
            {
                "label": "Regional banks (KRE)",
                "value": f"{_f(c.banks_offhi, '+.1%')} off-hi",
                "state": "bad" if (c.banks_offhi or 0) < -0.08 else None,
            },
        ],
        "note": (
            "CCC + private credit cracking while IG/banks calm = early/confined. "
            "IG widening or banks breaking = systemic."
        ),
    }


def _funding_stress_panel(f: macro.FundingStress | None) -> dict[str, Any]:
    """The money-market plumbing — repo (SOFR-IORB) + the RRP/reserves buffer."""
    if f is None:
        return _na_card("funding_stress", "Funding plumbing", "clockB")
    status = {"repo stress": "bad", "buffer drained": "warn", "ample": "good"}.get(
        f.band, "neutral"
    )
    si = f"{f.sofr_iorb * 100:+.0f}bp" if f.sofr_iorb is not None else "—"
    return {
        "key": "funding_stress",
        "title": "Funding plumbing",
        "group": "clockB",
        "kind": "metric",
        "status": status,
        "headline": {"value": si, "label": "SOFR - IORB", "sub": f.band},
        "rows": [
            {"label": "SOFR", "value": f"{_f(f.sofr, '.2f')}%"},
            {"label": "IORB", "value": f"{_f(f.iorb, '.2f')}%"},
            {
                "label": "SOFR - IORB",
                "value": si,
                "state": "bad" if (f.sofr_iorb or 0) > 0.05 else "good",
            },
            {
                "label": "RRP buffer",
                "value": f"${_f(f.rrp, ',.0f')}B",
                "delta": f"{_f(f.rrp_chg, '+,.0f')}B/mo",
                "state": "warn" if (f.rrp if f.rrp is not None else 1e9) < 50 else None,
            },
            {
                "label": "Bank reserves",
                "value": f"${f.reserves / 1000:.2f}T" if f.reserves is not None else "—",
                "delta": f"{_f(f.reserves_chg, '+,.0f')}B/mo",
                "state": "warn" if (f.reserves_chg or 0) < 0 else None,
            },
        ],
        "note": (
            "A plumbing leak is a different failure mode than spreads; SOFR "
            "spiking >IORB = the 2019 repo channel."
        ),
    }


def _private_credit_panel(pc: macro.PrivateCredit | None) -> dict[str, Any]:
    """The on-thesis shadow-bank / AI-infra-debt edge (equity proxy)."""
    if pc is None:
        return _na_card("private_credit", "Private credit / AI-infra debt", "clockB")
    status = {"cracking": "bad", "stressed": "warn", "calm": "good"}.get(pc.band, "neutral")
    worst_pc = f"{pc.pc_worst[0]} {pc.pc_worst[1]:+.0%}" if pc.pc_worst else "—"
    worst_inf = f"{pc.infra_worst[0]} {pc.infra_worst[1]:+.0%}" if pc.infra_worst else "—"
    worst_off = min([v for v in (pc.pc_offhi, pc.infra_offhi) if v is not None], default=None)
    return {
        "key": "private_credit",
        "title": "Private credit / AI-infra debt",
        "group": "clockB",
        "kind": "metric",
        "status": status,
        "headline": {
            "value": _f(worst_off, "+.1%"),
            "label": "worst basket off-hi",
            "sub": pc.band,
        },
        "rows": [
            {
                "label": "Private credit (BDCs)",
                "value": f"{_f(pc.pc_offhi, '+.1%')} off-hi",
                "delta": f"{_f(pc.pc_5d, '+.1%')} 5d",
                "state": "bad" if (pc.pc_offhi or 0) < -0.07 else "warn",
            },
            {"label": "PC worst name", "value": worst_pc, "state": "bad"},
            {
                "label": "AI-infra debt",
                "value": f"{_f(pc.infra_offhi, '+.1%')} off-hi",
                "delta": f"{_f(pc.infra_5d, '+.1%')} 5d",
                "state": "bad" if (pc.infra_offhi or 0) < -0.07 else "warn",
            },
            {"label": "Infra worst name", "value": worst_inf, "state": "bad"},
        ],
        "note": (
            "Equity proxy for the shadow-bank / AI-infra-debt edge (CDS/CLO/NAV "
            "are paywalled). Confirms credit_stress."
        ),
    }


def _neocloud_panel(n: macro.Neocloud | None) -> dict[str, Any]:
    """The levered GPU-cloud operators — the sharpest, most faith-dependent edge."""
    if n is None or n.n == 0:
        return _na_card("neocloud", "Neocloud watch", "clockB")
    status = {"cracking": "bad", "stressed": "warn", "calm": "good"}.get(n.band, "neutral")
    rows = [
        {
            "label": t,
            "value": f"{off:+.1%} off-hi",
            "delta": f"{_f(d5, '+.1%')} 5d",
            "state": "bad" if off <= -0.15 else "warn" if off <= -0.07 else None,
        }
        for t, off, d5 in n.names
    ]
    return {
        "key": "neocloud",
        "title": "Neocloud watch",
        "group": "clockB",
        "kind": "metric",
        "wide": True,  # per-name table → span the Clock B column
        "status": status,
        "headline": {
            "value": _f(n.avg_offhi, "+.1%"),
            "label": "basket off-hi",
            "sub": f"{n.n_cracking}/{n.n} cracking >15% · {n.band}",
        },
        "rows": rows,
        "note": (
            "Levered GPU-cloud operators (CRWV/IREN/…) — the most faith-dependent corner; "
            "cracks first. Bifurcation = name-specific, not a complex meltdown yet."
        ),
    }


def _momentum_panel(m: macro.Momentum | None) -> dict[str, Any]:
    if m is None:
        return _na_card("momentum", "Momentum / crowding", "magnitude")
    legs_data = [lg for lg in m.legs if lg.dd63 is not None]
    basing = sum(1 for lg in legs_data if lg.d5 is not None and lg.d5 >= 0)
    avg_dd = sum(lg.dd63 for lg in legs_data) / len(legs_data) if legs_data else None
    legs = [
        {
            "label": lg.label,
            "pair": lg.pair,
            "offhi": round((lg.dd63 or 0) * 100, 1),
            "run63": round((lg.run63 or 0) * 100, 1),
            "d5": round((lg.d5 or 0) * 100, 1),
        }
        for lg in m.legs
    ]
    return {
        "key": "momentum",
        "title": "Momentum / crowding",
        "group": "magnitude",
        "kind": "legs",
        "status": "warn" if basing >= 4 else "bad",
        "headline": {
            "value": f"{basing}/{len(legs_data)}",
            "label": "legs basing (5d ≥ 0)",
            "sub": f"avg {_f(avg_dd, '+.1%')} off-hi",
        },
        "extra": {
            "vix": round(m.vix, 1) if m.vix is not None else None,
            "vvix": round(m.vvix, 1) if m.vvix is not None else None,
            "legs": legs,
        },
        "note": (
            "off-hi = unwind so far · run63 = fuel left · 5d ≥ 0 = basing. "
            "Dip-buy needs legs basing."
        ),
    }


def _cta_panel(c: macro.Cta | None) -> dict[str, Any]:
    if c is None:
        return _na_card("cta", "CTA systematic flows", "magnitude")
    levels = [
        {"name": lv.name, "level": lv.level, "dist": round(lv.dist * 100, 1)} for lv in c.levels
    ]
    breached = [lv for lv in c.levels if lv.dist < 0]
    nearest = min((lv for lv in c.levels if lv.dist >= 0), key=lambda x: x.dist, default=None)
    if breached:
        status, hv = "bad", f"{breached[0].name} breached"
    elif nearest is not None:
        status = "warn" if nearest.dist < 0.02 else "good"
        hv = f"+{nearest.dist * 100:.1f}%"
    else:
        status, hv = "neutral", "—"
    return {
        "key": "cta",
        "title": "CTA systematic flows",
        "group": "magnitude",
        "kind": "cta",
        "status": status,
        "headline": {"value": hv, "label": "to short trigger", "sub": f"SPX {c.spot:,.0f}"},
        "extra": {"spot": c.spot, "levels": levels},
        "note": f"Breach = systematic supply ON. Levels asof {c.asof}.",
    }


def _breadth_panel(b: macro.SpxBreadth | None) -> dict[str, Any]:
    if b is None:
        return _na_card("spx_breadth", "SPX breadth", "magnitude")
    pct50 = round(b.pct_50 * 100)
    pct200 = round(b.pct_200 * 100)
    return {
        "key": "spx_breadth",
        "title": "SPX breadth",
        "group": "magnitude",
        "kind": "breadth",
        "status": "good" if pct50 >= 60 else "warn" if pct50 >= 50 else "bad",
        "headline": {"value": f"{pct50}%", "label": "> 50dma", "sub": f"n={b.total}"},
        "extra": {"pct50": pct50, "pct200": pct200},
        "note": "The load-bearing breadth measure (n≈500).",
    }


def _froth_panel(r: macro.RetailFroth | None) -> dict[str, Any]:
    if r is None:
        return _na_card("retail_froth", "Retail froth (payload size)", "magnitude")
    hb5 = getattr(r, "high_beta_5d", None)
    return {
        "key": "retail_froth",
        "title": "Retail froth (payload size)",
        "group": "magnitude",
        "kind": "metric",
        "status": "bad",
        "headline": {
            "value": _f(r.margin_yoy, "+.1%"),
            "label": "margin debt YoY",
            "sub": f"${_f(r.margin_debt, ',.0f')}B",
        },
        "rows": [
            {
                "label": "Margin debt",
                "value": f"${_f(r.margin_debt, ',.0f')}B",
                "delta": f"{_f(r.margin_yoy, '+.1%')} YoY",
                "state": "bad",
            },
            {
                "label": "High-beta SPHB/SPLV",
                "value": f"{_f(r.high_beta_offhi, '+.1%')} off-hi",
                "delta": f"{_f(hb5, '+.1%')} 5d",
                "state": "warn",
            },
            {"label": "2x-ETF casino off-hi", "value": _f(r.casino_offhi, "+.1%"), "state": "bad"},
            {
                "label": "2x-ETF casino 5d",
                "value": _f(getattr(r, "casino_5d", None), "+.1%"),
                "state": "bad",
            },
        ],
        "note": (
            "The payload size, not the fuse — froth amplifies the move; credit + "
            "ROI trigger the break."
        ),
    }


def _mag7_panel(m: macro.Mag7 | None) -> dict[str, Any]:
    if m is None:
        return _na_card("mag7", "Mag7 concentration", "magnitude")
    rows = []
    for n in m.names:
        rows.append(
            {
                "label": n.ticker,
                "value": _f(n.last, ",.2f"),
                "delta": _f(n.chg_1d, "+.1%"),
                "state": "good" if n.above_50dma else "bad",
            }
        )
    return {
        "key": "mag7",
        "title": "Mag7 concentration",
        "group": "magnitude",
        "kind": "metric",
        "status": "neutral",
        "headline": {
            "value": f"{m.above_50}/{m.total}",
            "label": "above 50dma",
            "sub": "color only — not breadth",
        },
        "rows": rows,
        "note": "n=7 is not breadth — the breadth measure is the SPX panel.",
    }


def _buffett_panel(buf: float | None) -> dict[str, Any]:
    if buf is None:
        return _na_card("buffett", "Buffett indicator", "backdrop")
    return {
        "key": "buffett",
        "title": "Buffett indicator",
        "group": "backdrop",
        "kind": "metric",
        "status": "neutral",
        "headline": {
            "value": f"{buf:.0f}%",
            "label": "market cap / GDP",
            "sub": "valuation backdrop",
        },
        "rows": [{"label": "Total mkt cap / GDP", "value": f"{buf:.0f}%"}],
        "note": "Valuation backdrop — magnitude, not a trigger.",
    }


def _cross_asset_panel(ca: macro.CrossAsset | None) -> dict[str, Any]:
    if ca is None:
        return _na_card("cross_asset", "Cross-asset tape", "backdrop")
    skew = f"SKEW {ca.skew:.0f}" if ca.skew is not None else "Cross-asset"
    return {
        "key": "cross_asset",
        "title": "Cross-asset tape",
        "group": "backdrop",
        "kind": "metric",
        "status": "neutral",
        "headline": {
            "value": skew,
            "label": "tail-hedge demand",
            "sub": f"pctile {_f(ca.skew_pctile, '.0%')}",
        },
        "rows": [
            {"label": "DXY", "value": _f(ca.dxy, ".2f")},
            {"label": "Gold", "value": f"${_f(ca.gold, ',.0f')}"},
            {"label": "BTC", "value": f"${_f(ca.btc, ',.0f')}"},
            {"label": "Copper", "value": f"${_f(ca.copper, '.2f')}"},
        ],
        "note": "Macro cross-asset backdrop.",
    }


def _memory_prices_panel(m: macro.MemoryPrices | None) -> dict[str, Any]:
    if m is None:
        return _na_card("memory_prices", "Memory super-cycle", "backdrop")
    fc = f"+{m.fc_3q[0]:.0f}-{m.fc_3q[1]:.0f}%" if m.fc_3q else "—"
    cons = f"+{m.consensus_3q[0]:.0f}-{m.consensus_3q[1]:.0f}%" if m.consensus_3q else "—"
    latest = "awaiting — MU print" if m.awaiting else str((m.latest or {}).get("asof", "—"))
    return {
        "key": "memory_prices",
        "title": "Memory super-cycle",
        "group": "backdrop",
        "kind": "metric",
        "status": "warn",
        "headline": {"value": fc, "label": "3Q26 QoQ forecast", "sub": f"vs consensus {cons}"},
        "rows": [
            {"label": "3Q26 forecast", "value": fc, "state": "good"},
            {"label": "Consensus", "value": cons},
            {"label": "Cycle-top marker", "value": m.top_marker or "—"},
            {"label": "Latest print", "value": latest, "state": "warn" if m.awaiting else None},
        ],
        "note": "Contract-price read vs the super-bull call. The crux gauge for the memory leg.",
    }


def _memory_tape_panel(t: macro.MemoryTape | None) -> dict[str, Any]:
    if t is None or t.ewy is None:
        return _na_card("memory_tape", "Memory tape (live proxy)", "backdrop")
    status = "bad" if (t.d1 or 0) < -0.03 else "warn" if (t.off_hi or 0) < -0.05 else "good"
    return {
        "key": "memory_tape",
        "title": "Memory tape (live proxy)",
        "group": "backdrop",
        "kind": "metric",
        "status": status,
        "headline": {
            "value": f"EWY {t.ewy:.1f}",
            "label": "Samsung / SK Hynix proxy",
            "sub": f"{_f(t.d1, '+.1%')} 1d",
        },
        "rows": [
            {"label": "EWY", "value": _f(t.ewy, ".2f")},
            {
                "label": "1d",
                "value": _f(t.d1, "+.1%"),
                "state": "bad" if (t.d1 or 0) < 0 else "good",
            },
            {
                "label": "5d",
                "value": _f(t.d5, "+.1%"),
                "state": "bad" if (t.d5 or 0) < 0 else "good",
            },
            {
                "label": "Off 63d high",
                "value": _f(t.off_hi, "+.1%"),
                "state": "bad" if (t.off_hi or 0) < -0.05 else "warn",
            },
        ],
        "note": "Live memory-duopoly proxy — leads the contract print + Asia risk.",
    }


# ---------- posture (derived from gauge fields) ----------


def _posture(
    m: macro.Momentum | None, cc: macro.CryptoCredit | None, cta: macro.Cta | None
) -> dict[str, Any]:
    legs = [lg for lg in (m.legs if m else []) if lg.dd63 is not None]
    basing = sum(1 for lg in legs if lg.d5 is not None and lg.d5 >= 0)
    vix = m.vix if m else None
    vvix = m.vvix if m else None
    band = cc.band if cc else "n/a"
    strc = cc.strc if cc else None

    legs_state = "good" if basing >= 4 else "warn" if basing >= 3 else "bad"
    if vix is None:
        vix_state, vix_detail = "neutral", "—"
    elif vix >= 22 or (vvix or 0) >= 100:
        vix_state = "bad"
        vix_detail = f"{vix:.1f}" + (f" · VVIX {vvix:.0f}" if vvix else "")
    elif vix >= 20:
        vix_state, vix_detail = "warn", f"{vix:.1f}"
    else:
        vix_state, vix_detail = "good", f"{vix:.1f}"
    credit_state = "good" if band == "normal" else "warn" if band == "stress building" else "bad"

    gates = [
        {"label": "Legs basing", "state": legs_state, "detail": f"{basing}/{len(legs)} basing"},
        {"label": "VIX settling", "state": vix_state, "detail": vix_detail},
        {"label": "Credit calm", "state": credit_state, "detail": band},
    ]
    breached = [lv.name for lv in (cta.levels if cta else []) if lv.dist < 0]
    nearest = min(
        ((lv for lv in cta.levels if lv.dist >= 0) if cta else []),
        key=lambda x: x.dist,
        default=None,
    )
    triggers = [
        {
            "label": "STRC < 90",
            "active": strc is not None and strc < 90,
            "detail": f"${strc:.1f} — de-risk" if strc is not None else "—",
        },
        {"label": "STRC < 80", "active": strc is not None and strc < 80, "detail": "cut hard"},
        {
            "label": "VIX > 22",
            "active": vix is not None and vix > 22,
            "detail": f"at {vix:.1f}" if vix is not None else "—",
        },
        {
            "label": "CTA breach",
            "active": bool(breached),
            "detail": "/".join(breached)
            if breached
            else (f"+{nearest.dist * 100:.1f}% away" if nearest else "—"),
        },
        {
            "label": "VVIX > 100",
            "active": vvix is not None and vvix > 100,
            "detail": f"{vvix:.1f}" if vvix is not None else "—",
        },
    ]
    window = "OPEN" if all(g["state"] == "good" for g in gates) else "SHUT"
    return {"window": window, "gates": gates, "triggers": triggers}


# ---------- what-changed (reuse daily's snapshot diff) ----------


def _what_changed(today_state: dict, prior: dict | None) -> list[str]:
    if not prior:
        return ["first snapshot — deltas begin next run"]
    items: list[str] = []
    if prior.get("regime") and today_state.get("regime") != prior.get("regime"):
        items.append(f"regime {prior['regime']} → {today_state['regime']}")

    def d(key: str, label: str, fmt: str, thresh: float, pct: bool = False) -> None:
        a, b = today_state.get(key), prior.get(key)
        if a is None or b is None or abs(a - b) < thresh:
            return
        items.append(f"{label} {b:.0%} → {a:.0%}" if pct else f"{label} {b:{fmt}} → {a:{fmt}}")

    d("vix", "VIX", ".0f", 1)
    d("spx_pct50", "SPX breadth", "", 0.02, pct=True)
    d("fng", "F&G", ".0f", 3)
    d("strc", "STRC", ".1f", 1)
    d("mag7_breadth", "Mag7", ".0f", 1)
    a, b = today_state.get("legs_basing"), prior.get("legs_basing")
    if a is not None and b is not None and a != b:
        items.append(f"legs basing {b} → {a}")
    a, b = today_state.get("ai_frontier"), prior.get("ai_frontier")
    if a is not None and b is not None and abs(a - b) >= 0.05:
        items.append(f"frontier ${b:.2f} → ${a:.2f}/Mtok")
    return items or ["no material change in the tracked signals"]


# ---------- assembly + write ----------


def build_payload(when: date | None = None) -> dict[str, Any]:
    when = when or date.today()
    print("· running gauges (this hits slow/flaky feeds — ~1 min)…", flush=True)

    def safe(fn: Callable[[], T], label: str) -> T | None:
        try:
            v = fn()
            print(f"  ✓ {label}", flush=True)
            return v
        except Exception as e:
            print(f"  ✗ {label}: {e}", flush=True)
            return None

    regime = safe(macro.build, "regime")
    fg = safe(macro.fear_greed, "fear_greed")
    buf = safe(macro.buffett_indicator, "buffett")
    ca = safe(macro.cross_asset, "cross_asset")
    momo = safe(macro.momentum, "momentum")
    m7 = safe(macro.mag7, "mag7")
    breadth = safe(macro.spx_breadth, "spx_breadth")
    cta = safe(macro.cta, "cta")
    cc = safe(macro.crypto_credit, "crypto_credit")
    creds = safe(macro.credit_stress, "credit_stress")
    funding = safe(macro.funding_stress, "funding_stress")
    privc = safe(macro.private_credit, "private_credit")
    nclo = safe(macro.neocloud, "neocloud")
    mem = safe(macro.memory_prices, "memory_prices")
    memtape = safe(macro.memory_tape, "memory_tape")
    cons = safe(macro.consumer_health, "consumer_health")
    dist = safe(macro.distribution, "distribution")
    froth = safe(macro.retail_froth, "retail_froth")
    aid = safe(ai_demand, "ai_demand")
    roi = safe(macro.roi_coverage, "roi_coverage")

    groups = {
        "header": [_regime_panel(regime), _fear_greed_panel(fg)],
        "clockA": [
            _roi_panel(roi),
            _ai_demand_panel(aid),
            _consumer_panel(cons),
            _distribution_panel(dist),
        ],
        "clockB": [
            _crypto_credit_panel(cc),
            _credit_stress_panel(creds),
            _funding_stress_panel(funding),
            _private_credit_panel(privc),
            _neocloud_panel(nclo),
        ],
        "magnitude": [
            _momentum_panel(momo),
            _cta_panel(cta),
            _breadth_panel(breadth),
            _froth_panel(froth),
            _mag7_panel(m7),
        ],
        "backdrop": [
            _buffett_panel(buf),
            _cross_asset_panel(ca),
            _memory_prices_panel(mem),
            _memory_tape_panel(memtape),
        ],
    }

    # what-changed via daily's snapshot machinery (guard if a gauge is None)
    what_changed = ["snapshot unavailable this run"]
    try:
        today_state = daily._snapshot_state(when, regime, momo, breadth, fg, m7, cc, aid)
        what_changed = _what_changed(today_state, daily._load_prior_snapshot(when))
    except Exception as e:
        print(f"  ! what-changed skipped: {e}", flush=True)

    return {
        "date": when.isoformat(),
        "regimeLabel": regime.verdict if regime else "n/a",
        "posture": _posture(momo, cc, cta),
        "synopsis": _SYNOPSIS_STUB,
        "what_changed": what_changed,
        "groups": groups,
    }


def _write(payload: dict[str, Any]) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS briefs (date TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    con.execute(
        "INSERT OR REPLACE INTO briefs (date, payload) VALUES (?, ?)",
        (payload["date"], json.dumps(payload)),
    )
    con.commit()
    con.close()


def _push_supabase(payload: dict[str, Any]) -> str:
    """Upsert the day's row to Supabase via PostgREST. Service key bypasses RLS."""
    url = os.environ.get("SUPABASE_URL")
    # new-format secret key (sb_secret_*); falls back to the legacy service_role key.
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
    if not (url and key):
        return "skipped (set SUPABASE_URL + SUPABASE_SECRET_KEY in .env to enable)"
    body = json.dumps([{"date": payload["date"], "payload": payload}]).encode()
    req = urllib.request.Request(
        f"{url}/rest/v1/briefs",
        data=body,
        method="POST",
        headers={
            # new-format keys are NOT JWTs — send only via apikey, never Authorization.
            "apikey": key,
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return f"ok ({r.status})"
    except urllib.error.HTTPError as e:
        return f"failed ({e.code}): {e.read().decode()[:200]}"
    except Exception as e:
        return f"failed: {e}"


def _backfill_from_sqlite() -> None:
    """Push every row already in the local SQLite DB up to Supabase (idempotent upsert)."""
    load_dotenv()
    con = sqlite3.connect(DB_PATH)
    rows = con.execute("SELECT date, payload FROM briefs ORDER BY date").fetchall()
    con.close()
    if not rows:
        print(f"no rows in {DB_PATH} to backfill")
        return
    print(f"backfilling {len(rows)} row(s) from {DB_PATH} → Supabase…")
    for d, payload_str in rows:
        print(f"  {d}: {_push_supabase(json.loads(payload_str))}")


def _existing_synopsis(date_str: str) -> str | None:
    """The synopsis already stored for `date_str` (Supabase if configured, else SQLite)."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
    if url and key:
        try:
            req = urllib.request.Request(
                f"{url}/rest/v1/briefs?select=payload&date=eq.{date_str}",
                headers={"apikey": key},
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                rows = json.loads(r.read())
            return rows[0]["payload"].get("synopsis") if rows else None
        except Exception:
            return None
    if not DB_PATH.exists():
        return None
    try:
        con = sqlite3.connect(DB_PATH)
        row = con.execute("SELECT payload FROM briefs WHERE date = ?", (date_str,)).fetchone()
        con.close()
        return json.loads(row[0]).get("synopsis") if row else None
    except Exception:
        return None


def main() -> None:
    if "backfill" in sys.argv[1:]:
        _backfill_from_sqlite()
        return
    load_dotenv()
    payload = build_payload()
    # never clobber a hand-curated synopsis: keep any existing non-stub memo.
    existing = _existing_synopsis(payload["date"])
    if existing and existing.strip() and existing.strip() != _SYNOPSIS_STUB.strip():
        payload["synopsis"] = existing
        print("  · preserved existing curated synopsis (not overwriting)", flush=True)
    _write(payload)
    n = sum(len(v) for v in payload["groups"].values())
    print(
        f"\n[wrote {payload['date']} → {DB_PATH} · {n} panels · "
        f"window {payload['posture']['window']}]"
    )
    print(f"[supabase: {_push_supabase(payload)}]")


if __name__ == "__main__":
    main()
