#!/usr/bin/env python3
"""
production_ready_check.py — deterministic build gate that halts the render
pipeline if a digest or preview markdown contains internal-process noise,
self-referential commentary, or scaffolding placeholders that should never
reach a circulation-quality deliverable.

This is the LAST-LINE gate run by render_digest.py and render_preview.py
right before pandoc → weasyprint. It runs on the FINAL markdown that would
otherwise be rendered. If any forbidden phrase is found, exit code 2 and the
render is aborted with a remediation list.

Why this exists
---------------
Circulation-quality outputs should:
  - never contain pre-draft scaffolding (Bias Pre-Commitment block, PENDING
    placeholders, "Sub-agent X fills" markers)
  - never use analyst-named labels — circulation
    copies use neutral institutional labels ("Recommended Action")
  - never reproduce internal pre-print rows in a post-print deliverable
    ("Pre-Print Decision (from preview)", "Earnings Preview Score" row in
    digest header — those belong only in the preview output, not the digest)
  - never carry version-history breadcrumbs ("from V10 preview", "the prior
    draft", "earlier framing")
  - never include first-person process commentary ("Going in I'm leaning…",
    "I'm at risk of confirmation bias…")
  - never include footer/metadata commentary ("End of Stage 1…", "Audit
    metadata", "Template Usage Notes — REMOVE BEFORE RENDERING")
  - never carry analyst-name placeholders awaiting human fill
  - never carry HTML/markdown comments that say "REMOVE BEFORE RENDERING"

Failure mode: previously, outputs reached circulation with these artifacts.
This gate is the deterministic backstop.

Usage
-----
    # Direct CLI:
    python3 production_ready_check.py path/to/digest.md
    python3 production_ready_check.py path/to/digest.md --strict
    python3 production_ready_check.py path/to/digest.md --json out.json

    # Programmatic:
    from production_ready_check import check_markdown
    result = check_markdown(open("digest.md").read())
    if not result["pass"]:
        sys.exit(2)

Exit codes
----------
    0 — clean (production-ready)
    2 — failed (at least one forbidden phrase / structural issue found)
    3 — file not found
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Forbidden patterns — every match HALTS the render
# ─────────────────────────────────────────────────────────────────────────────
# Each entry: { id, name, pattern (compiled regex), severity (always "fail"),
# fix (remediation guidance shown to operator) }

FORBIDDEN_PATTERNS = [
    # ── Bias pre-commitment scaffolding ────────────────────────────────────
    {
        "id": "PR-01",
        "name": "bias_pre_commitment_section",
        "pattern": re.compile(
            r"^#{1,4}\s+Bias Pre-?Commitment\b",
            re.IGNORECASE | re.MULTILINE,
        ),
        "fix": (
            "Remove the 'Bias Pre-Commitment' section. Pre-commitment is an "
            "internal pre-flight artifact and should live in synthesis/ work files, "
            "not in the circulation deliverable."
        ),
    },
    {
        "id": "PR-02",
        "name": "first_person_pre_commitment_language",
        "pattern": re.compile(
            r"\b(?:Going in I['’]m leaning|I['’]m at risk of "
            r"(?:confirmation|anchoring|recency) bias|"
            r"Pre-commit horizon|post-hoc rewrites? (?:of this section )?are? forbidden|"
            r"Post-extraction audit of (?:my )?pre-commitment)\b",
            re.IGNORECASE,
        ),
        "fix": (
            "Remove first-person pre-commitment language. State the conclusion "
            "directly without 'going in I'm leaning X' framing."
        ),
    },
    # ── Analyst-named action labels ────────────────────────────────────────
    {
        "id": "PR-03",
        "name": "analyst_named_action_label",
        # Flag any person-named action label (e.g. "<Name>'s AI Bot Call");
        # circulation deliverables use the neutral "Recommended Action".
        "pattern": re.compile(
            r"[A-Z][a-z]+['’]s AI Bot Call|AI Bot Call",
            re.IGNORECASE,
        ),
        "fix": (
            "Replace any analyst-named action label with 'Recommended Action'. "
            "Circulation deliverables use neutral institutional labels."
        ),
    },
    # ── Pre-print framing in post-print digest header ──────────────────────
    {
        "id": "PR-04",
        "name": "pre_print_decision_row_in_digest",
        "pattern": re.compile(
            r"\bPre-?Print Decision\s*\((?:from\s+(?:the\s+)?preview)?\)?",
            re.IGNORECASE,
        ),
        "fix": (
            "Remove the 'Pre-Print Decision (from preview)' row from the digest "
            "decision header. That field belongs in the preview output, not the "
            "post-print digest. The digest header uses Recommended Action + "
            "Headline Read + Day-of-Trade Triggers + Preferred Structure."
        ),
    },
    {
        "id": "PR-05",
        "name": "earnings_preview_score_row_in_digest",
        "pattern": re.compile(
            r"<td>\s*<strong>\s*Earnings Preview Score\s*</strong>\s*</td>|"
            r"\|\s*\*\*Earnings Preview Score\*\*\s*\|",
            re.IGNORECASE,
        ),
        "fix": (
            "Remove the 'Earnings Preview Score' row from the digest decision "
            "header. That score is a preview-output field and should not be "
            "reproduced in the post-print digest deliverable."
        ),
    },
    # ── Scaffolding placeholders that should never reach final ─────────────
    {
        "id": "PR-06",
        "name": "pending_subagent_placeholder",
        "pattern": re.compile(
            r"\[PENDING\b|PENDING\s*—\s*Sub-agent|<!--\s*LLM_FILL\b|"
            r"<!--\s*PENDING\b|TBD by Sub-agent|TBD per Sub-agent",
            re.IGNORECASE,
        ),
        "fix": (
            "Replace all [PENDING] / LLM_FILL / Sub-agent placeholders with "
            "actual content. If a section cannot be filled, omit it entirely; "
            "do not deliver scaffolding."
        ),
    },
    {
        "id": "PR-07",
        "name": "analyst_name_placeholder",
        # Catch residual fill-me placeholders awaiting human input, e.g.
        # "[user — pending size]" / "user pending" / "per user".
        "pattern": re.compile(
            r"\[user\s*—|\[user\s+pending\]|\[user\s+will\b|\[user\s+to\b|"
            r"\buser\s+pending\b|\buser\s+to\s+confirm\b|\bper\s+user\b",
            re.IGNORECASE,
        ),
        "fix": (
            "Remove analyst-name placeholders awaiting human fill. Either fill "
            "in the value or omit the line. Circulation copies do not name "
            "internal analysts."
        ),
    },
    # ── Internal version-history breadcrumbs ───────────────────────────────
    {
        "id": "PR-08",
        "name": "internal_version_reference",
        "pattern": re.compile(
            r"\b(?:from|since|than|vs|in)\s+V\d+\s+(?:preview|draft|note)\b|"
            r"\bV\d+\s+(?:was|had|missed|caught|said)\b|"
            r"\b(?:the\s+)?prior\s+(?:version|draft)\b|"
            r"\b(?:previous|earlier)\s+(?:version|iteration|draft)\s+of\s+(?:this|the)\b|"
            r"\bcompared\s+to\s+V\d+\b",
            re.IGNORECASE,
        ),
        "fix": (
            "Drop internal version history breadcrumbs. Circulation copies are "
            "self-contained and do not reference prior iteration drafts."
        ),
    },
    # ── Stage / footer / process commentary ────────────────────────────────
    {
        "id": "PR-09",
        "name": "stage_footer_commentary",
        "pattern": re.compile(
            r"\*?End of Stage [12]\b|"
            r"Stage 2 \(post-call transcript-integrated\) will compute|"
            r"^#{1,4}\s+Audit metadata\b|"
            r"^#{1,4}\s+Template Usage Notes\b|"
            r"REMOVE BEFORE RENDERING|"
            r"\*?Stage 1 of the digest is the preliminary",
            re.IGNORECASE | re.MULTILINE,
        ),
        "fix": (
            "Remove stage / process commentary footers ('End of Stage 1…', "
            "'Audit metadata', 'Template Usage Notes — REMOVE BEFORE RENDERING'). "
            "These are internal build artifacts."
        ),
    },
    # ── PRESTAGED naming or pre-staged file references ─────────────────────
    {
        "id": "PR-10",
        "name": "prestaged_reference",
        "pattern": re.compile(
            r"PRESTAGED|pre-?staged\s+(?:skeleton|digest|preview|file|template)",
            re.IGNORECASE,
        ),
        "fix": (
            "Remove references to 'PRESTAGED' or 'pre-staged' files. "
            "These are internal scaffolding artifacts; the final deliverable "
            "should not reference them."
        ),
    },
    # ── HTML/markdown comment blocks that explicitly say "internal" ────────
    {
        "id": "PR-12",
        "name": "internal_comment_leakage",
        "pattern": re.compile(
            r"<!--\s*(?:INTERNAL|FORMATTING NOTE|TEMPLATE NOTE|"
            r"NEVER RENDER|REMOVE BEFORE)",
            re.IGNORECASE,
        ),
        "fix": (
            "Internal HTML comments are fine in the template source but must "
            "be stripped from the rendered output. The renderer should drop "
            "<!-- INTERNAL --> blocks before pandoc."
        ),
    },
    # ── Self-referential drafting / synthesis commentary ───────────────────
    {
        "id": "PR-13",
        "name": "drafting_self_reference",
        "pattern": re.compile(
            r"\b(?:my\s+(?:earlier|prior)\s+(?:framing|read|take|analysis)|"
            r"the\s+(?:prior|earlier)\s+(?:framing|interpretation|read)|"
            r"as\s+(?:I|the\s+agent)\s+(?:wrote|noted|said)\s+(?:above|earlier|before)|"
            r"in\s+my\s+(?:initial|first|previous)\s+draft)\b",
            re.IGNORECASE,
        ),
        "fix": (
            "Remove self-referential commentary about drafting process or "
            "prior framings. The deliverable should read like a finished "
            "research note, not a workshop transcript."
        ),
    },
    # ── Performative / sell-side jargon (from style_linter L-03/L-04) ──────
    {
        "id": "PR-14",
        "name": "risk_symmetry_jargon",
        "pattern": re.compile(
            r"\b(?:risk\s+symmetry|asymmetric\s+right\s+vs\s+left|"
            r"asymmetric\s+left\s+vs\s+right)\b",
            re.IGNORECASE,
        ),
        "fix": (
            "Drop 'risk symmetry / asymmetric right vs left' jargon. State "
            "the directional asymmetry with specific quantification instead."
        ),
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Cross-document consistency checks
# ─────────────────────────────────────────────────────────────────────────────
# These look at the WHOLE document, not per-line. Specifically detect logical
# contradictions that pure forbidden-phrase regex cannot catch.

HIGH_CONVICTION_RE = re.compile(
    r"\bHIGH\b\s*(?:conviction|confidence)|"
    r"\bconviction:\s*HIGH|\bconfidence:\s*HIGH",
    re.IGNORECASE,
)

SIZING_RESTRAINT_RE = re.compile(
    r"\bdo\s*NOT\s*size\s*up\b|"
    r"\bdo\s*NOT\s*add\b|"
    r"\bdon['’]t\s*size\s*up\b|"
    r"\bhold\s+and\s+wait\b|"
    r"\bhold\s+off\b|"
    r"\bavoid\s+adding\b|"
    r"\bdo\s*NOT\s*chase\b",
    re.IGNORECASE,
)

# PR-16: direction-label inversion check.
# A "bull-friendly variable" paired with a "got better" verb in close
# proximity is a likely inversion error in a bearish digest context.
# "Bull-friendly variable" = something where higher = better for the company
# (achievability, attainability, execution, credibility, retention quality).
# "Got better" verbs = STRENGTHENED, IMPROVED, ENHANCED.
# A pairing like "achievability STRENGTHENED" almost always indicates the
# author meant "achievability WEAKENED" (or "bear thesis STRENGTHENED").
# This rule has false positives — sometimes achievability really does
# strengthen — so it's a WARN-level flag intended to force a polarity check,
# not a hard FAIL. The fix the operator should apply: rewrite with explicit
# claim polarity.
BULL_VARIABLE_INVERSION_RE = re.compile(
    r"\b(?:achievability|attainability|guide\s+attain|execution\s+credibility|"
    r"management\s+credibility|retention\s+quality)\b"
    r"[^.\n]{0,80}"
    r"\b(?:STRENGTHENED|IMPROVED\s+MATERIALLY|ENHANCED\s+MATERIALLY|"
    r"MATERIALLY\s+(?:STRENGTHENED|IMPROVED|ENHANCED))\b",
    re.IGNORECASE,
)
# Symmetric form (verb before noun).
BULL_VARIABLE_INVERSION_REV_RE = re.compile(
    r"\b(?:STRENGTHENED|IMPROVED\s+MATERIALLY|ENHANCED\s+MATERIALLY)\b"
    r"[^.\n]{0,80}"
    r"\b(?:achievability|attainability|guide\s+attain|execution\s+credibility|"
    r"management\s+credibility|retention\s+quality)\b",
    re.IGNORECASE,
)


_TIER_RE = re.compile(
    r"tier\s*([1-4])\s*(?:entry\s*)?[:\-—–]?\s*[^.\n$]*?"
    r"\$?(\d{1,4})\s*[-–]\s*\$?(\d{1,4})",
    re.IGNORECASE,
)

_SIZING_ACTION_PRICE_RE = re.compile(
    r"(SIZE\s*UP|RE-?SHORT|ADD)\b[^.\n]{0,80}"
    r"\$(\d{1,4})\s*[-–]\s*\$?(\d{1,4})",
    re.IGNORECASE,
)


def check_sizing_price_consistency(text: str) -> list[dict]:
    """PR-17: extract tier ladder from the document; verify any other
    size-up / add / re-short price range falls within the ladder.

    Failure mode caught: a stale price range from a prior version of the
    digest (e.g., 'SIZE UP into $32-35') co-existing with the current
    framework's tier ladder (e.g., 'Tier 1 $27-29; Tier 2 $30-33; Tier 3
    $34-37'). The stale range crosses tier boundaries and contradicts the
    canonical ladder.

    Logic:
    1. Scan for 'tier N: $X-$Y' patterns to build the canonical ladder.
    2. Scan for 'SIZE UP / ADD / RE-SHORT ... $X-$Y' patterns.
    3. Each action-price-range must fall within at least one tier of the
       canonical ladder. If not, flag.

    Returns a list of violation dicts.
    """
    # Build tier ladder
    tiers = {}
    for m in _TIER_RE.finditer(text):
        try:
            tier_num = int(m.group(1))
            lo = int(m.group(2))
            hi = int(m.group(3))
            if lo > hi:
                lo, hi = hi, lo
            tiers[tier_num] = (lo, hi)
        except (ValueError, IndexError):
            continue

    # If no tier ladder defined, can't check
    if not tiers:
        return []

    lines = text.splitlines()
    violations = []
    seen_match_keys = set()

    for m in _SIZING_ACTION_PRICE_RE.finditer(text):
        action_word = m.group(1)
        try:
            lo = int(m.group(2))
            hi = int(m.group(3))
            if lo > hi:
                lo, hi = hi, lo
        except (ValueError, IndexError):
            continue

        # Skip if this matches a known tier exactly (within ±$1 tolerance)
        in_tier = False
        for t_lo, t_hi in tiers.values():
            if t_lo - 1 <= lo and hi <= t_hi + 1:
                in_tier = True
                break

        if in_tier:
            continue

        # Check: does this range cross tier boundaries OR sit entirely outside?
        line_no = text[: m.start()].count("\n") + 1
        key = (line_no, lo, hi)
        if key in seen_match_keys:
            continue
        seen_match_keys.add(key)

        excerpt = lines[line_no - 1].strip() if line_no - 1 < len(lines) else ""
        tier_summary = ", ".join(
            f"Tier {n}: ${t_lo}-${t_hi}" for n, (t_lo, t_hi) in sorted(tiers.items())
        )
        violations.append(
            {
                "id": "PR-17",
                "name": "sizing_price_inconsistent_with_tier_ladder",
                "line": line_no,
                "matched": m.group(0)[:160],
                "excerpt": excerpt[:200],
                "fix": (
                    f"Price range ${lo}-${hi} in '{action_word}' context does "
                    f"not match the tier ladder defined elsewhere in the "
                    f"document ({tier_summary}). Likely a stale price reference "
                    f"from a prior digest version. Update to the current tier "
                    f"pricing, or revise the tier ladder if the framework has "
                    f"changed. Sizing references "
                    f"across sections must agree."
                ),
            }
        )

    return violations


def check_direction_label_inversion(text: str) -> list[dict]:
    """PR-16: detect 'bull-friendly variable + got-better verb' pairings that
    are likely direction-label inversions.

    The specific failure mode: writing 'achievability STRENGTHENED' when meaning
    'bear thesis STRENGTHENED' (or equivalently 'achievability WEAKENED'). The
    grammar parses but the polarity inverts.

    Returns a list of violation dicts (possibly empty).
    """
    lines = text.splitlines()
    violations = []
    for pattern_idx, pattern in enumerate(
        (BULL_VARIABLE_INVERSION_RE, BULL_VARIABLE_INVERSION_REV_RE)
    ):
        for m in pattern.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            excerpt = lines[line_no - 1].strip() if line_no - 1 < len(lines) else ""
            violations.append(
                {
                    "id": "PR-16",
                    "name": "direction_label_inversion",
                    "line": line_no,
                    "matched": m.group(0)[:160],
                    "excerpt": excerpt[:200],
                    "fix": (
                        "Likely direction-label inversion. A bull-friendly "
                        "variable (achievability, attainability, execution "
                        "credibility) paired with a 'got better' verb "
                        "(STRENGTHENED, IMPROVED, ENHANCED) almost always "
                        "means the author intended the OPPOSITE direction "
                        "(e.g., 'achievability WEAKENED' or 'bear thesis "
                        "STRENGTHENED'). Rewrite with explicit claim polarity. "
                        "If the pairing is correct (bull-friendly news in a "
                        "bullish context), rephrase as 'bull thesis "
                        "STRENGTHENED' or similar to remove ambiguity."
                    ),
                }
            )
    return violations


def check_sizing_conviction_consistency(text: str) -> list[dict]:
    """Detect contradictions between HIGH conviction language and sizing
    restraint language elsewhere in the document.

    A HIGH-conviction multi-quarter thesis paired with "do not size up" is
    internally contradictory in most cases. If both phrasings appear, flag
    for analyst review.

    Returns a list of violation dicts (possibly empty).
    """
    high_conv_matches = list(HIGH_CONVICTION_RE.finditer(text))
    sizing_matches = list(SIZING_RESTRAINT_RE.finditer(text))

    if not (high_conv_matches and sizing_matches):
        return []

    violations = []
    for hc in high_conv_matches:
        hc_line = text[: hc.start()].count("\n") + 1
        for sr in sizing_matches:
            sr_line = text[: sr.start()].count("\n") + 1
            # Within 100 lines = same broad section; flag as contradiction
            if abs(sr_line - hc_line) <= 100:
                violations.append(
                    {
                        "id": "PR-15",
                        "name": "sizing_conviction_contradiction",
                        "line": min(hc_line, sr_line),
                        "matched": (
                            f"HIGH conviction at L{hc_line} ({hc.group(0)!r}) + "
                            f"sizing restraint at L{sr_line} ({sr.group(0)!r})"
                        ),
                        "excerpt": text.splitlines()[min(hc_line, sr_line) - 1].strip()[:200],
                        "fix": (
                            "HIGH conviction on a multi-quarter thesis is "
                            "logically inconsistent with sizing restraint "
                            "language ('do not size up,' 'do not add'). Either "
                            "revise the conviction language down (e.g., MEDIUM) "
                            "or revise the sizing posture up (e.g., 'SIZE UP on "
                            "pops,' 'ADD on weakness'). Sizing "
                            "posture must derive from conviction posture."
                        ),
                    }
                )
                break  # only flag once per HIGH conviction instance
    return violations


# ─────────────────────────────────────────────────────────────────────────────
# Per-line scanner
# ─────────────────────────────────────────────────────────────────────────────

def check_markdown(text: str) -> dict:
    """Scan markdown for production-ready violations.

    Returns:
        {
          "pass": bool,
          "violations": [
            {"id", "name", "line", "matched", "excerpt", "fix"}, ...
          ],
          "violation_count": int,
        }
    """
    violations = []
    lines = text.splitlines()

    # Multi-line patterns (MULTILINE flag) — search whole text
    for rule in FORBIDDEN_PATTERNS:
        pat = rule["pattern"]
        if pat.flags & re.MULTILINE:
            for m in pat.finditer(text):
                # Compute line number from match start offset
                line_no = text[: m.start()].count("\n") + 1
                excerpt = lines[line_no - 1].strip() if line_no - 1 < len(lines) else ""
                violations.append(
                    {
                        "id": rule["id"],
                        "name": rule["name"],
                        "line": line_no,
                        "matched": m.group(0)[:120],
                        "excerpt": excerpt[:200],
                        "fix": rule["fix"],
                    }
                )

    # Single-line patterns — scan line by line for context
    for line_no, line in enumerate(lines, start=1):
        for rule in FORBIDDEN_PATTERNS:
            pat = rule["pattern"]
            if pat.flags & re.MULTILINE:
                continue  # already handled above
            for m in pat.finditer(line):
                violations.append(
                    {
                        "id": rule["id"],
                        "name": rule["name"],
                        "line": line_no,
                        "matched": m.group(0)[:120],
                        "excerpt": line.strip()[:200],
                        "fix": rule["fix"],
                    }
                )

    # Cross-document consistency check (PR-15): sizing-conviction contradiction
    violations.extend(check_sizing_conviction_consistency(text))

    # Semantic check (PR-16): direction-label inversion (e.g., "achievability
    # STRENGTHENED" in a bear context — likely meant "WEAKENED")
    violations.extend(check_direction_label_inversion(text))

    # Cross-document consistency check (PR-17): sizing price ranges across
    # sections must agree with the canonical tier ladder
    violations.extend(check_sizing_price_consistency(text))

    # De-duplicate (same id + same line)
    seen = set()
    unique = []
    for v in violations:
        key = (v["id"], v["line"], v["matched"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(v)

    return {
        "pass": len(unique) == 0,
        "violations": unique,
        "violation_count": len(unique),
    }


def check_file(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {
            "pass": False,
            "error": f"file not found: {path}",
            "violations": [],
            "violation_count": 0,
        }
    text = p.read_text(encoding="utf-8", errors="replace")
    result = check_markdown(text)
    result["input_path"] = str(p)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Production-readiness gate for digest / preview markdown. "
            "Halts the render pipeline if forbidden phrases or scaffolding "
            "placeholders are present."
        )
    )
    ap.add_argument("markdown_path", help="Path to the markdown file to check")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero even on de-minimis warnings (default: only on fails).",
    )
    ap.add_argument(
        "--json",
        default=None,
        help="Optional path to write JSON result for downstream tooling.",
    )
    ap.add_argument(
        "--quiet", action="store_true", help="Suppress text output; exit code only."
    )
    args = ap.parse_args(argv)

    result = check_file(args.markdown_path)

    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2), encoding="utf-8")

    if "error" in result:
        if not args.quiet:
            print(f"[error] {result['error']}", file=sys.stderr)
        return 3

    if not args.quiet:
        status = "PASS" if result["pass"] else "FAIL"
        print(f"=== production_ready_check ===")
        print(f"Input: {result['input_path']}")
        print(f"Status: {status}")
        print(f"Violations: {result['violation_count']}")
        if not result["pass"]:
            print()
            print("--- Violations ---")
            for v in result["violations"]:
                print(f"  L{v['line']} [{v['id']}] {v['name']}: {v['matched']!r}")
                print(f"    fix: {v['fix']}")
            print()
            print(
                "Render aborted. Remediate every violation above before re-running."
            )

    return 0 if result["pass"] else 2


if __name__ == "__main__":
    sys.exit(_cli())
