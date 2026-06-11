"""Daily ATM IV snapshot store. The piece no free API gives you.

Run `snapshot([...tickers])` once a day (cron, launchd, or by hand). Over a year
you build the history that lets `iv_rank()` answer the only question that matters
before buying premium: is vol cheap or crowded *for this name*?

Storage: SQLite at `data/iv_snapshots.db` (gitignored). One row per ticker per day.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from degen.data import atm_iv, expiries

DB_PATH = Path("data/iv_snapshots.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS iv_snapshots (
    snapshot_date TEXT NOT NULL,
    ticker        TEXT NOT NULL,
    atm_iv        REAL NOT NULL,
    PRIMARY KEY (snapshot_date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_ticker_date ON iv_snapshots(ticker, snapshot_date);
"""


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    return conn


def _pick_near_dte_expiry(ticker: str, target_dte: int = 30) -> str:
    """Pick the expiry closest to target_dte. Convention for IV rank: ~30 DTE."""
    from datetime import datetime

    today = date.today()
    best = min(
        expiries(ticker),
        key=lambda e: abs((datetime.strptime(e, "%Y-%m-%d").date() - today).days - target_dte),
    )
    return best


def snapshot(
    tickers: Iterable[str],
    db_path: Path = DB_PATH,
    target_dte: int = 30,
) -> dict[str, float | None]:
    """Record today's ~30-DTE ATM IV per ticker. Idempotent per (date, ticker).

    Using a constant-maturity-ish expiry (~30 DTE) instead of the front weekly
    keeps the IV-rank series comparable across days and immune to weekly noise.
    """
    today = date.today().isoformat()
    results: dict[str, float | None] = {}
    with _connect(db_path) as conn:
        for t in tickers:
            try:
                exp = _pick_near_dte_expiry(t, target_dte)
                iv = atm_iv(t, exp)
            except Exception as e:  # noqa: BLE001 — log and skip, don't abort the batch
                print(f"  {t}: skip ({e})")
                results[t] = None
                continue
            conn.execute(
                "INSERT OR REPLACE INTO iv_snapshots VALUES (?, ?, ?)",
                (today, t, iv),
            )
            results[t] = iv
    return results


def iv_history(ticker: str, lookback_days: int = 252, db_path: Path = DB_PATH) -> list[float]:
    """Most recent `lookback_days` IV observations for a ticker, oldest first."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT atm_iv FROM iv_snapshots
            WHERE ticker = ?
            ORDER BY snapshot_date DESC
            LIMIT ?
            """,
            (ticker, lookback_days),
        ).fetchall()
    return [r[0] for r in reversed(rows)]


def iv_rank(ticker: str, lookback_days: int = 252, db_path: Path = DB_PATH) -> float | None:
    """Where current IV sits in its [min, max] over the lookback. 0=cheapest, 1=richest.

    Returns None if fewer than 20 observations exist (not enough history to trust).
    """
    hist = iv_history(ticker, lookback_days, db_path)
    if len(hist) < 20:
        return None
    current = hist[-1]
    lo, hi = min(hist), max(hist)
    if hi == lo:
        return 0.5
    return (current - lo) / (hi - lo)


def iv_percentile(ticker: str, lookback_days: int = 252, db_path: Path = DB_PATH) -> float | None:
    """Fraction of past observations strictly below today's IV. None if too little history."""
    hist = iv_history(ticker, lookback_days, db_path)
    if len(hist) < 20:
        return None
    current = hist[-1]
    return sum(1 for x in hist[:-1] if x < current) / (len(hist) - 1)


def _read_tickers_file(path: Path = Path("tickers.txt")) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"no ticker list at {path}")
    out = []
    for line in path.read_text().splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s.upper())
    return out


def main() -> None:
    """CLI: `uv run python -m degen.iv_store snapshot [TICKER ...]`

    Subcommands:
      snapshot [tickers]   record today's ATM IV; defaults to tickers.txt
      rank <ticker>        print IV rank + percentile + observation count
    """
    import sys

    args = sys.argv[1:]
    cmd = args[0] if args else "snapshot"

    if cmd == "snapshot":
        tickers = args[1:] or _read_tickers_file()
        print(f"snapshotting {len(tickers)} tickers → {DB_PATH}")
        results = snapshot(tickers)
        for t, iv in results.items():
            print(f"  {t}: {iv:.1%}" if iv is not None else f"  {t}: —")
    elif cmd == "rank":
        if len(args) < 2:
            sys.exit("usage: rank <TICKER>")
        t = args[1].upper()
        hist = iv_history(t)
        r = iv_rank(t)
        p = iv_percentile(t)
        print(f"{t}: n={len(hist)}")
        print(f"  rank      : {r:.0%}" if r is not None else "  rank      : n/a (need ≥20 obs)")
        print(f"  percentile: {p:.0%}" if p is not None else "  percentile: n/a")
    else:
        sys.exit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
