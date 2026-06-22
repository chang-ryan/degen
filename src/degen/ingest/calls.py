"""Inspector Lee's call ledger — turn directional chatter into a forward-return hit rate.

Layer 2 of the chat-derived signal (see `ingest/__init__`). The `messages` table
(discord_log) is the deterministic spine; this turns a *curated* subset of those
messages into structured calls and scores them against realized price.

The split that keeps it honest:
  - DETECTING a call + its direction/target is interpretation — an LLM-assisted,
    human-in-the-loop step. `candidates` surfaces directional messages; a Claude
    session (or you) reads them and writes structured rows via `add` / `import`.
    No LLM is baked into this module: extraction is a session step, scoring is code.
  - SCORING is deterministic: forward return at +21d / +63d from the call date,
    absolute and SPY-relative, compared against the call's expected direction.

A "sell X for Y" rotation is just two rows (sell X, buy Y). Fuzzy exits — "trim
GEV", "sell SNDK" — are first-class directions, scored as expected-underperform.

This is a *calibration gauge*, not a scorecard: small N, fuzzy entries, no clean
exits. It replaces the vibes-based "Confidence / track record" line in input notes
with a number — read it with its caveats.

  uv run python -m degen.ingest.calls candidates --author <handle> --json /tmp/c.json
  # (review/fill direction+target in the JSON, then:)
  uv run python -m degen.ingest.calls import /tmp/c.json
  uv run python -m degen.ingest.calls score
  uv run python -m degen.ingest.calls report --author <handle>
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from degen import data
from degen.ingest.discord_log import DB_PATH

# Expected forward-return sign per direction. Reduce/exit calls (trim/sell/avoid)
# express "this underperforms from here" → scored as a short. watch/note = no view.
DIRECTIONS = {
    "long": 1,
    "add": 1,
    "buy": 1,
    "cover": 1,
    "short": -1,
    "sell": -1,
    "trim": -1,
    "avoid": -1,
    "watch": 0,
}
CONVICTIONS = ("high", "med", "low")
HORIZONS = {"21d": 21, "63d": 63}  # trading days
BENCHMARK = "SPY"

# Surfacing heuristic only — finds *candidate* messages for human review, never
# auto-creates calls. Deliberately broad; precision comes from the HITL pass.
_DIR_RE = re.compile(
    r"\b(long|short|buy|bought|sell|sold|trim|trimm|add|adding|cover|"
    r"puts?|calls?|upside|downside|target|stop|double|r/?r|risk.?reward)\b",
    re.I,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    call_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_message_id  TEXT NOT NULL,
    author_name        TEXT NOT NULL,
    call_ts            TEXT NOT NULL,          -- ISO8601 UTC (the message time)
    ticker             TEXT NOT NULL,
    direction          TEXT NOT NULL,          -- see DIRECTIONS
    conviction         TEXT,                   -- high | med | low | NULL
    target             REAL,                   -- optional stated price target
    horizon            TEXT,                   -- optional free-text ("into July Ph3")
    thesis             TEXT,                   -- one-line rationale (LLM/human)
    notes              TEXT,
    curated_at         TEXT NOT NULL,
    -- scoring (filled by `score`, recomputed idempotently)
    spot_at_call       REAL,
    ret_21d            REAL,
    ret_63d            REAL,
    rel_21d            REAL,
    rel_63d            REAL,
    scored_at          TEXT,
    UNIQUE(source_message_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_calls_author ON calls(author_name, call_ts);
"""


@dataclass(frozen=True, slots=True)
class Candidate:
    message_id: str
    ts: str
    tickers: list[str]
    content: str


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)  # coexists with the messages table in the same DB
    return conn


# ---------- candidate surfacing (input to the HITL/LLM pass) ----------


def candidates(
    author: str | None = None,
    since: str | None = None,
    db_path: Path = DB_PATH,
) -> list[Candidate]:
    """Ticker-bearing, directional-sounding messages NOT yet in the ledger.

    A surfacing heuristic, not a classifier — the LLM/human pass decides what's a
    real call. Excludes messages whose (id) already produced a curated call.
    """
    q = "SELECT message_id, ts, content, tickers FROM messages WHERE tickers != '[]'"
    params: list[str] = []
    if author:
        q += " AND author_name LIKE ?"
        params.append(f"%{author}%")
    if since:
        q += " AND ts >= ?"
        params.append(since)
    q += " ORDER BY ts"
    with _connect(db_path) as conn:
        curated = {r[0] for r in conn.execute("SELECT DISTINCT source_message_id FROM calls")}
        rows = conn.execute(q, params).fetchall()
    out = []
    for mid, ts, content, tickers in rows:
        if mid in curated or not _DIR_RE.search(content):
            continue
        out.append(Candidate(mid, ts, json.loads(tickers), content))
    return out


def candidates_skeleton(cands: list[Candidate]) -> list[dict[str, object]]:
    """JSON skeleton for the HITL pass — one entry per (candidate, ticker), with
    empty fields to fill. Drop entries that aren't real calls before `import`."""
    skel: list[dict[str, object]] = []
    for c in cands:
        for t in c.tickers:
            entry: dict[str, object] = {
                "source_message_id": c.message_id,
                "call_ts": c.ts,
                "ticker": t,
                "direction": "",  # one of DIRECTIONS
                "conviction": "",  # high|med|low or ""
                "target": None,
                "horizon": "",
                "thesis": "",
                "_text": c.content,  # context for review; ignored on import
            }
            skel.append(entry)
    return skel


# ---------- writing calls ----------


def add_call(
    *,
    source_message_id: str,
    ticker: str,
    direction: str,
    call_ts: str | None = None,
    conviction: str | None = None,
    target: float | None = None,
    horizon: str | None = None,
    thesis: str | None = None,
    notes: str | None = None,
    db_path: Path = DB_PATH,
) -> None:
    """Insert (or replace) one curated call. `call_ts`/author are pulled from the
    source message if not given. Validates direction/conviction against the enums."""
    if direction not in DIRECTIONS:
        raise ValueError(f"direction {direction!r} not in {sorted(DIRECTIONS)}")
    if conviction and conviction not in CONVICTIONS:
        raise ValueError(f"conviction {conviction!r} not in {CONVICTIONS}")
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT author_name, ts FROM messages WHERE message_id = ?",
            (source_message_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"no message {source_message_id} in the log")
        author, msg_ts = row
        conn.execute(
            """
            INSERT OR REPLACE INTO calls
                (call_id, source_message_id, author_name, call_ts, ticker, direction,
                 conviction, target, horizon, thesis, notes, curated_at)
            VALUES (
                (SELECT call_id FROM calls WHERE source_message_id=? AND ticker=?),
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_message_id,
                ticker.upper(),
                source_message_id,
                author,
                call_ts or msg_ts,
                ticker.upper(),
                direction,
                conviction or None,
                target,
                horizon or None,
                thesis or None,
                notes or None,
                datetime.now(UTC).isoformat(),
            ),
        )


def import_calls(path: Path, db_path: Path = DB_PATH) -> int:
    """Bulk-load reviewed calls from a JSON list (the filled skeleton). Entries with
    a blank direction are skipped (not yet classified / not a call)."""
    items = json.loads(Path(path).read_text())
    n = 0
    for it in items:
        if not it.get("direction"):
            continue
        add_call(
            source_message_id=it["source_message_id"],
            ticker=it["ticker"],
            direction=it["direction"],
            call_ts=it.get("call_ts"),
            conviction=it.get("conviction") or None,
            target=it.get("target"),
            horizon=it.get("horizon") or None,
            thesis=it.get("thesis") or None,
            db_path=db_path,
        )
        n += 1
    return n


# ---------- scoring (deterministic) ----------


def _fwd_return(
    closes: pd.Series | None, call_date: date, n: int
) -> tuple[float | None, float | None]:
    """(base_close, n-trading-day forward return) anchored at the first close on/after
    call_date. Forward return is None if there isn't yet `n` more sessions of data."""
    if closes is None or len(closes) == 0:
        return None, None
    idx = int(closes.index.searchsorted(pd.Timestamp(call_date, tz=closes.index.tz)))
    if idx >= len(closes):
        return None, None
    base = float(closes.iloc[idx])
    if idx + n >= len(closes):
        return base, None
    return base, float(closes.iloc[idx + n] / base - 1)


def _closes(ticker: str) -> pd.Series | None:
    try:
        h = data.history(ticker, period="2y")
        return None if h.empty else h["Close"]
    except Exception:
        return None


def score(db_path: Path = DB_PATH) -> int:
    """Recompute forward returns (abs + benchmark-relative) for every call. Idempotent.

    Returns the count of calls that now have a 63d (full-horizon) result.
    """
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        calls = conn.execute("SELECT call_id, ticker, call_ts FROM calls").fetchall()
        bench = _closes(BENCHMARK)
        price_cache: dict[str, pd.Series | None] = {}
        full = 0
        for c in calls:
            cdate = date.fromisoformat(c["call_ts"][:10])
            tkr = c["ticker"]
            if tkr not in price_cache:
                price_cache[tkr] = _closes(tkr)
            base, r21 = _fwd_return(price_cache[tkr], cdate, HORIZONS["21d"])
            _, r63 = _fwd_return(price_cache[tkr], cdate, HORIZONS["63d"])
            _, b21 = _fwd_return(bench, cdate, HORIZONS["21d"])
            _, b63 = _fwd_return(bench, cdate, HORIZONS["63d"])
            rel21 = (r21 - b21) if (r21 is not None and b21 is not None) else None
            rel63 = (r63 - b63) if (r63 is not None and b63 is not None) else None
            conn.execute(
                """UPDATE calls SET spot_at_call=?, ret_21d=?, ret_63d=?,
                   rel_21d=?, rel_63d=?, scored_at=? WHERE call_id=?""",
                (base, r21, r63, rel21, rel63, datetime.now(UTC).isoformat(), c["call_id"]),
            )
            if r63 is not None:
                full += 1
    return full


# ---------- reporting ----------


def _hit(direction: str, ret: float | None) -> bool | None:
    """Did the call's direction match the realized move? None if no view / no data."""
    sign = DIRECTIONS[direction]
    if sign == 0 or ret is None:
        return None
    return (sign > 0 and ret > 0) or (sign < 0 and ret < 0)


def report(author: str | None = None, db_path: Path = DB_PATH) -> str:
    q = "SELECT * FROM calls"
    params: list[str] = []
    if author:
        q += " WHERE author_name LIKE ?"
        params.append(f"%{author}%")
    q += " ORDER BY call_ts"
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(q, params).fetchall()
    if not rows:
        return "_No curated calls. Run `candidates` → review → `import` → `score`._"

    def rate(rs: list[sqlite3.Row], col: str) -> str:
        hits = [_hit(r["direction"], r[col]) for r in rs]
        graded = [h for h in hits if h is not None]
        if not graded:
            return "—"
        return f"{sum(graded) / len(graded):.0%} (n={len(graded)})"

    def avg(rs: list[sqlite3.Row], col: str) -> str:
        vals = [r[col] for r in rs if r[col] is not None]
        return f"{sum(vals) / len(vals):+.1%}" if vals else "—"

    n_full = sum(1 for r in rows if r["ret_63d"] is not None)
    lines = [
        f"# Call ledger — {author or 'all authors'}",
        "_Calibration gauge: small N, fuzzy entries/exits. Forward return from the call "
        "date; rel = vs SPY. Read with caveats, not as a scorecard._",
        "",
        f"calls: {len(rows)}  ·  scored (full 63d): {n_full}",
        "",
        "## Overall",
        f"  hit rate  21d abs {rate(rows, 'ret_21d')}   63d abs {rate(rows, 'ret_63d')}",
        f"            21d rel {rate(rows, 'rel_21d')}   63d rel {rate(rows, 'rel_63d')}",
        f"  avg ret   21d {avg(rows, 'ret_21d')} (rel {avg(rows, 'rel_21d')})   "
        f"63d {avg(rows, 'ret_63d')} (rel {avg(rows, 'rel_63d')})",
        "",
        "## By direction",
    ]

    def line(label: str, rs: list[sqlite3.Row]) -> str:
        a, rel = rate(rs, "ret_63d"), rate(rs, "rel_63d")
        return f"  {label:<6} n={len(rs):<3} 63d abs {a}  rel {rel}"

    for d in sorted({r["direction"] for r in rows}):
        lines.append(line(d, [r for r in rows if r["direction"] == d]))
    lines.append("")
    lines.append("## By conviction")
    for cv in (*CONVICTIONS, None):
        rs = [r for r in rows if r["conviction"] == cv]
        if rs:
            lines.append(line(cv or "—", rs))
    return "\n".join(lines)


# ---------- CLI ----------


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(prog="degen.ingest.calls")
    sub = p.add_subparsers(dest="cmd")

    cd = sub.add_parser("candidates", help="surface directional messages for review")
    cd.add_argument("--author", default=None)
    cd.add_argument("--since", default=None, help="ISO date lower bound")
    cd.add_argument("--json", default=None, help="write a fill-in skeleton here")

    im = sub.add_parser("import", help="bulk-load reviewed calls from a JSON file")
    im.add_argument("file")

    sub.add_parser("score", help="recompute forward returns for all calls")

    rp = sub.add_parser("report", help="print the track record")
    rp.add_argument("--author", default=None)

    args = p.parse_args()
    cmd = args.cmd or "report"

    if cmd == "candidates":
        cands = candidates(args.author, args.since)
        if args.json:
            skel = candidates_skeleton(cands)
            Path(args.json).write_text(json.dumps(skel, indent=2))
            print(f"{len(cands)} candidate message(s), {len(skel)} (msg,ticker) rows → {args.json}")
            print("Fill `direction` (+ conviction/target/thesis), drop non-calls, then `import`.")
        else:
            for c in cands:
                print(f"[{c.ts[:16]}] {c.message_id}  {c.tickers}")
                print(f"    {c.content[:200].strip()}")
        return
    if cmd == "import":
        n = import_calls(Path(args.file))
        print(f"imported {n} call(s); now run `score`")
        return
    if cmd == "score":
        full = score()
        print(f"scored; {full} call(s) have a full 63d forward return")
        return
    if cmd == "report":
        print(report(args.author))
        return
    p.error(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
