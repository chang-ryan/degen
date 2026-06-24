"""Daily market brief — one command for a fresh, numbers-only look at the tape.

Fuses three layers, all from free/no-key sources:
  1. Macro regime verdict          (degen.macro — credit/vol/breadth stress)
  2. Sentiment + valuation panel    (Fear & Greed + subs, Buffett, cross-asset, SKEW)
  3. Per-ticker book table          (compact for the whole list, full options row
                                     for the active-thesis "focus" names)

Writes the brief to `docs/daily/YYYY-MM-DD.md` so qualitative inputs — articles,
essays, X posts (see `fetch_xpost`) — can be layered onto the same dated page.

`uv run python -m degen.daily`                 # full book from tickers.txt
`uv run python -m degen.daily CRM TEAM`        # ad-hoc focus list
"""

from __future__ import annotations

import contextlib
import json
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from degen import macro
from degen.ai_demand import AiDemand, ai_demand
from degen.data import atm_iv, expiries, history, next_earnings, realized_vol

FOCUS_DEFAULT = ("CRM", "TEAM", "SMH", "SOXX", "USO")  # active-thesis names get the full row
TICKERS_FILE = Path("tickers.txt")
BRIEF_DIR = Path("docs/daily")
# Raw Discord digest lands here — under data/ so it's gitignored AND skipped by the
# privacy scan. The tracked brief never gets raw chatter, only a pointer to this.
STAGING_DIR = Path("data/discord_staging")


# ---------- per-ticker book rows ----------


@dataclass(frozen=True, slots=True)
class BookRow:
    ticker: str
    spot: float | None
    chg_1d: float | None
    chg_5d: float | None
    hv30: float | None
    atm_iv: float | None
    iv_hv: float | None
    dte_earn: int | None
    full: bool


def _pct(closes: object, n: int) -> float | None:
    try:
        c = closes  # pandas Series
        return float(c.iloc[-1] / c.iloc[-1 - n] - 1) if len(c) > n else None  # type: ignore[attr-defined]
    except Exception:
        return None


def _near_30d_expiry(ticker: str) -> str | None:
    today = date.today()
    exps = expiries(ticker)
    if not exps:
        return None
    return min(exps, key=lambda e: abs((datetime.strptime(e, "%Y-%m-%d").date() - today).days - 30))


def book_row(ticker: str, full: bool) -> BookRow:
    """One ticker's row. `full` adds ~30-DTE ATM IV, IV/HV, and earnings clock.

    Every field is independently guarded — a single flaky call degrades to None
    rather than dropping the whole row.
    """
    spot = c1 = c5 = hv = None
    try:
        h = history(ticker, period="3mo")
        if not h.empty:
            spot = float(h["Close"].iloc[-1])
            c1, c5 = _pct(h["Close"], 1), _pct(h["Close"], 5)
    except Exception:
        pass
    with contextlib.suppress(Exception):
        hv = realized_vol(ticker, 30)

    iv = iv_hv = dte = None
    if full:
        try:
            exp = _near_30d_expiry(ticker)
            iv = atm_iv(ticker, exp) if exp else None
            iv_hv = (iv / hv) if (iv and hv) else None
        except Exception:
            pass
        try:
            e = next_earnings(ticker)
            dte = (e - date.today()).days if e else None
        except Exception:
            pass
    return BookRow(ticker, spot, c1, c5, hv, iv, iv_hv, dte, full)


def _read_tickers() -> list[str]:
    if not TICKERS_FILE.exists():
        return list(FOCUS_DEFAULT)
    out: list[str] = []
    for line in TICKERS_FILE.read_text().splitlines():
        s = line.split("#", 1)[0].strip()
        if s:
            out.append(s.upper())
    return out


# ---------- X / news ingestion ----------


def fetch_xpost(url_or_id: str) -> dict | None:
    """Fetch a single public X post via the unauthenticated syndication endpoint.

    Accepts a full x.com/twitter.com status URL or a bare numeric id. Returns
    {author, handle, date, text} or None. Note: this works for *individual*
    posts only — a user's full timeline/feed needs the paid X API.
    """
    tid = url_or_id.rstrip("/").split("/")[-1].split("?")[0]
    if not tid.isdigit():
        return None
    try:
        req = urllib.request.Request(
            f"https://cdn.syndication.twimg.com/tweet-result?id={tid}&token=a",
            headers=macro._BROWSER_HEADERS,
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        user = d.get("user", {})
        return {
            "author": user.get("name"),
            "handle": user.get("screen_name"),
            "date": d.get("created_at"),
            "text": d.get("text", ""),
        }
    except Exception:
        return None


# ---------- formatting ----------


def _p(x: float | None, fmt: str = ".1%", na: str = "—") -> str:
    return format(x, fmt) if x is not None else na


def _fear_greed_block(fg: macro.FearGreed | None) -> list[str]:
    if fg is None:
        return ["  Fear & Greed   : n/a (endpoint blocked)"]
    subs = "  ".join(f"{label} {rating}" for label, rating in fg.subs)
    return [
        f"  Fear & Greed   : {fg.score:.0f} ({fg.rating})   "
        "[contrarian: deep fear = constructive for buyers]",
        f"    subs: {subs}",
    ]


def _cross_asset_block(ca: macro.CrossAsset) -> list[str]:
    skew = (
        f"{ca.skew:.0f} (pctile {ca.skew_pctile:.0%})"
        if ca.skew is not None and ca.skew_pctile is not None
        else "—"
    )
    return [
        f"  DXY {_p(ca.dxy, '.2f')}   Gold ${_p(ca.gold, ',.0f')}   "
        f"BTC ${_p(ca.btc, ',.0f')}   Copper ${_p(ca.copper, '.2f')}",
        f"  SKEW {skew}   (tail-hedge demand; elevated = crash protection bid)",
    ]


def _signal_digest(
    regime: macro.Regime,
    momo: macro.Momentum,
    breadth: macro.SpxBreadth | None,
    cta: macro.Cta | None,
    cc: macro.CryptoCredit | None = None,
) -> list[str]:
    """The day's key signals as one machine-read line — the scaffold the memo draws from.

    Deterministic facts only (the tedious-to-eyeball derived numbers). The narrative
    memo above it is written by hand each day; this line keeps that prose honest.
    """
    sig = {s.key: s for s in regime.signals}
    credit = sig.get("credit")
    credit_state = (
        ("calm" if not credit.stress else "cracking")
        if credit is not None and credit.available
        else "n/a"
    )
    legs = [leg for leg in momo.legs if leg.dd63 is not None]
    avg_dd = sum(leg.dd63 for leg in legs) / len(legs) if legs else None
    basing = sum(1 for leg in legs if leg.d5 is not None and leg.d5 >= 0)

    bits = [
        f"regime {regime.verdict} ({regime.stress_count}/{regime.available_count})",
        f"VIX {momo.vix:.0f}" if momo.vix is not None else "VIX —",
        f"credit {credit_state}",
    ]
    if legs and avg_dd is not None:
        bits.append(f"legs avg {avg_dd:+.1%} off-hi, {basing}/{len(legs)} basing")
    if breadth is not None:
        bits.append(f"SPX {breadth.pct_50:.0%} >50dma")
    if cta is not None:
        breached = [lv.name for lv in cta.levels if lv.dist < 0]
        nearest = min((lv for lv in cta.levels if lv.dist >= 0), key=lambda x: x.dist, default=None)
        if breached:
            bits.append(f"CTA {'/'.join(breached)} breached")
        elif nearest is not None:
            bits.append(f"CTA {nearest.dist:+.1%} to {nearest.name}")
    if cc is not None and cc.strc is not None and cc.strc < 95:
        bits.append(f"STRC {cc.strc:.0f} ({cc.band})")

    return [
        "## Synopsis",
        "",
        "<!-- MEMO: write the narrative read here (LLM, by hand each day). -->",
        "",
        "`" + "  ·  ".join(bits) + "`",
        "",
    ]


def _momentum_block(m: macro.Momentum) -> list[str]:
    def p(x: float | None, fmt: str = "+.1%") -> str:
        return format(x, fmt) if x is not None else "—"

    head = f"  {'sleeve':<18} {'pair':<11} {'off-hi':>7} {'run63':>7} {'5d':>7}"
    out = [head, "  " + "-" * 54]
    for leg in m.legs:
        out.append(
            f"  {leg.label:<18} {leg.pair:<11} {p(leg.dd63):>7} {p(leg.run63):>7} {p(leg.d5):>7}"
        )
    vix = f"{m.vix:.1f}" if m.vix is not None else "—"
    vvix = f"{m.vvix:.1f}" if m.vvix is not None else "—"
    out.append("")
    out.append(f"  VIX {vix}   VVIX {vvix}   (off-hi = unwind so far; run63 = fuel left)")
    out.append("  dip-buy window = legs basing (5d ≥ 0) while VIX settles AND credit stays calm")
    return out


def _breadth_cta_block(b: macro.SpxBreadth | None, cta: macro.Cta | None) -> list[str]:
    out = []
    if b is not None:
        out.append(
            f"  SPX breadth    : {b.pct_50:.0%} above 50dma, "
            f"{b.pct_200:.0%} above 200dma  (n={b.total})"
        )
    else:
        out.append("  SPX breadth    : n/a (constituent feed unavailable)")
    if cta is not None:
        parts = []
        for lv in cta.levels:
            tag = "BREACHED" if lv.dist < 0 else f"{lv.dist:+.1%}"
            parts.append(f"{lv.name} {lv.level:,.0f} [{tag}]")
        out.append(f"  CTA thresholds : SPX {cta.spot:,.0f} vs  " + "  ".join(parts))
        out.append(
            f"                   (levels asof {cta.asof}; breach = systematic supply ON — "
            "supply into calm credit is the entry phase)"
        )
    else:
        out.append(
            "  CTA thresholds : n/a (no cta_levels.json — add levels when the team shares them)"
        )
    return out


def _mag7_block(m: macro.Mag7) -> list[str]:
    head = f"  {'':6} {'last':>9} {'1d':>7} {'21d':>7} {'vs50d':>6}"
    out = [head, "  " + "-" * 40]
    for n in m.names:
        if n.last is None:
            out.append(f"  {n.ticker:6} {'—':>9}")
            continue
        flag = "↑" if n.above_50dma else "↓"
        out.append(
            f"  {n.ticker:6} {n.last:>9,.2f} {_p(n.chg_1d):>7} {_p(n.chg_21d):>7} {flag:>6}"
        )
    out.append("")
    out.append(
        f"  concentration: {m.above_50}/{m.total} above 50dma  "
        "(color only — n=7 is not breadth; the breadth measure is the SPX panel)"
    )
    return out


def _crypto_credit_block(c: macro.CryptoCredit) -> list[str]:
    out: list[str] = []
    if c.strc is not None and c.strc_discount is not None:
        out.append(
            f"  STRC (par 100) : {c.strc:>8,.2f}  ({c.strc_discount:+.1%} vs par)  [{c.band}]"
        )
    else:
        out.append("  STRC (par 100) : n/a")
    line = f"  Strategy prefs : {c.pref_below_par}/{c.pref_total} below par"
    if c.pref_5d is not None:
        line += f", {c.pref_5d:+.1%} avg 5d"
    out.append(line + "  (whole stack cracking together = credit, not idiosyncratic)")
    if c.mstr_btc_21d is not None:
        tag = (
            "MSTR underperforming → mNAV compressing, funding window closing"
            if c.mstr_btc_21d < 0
            else "premium holding"
        )
        out.append(f"  MSTR vs BTC    : {c.mstr_btc_21d:+.1%} (21d)  — {tag}")
    if c.btc is not None and c.mstr is not None:
        out.append(f"  BTC {c.btc:>9,.0f}   MSTR {c.mstr:,.2f}   (the leverage node)")
    out.append(
        "  read: STRC <90 falling = de-risk miners · <80 = cut hard  "
        "(crypto-credit is the dress rehearsal for AI-infra credit)"
    )
    return out


def _retail_attention_block(r: macro.RetailAttention | None) -> list[str]:
    if r is None:
        return ["  attention: n/a (cp retail_attention.example.json → .json; `macro attention`)"]
    out: list[str] = []
    if r.trends_index is not None:
        terms = ", ".join(f"{k} {v:.0f}" for k, v in r.terms[:4])
        chg = f" ({r.trends_chg:+.0f}pp vs prior)" if r.trends_chg is not None else ""
        out.append(
            f"  search interest: idx {r.trends_index:.0f}/100{chg}  [{terms}]  (Google Trends)"
        )
    else:
        out.append("  search interest: — (hand-enter google_trends in retail_attention.json)")
    if r.wsb_total is not None:
        vel = f" ({r.wsb_chg:+.0%}/24h)" if r.wsb_chg is not None else ""
        top = ", ".join(t for t, _, _ in r.wsb_top[:6])
        out.append(f"  WSB mentions   : {r.wsb_total:,} (top {len(r.wsb_top)}){vel}  top: {top}")
    out.append(
        "  read: retail-attention proxy — magnitude/lateness, not a trigger (pairs with froth). "
        f"Refresh ~monthly; asof {r.asof}."
    )
    return out


def _retail_froth_block(r: macro.RetailFroth) -> list[str]:
    def p(x: float | None, fmt: str = "+.1%") -> str:
        return format(x, fmt) if x is not None else "—"

    md = f"${r.margin_debt:,.0f}B ({p(r.margin_yoy)} YoY)" if r.margin_debt is not None else "n/a"
    return [
        f"  margin debt    : {md}  — leverage piling in (>~25% YoY = late-cycle)",
        f"  high-beta      : SPHB/SPLV {p(r.high_beta_offhi)} off-hi, {p(r.high_beta_5d)}/5d  "
        "— speculative appetite",
        f"  casino (2x ETF): avg {p(r.casino_5d)}/5d, avg {p(r.casino_offhi)} off-hi  "
        "— MSTU/NVDL/TSLL (cratering = spec crowd wrecked)",
        "  read: the payload size, not the fuse — froth amplifies the move; credit + ROI "
        "trigger the break. Pair with the F&G put/call sub.",
    ]


def _credit_stress_block(c: macro.CreditStress) -> list[str]:
    def p(x: float | None, fmt: str = "+.1%") -> str:
        return format(x, fmt) if x is not None else "—"

    def pct(x: float | None) -> str:
        return f"{x:.2f}%" if x is not None else "—"

    disp = f"{c.dispersion:.1f}pp" if c.dispersion is not None else "—"
    cccc = f" ({p(c.ccc_chg, '+.2f')}pp/mo)" if c.ccc_chg is not None else ""
    out = [
        f"  quality ladder : IG {pct(c.ig_oas)}  BB {pct(c.bb_oas)}  HY {pct(c.hy_oas)}  "
        f"CCC {pct(c.ccc_oas)}{cccc}",
        f"  dispersion     : CCC-IG {disp}  [{c.band}]  (wide = stress stuck at the bottom)",
        f"  levered edge   : private-credit/BDC {p(c.bdc_offhi)} off-hi ({p(c.bdc_5d)}/5d) · "
        f"loans {p(c.loans_offhi)} · banks {p(c.banks_offhi)} off-hi",
        "  read: CCC + private credit cracking while IG/banks calm = early/confined. IG "
        "widening or banks breaking = stress reaching quality (systemic). Pairs w/ crypto_credit.",
    ]
    if c.stale:
        out.append(f"  [stale: {','.join(c.stale)}]")
    return out


def _private_credit_block(pc: macro.PrivateCredit) -> list[str]:
    def p(x: float | None, fmt: str = "+.1%") -> str:
        return format(x, fmt) if x is not None else "—"

    def worst(w: tuple[str, float] | None) -> str:
        return f"worst {w[0]} {w[1]:+.0%}" if w else ""

    return [
        f"  private credit : {p(pc.pc_offhi)} off-hi ({p(pc.pc_5d)}/5d, n={pc.pc_n})  "
        f"{worst(pc.pc_worst)}  — BDCs + Ares/Blue Owl",
        f"  build debt     : {p(pc.infra_offhi)} off-hi ({p(pc.infra_5d)}/5d, n={pc.infra_n})  "
        f"{worst(pc.infra_worst)}  — Oracle/datacenter (ORCL/VRT/DLR); neoclouds → own panel",
        f"  read: [{pc.band}] equity proxy for the shadow-bank/AI-infra-debt bomb (CDS/CLO/NAV "
        "are paywalled). Confirms credit_stress; not a standalone trigger.",
    ]


def _neocloud_block(nc: macro.Neocloud) -> list[str]:
    if nc.n == 0:
        return ["  neocloud: n/a"]
    avg = f"{nc.avg_offhi:+.1%}" if nc.avg_offhi is not None else "—"
    worst = "  ".join(f"{t} {o:+.0%}" for t, o, _ in nc.names[:4])
    return [
        f"  neocloud edge  : avg {avg} off-hi ({nc.n_cracking}/{nc.n} cracking >15%)  [{nc.band}]",
        f"  most-stressed  : {worst}",
        "  read: levered GPU-cloud operators (CRWV/IREN/…) — most faith-dependent corner, cracks "
        "first. Bifurcation = name-specific, not a complex meltdown yet. `macro neocloud` = full.",
    ]


def _funding_stress_block(f: macro.FundingStress) -> list[str]:
    si = f"{f.sofr_iorb * 100:+.0f}bp" if f.sofr_iorb is not None else "—"
    sofr = f"{f.sofr:.2f}%" if f.sofr is not None else "—"
    iorb = f"{f.iorb:.2f}%" if f.iorb is not None else "—"
    rrp = f"${f.rrp:,.0f}B" if f.rrp is not None else "—"
    rrpc = f" ({f.rrp_chg:+,.0f}B/mo)" if f.rrp_chg is not None else ""
    res = f"${f.reserves / 1000:.2f}T" if f.reserves is not None else "—"
    resc = f" ({f.reserves_chg:+,.0f}B/mo)" if f.reserves_chg is not None else ""
    return [
        f"  SOFR-IORB    : {si}  (SOFR {sofr} vs IORB {iorb})  — >+5bp = repo stress",
        f"  RRP buffer   : {rrp}{rrpc}  — near-zero = QT now drains reserves directly",
        f"  bank reserves: {res}{resc}  — toward the ~$3T scarcity zone = funding tightens",
        f"  read: [{f.band}] — plumbing leak is a different failure mode than spreads; "
        "SOFR spiking >IORB = the 2019-repo channel. Pairs with credit_stress.",
    ]


def _consumer_block(c: macro.ConsumerHealth) -> list[str]:
    def p(x: float | None, fmt: str = "+.1%") -> str:
        return format(x, fmt) if x is not None else "—"

    out = [
        f"  spend vs income: real PCE {p(c.pce_yoy)} YoY vs real DPI {p(c.dpi_yoy)} YoY  "
        f"→ gap {p(c.gap)} (>0 = spending outrunning income = credit-funded)",
        f"  savings rate   : {p(c.savings, '.1f')}%   revolving credit {p(c.revolving_yoy)} YoY",
    ]
    delinq = (
        f"{c.cc_delinq:.2f}% ({p(c.cc_delinq_chg, '+.2f')}pp/yr)"
        if c.cc_delinq is not None
        else "—"
    )
    out.append(f"  CC delinquency : {delinq}   UMich sentiment {p(c.sentiment, '.0f')}")
    ds = (
        f"{c.debt_service:.1f}% of DPI ({p(c.debt_service_chg, '+.2f')}pp/yr)"
        if c.debt_service is not None
        else "—"
    )
    if c.claims is not None:
        chg_k = c.claims_chg / 1000 if c.claims_chg is not None else None
        claims = f"{c.claims / 1000:.0f}k ({p(chg_k, '+.0f')}k/qtr)"
    else:
        claims = "—"
    out.append(f"  debt service   : {ds}   initial claims {claims}")
    health = f"FRED {c.resolved}/{c.total} live"
    if c.stale:
        health += f", stale {','.join(c.stale)}"
    out.append(
        "  read: spend>income + low savings + rising debt-service = the consumer-funded leg is "
        "stretched (ad-rev growth = real-time tell). The bridge to Clock B: bottom-half "
        "delinquency → climbing into prime → initial claims turning up (labor migration) → "
        f"HY OAS widening (regime panel) = the credit trigger releasing.  [{health}]"
    )
    return out


def _labor_block(lab: macro.Labor) -> list[str]:
    def p(x: float | None, fmt: str = "+.1f") -> str:
        return format(x, fmt) if x is not None else "—"

    ur = f"{lab.unrate:.1f}% ({p(lab.unrate_chg, '+.1f')}pp/yr)" if lab.unrate is not None else "—"
    sahm = f"{lab.sahm:.2f}" if lab.sahm is not None else "—"
    pm = f"{lab.payrolls_mom:+,.0f}k" if lab.payrolls_mom is not None else "—"
    op = f"{lab.openings:,.0f}k" if lab.openings is not None else "—"
    q = f"{lab.quits:.1f}%" if lab.quits is not None else "—"
    tech = f"{lab.tech_yoy:+.1%}" if lab.tech_yoy is not None else "—"
    out = [
        f"  unemployment : {ur}   Sahm rule {sahm} [{lab.band}]  (>=0.50 = recession trigger)",
        f"  payrolls     : {pm}/mo   openings {op}   quits {q} (low = workers not confident)",
        f"  tech jobs    : computer-systems-design {tech} YoY  — the AI-substitution tell",
        "  read: jobs = the consumer income engine (Clock A) + where AI substitution shows up "
        "first. Sahm rising / tech-jobs rolling = the K-shape biting labor → consumer → credit.",
    ]
    if lab.stale:
        out.append(f"  [stale: {','.join(lab.stale)}]")
    return out


def _makers_block(m: macro.Makers) -> list[str]:
    if m.n == 0:
        return ["  makers: n/a"]
    avg = f"{m.avg_offhi:+.1%}" if m.avg_offhi is not None else "—"
    names = "  ".join(f"{t.split('.')[0]} {o:+.0%}" for t, o, _ in m.names)
    return [
        f"  bottleneck     : avg {avg} off-hi (n={m.n})  — deep-moat supply leaders",
        f"  names          : {names}",
        "  read: memory/packaging/litho/power oligopoly (Samsung/Hynix/TSMC/ASML/Infineon/MU). "
        "Price-maker on margin, price-taker on demand — leveraged to capex. `macro makers` = full.",
    ]


def _distribution_block(d: macro.Distribution) -> list[str]:
    def p(x: float | None, fmt: str = "+.1%") -> str:
        return format(x, fmt) if x is not None else "—"

    ls = f"{d.labor_share:.1f}" if d.labor_share is not None else "—"
    verdict = "→ to CAPITAL (demand base capped)" if d.to_capital else "→ shared / inconclusive"
    out = [
        f"  productivity   : {p(d.productivity_yoy)} YoY (output/hr) — the real boom",
        f"  real pay       : {p(d.real_comp_yoy)} YoY (real comp/hr) — labor's cut",
        f"  wedge          : {p(d.gap)} (productivity minus pay)  {verdict}",
        f"  labor share    : {ls} (2017=100), {p(d.labor_share_yoy)} YoY  "
        "— falling = gains to capital",
        f"  corp profits   : {p(d.profits_yoy)} YoY — capital's cut",
        "  read: a boom only ROIs if gains reach the demand base. K-shape slows Clock A (ROI) "
        "by income-capping consumers; pairs with consumer_health (base) + crypto_credit (Clock B).",
    ]
    if d.stale:
        out.append(f"  [stale: {','.join(d.stale)}]")
    return out


def _memory_block(
    m: macro.MemoryPrices | None, tape: macro.MemoryTape | None = None
) -> list[str]:
    def p(x: float | None, fmt: str = "+.1%") -> str:
        return format(x, fmt) if x is not None else "—"

    if m is None and (tape is None or tape.ewy is None):
        return ["  memory: n/a (add memory_prices.json — see memory_prices.example.json)"]
    out: list[str] = []
    if tape is not None and tape.ewy is not None:
        out.append(
            f"  maker tape     : EWY {tape.ewy:.2f}  {p(tape.d1)}/1d  {p(tape.d5)}/5d  "
            f"{p(tape.off_hi)} off-hi  — Samsung/SK Hynix proxy (live; leads the print)"
        )
    if m is None:
        return out
    if m.fc_3q:
        cons = (
            f" vs consensus +{m.consensus_3q[0]:.0f}-{m.consensus_3q[1]:.0f}%"
            if m.consensus_3q
            else ""
        )
        out.append(
            f"  3Q26 forecast  : +{m.fc_3q[0]:.0f}-{m.fc_3q[1]:.0f}% QoQ{cons}  ({m.source})"
        )
    if m.top_marker:
        out.append(f"  cycle-top mark : {m.top_marker}")
    if m.awaiting:
        out.append("  latest print   : awaiting (MU guide + 3Q contract prices) — the crux gauge")
    else:
        latest = m.latest or {}
        d = f"DRAM {latest['dram_qoq_pct']:+.0f}%" if latest.get("dram_qoq_pct") is not None else ""
        n = f"NAND {latest['nand_qoq_pct']:+.0f}%" if latest.get("nand_qoq_pct") is not None else ""
        out.append(f"  latest print   : {latest.get('asof')} {d} {n} ({latest.get('source')})")
    out.append(
        "  read: prints > consensus = super-cycle real (tops ~2028; trim=sizing not "
        "timing) · < consensus = top sooner."
    )
    return out


def _ai_demand_block(d: AiDemand | None) -> list[str]:
    if d is None:
        return ["  frontier intel : n/a (OpenRouter fetch failed)"]
    fc = f"${d.frontier_cheapest:.2f}" if d.frontier_cheapest is not None else "n/a"
    fm = f"${d.frontier_median:.2f}" if d.frontier_median is not None else "n/a"
    return [
        f"  frontier intel : cheapest {fc}/Mtok · median {fm}/Mtok  "
        f"({d.frontier_count} frontier-class / {d.model_count} models)",
        "  read: PRICE side only (the Jevons *denominator*) — snapshot the trend; "
        "falling = intelligence commoditizing, volume must outrun it.",
        "  token VOLUME (the demand numerator) isn't here — needs an API key / manual rankings.",
    ]


def _roi_coverage_block(r: macro.RoiCoverage | None) -> list[str]:
    if r is None:
        return ["  roi coverage: n/a (add roi_coverage.json — see roi_coverage.example.json)"]

    def p(x: float | None, fmt: str = "+.0%") -> str:
        return format(x, fmt) if x is not None else "—"

    labs = ", ".join(f"{n} ${a:.0f}B" for n, a in r.labs) or "—"
    arr = f"${r.total_arr:.0f}B" if r.total_arr is not None else "—"
    cap = f"${r.capex:.0f}B" if r.capex is not None else "—"
    cov = f"{r.coverage:.0%}" if r.coverage is not None else "—"
    exo = f"{r.exo_coverage:.0%}" if r.exo_coverage is not None else "—"
    circ = f"{r.circular_pct:.0%}" if r.circular_pct is not None else "—"
    if r.closing is True:
        race = "ARR outgrowing capex → Clock A closing the gap (on paper)"
    elif r.closing is False:
        race = "capex outgrowing ARR → ROI gap WIDENING (supply ahead of paid demand)"
    else:
        race = "growth read incomplete"
    out = [
        f"  lab ARR        : {arr} ({labs})  growth {p(r.arr_growth)}",
        f"  vs capex       : {cap}/yr  growth {p(r.capex_growth)}",
        f"  coverage       : {cov} of capex  (exogenous {exo}, ~{circ} circular)",
    ]
    if r.vol_growth is not None:
        out.append(
            f"  token volume   : {p(r.vol_growth)} (Jevons numerator — must outrun price fall)"
        )
    out.append(
        f"  read: {race}. Coverage = headline; exogenous-vs-circular = honesty check "
        "(circular = NVDA→OpenAI→Azure→NVDA, inflates ARR without anchoring it). "
        f"asof {r.asof}."
    )
    return out


# ---------- delta snapshots (atlas-brief idea: a "what changed" lede) ----------

SNAP_DIR = Path("data/snapshots")


def _snapshot_state(
    when: date,
    regime: macro.Regime,
    momo: macro.Momentum,
    breadth: macro.SpxBreadth | None,
    fg: macro.FearGreed | None,
    m7: macro.Mag7,
    cc: macro.CryptoCredit,
    aid: AiDemand | None,
) -> dict:
    legs = [lg for lg in momo.legs if lg.dd63 is not None]
    basing = sum(1 for lg in legs if lg.d5 is not None and lg.d5 >= 0)
    avg_dd = sum(lg.dd63 for lg in legs) / len(legs) if legs else None
    return {
        "date": when.isoformat(),
        "regime": regime.verdict,
        "stress": regime.stress_count,
        "available": regime.available_count,
        "vix": momo.vix,
        "spx_pct50": breadth.pct_50 if breadth else None,
        "fng": fg.score if fg else None,
        "mag7_breadth": m7.above_50,
        "legs_basing": basing,
        "legs_avg_offhi": avg_dd,
        "strc": cc.strc,
        "ai_frontier": aid.frontier_cheapest if aid else None,
    }


def _write_snapshot(state: dict, when: date) -> None:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    (SNAP_DIR / f"{when.isoformat()}.json").write_text(json.dumps(state, indent=2))


def _load_prior_snapshot(before: date) -> dict | None:
    if not SNAP_DIR.exists():
        return None
    files = sorted(p for p in SNAP_DIR.glob("*.json") if p.stem < before.isoformat())
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text())
    except Exception:
        return None


def _deltas_block(today: dict, prior: dict | None) -> list[str]:
    """The 'what changed since the last brief' lede — keeps the brief newsworthy."""
    if not prior:
        return ['_First snapshot — "what changed" deltas begin on the next run._', ""]
    items: list[str] = []
    if prior.get("regime") and today.get("regime") != prior.get("regime"):
        items.append(f"**regime {prior['regime']} → {today['regime']}**")

    def _d(key: str, label: str, fmt: str, thresh: float, *, pct: bool = False) -> None:
        a, b = today.get(key), prior.get(key)
        if a is None or b is None or abs(a - b) < thresh:
            return
        items.append(f"{label} {b:.0%} → {a:.0%}" if pct else f"{label} {b:{fmt}} → {a:{fmt}}")

    _d("vix", "VIX", ".0f", 1)
    _d("spx_pct50", "SPX breadth", "", 0.02, pct=True)
    _d("fng", "F&G", ".0f", 3)
    _d("strc", "STRC", ".1f", 1)
    _d("mag7_breadth", "Mag7", ".0f", 1)
    a, b = today.get("legs_basing"), prior.get("legs_basing")
    if a is not None and b is not None and a != b:
        items.append(f"legs basing {b} → {a}")
    a, b = today.get("ai_frontier"), prior.get("ai_frontier")
    if a is not None and b is not None and abs(a - b) >= 0.05:
        items.append(f"frontier ${b:.2f} → ${a:.2f}/Mtok")
    if not items:
        items.append("no material change in the tracked signals")
    return [f"_vs prior brief ({prior.get('date', '?')}):_  " + "  ·  ".join(items), ""]


def _book_table(rows: list[BookRow]) -> list[str]:
    head = (
        f"  {'':6} {'spot':>9} {'1d':>7} {'5d':>7} {'HV30':>7} "
        f"{'ATM IV':>7} {'IV/HV':>6} {'→ER':>5}"
    )
    out = [head, "  " + "-" * 60]
    for r in rows:
        out.append(
            f"  {r.ticker:6} {_p(r.spot, ',.2f'):>9} {_p(r.chg_1d):>7} {_p(r.chg_5d):>7} "
            f"{_p(r.hv30):>7} {_p(r.atm_iv):>7} {_p(r.iv_hv, '.2f'):>6} "
            f"{(str(r.dte_earn) if r.dte_earn is not None else '—'):>5}"
        )
    return out


def _days_since_prev_brief(when: date) -> int:
    """Days back to the previous brief, so chatter between runs isn't missed. ≥1."""
    prev: date | None = None
    for p in BRIEF_DIR.glob("*.md"):
        try:
            d = date.fromisoformat(p.stem)
        except ValueError:
            continue
        if d < when and (prev is None or d > prev):
            prev = d
    return max(1, (when - prev).days) if prev else 1


def _catalyst_block(when: date) -> list[str]:
    """'## Upcoming catalysts' — curated, commit-safe calendar (neutral event text)."""
    try:
        from degen.ingest import catalysts

        if not catalysts.DB_PATH.exists():
            return []
        return ["## Upcoming catalysts", "```", *catalysts.brief_lines(as_of=when), "```"]
    except Exception:
        return []


def _qualitative_inputs(when: date) -> list[str]:
    """Stage the raw Discord digest to a gitignored file; point the brief at it.

    PRIVACY: the digest is raw third-party chatter (real handles, P&L). It is written
    ONLY under data/ (gitignored + skipped by the privacy scan). The tracked brief
    gets a pointer, never the raw text — synthesize anonymized prose by hand here.
    """
    out = [
        "## Qualitative inputs",
        "_Paste article links / X posts below; pull X text with degen.daily.fetch_xpost._",
        "",
    ]
    try:
        from degen.ingest import discord_log

        if not discord_log.DB_PATH.exists():
            return out
        days = _days_since_prev_brief(when)
        STAGING_DIR.mkdir(parents=True, exist_ok=True)
        staged = STAGING_DIR / f"{when.isoformat()}.md"
        staged.write_text(
            f"# Discord digest (raw, last {days}d) — {when.isoformat()}\n\n"
            f"{discord_log.digest(days=days)}\n"
        )
        out += [
            f"_Discord (last {days}d): raw digest staged at `{staged}` (gitignored). "
            "Synthesize anonymized prose here — never paste raw handles/P&L._",
            "",
        ]
    except Exception:
        pass  # the brief must never break on the optional Discord layer
    return out


def build_brief(
    tickers: list[str], focus: tuple[str, ...] = FOCUS_DEFAULT, when: date | None = None
) -> str:
    when = when or date.today()
    regime = macro.build()
    fg = macro.fear_greed()
    buf = macro.buffett_indicator()
    ca = macro.cross_asset()
    momo = macro.momentum()
    m7 = macro.mag7()
    breadth = macro.spx_breadth()
    cta = macro.cta()
    cc = macro.crypto_credit()
    creds = macro.credit_stress()
    privc = macro.private_credit()
    nclo = macro.neocloud()
    funding = macro.funding_stress()
    mem = macro.memory_prices()
    memtape = macro.memory_tape()
    cons = macro.consumer_health()
    lab = macro.labor()
    dist = macro.distribution()
    mkrs = macro.makers()
    froth = macro.retail_froth()
    attn = macro.retail_attention()
    aid = ai_demand()
    roi = macro.roi_coverage()

    # delta snapshot: load yesterday's state, compute "what changed", persist today's
    today = date.today()
    today_state = _snapshot_state(today, regime, momo, breadth, fg, m7, cc, aid)
    deltas = _deltas_block(today_state, _load_prior_snapshot(today))
    _write_snapshot(today_state, today)

    focus_set = {t.upper() for t in focus}
    focus_rows = [book_row(t, full=True) for t in tickers if t.upper() in focus_set]
    other_rows = [book_row(t, full=False) for t in tickers if t.upper() not in focus_set]

    buf_line = f"{buf:.0f}% of GDP" if buf is not None else "n/a (FRED unavailable)"
    lines = [
        f"# Daily brief — {regime.asof}",
        "",
        *_signal_digest(regime, momo, breadth, cta, cc),
        "## What changed",
        *deltas,
        "## Macro regime",
        "```",
        str(regime),
        "```",
        "## Consumer (the demand base that funds AI)",
        "```",
        *_consumer_block(cons),
        "```",
        "## Labor (jobs — Clock A income engine + AI-substitution tell)",
        "```",
        *_labor_block(lab),
        "```",
        "## Distribution (who gets the productivity gains)",
        "```",
        *_distribution_block(dist),
        "```",
        "## Sentiment & valuation",
        "```",
        *_fear_greed_block(fg),
        f"  Buffett ind.   : {buf_line}",
        *_cross_asset_block(ca),
        "```",
        "## Momentum / crowding",
        "```",
        *_momentum_block(momo),
        "```",
        "## Breadth & systematic flows",
        "```",
        *_breadth_cta_block(breadth, cta),
        "```",
        "## Crypto / AI-infra credit",
        "```",
        *_crypto_credit_block(cc),
        "```",
        "## Credit stress (Clock B — quality ladder + levered edge)",
        "```",
        *_credit_stress_block(creds),
        "```",
        "## Private credit (Clock B — shadow-bank / AI-infra-debt edge)",
        "```",
        *_private_credit_block(privc),
        "```",
        "## Neocloud watch (Clock B — the levered GPU-cloud operators)",
        "```",
        *_neocloud_block(nclo),
        "```",
        "## Funding plumbing (Clock B — repo / liquidity)",
        "```",
        *_funding_stress_block(funding),
        "```",
        "## AI-infra demand (commoditization)",
        "```",
        *_ai_demand_block(aid),
        "```",
        "## AI ROI coverage (revenue vs capex — Clock A)",
        "```",
        *_roi_coverage_block(roi),
        "```",
        "## Memory super-cycle (price-hike tracker)",
        "```",
        *_memory_block(mem, memtape),
        "```",
        "## Bottleneck makers (deep-moat supply leaders)",
        "```",
        *_makers_block(mkrs),
        "```",
        "## Mag7 — concentration",
        "```",
        *_mag7_block(m7),
        "```",
        "## Retail froth (the payload size, not the fuse)",
        "```",
        *_retail_froth_block(froth),
        "```",
        "## Retail attention (search + social — who's showing up)",
        "```",
        *_retail_attention_block(attn),
        "```",
        "## Book — focus (active theses)",
        "```",
        *_book_table(focus_rows),
        "```",
        "## Book — watch (compact)",
        "```",
        *_book_table(other_rows),
        "```",
        *_catalyst_block(when),
        *_qualitative_inputs(when),
    ]
    return "\n".join(lines)


def write_brief(text: str, when: date | None = None) -> Path:
    when = when or date.today()
    BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    path = BRIEF_DIR / f"{when.isoformat()}.md"
    path.write_text(text)
    return path


def main() -> None:
    args = [a.upper() for a in sys.argv[1:]]
    tickers = args or _read_tickers()
    when = date.today()
    text = build_brief(tickers, when=when)
    path = write_brief(text, when=when)
    print(text)
    print(f"\n[written to {path}]")


if __name__ == "__main__":
    main()
