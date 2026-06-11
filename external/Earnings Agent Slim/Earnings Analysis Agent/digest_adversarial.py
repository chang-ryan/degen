#!/usr/bin/env python3
"""
digest_adversarial.py — adversarial verification subagent driver.

PURPOSE
-------
Per the verification hierarchy (deterministic > adversarial-different-goal >
LLM-redundant), this driver emits a prompt for an adversarial verification
subagent whose goal is structurally DIFFERENT from the drafting subagents.

The drafting subagents write content. This adversarial subagent's only goal
is to FIND ERRORS — it doesn't confirm anything. Different goal = uncorrelated
failure modes, which is the math underlying the verification hierarchy.

WHEN TO USE
-----------
After main draft is complete, audit_agent has run, BEFORE final render.
This is a final gate. If the adversarial subagent surfaces material
errors, the draft is sent back for fixes; if it's clean, render proceeds.

USAGE
-----
    # Step 1: emit the adversarial prompt
    python3 digest_adversarial.py emit \\
        --ticker XYZ --analyst user --period C1Q26 --mode print

    # Output: digest_work/{period}/adversarial_prompt.json
    # The orchestrator reads this and dispatches a Task subagent with the
    # prompt + the input files. Subagent returns a findings JSON.

    # Step 2: ingest subagent findings + classify
    python3 digest_adversarial.py ingest \\
        --ticker XYZ --analyst user --period C1Q26 --mode print

    # Reads digest_work/{period}/adversarial_findings.json
    # Outputs: pass/fail + specific remediation list

DESIGN NOTES
------------
- The adversarial subagent prompt is INTENTIONALLY HOSTILE in framing.
  It is told its ONLY job is to find errors, not confirm anything. This
  is the structural difference from the drafting subagents.
- Specific failure modes the subagent is briefed on (from observed errors):
    1. Apples-to-oranges period-average comparisons (different denominators)
    2. Derived non-GAAP OM cited as if stated (tax-rate assumption errors)
    3. Fabricated cons / variant numbers without source
    4. Day-of-binary metric overridden vs preview
    5. Sizing pointers in Synthesis (should be in the Trade Construction section only)
    6. Performative jargon ("risk symmetry / asymmetric right vs left")
    7. Missing calculation persistence on consequential numbers
    8. Source-tier confusion (derived margin treated as STATED)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Match the workdir resolution used by the digest runner
REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_BASE = REPO_ROOT / "workspace"


def workdir(analyst: str, ticker: str, period: str) -> Path:
    p = WORKSPACE_BASE / ticker / "digest_work" / period
    return p


def find_latest_md(analyst: str, ticker: str, period: str, mode: str) -> str:
    """Find the latest digest markdown for the given mode."""
    out = WORKSPACE_BASE / ticker / "outputs"
    if mode == "print":
        candidates = sorted(
            out.glob(f"digest_v1_print_{period}_*.md")
        ) + sorted(out.glob(f"{ticker}_*Stage1*.md"))
    else:
        candidates = sorted(
            out.glob(f"digest_v2_transcript_{period}_*.md")
        ) + sorted(out.glob(f"{ticker}_*Stage2*.md"))
    if not candidates:
        return ""
    candidates = [c for c in candidates if "PRESTAGED" not in c.name]
    return str(candidates[-1]) if candidates else ""


ADVERSARIAL_PROMPT_TEMPLATE = """\
# Adversarial Verification Subagent — {ticker} {period} {mode}

## Your role
You are an ADVERSARIAL verification subagent. Your ONLY goal is to FIND ERRORS in the digest draft. You do NOT confirm anything. You do NOT validate. You FIND WHAT IS WRONG.

This is a structurally different goal from the drafting subagents. They wrote content. You attack that content.

## Inputs
- Digest draft markdown: {md_path}
- Source data:
    - actuals.json (extracted numbers): {actuals_path}
    - scorecard.json (computed beat/miss): {scorecard_path}
    - digest_baseline.json (preview baseline / cons / variant): {baseline_path}
- Programmatic audit findings (already run): {audit_path}

## Specific failure modes to hunt for

### 1. Apples-to-oranges period-average comparisons
Look for any sentence that compares two period averages where the denominators differ. Examples:
- "2H'26 averaging X% vs 2Q-4Q'26 averaging Y%" (2-quarter vs 3-quarter avg — INVALID)
- "1H'26 vs FY'26" (2-quarter vs 4-quarter — INVALID without normalization)
- "Q4'25 vs 2H'26 average" (single quarter vs 2-quarter avg — VALID only if explicitly framed)

For every "step-up of X bps" / "averaging Y%" / "from N to M" claim, write out both denominators in your head. If they don't match, FLAG.

### 2. Derived non-GAAP margins cited as STATED
Scan actuals.json for any metric with `estimated_flag: true` or `source: derived`. Then scan the digest body for citations of those values. Any citation WITHOUT explicit hedge language ("derived," "estimated," "see deck/10-Q for actual," "[INFERRED]") is an ERROR.

An example historical case: a Stage 1 digest cited a prior-quarter non-GAAP OM as 22.5% (derived from non-GAAP NI / revenue with a tax-rate assumption). The deck showed 26.1% actual — a 360bps error that propagated into the OM bridge framing. Hunt for this pattern.

### 3. Fabricated cons / variant numbers
Every cons or your variant figure cited must trace to digest_baseline.json (preview KPI tables, consensus.csv, or positioning.json). Flag any cited cons number that you can't trace.

### 4. Day-of-binary metric overridden vs preview
The Synthesis paragraph must NAME the day-of-binary trigger metric anchored to the preview's "What metrics matter" section (e.g., volumes/units for a volume-driven name). If the Synthesis frames OM, EPS, or any other metric as the day-of binary, that's an ERROR (the preview's named trigger was overridden by the agent's analytical preference).

### 5. Sizing pointers in Synthesis
Synthesis paragraph should NOT contain HOLD/ADD/TRIM/EXIT recommendations or sizing math. Those belong in the Trade Construction + Positioning section / Recommended Action box. If the Synthesis has a sizing pointer, FLAG.

### 6. Performative jargon
Flag any of these phrasings as performative (they sound incisive but don't add information):
- "Risk symmetry: upside asymmetric to the right; downside asymmetric to the left"
- "Asymmetric right" / "asymmetric left" without specific quantification
- Generic "raise-to-fix-walk-down vs pull-forward-upside" without the underlying math

### 7. Missing calculation persistence on consequential numbers
For every "step-up of X bps," "cushion of $Y," "gap of Z%" claim in the body, there should be nearby math: input × formula = result. If a consequential numerical claim is asserted without the arithmetic, FLAG.

### 8. Source-tier confusion in evidence tags
If the doc uses [STATED] / [INFERRED] / [SPECULATIVE] tags, scan for misclassifications. A derivation tagged [STATED] is wrong. A direct PR quote tagged [INFERRED] is wrong. A future projection tagged [STATED] is wrong.

### 9. Other red flags
- Banned internal codename strings anywhere in body
- Verbatim earnings call quotes when paraphrase was requested
- Version references (v3, v4, v5) or meta-commentary about prior drafts
- LLM_FILL placeholders not replaced

### 10. Production-ready violations (auto-checked by production_ready_check.py)
Run production_ready_check on the draft. Every violation it returns IS an adversarial finding — promote to error level. Categories include:
- PR-01: Bias Pre-Commitment section in deliverable (must live in synthesis/ work files only)
- PR-02: first-person pre-commitment language ("Going in I'm leaning…", "I'm at risk of confirmation bias…")
- PR-03: any analyst-named action label (use "Recommended Action")
- PR-04: "Pre-Print Decision (from preview)" row in digest header
- PR-05: "Earnings Preview Score" row in digest header (preview-only field)
- PR-06: [PENDING] / LLM_FILL / "Sub-agent X fills" scaffolding placeholders
- PR-07: analyst-name placeholders awaiting human fill
- PR-08: internal version references ("from V10 preview", "the prior draft")
- PR-09: stage / process footers ("End of Stage 1…", "Audit metadata", "Template Usage Notes")
- PR-10: "PRESTAGED" naming references
- PR-11: banned internal codename terminology
- PR-12: internal HTML comments leaking into render (<!-- INTERNAL -->, <!-- REMOVE BEFORE -->)
- PR-13: self-referential drafting commentary ("my earlier framing", "in my initial draft")
- PR-14: "risk symmetry / asymmetric right vs left" performative jargon
- PR-15: sizing-conviction contradiction ("HIGH conviction" + "do not size up" in same doc)
- PR-16: direction-label inversion ("achievability STRENGTHENED" likely means "achievability WEAKENED" or "bear thesis STRENGTHENED")
- PR-17: sizing price inconsistent with tier ladder (price range in a SIZE UP / ADD / RE-SHORT context that does not match the canonical Tier 1/2/3 ranges defined elsewhere in the document)

### 11. Whole-document consistency review (semantic — LLM judgment required)

Read the ENTIRE document and verify all directional / sizing / conviction statements agree. Specific cross-section consistency checks:

(a) **Decision header row vs Action box vs Delta vs Stage 1 vs Sizing framework section** — all must state the SAME action recommendation, the SAME price entry zone (or compatible tier ladder), and the SAME conviction posture. If the decision header says "SIZE UP TOWARD 1.5-2.5% GROSS; TIER 1 ENTRY $27-29" but the Delta vs Stage 1 says "SIZE UP on squeeze pops into $32-35", that's the failure mode that occurred and must be flagged.

(b) **Conviction posture consistency** — if "HIGH conviction" appears in one section and "MEDIUM conviction" in another, that's a contradiction. Use the most-recent statement and ensure all references update.

(c) **Bear thesis state consistency** — if the document says the bear thesis is "STRENGTHENED" in one section and "WEAKENED" in another (for the same component), that's a contradiction.

(d) **FY EBITDA landing zone consistency** — if the digest cites $225M base case in one section and $250M in another, flag for reconciliation.

(e) **Sizing target consistency** — target gross weight, target dollar size, current size, incremental size — all numeric values across sections must reconcile arithmetically.

The deterministic PR rules (PR-15, PR-16, PR-17) catch literal phrase patterns. The adversarial subagent's job is to catch SEMANTIC inconsistencies that span sections and survive the regex checks. Read the doc end-to-end with the single question: "do all directional / sizing / conviction statements agree across every section?"

### 12. Direction-label inversion (semantic — LLM judgment required)
Pure regex (PR-16) catches the most common literal inversions but misses semantic ones. The adversarial subagent should check EVERY use of STRENGTHENED / WEAKENED / IMPROVED / DETERIORATED / MATERIALLY SHIFTED in the draft and answer:

(a) What is the variable being labeled? (bull-friendly polarity? bear-friendly polarity?)
(b) What is the surrounding context? (bullish recommendation? bearish recommendation?)
(c) Does the label direction match the intended analytical point?

Specific patterns to hunt for:
- Bull-friendly variable + got-better verb in a bear digest → almost certainly inverted (PR-16 catches the common ones)
- Bear-friendly variable + got-worse verb in a bear digest → also likely inverted ("bear thesis WEAKENED" in a digest arguing the bear case stronger is self-contradictory)
- Direction labels in Delta-vs-Stage-1 tables without explicit claim polarity in the same row

The drafting-time discipline is to ALWAYS pair direction labels with claim polarity in the same sentence. If the subagent finds direction labels naked (without explicit polarity), flag for rewrite.

## Output format
Write findings to: {findings_path}

```json
{{
  "audit_at": "ISO8601 timestamp",
  "ticker": "{ticker}",
  "period": "{period}",
  "mode": "{mode}",
  "findings": [
    {{
      "level": "error" | "warning",
      "category": "period_denominator | derived_margin | fabrication | day_of_binary | sizing_in_synthesis | performative | calc_persistence | source_tier | other",
      "msg": "specific description of the error",
      "context": "surrounding sentence / paragraph from the draft",
      "remediation": "specific fix to apply"
    }}
  ],
  "pass": true_only_if_zero_errors,
  "elapsed_sec": int
}}
```

## Constraints
- Do NOT confirm correctness. Your job is to find errors.
- For every "looks ok" temptation, ask: "what could be wrong here that I'm missing?"
- Cite specific sentences from the draft, not generic patterns.
- If you find zero errors, that result must be qualified — return findings: [] with a note that you searched but didn't find issues. Don't write a summary that confirms the draft.
"""


def emit_adversarial_prompt(
    analyst: str, ticker: str, period: str, mode: str
) -> Path:
    wd = workdir(analyst, ticker, period)
    md_path = find_latest_md(analyst, ticker, period, mode)
    actuals_path = wd / "actuals.json"
    scorecard_path = wd / "scorecard.json"
    baseline_path = wd / "digest_baseline.json"
    audit_path = (
        Path(md_path).with_suffix(".audit.json") if md_path else wd / "audit.json"
    )
    findings_path = wd / "adversarial_findings.json"

    prompt = ADVERSARIAL_PROMPT_TEMPLATE.format(
        ticker=ticker,
        period=period,
        mode=mode,
        md_path=md_path,
        actuals_path=str(actuals_path),
        scorecard_path=str(scorecard_path),
        baseline_path=str(baseline_path),
        audit_path=str(audit_path),
        findings_path=str(findings_path),
    )

    out = wd / "adversarial_prompt.md"
    out.write_text(prompt)

    # Also emit a compact JSON dispatch for chat orchestrator
    dispatch = {
        "request_type": "adversarial_verification",
        "ticker": ticker,
        "period": period,
        "mode": mode,
        "prompt_md": str(out),
        "input_files": {
            "draft_md": md_path,
            "actuals": str(actuals_path),
            "scorecard": str(scorecard_path),
            "baseline": str(baseline_path),
            "audit": str(audit_path),
        },
        "expected_output": str(findings_path),
        "instructions": [
            "1. Spawn a Task subagent with the prompt at adversarial_prompt.md",
            "2. Subagent reads the input files",
            "3. Subagent writes findings to adversarial_findings.json per the schema in the prompt",
            "4. Run `python3 digest_adversarial.py ingest ...` to classify",
        ],
    }
    (wd / "adversarial_dispatch.json").write_text(json.dumps(dispatch, indent=2))
    return out


def ingest_adversarial_findings(
    analyst: str, ticker: str, period: str, mode: str = "print"
) -> dict:
    wd = workdir(analyst, ticker, period)
    findings_path = wd / "adversarial_findings.json"
    if not findings_path.exists():
        return {"pass": False, "msg": f"no findings file at {findings_path}"}
    findings = json.loads(findings_path.read_text())
    errors = [f for f in findings.get("findings", []) if f.get("level") == "error"]
    warnings = [f for f in findings.get("findings", []) if f.get("level") == "warning"]

    # Promote production_ready_check violations to adversarial errors. This is
    # the deterministic backstop — even if the LLM subagent misses a forbidden
    # phrase, the regex check catches it.
    md_path = find_latest_md(analyst, ticker, period, mode)
    if md_path:
        try:
            from production_ready_check import check_file as _prd_check
        except ImportError:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).resolve().parent))
            from production_ready_check import check_file as _prd_check
        prd = _prd_check(md_path)
        for v in prd.get("violations", []):
            errors.append(
                {
                    "level": "error",
                    "category": "production_ready",
                    "msg": f"{v['id']} {v['name']}: matched {v['matched']!r}",
                    "context": v.get("excerpt", ""),
                    "remediation": v.get("fix", ""),
                }
            )

    return {
        "pass": len(errors) == 0,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Digest Adversarial Verification")
    p.add_argument("phase", choices=["emit", "ingest"])
    p.add_argument("--ticker", required=True)
    p.add_argument("--analyst", required=True)
    p.add_argument("--period", required=True)
    p.add_argument("--mode", choices=["print", "transcript"], default="print")
    args = p.parse_args(argv)

    if args.phase == "emit":
        out = emit_adversarial_prompt(
            args.analyst, args.ticker, args.period, args.mode
        )
        print(f"[ok] adversarial prompt → {out}")
        print(
            "[next] LLM-in-chat: spawn Task subagent with this prompt; "
            "subagent writes findings to adversarial_findings.json"
        )
        return 0
    if args.phase == "ingest":
        result = ingest_adversarial_findings(
            args.analyst, args.ticker, args.period, args.mode
        )
        if result.get("pass"):
            print(
                f"[pass] adversarial verification: 0 errors, "
                f"{result.get('warning_count', 0)} warnings"
            )
            return 0
        print(
            f"[fail] adversarial verification: "
            f"{result.get('error_count', 0)} errors, "
            f"{result.get('warning_count', 0)} warnings"
        )
        for e in result.get("errors", []):
            print(f"  ERROR [{e.get('category')}]: {e.get('msg')}")
            if e.get("remediation"):
                print(f"    fix: {e.get('remediation')}")
        return 2

    return 1


if __name__ == "__main__":
    sys.exit(main())
