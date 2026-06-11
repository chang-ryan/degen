"""Smoke tests for production_ready_check.py.

This is the deterministic build gate that halts the render pipeline when
internal scaffolding, first-person pre-commitment, analyst-named action
labels, or pre-print framing reach what would otherwise be a circulation
deliverable.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make production_ready_check importable from the package root
PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

from production_ready_check import check_markdown  # noqa: E402


def _matched_ids(violations):
    return {v["id"] for v in violations}


def test_clean_digest_passes():
    """A circulation-quality digest body should produce zero violations."""
    clean = """\
# ACME — C1Q26 Print Digest

**Print:** Mon 5/11/26 AMC, 4:05pm ET release | **Call:** 5:00pm ET

<table class="decision-table">
<tr><th>Field</th><th>Value</th></tr>
<tr><td><strong>Recommended Action</strong></td><td><strong>HOLD</strong> — rationale.</td></tr>
<tr><td><strong>Headline Read</strong></td><td><strong>One line summary.</strong></td></tr>
<tr><td><strong>Day-of-Trade Triggers</strong></td><td>One line.</td></tr>
<tr><td><strong>Preferred Structure</strong></td><td>One line.</td></tr>
</table>

## Synthesis

Story paragraph with substantive content. *[STATED]*

## Beat/Miss Scorecard

| Metric | Actual | Cons |
|---|---|---|
| Revenue | 100 | 99 |
"""
    result = check_markdown(clean)
    assert result["pass"] is True, result["violations"]
    assert result["violation_count"] == 0


def test_bias_pre_commitment_block_blocks():
    md = "## Bias Pre-Commitment (pre-draft)\n\nGoing in I'm leaning bullish.\n"
    result = check_markdown(md)
    assert result["pass"] is False
    ids = _matched_ids(result["violations"])
    assert "PR-01" in ids
    assert "PR-02" in ids


def test_wesley_ai_bot_call_blocks():
    md = "<strong>Wesley's AI Bot Call: HOLD</strong> — rationale.\n"
    result = check_markdown(md)
    assert result["pass"] is False
    assert "PR-03" in _matched_ids(result["violations"])


def test_pre_print_decision_row_blocks():
    md = "| Pre-Print Decision (from preview) | analyst |\n"
    result = check_markdown(md)
    assert result["pass"] is False
    assert "PR-04" in _matched_ids(result["violations"])


def test_earnings_preview_score_row_in_digest_blocks():
    md = (
        "<tr><td><strong>Earnings Preview Score</strong></td>"
        "<td>3</td></tr>\n"
    )
    result = check_markdown(md)
    assert result["pass"] is False
    assert "PR-05" in _matched_ids(result["violations"])


def test_pending_placeholder_blocks():
    md = "Some content [PENDING — Sub-agent A fills] more content.\n"
    result = check_markdown(md)
    assert result["pass"] is False
    assert "PR-06" in _matched_ids(result["violations"])


def test_analyst_name_placeholder_blocks():
    md = "Position: [user — pending size] / 100k shares.\n"
    result = check_markdown(md)
    assert result["pass"] is False
    assert "PR-07" in _matched_ids(result["violations"])


def test_internal_version_reference_blocks():
    md = "From V10 preview, the day-of binary was volumes.\n"
    result = check_markdown(md)
    assert result["pass"] is False
    assert "PR-08" in _matched_ids(result["violations"])


def test_stage_footer_blocks():
    md = "*End of Stage 1. Stage 2 will compute deltas after the call.*\n"
    result = check_markdown(md)
    assert result["pass"] is False
    assert "PR-09" in _matched_ids(result["violations"])


def test_audit_metadata_header_blocks():
    md = "## Audit metadata\n\n- digest_baseline.json path: ...\n"
    result = check_markdown(md)
    assert result["pass"] is False
    assert "PR-09" in _matched_ids(result["violations"])


def test_prestaged_reference_blocks():
    md = "See the PRESTAGED skeleton at outputs/foo_PRESTAGED.md.\n"
    result = check_markdown(md)
    assert result["pass"] is False
    assert "PR-10" in _matched_ids(result["violations"])


def test_drafting_self_reference_blocks():
    md = "As I wrote above, the bear thesis is intact.\n"
    result = check_markdown(md)
    assert result["pass"] is False
    assert "PR-13" in _matched_ids(result["violations"])


def test_risk_symmetry_jargon_blocks():
    md = "Risk symmetry: asymmetric right vs left on this setup.\n"
    result = check_markdown(md)
    assert result["pass"] is False
    assert "PR-14" in _matched_ids(result["violations"])


def test_violation_includes_fix_field():
    """Every violation must include a remediation hint for the operator."""
    md = "## Bias Pre-Commitment\n"
    result = check_markdown(md)
    assert result["violations"], "expected a violation"
    for v in result["violations"]:
        assert v.get("fix"), f"violation {v['id']} missing fix"
        assert v.get("line"), f"violation {v['id']} missing line"


def test_sizing_conviction_contradiction_blocks():
    """PR-15: HIGH conviction + sizing restraint in same doc is a contradiction."""
    md = """
## Recommended Action
HOLD existing short; do NOT size up on squeeze pop.

## Confidence
HIGH conviction on FY 26 EBITDA below new guide LOW.
"""
    result = check_markdown(md)
    assert result["pass"] is False
    ids = _matched_ids(result["violations"])
    assert "PR-15" in ids


def test_consistent_high_conviction_with_add_passes():
    """HIGH conviction paired with ADD posture should pass."""
    md = """
## Recommended Action
SIZE UP on squeeze pops into $32-35.

## Confidence
HIGH conviction on FY 26 EBITDA below new guide LOW. Multi-quarter horizon.
"""
    result = check_markdown(md)
    # Should not flag PR-15
    ids = _matched_ids(result["violations"])
    assert "PR-15" not in ids


def test_medium_conviction_with_hold_passes():
    """MEDIUM conviction + hold is internally consistent — no flag."""
    md = """
## Recommended Action
HOLD existing short; do NOT size up.

## Confidence
MEDIUM conviction on the thesis. Awaiting Q2 print before committing.
"""
    result = check_markdown(md)
    ids = _matched_ids(result["violations"])
    assert "PR-15" not in ids


def test_achievability_strengthened_inversion_blocks():
    """PR-16: 'achievability STRENGTHENED' is the literal error pattern that
    triggered the original failure. Must be flagged."""
    md = "- FY 26 EBITDA achievability via the implied 2H bridge: STRENGTHENED MATERIALLY"
    result = check_markdown(md)
    assert result["pass"] is False
    ids = _matched_ids(result["violations"])
    assert "PR-16" in ids


def test_attainability_improved_blocks():
    """PR-16: variant — 'attainability MATERIALLY IMPROVED' same pattern."""
    md = "Guide attainability MATERIALLY IMPROVED on the 2H bridge math."
    result = check_markdown(md)
    assert result["pass"] is False
    ids = _matched_ids(result["violations"])
    assert "PR-16" in ids


def test_bear_thesis_strengthened_passes():
    """The CORRECT phrasing — 'bear thesis STRENGTHENED' is unambiguous and
    should not trigger PR-16."""
    md = "Bear thesis on FY 26 EBITDA: STRENGTHENED MATERIALLY"
    result = check_markdown(md)
    ids = _matched_ids(result["violations"])
    assert "PR-16" not in ids


def test_achievability_weakened_passes():
    """The OTHER correct phrasing — 'achievability WEAKENED' is grammatically
    consistent (achievability got worse = bull-unfriendly = bear-friendly in
    intent). Should not trigger PR-16."""
    md = "FY 26 EBITDA achievability: WEAKENED MATERIALLY"
    result = check_markdown(md)
    ids = _matched_ids(result["violations"])
    assert "PR-16" not in ids


def test_reverse_order_inversion_also_blocks():
    """PR-16 reverse pattern: verb before noun. 'STRENGTHENED on
    achievability' — same likely inversion."""
    md = "The print MATERIALLY STRENGTHENED our read on guide attainability."
    result = check_markdown(md)
    ids = _matched_ids(result["violations"])
    assert "PR-16" in ids


def test_sizing_price_inconsistent_with_tier_ladder_blocks():
    """PR-17: 'SIZE UP into $32-35' co-existing with 'Tier 1 entry $27-29'
    in the same doc is the literal failure pattern that occurred. Must be
    flagged."""
    md = """
## Recommended Action
SIZE UP toward target weight; Tier 1 entry $27-29 per the position sizing framework.
Tier 2 entry $30-33. Tier 3 entry $34-37.

## Delta vs Stage 1
**Action: SIZE UP on squeeze pops into $32-35.** Trade thesis intact.
"""
    result = check_markdown(md)
    assert result["pass"] is False
    ids = _matched_ids(result["violations"])
    assert "PR-17" in ids


def test_sizing_price_consistent_with_tier_ladder_passes():
    """PR-17 negative case: all sizing price refs match the tier ladder."""
    md = """
## Recommended Action
SIZE UP toward target weight; Tier 1 entry $27-29.
Tier 2 entry $30-33. Tier 3 entry $34-37.

## Delta vs Stage 1
Tier 1 add at $27-29 is the entry zone per the sizing framework.
"""
    result = check_markdown(md)
    ids = _matched_ids(result["violations"])
    assert "PR-17" not in ids


def test_sizing_without_tier_ladder_passes():
    """PR-17: if no tier ladder is defined, can't check; should pass."""
    md = """
## Recommended Action
ADD on weakness toward target weight in the $27-29 range.
"""
    result = check_markdown(md)
    ids = _matched_ids(result["violations"])
    assert "PR-17" not in ids


def test_sizing_price_within_one_dollar_tolerance_passes():
    """PR-17: ±$1 tolerance — minor rounding differences should not flag."""
    md = """
## Recommended Action
Tier 1 entry $27-29. Tier 2 entry $30-33. Tier 3 entry $34-37.

## Action box
SIZE UP at $28-29 entry (within Tier 1 band).
"""
    result = check_markdown(md)
    ids = _matched_ids(result["violations"])
    assert "PR-17" not in ids
