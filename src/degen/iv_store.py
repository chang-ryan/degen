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

from degen.data import atm_iv

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


def snapshot(tickers: Iterable[str], db_path: Path = DB_PATH) -> dict[str, float | None]:
    """Record today's ATM IV for each ticker. Idempotent per (date, ticker)."""
    today = date.today().isoformat()
    results: dict[str, float | None] = {}
    with _connect(db_path) as conn:
        for t in tickers:
            try:
                iv = atm_iv(t)
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
