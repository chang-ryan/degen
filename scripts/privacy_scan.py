#!/usr/bin/env python3
"""Privacy guardrail — fail if tracked files leak live-book personal info.

The repo is a shareable skeleton; the live book (real positions, P&L, account
info, net worth) lives in gitignored files (POSITIONS.md / JOURNAL.md /
WATCHLIST.md / cta_levels.json / .env / data/). This scans the *tracked* text
files for personal-info patterns that shouldn't be committed and exits non-zero
on a hit — wire it as a pre-commit hook (see scripts/hooks/pre-commit) or run
`uv run python scripts/privacy_scan.py` manually.

Heuristic, not perfect: it targets dollar P&L, net-worth/account references, and
share-count P&L — NOT market data (prices, IV%, breadth%), which are fine. Tune
PATTERNS if it false-positives; the goal is a tripwire, not a proof.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# (regex, why) — case-insensitive. Tightened to skip market data (prices, IV%,
# breadth%) AND generic rule language ("1% of port", "≤8% of port") and hit only
# live-book leakage: signed-dollar P&L, net-worth/account talk, $Nk book sizes.
PATTERNS: list[tuple[str, str]] = [
    (r"\+\$\d", "dollar gain / P&L (e.g. +$1,739)"),
    (r"[+\-\u2212]\$[\d,]+\s*\(", "signed-dollar P&L with a parenthetical (e.g. -$2,146 (...))"),
    (r"net worth", "net-worth reference"),
    (r"\$[\d.]+k\s+(book|cash|port|net|account|premium|sleeve)", "$Nk book/cash/port size"),
    (r"\b(REDACTED-ACCT|REDACTED-ACCT|REDACTED-ACCT)\b", "broker account number"),
    # NB: bare gain %s (e.g. "1,734%") are NOT scanned — indistinguishable from
    # public trailing-return stats ("+1,100%/252d"). Scrub personal gains by hand.
]

# Skipped: templates (meant to be empty), vendored code, local data, and THIS
# file (it necessarily contains the example patterns it scans for).
SKIP = re.compile(r"\.example\.|^external/|^data/|scripts/privacy_scan\.py$")

_COMPILED = [(re.compile(p, re.IGNORECASE), why) for p, why in PATTERNS]


def _tracked_files() -> list[str]:
    globs = ["*.md", "*.txt", "*.json", "*.py"]
    # tracked files + new (untracked, not-gitignored) files — both get committed.
    tracked = subprocess.run(
        ["git", "ls-files", *globs], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    new = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", *globs],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    seen = dict.fromkeys(tracked + new)  # dedupe, preserve order
    return [f for f in seen if not SKIP.search(f) and "example" not in f]


def scan() -> int:
    hits: list[str] = []
    for path in _tracked_files():
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in enumerate(lines, 1):
            for rx, why in _COMPILED:
                if rx.search(line):
                    hits.append(f"  {path}:{n}  [{why}]\n      {line.strip()[:120]}")
                    break
    if hits:
        print("PRIVACY SCAN FAILED — tracked files contain live-book personal info:\n")
        print("\n".join(hits))
        print(
            f"\n{len(hits)} hit(s). Scrub the personal numbers (keep the analysis), "
            "or move the content to a gitignored file. See README 'Local-only files'."
        )
        return 1
    print("privacy scan: clean — no live-book personal info in tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(scan())
