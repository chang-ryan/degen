#!/usr/bin/env python3
"""
runner_preconditions.py — phase precondition gates for earnings_digest_runner.

Purpose
-------
Each phase of the digest workflow has dependencies. Without enforcement, the
runner can advance through phases even when prereqs are missing — leading to
half-built baselines, fabricated source labels, or empty digest sections.

This module provides a `check_preconditions(phase, ...)` function that
the digest runner can call before each phase to verify dependencies.

Phase prerequisites
-------------------
fetch_baseline:           none (this is the first phase)
parse_preview:            preview file present in print_materials/ or root
pre_print_checklist:      baseline + preview_metadata.yaml present
fetch_print_materials:    pre-print checklist passed (READY)
extract_actuals:          press_release.txt or similar in workdir
compute_scorecard:        actuals.json + digest_baseline.json present
draft_skeleton:           skeleton template + preview_metadata.yaml + config.yaml + salient_kpis loaded
fill_content:             skeleton draft started; baseline + actuals available
baseline_audit:           digest markdown exists
render:                   audit gate is PASS or WARN (not FAIL); skeleton + content complete
delivered:                rendered PDF exists; state advanced to delivered

Usage
-----
    from runner_preconditions import check_preconditions

    ok, missing = check_preconditions("draft_skeleton", "user", "XYZ", "C1Q26")
    if not ok:
        print(f"Cannot start draft_skeleton — missing: {missing}")
        sys.exit(2)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

# P1-5: structured logging for the silent-fallback patterns below. The
# functions intentionally return permissive defaults (False/[]/"NOT_RUN")
# on parse errors — that lets the pipeline keep advancing and surface the
# missing-input via the requirement check rather than a stack trace. But
# silent fallback also hides corrupt inputs (e.g., a manifest.json that's
# truncated mid-write). Logging at WARNING makes the corruption visible
# without changing control flow.
_log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_BASE = REPO_ROOT / "workspace"


def ticker_root(analyst: str, ticker: str) -> Path:
    return WORKSPACE_BASE / ticker


def workdir(analyst: str, ticker: str, period: str) -> Path:
    return ticker_root(analyst, ticker) / "digest_work" / period


def _exists(p: Path) -> bool:
    return p.exists() and (p.stat().st_size > 0 if p.is_file() else True)


# ──────────────────────────────────────────────────────────────────
# Phase-by-phase prerequisite checks
# ──────────────────────────────────────────────────────────────────

PHASE_REQUIREMENTS = {
    "fetch_baseline": [],

    "parse_preview": [
        ("preview_file", lambda a, t, p: any([
            _exists(ticker_root(a, t) / "print_materials" / "notification.pdf"),
            _exists(ticker_root(a, t) / "notification.pdf"),
            list((ticker_root(a, t) / "outputs").glob("*PREVIEW*V*.md")) if (ticker_root(a, t) / "outputs").exists() else [],
        ])),
    ],

    "pre_print_checklist": [
        ("data_manifest_or_baseline", lambda a, t, p: _exists(ticker_root(a, t) / "data_manifest.json") or _exists(ticker_root(a, t) / "baseline" / f"digest_baseline_{p}.json")),
        ("preview_metadata", lambda a, t, p: _exists(ticker_root(a, t) / "preview_metadata.yaml")),
    ],

    "fetch_print_materials": [
        ("config_yaml", lambda a, t, p: _exists(ticker_root(a, t) / "config.yaml")),
        ("earnings_date_confirmed", lambda a, t, p: _check_manifest_has(a, t, "earnings_date")),
    ],

    "extract_actuals": [
        ("press_release", lambda a, t, p: _exists(workdir(a, t, p) / "press_release.txt") or _exists(workdir(a, t, p) / "press_release.md") or _check_uploads_for_pr(a, t)),
    ],

    "compute_scorecard": [
        ("actuals_json", lambda a, t, p: _exists(workdir(a, t, p) / "actuals.json") or _exists(workdir(a, t, p) / "extracted_actuals.json")),
        ("baseline_json", lambda a, t, p: _exists(workdir(a, t, p) / "digest_baseline.json") or _exists(ticker_root(a, t) / "baseline" / f"digest_baseline_{p}.json")),
    ],

    "draft_skeleton": [
        ("skeleton_template", lambda a, t, p: _exists(REPO_ROOT / "Earnings Analysis Agent" / "digest_skeleton_adaptive.md")),
        ("preview_metadata", lambda a, t, p: _exists(ticker_root(a, t) / "preview_metadata.yaml")),
        ("config_with_salient_kpis", lambda a, t, p: _config_has_salient_kpis(a, t)),
    ],

    "fill_content": [
        ("skeleton_draft_present", lambda a, t, p: _has_draft_md(a, t, p)),
    ],

    "baseline_audit": [
        ("digest_md_present", lambda a, t, p: _has_draft_md(a, t, p)),
    ],

    "render": [
        ("digest_md_present", lambda a, t, p: _has_draft_md(a, t, p)),
        ("audit_gate_not_fail", lambda a, t, p: _audit_gate_status(a, t, p) != "FAIL"),
    ],

    "delivered": [
        ("pdf_rendered", lambda a, t, p: _has_rendered_pdf(a, t, p)),
    ],
}


def _check_manifest_has(analyst: str, ticker: str, tool_name: str) -> bool:
    p = ticker_root(analyst, ticker) / "data_manifest.json"
    if not p.exists():
        return False
    try:
        m = json.loads(p.read_text())
    except Exception as e:
        _log.warning("data_manifest.json at %s failed to parse: %s", p, e)
        return False
    return any(s.get("tool_name") == tool_name for s in m.get("sources", []))


def _company_name_aliases(analyst: str, ticker: str) -> list[str]:
    """Read `company_name_aliases` from the ticker's config.yaml, lowercased.

    Returns an empty list if config is absent, malformed, or doesn't define
    aliases. The check that uses this list always also matches against the
    ticker symbol itself, so an empty alias list is safe — it just means
    PR-uploads must contain the literal ticker symbol to be recognized.

    Why this exists: SEC filings and PR uploads frequently use the company
    name (e.g., the full corporate name) rather than the ticker, so matching
    against the ticker alone misses real PRs. Previously this was patched
    by hardcoding a single company name in the filename check — which would
    silently accept that company's PR file during a run for a different
    ticker. The config-driven version eliminates that cross-ticker risk.
    """
    cfg = ticker_root(analyst, ticker) / "config.yaml"
    if not cfg.exists():
        return []
    try:
        import yaml
    except ImportError:
        return []
    try:
        data = yaml.safe_load(cfg.read_text()) or {}
    except Exception as e:
        _log.warning("config.yaml at %s failed to parse for alias check: %s", cfg, e)
        return []
    aliases = data.get("company_name_aliases", [])
    if not isinstance(aliases, list):
        return []
    return [str(a).lower().strip() for a in aliases if a and str(a).strip()]


def _check_uploads_for_pr(analyst: str, ticker: str) -> bool:
    """Check workspace uploads dir for any PR-like file matching this ticker.

    A match requires BOTH:
      1. A PR-like keyword in the filename ("financial res", "earnings",
         "press release", "results"), AND
      2. The lowercased ticker symbol OR a config-declared company-name
         alias appears in the filename.

    The previous implementation also hardcoded a single company name as a
    fallback alias, which would silently accept that company's PR uploads
    during runs for any other ticker. That hardcode is gone; aliases now
    come from the ticker's config.yaml.

    Path-resolution: the uploads dir is looked for at the sibling of the
    repo root (`REPO_ROOT.parent / "uploads"`), with a legacy three-levels-up
    path preserved as a fallback so any environment that depended on it does
    not regress.
    """
    candidates = [
        REPO_ROOT.parent / "uploads",                # repo sibling (preferred)
        REPO_ROOT.parent.parent.parent / "uploads",  # legacy path (preserved as fallback)
    ]
    uploads = next((p for p in candidates if p.exists()), None)
    if uploads is None:
        return False
    needles = [ticker.lower()] + _company_name_aliases(analyst, ticker)
    pr_keywords = ("financial res", "earnings", "press release", "results")
    for f in uploads.iterdir():
        name = f.name.lower()
        # Normalize separators: real upload filenames frequently use underscores
        # or dashes where the keyword phrase has spaces (e.g. "press_release"
        # vs "press release"). Without this, the function silently failed to
        # detect canonical PR uploads.
        normalized = name.replace("_", " ").replace("-", " ")
        if not any(k in normalized for k in pr_keywords):
            continue
        if any(n in normalized for n in needles):
            return True
    return False


def _config_has_salient_kpis(analyst: str, ticker: str) -> bool:
    p = ticker_root(analyst, ticker) / "config.yaml"
    if not p.exists():
        return False
    try:
        import yaml
        d = yaml.safe_load(p.read_text()) or {}
        return bool(d.get("salient_kpis"))
    except Exception as e:
        _log.warning("config.yaml at %s failed to parse for salient_kpis check: %s", p, e)
        return False


def _has_draft_md(analyst: str, ticker: str, period: str) -> bool:
    out = ticker_root(analyst, ticker) / "outputs"
    if not out.exists():
        return False
    candidates = list(out.glob(f"digest_v1_print_{period}_*.md"))
    return len(candidates) > 0


def _has_rendered_pdf(analyst: str, ticker: str, period: str) -> bool:
    out = ticker_root(analyst, ticker) / "outputs"
    if not out.exists():
        return False
    candidates = list(out.glob(f"digest_v1_print_{period}_*.pdf"))
    return len(candidates) > 0


def _audit_gate_status(analyst: str, ticker: str, period: str) -> str:
    p = workdir(analyst, ticker, period) / "digest_state.json"
    if not p.exists():
        return "NOT_RUN"
    try:
        s = json.loads(p.read_text())
        return s.get("audit_gate_status", "NOT_RUN")
    except Exception as e:
        _log.warning("digest_state.json at %s failed to parse, treating as NOT_RUN: %s", p, e)
        return "NOT_RUN"


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def check_preconditions(phase: str, analyst: str, ticker: str, period: str) -> tuple[bool, list[str]]:
    """Check preconditions for entering a phase.

    Returns: (all_passed, list_of_missing_requirements)
    """
    if phase not in PHASE_REQUIREMENTS:
        return False, [f"unknown phase: {phase}"]

    requirements = PHASE_REQUIREMENTS[phase]
    missing = []
    for req_id, check_fn in requirements:
        try:
            if not check_fn(analyst, ticker, period):
                missing.append(req_id)
        except Exception as e:
            missing.append(f"{req_id} (check error: {e})")

    return len(missing) == 0, missing


def main():
    """CLI for ad-hoc precondition checks."""
    import argparse
    parser = argparse.ArgumentParser(description="Check phase preconditions")
    parser.add_argument("--phase", required=True, choices=list(PHASE_REQUIREMENTS.keys()))
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--analyst", required=True)
    parser.add_argument("--period", required=True)
    parser.add_argument("--exit-nonzero-on-fail", action="store_true")
    args = parser.parse_args()

    ok, missing = check_preconditions(args.phase, args.analyst, args.ticker, args.period)
    if ok:
        print(f"[+] preconditions OK for phase '{args.phase}' ({args.ticker} {args.period})")
    else:
        print(f"[X] preconditions FAILED for phase '{args.phase}' ({args.ticker} {args.period})")
        for m in missing:
            print(f"    - missing: {m}")
        if args.exit_nonzero_on_fail:
            import sys
            sys.exit(2)


if __name__ == "__main__":
    main()
