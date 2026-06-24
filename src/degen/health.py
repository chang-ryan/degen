"""End-to-end health check — ping every external source/gauge and report.

This is a *liveness smoke check* (network, non-deterministic) — NOT a CI unit
test. Run it when something feels off, or after an endpoint might have changed
shape (it's how a broken series like Wilshire/Buffett gets caught fast):

    uv run python -m degen.health

Each row is one source the daily brief depends on. A FAIL means the pipe is down
or changed; a degraded/stale note means it fell back to cache or partial data.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from degen import ai_demand, macro
from degen.data import history


def _check(name: str, fn: Callable[[], str]) -> tuple[str, str, str, float]:
    t0 = time.monotonic()
    try:
        detail = fn()
        return name, "ok", detail, time.monotonic() - t0
    except Exception as e:  # report, never abort the sweep
        return name, "FAIL", f"{type(e).__name__}: {str(e)[:60]}", time.monotonic() - t0


def _checks() -> list[tuple[str, Callable[[], str]]]:
    def yf_spot() -> str:
        h = history("AAPL", period="5d")
        return f"AAPL {float(h['Close'].iloc[-1]):.2f}" if not h.empty else "empty"

    def yf_vol() -> str:
        return f"VIX {float(macro._close('^VIX').iloc[-1]):.1f}"

    def fred_regime() -> str:
        rows = macro.fred_health()
        ok = sum(1 for _, s, _ in rows if s == "ok")
        bad = [sid for sid, s, _ in rows if s != "ok"]
        return f"{ok}/{len(rows)} series live" + (f"  FAIL: {','.join(bad)}" if bad else "")

    def consumer() -> str:
        c = macro.consumer_health()
        return f"{c.resolved}/{c.total} live, gap {c.gap:+.1%}" if c.gap is not None else "no gap"

    def distribution() -> str:
        d = macro.distribution()
        if d.gap is None:
            return "no gap"
        tag = "to-capital" if d.to_capital else "shared"
        return f"wedge {d.gap:+.1%} [{tag}], labor share {d.labor_share:.1f}"

    def fng() -> str:
        fg = macro.fear_greed()
        return f"{fg.score:.0f} ({fg.rating})" if fg else "n/a (blocked)"

    def crypto() -> str:
        cc = macro.crypto_credit()
        return f"STRC {cc.strc:.1f} [{cc.band}]" if cc.strc is not None else "n/a"

    def credit() -> str:
        cs = macro.credit_stress()
        d = f"{cs.dispersion:.1f}pp" if cs.dispersion is not None else "—"
        return f"CCC {cs.ccc_oas:.1f}% disp {d} [{cs.band}]" if cs.ccc_oas is not None else "n/a"

    def funding() -> str:
        f = macro.funding_stress()
        si = f"{f.sofr_iorb * 100:+.0f}bp" if f.sofr_iorb is not None else "—"
        return f"SOFR-IORB {si}, RRP ${f.rrp:,.0f}B [{f.band}]" if f.sofr is not None else "n/a"

    def privcred() -> str:
        pc = macro.private_credit()
        inf = f"{pc.infra_offhi:+.0%}" if pc.infra_offhi is not None else "—"
        return f"PC {pc.pc_offhi:+.0%}, infra-debt {inf} [{pc.band}]" if pc.pc_n else "n/a"

    def ai() -> str:
        d = ai_demand.ai_demand()
        return f"{d.model_count} models, frontier ${d.frontier_cheapest:.2f}/Mtok" if d else "n/a"

    def spx() -> str:
        return f"{len(macro._spx_symbols())} S&P constituents"

    def cross() -> str:
        ca = macro.cross_asset()
        return f"BTC ${ca.btc:,.0f}" if ca.btc is not None else "n/a"

    def edgar_resolve() -> str:
        from degen.edgar import _user_agent, resolve_cik

        cik, _ = resolve_cik("MU", _user_agent())
        return f"MU → CIK {cik}"

    def xpost() -> str:
        from degen.daily import fetch_xpost

        p = fetch_xpost("1518900000000000000")  # bogus id; success = endpoint reachable
        return "endpoint reachable" if p is None else f"got @{p.get('handle')}"

    return [
        ("yfinance — spot/history", yf_spot),
        ("yfinance — vol (^VIX)", yf_vol),
        ("yfinance — cross-asset", cross),
        ("FRED — regime series", fred_regime),
        ("FRED — consumer series", consumer),
        ("FRED — distribution series", distribution),
        ("CNN — Fear & Greed", fng),
        ("OpenRouter — ai_demand", ai),
        ("crypto-credit (STRC/MSTR)", crypto),
        ("credit stress (ladder/edge)", credit),
        ("funding plumbing (repo/RRP)", funding),
        ("private credit (BDC/infra)", privcred),
        ("Wikipedia — SPX list", spx),
        ("SEC EDGAR — resolve", edgar_resolve),
        ("X syndication — fetch", xpost),
    ]


def main() -> int:
    print("=== degen health check (live) ===")
    rows = [_check(name, fn) for name, fn in _checks()]
    fails = 0
    for name, status, detail, dt in rows:
        mark = "ok  " if status == "ok" else "FAIL"
        if status != "ok":
            fails += 1
        print(f"  [{mark}] {name:28} {detail:48} {dt:5.1f}s")
    print(f"\n  {len(rows) - fails}/{len(rows)} sources healthy")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
