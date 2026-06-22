"""Catalyst calendar — dated events pulled from the channel, counted down for the brief.

Layer 3 of the chat-derived signal (see `ingest/__init__`). Same split as the call
ledger: EXTRACTING an event + its date from a message is interpretation (an
LLM/human pass over `candidates`), but the COUNTDOWN is deterministic — days-to-go
from today, surfaced in the daily brief next to the book row.

Unlike the raw digest and the call ledger, a *curated* catalyst row is commit-safe:
keep `event` a short neutral description ("Ph3 readout", "MU earnings", "CPO roadmap")
— no handles, no P&L — and the calendar can render straight into the tracked brief.

  uv run python -m degen.ingest.catalysts candidates --author <handle> --json /tmp/cat.json
  # (fill ticker/event/event_date, drop non-events, then:)
  uv run python -m degen.ingest.catalysts import /tmp/cat.json
  uv run python -m degen.ingest.catalysts upcoming --within 90
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from degen.ingest.discord_log import DB_PATH

PRECISIONS = ("exact", "approx")  # is event_date a firm date or a best-estimate?

# Surfacing heuristic only — finds candidate messages for the human/LLM pass.
_EVENT_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|q[1-4]|"
    r"\d{1,2}/\d{1,2}|earnings|readout|catalyst|fda|ph\s?[1-3]|approval|"
    r"guidance|investor day|analyst day|trial|data\b)\w*",
    re.I,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS catalysts (
    catalyst_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    source_message_id  TEXT NOT NULL,
    ticker             TEXT NOT NULL,
    event              TEXT NOT NULL,          -- short NEUTRAL description (commit-safe)
    event_date         TEXT NOT NULL,          -- ISO date (best estimate)
    precision          TEXT NOT NULL DEFAULT 'approx',  -- exact | approx
    notes              TEXT,
    curated_at         TEXT NOT NULL,
    UNIQUE(source_message_id, ticker, event_date)
);
CREATE INDEX IF NOT EXISTS idx_cat_date ON catalysts(event_date);
"""


@dataclass(frozen=True, slots=True)
class Candidate:
    message_id: str
    ts: str
    tickers: list[str]
    content: str


@dataclass(frozen=True, slots=True)
class Upcoming:
    ticker: str
    event: str
    event_date: str
    precision: str
    days_to_go: int


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    return conn


# ---------- candidate surfacing ----------


def candidates(
    author: str | None = None,
    since: str | None = None,
    db_path: Path = DB_PATH,
) -> list[Candidate]:
    """Ticker-bearing messages that mention a date/event word — input to the HITL pass."""
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
        curated = {r[0] for r in conn.execute("SELECT DISTINCT source_message_id FROM catalysts")}
        rows = conn.execute(q, params).fetchall()
    out = []
    for mid, ts, content, tickers in rows:
        if mid in curated or not _EVENT_RE.search(content):
            continue
        out.append(Candidate(mid, ts, json.loads(tickers), content))
    return out


def candidates_skeleton(cands: list[Candidate]) -> list[dict[str, object]]:
    """JSON skeleton for the HITL pass — one entry per (candidate, ticker)."""
    skel: list[dict[str, object]] = []
    for c in cands:
        for t in c.tickers:
            entry: dict[str, object] = {
                "source_message_id": c.message_id,
                "ticker": t,
                "event": "",  # short neutral description
                "event_date": "",  # YYYY-MM-DD (best estimate)
                "precision": "approx",  # exact | approx
                "_text": c.content,  # context for review; ignored on import
            }
            skel.append(entry)
    return skel


# ---------- writing ----------


def add_catalyst(
    *,
    source_message_id: str,
    ticker: str,
    event: str,
    event_date: str,
    precision: str = "approx",
    notes: str | None = None,
    db_path: Path = DB_PATH,
) -> None:
    """Insert (or replace) one curated catalyst. Validates date + precision."""
    if precision not in PRECISIONS:
        raise ValueError(f"precision {precision!r} not in {PRECISIONS}")
    date.fromisoformat(event_date)  # raises on a malformed date
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO catalysts
                (catalyst_id, source_message_id, ticker, event, event_date,
                 precision, notes, curated_at)
            VALUES (
                (SELECT catalyst_id FROM catalysts
                 WHERE source_message_id=? AND ticker=? AND event_date=?),
                ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_message_id,
                ticker.upper(),
                event_date,
                source_message_id,
                ticker.upper(),
                event,
                event_date,
                precision,
                notes or None,
                datetime.now(UTC).isoformat(),
            ),
        )


def import_catalysts(path: Path, db_path: Path = DB_PATH) -> int:
    """Bulk-load reviewed catalysts from a JSON list. Entries missing event/date skipped."""
    items = json.loads(Path(path).read_text())
    n = 0
    for it in items:
        if not it.get("event") or not it.get("event_date"):
            continue
        add_catalyst(
            source_message_id=it["source_message_id"],
            ticker=it["ticker"],
            event=it["event"],
            event_date=it["event_date"],
            precision=it.get("precision") or "approx",
            notes=it.get("notes") or None,
            db_path=db_path,
        )
        n += 1
    return n


# ---------- the deterministic part: countdown ----------


def upcoming(
    within_days: int | None = None,
    as_of: date | None = None,
    db_path: Path = DB_PATH,
) -> list[Upcoming]:
    """Catalysts on/after `as_of`, soonest first, with days-to-go. Optional horizon cap."""
    today = as_of or date.today()
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT ticker, event, event_date, precision FROM catalysts "
            "WHERE event_date >= ? ORDER BY event_date",
            (today.isoformat(),),
        ).fetchall()
    out = []
    for ticker, event, ev_date, prec in rows:
        dtg = (date.fromisoformat(ev_date) - today).days
        if within_days is not None and dtg > within_days:
            continue
        out.append(Upcoming(ticker, event, ev_date, prec, dtg))
    return out


def brief_lines(
    as_of: date | None = None, within_days: int = 90, db_path: Path = DB_PATH
) -> list[str]:
    """Rendered '## Upcoming catalysts' block for the daily brief (commit-safe)."""
    ups = upcoming(within_days, as_of, db_path)
    if not ups:
        return ["  (no catalysts within horizon — run degen.ingest.catalysts candidates)"]
    out = [f"  {'':6} {'in':>5}  {'date':<10} event"]
    for u in ups:
        approx = "~" if u.precision == "approx" else " "
        out.append(f"  {u.ticker:6} {u.days_to_go:>4}d  {approx}{u.event_date:<9} {u.event}")
    return out


# ---------- CLI ----------


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(prog="degen.ingest.catalysts")
    sub = p.add_subparsers(dest="cmd")

    cd = sub.add_parser("candidates", help="surface date/event messages for review")
    cd.add_argument("--author", default=None)
    cd.add_argument("--since", default=None)
    cd.add_argument("--json", default=None, help="write a fill-in skeleton here")

    im = sub.add_parser("import", help="bulk-load reviewed catalysts from a JSON file")
    im.add_argument("file")

    up = sub.add_parser("upcoming", help="print the countdown calendar")
    up.add_argument("--within", type=int, default=None, help="horizon cap in days")

    args = p.parse_args()
    cmd = args.cmd or "upcoming"

    if cmd == "candidates":
        cands = candidates(args.author, args.since)
        if args.json:
            skel = candidates_skeleton(cands)
            Path(args.json).write_text(json.dumps(skel, indent=2))
            print(f"{len(cands)} candidate message(s), {len(skel)} (msg,ticker) rows → {args.json}")
            print("Fill event + event_date (YYYY-MM-DD), drop non-events, then `import`.")
        else:
            for c in cands:
                print(f"[{c.ts[:16]}] {c.message_id}  {c.tickers}")
                print(f"    {c.content[:200].strip()}")
        return
    if cmd == "import":
        n = import_catalysts(Path(args.file))
        print(f"imported {n} catalyst(s)")
        return
    if cmd == "upcoming":
        print("\n".join(brief_lines(within_days=args.within or 365)))
        return
    p.error(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
