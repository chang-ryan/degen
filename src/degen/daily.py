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
from degen.data import atm_iv, expiries, history, next_earnings, realized_vol

FOCUS_DEFAULT = ("CRM", "TEAM", "SMH", "SOXX", "USO")  # active-thesis names get the full row
TICKERS_FILE = Path("tickers.txt")
BRIEF_DIR = Path("docs/daily")


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


def build_brief(tickers: list[str], focus: tuple[str, ...] = FOCUS_DEFAULT) -> str:
    regime = macro.build()
    fg = macro.fear_greed()
    buf = macro.buffett_indicator()
    ca = macro.cross_asset()
    momo = macro.momentum()
    m7 = macro.mag7()
    breadth = macro.spx_breadth()
    cta = macro.cta()

    focus_set = {t.upper() for t in focus}
    focus_rows = [book_row(t, full=True) for t in tickers if t.upper() in focus_set]
    other_rows = [book_row(t, full=False) for t in tickers if t.upper() not in focus_set]

    buf_line = f"{buf:.0f}% of GDP" if buf is not None else "n/a (FRED unavailable)"
    lines = [
        f"# Daily brief — {regime.asof}",
        "",
        *_signal_digest(regime, momo, breadth, cta),
        "## Macro regime",
        "```",
        str(regime),
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
        "## Mag7 — concentration",
        "```",
        *_mag7_block(m7),
        "```",
        "## Book — focus (active theses)",
        "```",
        *_book_table(focus_rows),
        "```",
        "## Book — watch (compact)",
        "```",
        *_book_table(other_rows),
        "```",
        "## Qualitative inputs",
        "_Paste article links / X posts below; pull X text with degen.daily.fetch_xpost._",
        "",
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
    text = build_brief(tickers)
    path = write_brief(text)
    print(text)
    print(f"\n[written to {path}]")


if __name__ == "__main__":
    main()
