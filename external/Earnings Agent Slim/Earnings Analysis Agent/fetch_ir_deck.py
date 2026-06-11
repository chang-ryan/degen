#!/usr/bin/env python3
"""
fetch_ir_deck.py — fetch the IR-hosted earnings deck for tickers where 8-K is PR-only.

Purpose
-------
For tickers that file the press release in the 8-K but post the earnings deck
only on their IR site, the digest agent needs a way to fetch the deck at print
time. Without this, the agent has to either skip the deck (weakening the OM
cadence and segment-split disclosure) or wait for the user to manually drop it
(delays the digest).

This script reads `config.yaml`'s `ir_deck_url` and `files_deck_in_8k` flags
and, when `files_deck_in_8k: false`, emits a fetch request that the agent
fulfills via a web fetch. Same emit/fulfill pattern the digest runner uses
for other deferred fetches.

Usage
-----
    # Step 1: emit a fetch request
    python3 fetch_ir_deck.py emit --ticker XYZ --analyst user --period C1Q26

    # Output: print_materials/{period}/ir_deck_fetch_request.json
    # The agent reads the request, fetches the URL, and saves
    # the result to print_materials/{period}/earnings_deck.pdf.

    # Step 2: verify the deck was saved
    python3 fetch_ir_deck.py verify --ticker XYZ --analyst user --period C1Q26
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_BASE = REPO_ROOT / "workspace"


def ticker_root(analyst: str, ticker: str) -> Path:
    return WORKSPACE_BASE / ticker


def print_materials_dir(analyst: str, ticker: str, period: str) -> Path:
    p = ticker_root(analyst, ticker) / "print_materials" / period
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_config(analyst: str, ticker: str) -> dict:
    p = ticker_root(analyst, ticker) / "config.yaml"
    if not p.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(p.read_text()) or {}
    except ImportError:
        return {}


def emit_fetch_request(analyst: str, ticker: str, period: str) -> Path:
    """Emit a JSON request that the agent fulfills via a web fetch."""
    config = load_config(analyst, ticker)
    files_in_8k = config.get("files_deck_in_8k", "pending_verification")
    ir_url = config.get("ir_deck_url", "")

    if files_in_8k is True:
        print(f"[skip] config says files_deck_in_8k=true for {ticker}; deck should come from 8-K Exhibit 99.2 not IR site",
              file=sys.stderr)
        sys.exit(0)

    if not ir_url or "pending" in str(ir_url).lower():
        print(f"[error] ir_deck_url not configured for {ticker}; add to config.yaml first",
              file=sys.stderr)
        sys.exit(2)

    workdir = print_materials_dir(analyst, ticker, period)
    request = {
        "request_type": "fetch_ir_deck",
        "ticker": ticker,
        "analyst": analyst,
        "period": period,
        "ir_deck_url": ir_url,
        "instructions": [
            "1. Use a web fetch to retrieve the IR Quarterly Results page at ir_deck_url.",
            "2. From the page, locate the most recent earnings deck PDF link "
            "(typically named 'Q{N} {YEAR} Earnings Presentation' or similar).",
            "3. Fetch the deck PDF binary.",
            "4. Save the PDF to: " + str(workdir / "earnings_deck.pdf"),
            "5. Write a fetch_manifest.json with: {url, fetched_at, file_size, method, notes}.",
            "6. If the deck is not yet posted (e.g., agent runs <30 min after PR), retry every 5 minutes "
            "for up to 30 minutes total before giving up. Some companies post the deck simultaneously "
            "with the PR; others post 15-30 min later.",
            "7. If unable to fetch (paywall, JS-only page, blocked by content restriction), write a "
            "fetch_manifest.json with status='FAILED' and a specific reason. The digest agent will "
            "downgrade gracefully and note the deck was unavailable in the audit log.",
        ],
        "expected_outputs": [
            str(workdir / "earnings_deck.pdf"),
            str(workdir / "fetch_manifest.json"),
        ],
        "emitted_at": datetime.now(timezone.utc).isoformat(),
    }
    out = workdir / "ir_deck_fetch_request.json"
    out.write_text(json.dumps(request, indent=2))
    return out


def verify(analyst: str, ticker: str, period: str) -> int:
    workdir = print_materials_dir(analyst, ticker, period)
    deck = workdir / "earnings_deck.pdf"
    manifest = workdir / "fetch_manifest.json"

    if deck.exists():
        size_kb = deck.stat().st_size / 1024
        print(f"[ok] deck present at {deck} ({size_kb:.1f}KB)")
        if manifest.exists():
            try:
                m = json.loads(manifest.read_text())
                print(f"     fetched_at: {m.get('fetched_at', 'n/a')}")
            except (OSError, json.JSONDecodeError) as e:
                # P1-5: previously a bare `except: pass`. The deck is
                # present, so we don't change the return value, but the
                # operator should see that the manifest is corrupt — it
                # may indicate a half-completed fetch that needs cleanup.
                print(f"     [warn] fetch_manifest.json unreadable: {e}", file=sys.stderr)
        return 0

    if manifest.exists():
        try:
            m = json.loads(manifest.read_text())
            if m.get("status") == "FAILED":
                print(f"[fail] deck fetch FAILED: {m.get('reason', 'no reason given')}")
                return 1
        except (OSError, json.JSONDecodeError) as e:
            # P1-5: previously a bare `except: pass`. A corrupt manifest
            # AND a missing deck is a legitimate failure mode — surface it
            # to stderr so the operator can investigate, then fall through
            # to the [pending] return below (which is the safe default).
            print(f"[warn] fetch_manifest.json unreadable: {e}; treating as pending", file=sys.stderr)

    print(f"[pending] deck not yet fetched at {deck}")
    return 1


def main():
    parser = argparse.ArgumentParser(description="Fetch IR-hosted earnings deck for PR-only filers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    em = sub.add_parser("emit", help="Emit fetch request for the agent to fulfill")
    em.add_argument("--ticker", required=True)
    em.add_argument("--analyst", required=True)
    em.add_argument("--period", required=True)

    vf = sub.add_parser("verify", help="Verify the deck was saved")
    vf.add_argument("--ticker", required=True)
    vf.add_argument("--analyst", required=True)
    vf.add_argument("--period", required=True)

    args = parser.parse_args()

    if args.cmd == "emit":
        out = emit_fetch_request(args.analyst, args.ticker, args.period)
        print(f"[ok] fetch request emitted → {out}")
        print(f"[next] The agent reads the request and fetches the deck.")
    elif args.cmd == "verify":
        rc = verify(args.analyst, args.ticker, args.period)
        sys.exit(rc)


if __name__ == "__main__":
    main()
