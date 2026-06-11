#!/usr/bin/env python3
"""
pre_print_checklist.py — verify all required inputs are present before digest start.

Purpose
-------
Pre-print, the digest needs a known set of inputs:
- Earnings date (from the company IR site / latest 8-K)
- Consensus estimates (current Q + FY) — manually entered consensus.csv
- Short-interest snapshot (optional)
- Your positioning read (optional)
- Preview metadata (parsed from the notification PDF via parse_preview.py)
- IR deck URL (for tickers where the 8-K is PR-only)
- Prior-quarter transcript (for the guide baseline)

Without a structured check, the agent starts drafting and then asks for inputs
mid-flight (or worse, fabricates them). The checklist runs FIRST, reports what's
missing, and blocks the digest if any REQUIRED input is missing.

Usage
-----
    python3 pre_print_checklist.py --ticker XYZ

    # Output:
    #   [+] Earnings date confirmed                  (in manifest)
    #   [+] Consensus pulled                         (consensus.csv)
    #   [+] Preview metadata parsed                  (auto)
    #   [-] Short-interest snapshot                  MISSING — optional
    #   [+] IR deck URL                              (in config.yaml)
    #   [+] Prior quarter transcript                 (in transcripts/)
    #
    # 1 of N BLOCKING items missing. Digest cannot start until provided.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_BASE = REPO_ROOT / "workspace"


def ticker_root(analyst: str, ticker: str) -> Path:
    # Single-user workspace: workspace/{TICKER}. The `analyst` parameter is
    # retained only for call-signature compatibility and is not used in the path.
    return WORKSPACE_BASE / ticker.upper()


# ──────────────────────────────────────────────────────────────────
# Default checklist — applied to every ticker unless overridden
# ──────────────────────────────────────────────────────────────────

DEFAULT_CHECKLIST = [
    {
        "id": "calendar_event",
        "label": "Earnings date confirmed (IR site / latest 8-K)",
        "required": True,
        "auto_fetch": False,
        "check_path": "data/data_manifest.json",
        "check_method": "manifest_contains",
        "manifest_tool": "earnings_date",
    },
    {
        "id": "consensus",
        "label": "Consensus (current Q + FY) — manually entered consensus.csv",
        "required": True,
        "auto_fetch": False,
        "check_path": "consensus.csv",
        "check_method": "file_exists",
    },
    {
        "id": "preview_metadata",
        "label": "Preview metadata parsed (parse_preview.py)",
        "required": True,
        "auto_fetch": True,
        "check_path": "preview_metadata.yaml",
        "check_method": "file_exists",
    },
    {
        "id": "salient_kpis_in_config",
        "label": "salient_kpis declared in config.yaml",
        "required": True,
        "auto_fetch": False,
        "check_path": "config.yaml",
        "check_method": "yaml_field_exists",
        "field_name": "salient_kpis",
    },
    {
        "id": "short_interest_snapshot",
        "label": "Short-interest snapshot (optional)",
        "required": False,  # nice to have but not blocking
        "auto_fetch": False,
        "check_path": "positioning.json",
        "check_method": "json_field_present",
        "field_path": "short_interest.shares",
    },
    {
        "id": "positioning_read",
        "label": "Your positioning read (optional)",
        "required": False,
        "auto_fetch": False,
        "check_path": "positioning.json",
        "check_method": "json_field_present",
        "field_path": "positioning_read.tilt",
    },
    {
        "id": "ir_deck_url",
        "label": "IR deck URL in config (for PR-only filers)",
        "required": False,
        "auto_fetch": False,
        "check_path": "config.yaml",
        "check_method": "yaml_field_exists",
        "field_name": "ir_deck_url",
        "applies_when": "files_deck_in_8k_is_false",
    },
    {
        "id": "prior_quarter_transcript",
        "label": "Prior quarter transcript (for guide baseline)",
        "required": True,
        "auto_fetch": True,
        "check_path": "transcripts/",
        "check_method": "directory_has_files",
        "min_files": 1,
    },
]


# ──────────────────────────────────────────────────────────────────
# Check methods
# ──────────────────────────────────────────────────────────────────

def check_file_exists(ticker_dir: Path, item: dict) -> tuple[bool, str]:
    p = ticker_dir / item["check_path"]
    if p.exists():
        return True, f"OK ({p.stat().st_size}B)"
    return False, f"MISSING — file not found at {item['check_path']}"


def check_directory_has_files(ticker_dir: Path, item: dict) -> tuple[bool, str]:
    p = ticker_dir / item["check_path"]
    if not p.exists() or not p.is_dir():
        return False, f"MISSING — directory {item['check_path']} does not exist"
    n = len([f for f in p.iterdir() if f.is_file()])
    min_files = item.get("min_files", 1)
    if n < min_files:
        return False, f"INCOMPLETE — {n}/{min_files} files in {item['check_path']}"
    return True, f"OK ({n} files)"


def check_manifest_contains(ticker_dir: Path, item: dict) -> tuple[bool, str]:
    p = ticker_dir / item["check_path"]
    if not p.exists():
        return False, f"MISSING — data_manifest.json not found"
    try:
        manifest = json.loads(p.read_text())
    except Exception as e:
        return False, f"ERROR — could not parse manifest: {e}"
    tool_name = item["manifest_tool"]
    sources = manifest.get("sources", [])
    matching = [s for s in sources if s.get("tool_name") == tool_name]
    if matching:
        latest = max(s.get("pulled_at", "") for s in matching)
        return True, f"OK ({len(matching)} entries, latest {latest})"
    return False, f"MISSING — no {tool_name} entries in manifest"


def check_yaml_field_exists(ticker_dir: Path, item: dict) -> tuple[bool, str]:
    p = ticker_dir / item["check_path"]
    if not p.exists():
        return False, f"MISSING — {item['check_path']} not found"
    try:
        import yaml
        data = yaml.safe_load(p.read_text())
    except Exception as e:
        return False, f"ERROR — could not parse yaml: {e}"
    field = item["field_name"]
    if field in (data or {}):
        val = data[field]
        n = len(val) if isinstance(val, (list, dict)) else 1
        return True, f"OK ({field}: {n} entries)"
    return False, f"MISSING — field {field} not in {item['check_path']}"


def check_json_field_present(ticker_dir: Path, item: dict) -> tuple[bool, str]:
    p = ticker_dir / item["check_path"]
    if not p.exists():
        return False, f"MISSING — {item['check_path']} not found"
    try:
        data = json.loads(p.read_text())
    except Exception as e:
        return False, f"ERROR — could not parse json: {e}"
    # Walk dotted path
    cur = data
    for part in item["field_path"].split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False, f"MISSING — field {item['field_path']} not in {item['check_path']}"
    if cur is None or cur == "" or cur == "PENDING_USER_INPUT":
        return False, f"PENDING — field {item['field_path']} not yet provided"
    return True, f"OK ({item['field_path']}: {str(cur)[:40]})"


CHECK_METHODS = {
    "file_exists": check_file_exists,
    "directory_has_files": check_directory_has_files,
    "manifest_contains": check_manifest_contains,
    "yaml_field_exists": check_yaml_field_exists,
    "json_field_present": check_json_field_present,
}


# ──────────────────────────────────────────────────────────────────
# Main runner
# ──────────────────────────────────────────────────────────────────

def _resolve_item_templates(item: dict, analyst: str, ticker: str) -> dict:
    """Resolve `{analyst}` and `{ticker}` placeholders in templated string fields.

    Previously, items hardcoded analyst-specific paths like
    `wes_positioning_read.tilt`. Now those fields use `{analyst}_...` and
    `{ticker}_...` placeholders, resolved here once per check so the check
    methods don't need to know about analyst/ticker context.

    Only string values in the templated fields below are formatted.
    """
    templated_fields = ("field_path", "field_name", "manifest_tool", "check_path")
    out = dict(item)
    for k in templated_fields:
        v = out.get(k)
        if isinstance(v, str) and ("{analyst}" in v or "{ticker}" in v):
            out[k] = v.format(analyst=analyst, ticker=ticker)
    return out


def run_checklist(analyst: str, ticker: str, checklist: list[dict] = None) -> dict:
    if checklist is None:
        checklist = DEFAULT_CHECKLIST
    ticker_dir = ticker_root(analyst, ticker)

    if not ticker_dir.exists():
        return {
            "status": "BLOCKED",
            "message": f"Ticker directory does not exist: {ticker_dir}",
            "results": [],
        }

    results = []
    blocking_missing = []
    optional_missing = []

    for raw_item in checklist:
        item = _resolve_item_templates(raw_item, analyst, ticker)
        method = CHECK_METHODS.get(item["check_method"])
        if not method:
            results.append({
                "id": item["id"],
                "label": item["label"],
                "status": "ERROR",
                "detail": f"Unknown check method: {item['check_method']}",
            })
            continue

        passed, detail = method(ticker_dir, item)
        results.append({
            "id": item["id"],
            "label": item["label"],
            "required": item["required"],
            "auto_fetch": item.get("auto_fetch", False),
            "status": "OK" if passed else ("BLOCKING_MISSING" if item["required"] else "OPTIONAL_MISSING"),
            "detail": detail,
        })
        if not passed:
            if item["required"]:
                blocking_missing.append(item["id"])
            else:
                optional_missing.append(item["id"])

    overall_status = "READY" if not blocking_missing else "BLOCKED"
    return {
        "ticker": ticker,
        "analyst": analyst,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": overall_status,
        "blocking_missing": blocking_missing,
        "optional_missing": optional_missing,
        "results": results,
    }


def print_report(report: dict) -> None:
    print("=" * 72)
    print(f"PRE-PRINT CHECKLIST — {report['ticker']} ({report['analyst']})")
    print(f"Checked at: {report['checked_at']}")
    print("=" * 72)
    for r in report["results"]:
        symbol = "[+]" if r["status"] == "OK" else "[-]"
        req_tag = "REQ" if r.get("required") else "opt"
        auto_tag = "(auto)" if r.get("auto_fetch") else "(manual)"
        print(f"  {symbol} [{req_tag}] {r['label']:<48} {auto_tag}  {r['detail']}")
    print()
    if report["status"] == "READY":
        print(f"STATUS: {report['status']} — all required inputs present, digest can start")
    else:
        print(f"STATUS: {report['status']} — {len(report['blocking_missing'])} required input(s) missing:")
        for mid in report["blocking_missing"]:
            print(f"   - {mid}")
        if report["optional_missing"]:
            print(f"Optional missing ({len(report['optional_missing'])}):")
            for mid in report["optional_missing"]:
                print(f"   - {mid}")
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(description="Pre-print checklist runner")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--analyst", default="user")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human report")
    parser.add_argument("--exit-nonzero-on-blocking", action="store_true",
                        help="Exit with code 2 if any REQUIRED input is missing (for CI/runner gates)")
    args = parser.parse_args()

    report = run_checklist(args.analyst, args.ticker)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)

    if args.exit_nonzero_on_blocking and report["status"] == "BLOCKED":
        sys.exit(2)


if __name__ == "__main__":
    main()
