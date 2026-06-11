#!/usr/bin/env python3
"""
digest_state.py — workflow state tracker for the digest agent.

Purpose
-------
Single source of truth for "where are we in the digest workflow for THIS
ticker / period." Replaces ad-hoc memory of "I've pulled consensus but haven't
parsed the preview yet" with a persistent JSON file.

State shape
-----------
{
  "ticker": "XYZ",
  "analyst": "user",
  "period": "C1Q26",
  "current_phase": "draft_skeleton",
  "phase_history": [
    {"phase": "fetch_baseline", "at": "...", "status": "completed"},
    {"phase": "fetch_print_materials", "at": "...", "status": "completed"},
    ...
  ],
  "blockers": [
    {"id": "ir_deck", "description": "...", "since": "..."}
  ],
  "audit_gate_status": "PASS" | "WARN" | "FAIL" | "NOT_RUN",
  "last_action": "render_digest v3",
  "last_action_at": "...",
  "eta_to_delivery": "...",
  "outputs": [
    {"path": "...", "type": "stage1_md", "rendered_at": "..."}
  ]
}

Phases (canonical order)
------------------------
1. fetch_baseline
2. parse_preview
3. pre_print_checklist
4. fetch_print_materials  (PR + deck)
5. extract_actuals
6. compute_scorecard
7. draft_skeleton
8. fill_content
9. baseline_audit
10. render
11. delivered

Usage
-----
    # Read current state
    python3 digest_state.py read --ticker XYZ --analyst user --period C1Q26

    # Update state (advance phase)
    python3 digest_state.py advance --ticker XYZ --analyst user --period C1Q26 --to draft_skeleton

    # Add a blocker
    python3 digest_state.py block --ticker XYZ --analyst user --period C1Q26 \\
        --id missing_deck --description "IR deck not yet posted; retrying"

    # Mark a blocker resolved
    python3 digest_state.py unblock --ticker XYZ --analyst user --period C1Q26 --id missing_deck
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_BASE = REPO_ROOT / "workspace"

CANONICAL_PHASES = [
    "fetch_baseline",
    "parse_preview",
    "pre_print_checklist",
    "fetch_print_materials",
    "extract_actuals",
    "compute_scorecard",
    "draft_skeleton",
    "fill_content",
    "baseline_audit",
    "render",
    "delivered",
]


def state_path(analyst: str, ticker: str, period: str) -> Path:
    p = WORKSPACE_BASE / ticker / "digest_work" / period
    p.mkdir(parents=True, exist_ok=True)
    return p / "digest_state.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(analyst: str, ticker: str, period: str) -> dict:
    p = state_path(analyst, ticker, period)
    if p.exists():
        return json.loads(p.read_text())
    return {
        "ticker": ticker,
        "analyst": analyst,
        "period": period,
        "current_phase": "not_started",
        "phase_history": [],
        "blockers": [],
        "audit_gate_status": "NOT_RUN",
        "last_action": "state_created",
        "last_action_at": now_iso(),
        "eta_to_delivery": None,
        "outputs": [],
    }


def save_state(state: dict) -> Path:
    p = state_path(state["analyst"], state["ticker"], state["period"])
    p.write_text(json.dumps(state, indent=2))
    return p


def advance_phase(state: dict, to_phase: str, status: str = "completed") -> dict:
    if to_phase not in CANONICAL_PHASES:
        raise ValueError(f"Unknown phase: {to_phase}. Valid: {CANONICAL_PHASES}")
    # Append previous phase to history if it wasn't 'not_started'
    if state["current_phase"] != "not_started" and state["current_phase"] != to_phase:
        state["phase_history"].append({
            "phase": state["current_phase"],
            "at": state["last_action_at"],
            "status": "completed",
        })
    state["current_phase"] = to_phase
    state["last_action"] = f"advanced to {to_phase}"
    state["last_action_at"] = now_iso()
    return state


def add_blocker(state: dict, blocker_id: str, description: str) -> dict:
    state["blockers"] = [b for b in state["blockers"] if b["id"] != blocker_id]
    state["blockers"].append({
        "id": blocker_id,
        "description": description,
        "since": now_iso(),
    })
    state["last_action"] = f"blocker added: {blocker_id}"
    state["last_action_at"] = now_iso()
    return state


def remove_blocker(state: dict, blocker_id: str) -> dict:
    before = len(state["blockers"])
    state["blockers"] = [b for b in state["blockers"] if b["id"] != blocker_id]
    if len(state["blockers"]) < before:
        state["last_action"] = f"blocker resolved: {blocker_id}"
        state["last_action_at"] = now_iso()
    return state


def set_audit_status(state: dict, status: str) -> dict:
    state["audit_gate_status"] = status
    state["last_action"] = f"audit_gate: {status}"
    state["last_action_at"] = now_iso()
    return state


def add_output(state: dict, path: str, output_type: str) -> dict:
    state["outputs"].append({
        "path": path,
        "type": output_type,
        "rendered_at": now_iso(),
    })
    state["last_action"] = f"output added: {output_type}"
    state["last_action_at"] = now_iso()
    return state


def print_state(state: dict) -> None:
    print("=" * 72)
    print(f"DIGEST STATE — {state['ticker']} {state['period']} ({state['analyst']})")
    print("=" * 72)
    print(f"Current phase:    {state['current_phase']}")
    phase_idx = CANONICAL_PHASES.index(state["current_phase"]) if state["current_phase"] in CANONICAL_PHASES else -1
    if phase_idx >= 0:
        progress = f"{phase_idx + 1} / {len(CANONICAL_PHASES)}"
        print(f"Progress:         {progress}")
    print(f"Audit gate:       {state['audit_gate_status']}")
    print(f"Last action:      {state['last_action']} at {state['last_action_at']}")
    print(f"ETA:              {state.get('eta_to_delivery', 'n/a')}")
    print()
    if state["blockers"]:
        print(f"BLOCKERS ({len(state['blockers'])}):")
        for b in state["blockers"]:
            print(f"  [{b['id']}] {b['description']}  (since {b['since']})")
    else:
        print("No blockers.")
    print()
    if state["phase_history"]:
        print("Phase history:")
        for h in state["phase_history"][-10:]:
            print(f"  - {h['phase']:<25} {h['status']:<12} at {h['at']}")
    if state["outputs"]:
        print()
        print(f"Outputs ({len(state['outputs'])}):")
        for o in state["outputs"][-5:]:
            print(f"  - {o['type']}: {o['path']}")
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(description="Digest workflow state tracker")
    sub = parser.add_subparsers(dest="cmd", required=True)

    common_args = lambda p: (
        p.add_argument("--ticker", required=True),
        p.add_argument("--analyst", required=True),
        p.add_argument("--period", required=True),
    )

    rd = sub.add_parser("read")
    common_args(rd)
    rd.add_argument("--json", action="store_true")

    av = sub.add_parser("advance")
    common_args(av)
    av.add_argument("--to", required=True, help=f"Target phase. Options: {', '.join(CANONICAL_PHASES)}")
    av.add_argument("--status", default="completed")

    bl = sub.add_parser("block")
    common_args(bl)
    bl.add_argument("--id", required=True)
    bl.add_argument("--description", required=True)

    ub = sub.add_parser("unblock")
    common_args(ub)
    ub.add_argument("--id", required=True)

    sa = sub.add_parser("audit")
    common_args(sa)
    sa.add_argument("--status", required=True, choices=["PASS", "WARN", "FAIL", "NOT_RUN"])

    ao = sub.add_parser("output")
    common_args(ao)
    ao.add_argument("--path", required=True)
    ao.add_argument("--type", required=True)

    args = parser.parse_args()
    state = load_state(args.analyst, args.ticker, args.period)

    if args.cmd == "read":
        if args.json:
            print(json.dumps(state, indent=2))
        else:
            print_state(state)
        return

    if args.cmd == "advance":
        state = advance_phase(state, args.to, args.status)
    elif args.cmd == "block":
        state = add_blocker(state, args.id, args.description)
    elif args.cmd == "unblock":
        state = remove_blocker(state, args.id)
    elif args.cmd == "audit":
        state = set_audit_status(state, args.status)
    elif args.cmd == "output":
        state = add_output(state, args.path, args.type)

    p = save_state(state)
    print(f"[ok] state saved → {p}")
    print_state(state)


if __name__ == "__main__":
    main()
