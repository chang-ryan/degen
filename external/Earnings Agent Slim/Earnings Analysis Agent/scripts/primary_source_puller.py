"""
primary_source_puller.py — pull latest SEC primary sources for a ticker.

Thin wrapper over edgar_fetch.py (free SEC EDGAR endpoints). Pulls the latest
10-K and 10-Q, recent 8-Ks, and carves out the sections the earnings workflow
cares about (revenue recognition, critical accounting policies, business
description, latest earnings 8-K). Then validates that the required outputs
landed on disk.

Outputs:
    workspace/{TICKER}/filings/
        latest_10K.txt, latest_10K_rev_rec.txt, latest_10K_critical_acct.txt,
        latest_10K_business.txt, latest_10Q.txt, latest_10Q_rev_rec.txt,
        latest_earnings_8K.txt, recent_8Ks/, manifest.json

Usage:
    python primary_source_puller.py --ticker XYZ --mode pull
    python primary_source_puller.py --ticker XYZ --mode validate
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from _paths import ticker_dir
import edgar_fetch


# Required outputs the validation step checks for. Mirrors what fetch_ticker
# produces for the 10-K/10-Q/8-K forms.
REQUIRED_OUTPUTS = [
    "latest_10K.txt",
    "latest_10K_rev_rec.txt",
    "latest_10K_critical_acct.txt",
    "latest_10Q.txt",
    "latest_earnings_8K.txt",
]
OPTIONAL_OUTPUTS = [
    "latest_10K_business.txt",
    "latest_10Q_rev_rec.txt",
    "recent_8Ks/",
]


def pull(ticker: str, count: int = 6, user_agent: str | None = None) -> dict:
    """Fetch primary sources via EDGAR and return the manifest."""
    ua = edgar_fetch._user_agent(user_agent)
    return edgar_fetch.fetch_ticker(
        ticker, forms=["10-K", "10-Q", "8-K"], count=count, user_agent=ua,
    )


def validate(ticker: str) -> dict:
    """Check that the required primary-source files exist and are non-empty."""
    out_dir = ticker_dir(ticker) / "filings"
    result = {
        "ticker": ticker.upper(),
        "out_dir": str(out_dir),
        "checked_at": datetime.utcnow().isoformat() + "Z",
        "items": [],
        "summary": {"required_present": 0, "required_missing": 0, "optional_present": 0},
    }

    def _present(name: str) -> bool:
        target = out_dir / name
        if name.endswith("/"):
            return target.exists() and target.is_dir() and any(target.iterdir())
        return target.exists() and not target.is_dir() and target.stat().st_size > 100

    for name in REQUIRED_OUTPUTS:
        ok = _present(name)
        result["items"].append({"name": name, "required": True, "present": ok})
        result["summary"]["required_present" if ok else "required_missing"] += 1
    for name in OPTIONAL_OUTPUTS:
        ok = _present(name)
        result["items"].append({"name": name, "required": False, "present": ok})
        if ok:
            result["summary"]["optional_present"] += 1

    result["status"] = "complete" if result["summary"]["required_missing"] == 0 else "incomplete"
    return result


def _cli() -> int:
    ap = argparse.ArgumentParser(description="Primary-source puller for SEC filings (free EDGAR)")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--count", type=int, default=6, help="Recent 8-Ks to pull")
    ap.add_argument("--user-agent", default=None,
                    help="SEC contact string, e.g. 'Jane Analyst jane@example.com'")
    ap.add_argument("--mode", choices=["pull", "validate"], default="pull",
                    help="pull: download from EDGAR; validate: check produced files")
    ap.add_argument("--json", default=None, help="Write result JSON to path")
    args = ap.parse_args()

    if args.mode == "pull":
        try:
            result = pull(args.ticker, args.count, args.user_agent)
        except (ValueError, RuntimeError) as e:
            print(f"[error] {e}", file=sys.stderr)
            return 1
    else:
        result = validate(args.ticker)

    text = json.dumps(result, indent=2)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
    print(text)

    if args.mode == "validate" and result.get("status") != "complete":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
