"""
Test cases for the arithmetic consistency gate.

These tests use the actual error patterns from HROW C1Q26 (and the corrected
versions) to verify the gate catches the failure class.

Failure class: derivation errors — i.e., the digest cites a computed value
that does not match the arithmetic of the inputs given in the same sentence
or in nearby calculation persistence blocks.

Real-world examples that escaped the existing audit:
  1. HROW C1Q26 Stage 1: "$52.2M, still -1.4% YoY vs Q1'25 $47.8M"
     Actual: 52.2 / 47.8 - 1 = +9.14%, not -1.4%
  2. HROW C1Q26 Stage 1: "net debt $197M / TTM Adj EBITDA ~$56M = 3.5x"
     The 3.5x is correct for the inputs ($197/$56 = 3.52), but the
     denominator label is wrong (TTM was $45M; $56M is FY25).
     This is caught by the temporal-denominator-match gate, not pure
     arithmetic. Arithmetic alone would mark the 3.5x as PASS.
"""

from __future__ import annotations

import pytest

# Import would be: from baseline_audit import gate_arithmetic_consistency
# Placeholder until gate is moved into baseline_audit.py


# ─────────────────────────────────────────────────────────────────
# Arithmetic gate — pattern detection + recomputation
# ─────────────────────────────────────────────────────────────────


CASES_ARITHMETIC_FAIL = [
    # The actual HROW error: sign and magnitude both wrong
    pytest.param(
        "Adjusting for the $8M VEVYE GTN charge brings Q1 to $52.2M, "
        "still -1.4% YoY vs Q1'25 $47.8M",
        "yoy_pct_mismatch",
        id="hrow_normalized_yoy_inverted",
    ),
    # Wrong-sign percentage
    pytest.param(
        "Revenue grew to $120M from $100M, up -20% YoY.",
        "yoy_pct_mismatch",
        id="yoy_sign_inverted",
    ),
    # Wrong arithmetic in margin computation
    pytest.param(
        "Gross profit was $27M on revenue of $44.2M, a gross margin of 75%.",
        "margin_pct_mismatch",
        id="gm_pct_wrong",
    ),
    # Wrong sum
    pytest.param(
        "VEVYE $20.9M + IHEEZO $1.9M + Other $21.4M = total $40M",
        "sum_mismatch",
        id="sum_wrong",
    ),
]


CASES_ARITHMETIC_PASS = [
    # Correct YoY math with sources
    pytest.param(
        "Adjusting for the $8M VEVYE GTN charge brings Q1 to $52.2M, "
        "+9.1% YoY vs Q1'25 $47.8M ($52.2 / $47.8 - 1 = +9.1%)",
        id="hrow_normalized_yoy_correct",
    ),
    # Correct margin
    pytest.param(
        "Gross profit was $27.045M on revenue of $44.203M, a gross margin of 61%.",
        id="gm_pct_correct",
    ),
    # Correct sum
    pytest.param(
        "VEVYE $20.9M + IHEEZO $1.9M + Other branded $7.8M + ImprimisRx $13.5M "
        "+ Other revenues $0.1M = total $44.2M",
        id="sum_correct",
    ),
]


@pytest.mark.parametrize("text,expected_violation", CASES_ARITHMETIC_FAIL)
def test_gate_arithmetic_consistency_catches_errors(text, expected_violation):
    """Gate should flag derived percentage/margin/sum claims that don't reconcile."""
    pytest.skip("gate_arithmetic_consistency not yet implemented in baseline_audit.py")


@pytest.mark.parametrize("text", CASES_ARITHMETIC_PASS)
def test_gate_arithmetic_consistency_passes_correct(text):
    """Gate should not flag correctly-stated arithmetic."""
    pytest.skip("gate_arithmetic_consistency not yet implemented in baseline_audit.py")


# ─────────────────────────────────────────────────────────────────
# Temporal denominator match gate
# ─────────────────────────────────────────────────────────────────


CASES_TEMPORAL_FAIL = [
    # The actual HROW error
    pytest.param(
        "net debt $197M / TTM Adj EBITDA ~$56M = 3.5x",
        # ... where the manifest has TTM Adj EBITDA = $45M, FY25 = $56M.
        # The 3.5x arithmetic checks out; the label "TTM" is wrong.
        "ttm_denominator_mismatch",
        id="hrow_ttm_label_wrong",
    ),
    # NTM mislabel
    pytest.param(
        "EV/NTM Sales of 1.2x using $350M NTM revenue",
        # Manifest has NTM Sales = $400M; $350M was FY26 consensus, not NTM.
        "ntm_denominator_mismatch",
        id="ntm_denominator_uses_fy_value",
    ),
]


@pytest.mark.parametrize("text,expected_violation", CASES_TEMPORAL_FAIL)
def test_gate_temporal_denominator_match(text, expected_violation):
    pytest.skip("gate_temporal_denominator_match not yet implemented")


# ─────────────────────────────────────────────────────────────────
# Source citation validity gate
# ─────────────────────────────────────────────────────────────────


CASES_SOURCE_CITATION_FAIL = [
    # The actual HROW error
    pytest.param(
        "Exhibit 99.3 Corporate Presentation",
        # Manifest shows 8-K filed only Exhibits 99.1 and 99.2.
        "exhibit_not_in_manifest",
        id="hrow_phantom_exhibit_993",
    ),
]


@pytest.mark.parametrize("text,expected_violation", CASES_SOURCE_CITATION_FAIL)
def test_gate_source_citation_valid(text, expected_violation):
    pytest.skip("gate_source_citation_valid not yet implemented")


# ─────────────────────────────────────────────────────────────────
# Cross-document derived-value consistency gate
# ─────────────────────────────────────────────────────────────────


def test_gate_cross_doc_consistency_iheezo_per_unit():
    """
    If Stage 1 digest derives IHEEZO per-unit as $41 and Stage 2 digest derives
    the same from the same inputs as $42, flag the inconsistency.

    Real-world example: chat response cited $42; Stage 1 PDF cited $41 (actual
    $1,851,000 / 45,509 = $40.67 ≈ $41).
    """
    pytest.skip("gate_cross_doc_consistency not yet implemented")


# ─────────────────────────────────────────────────────────────────
# Historical specificity gate
# ─────────────────────────────────────────────────────────────────


CASES_HISTORICAL_SPECIFIC_FAIL = [
    pytest.param(
        "This is the first meaningfully negative OCF quarter since Q3 2023",
        # No citation, no [INFERRED-UNVERIFIED] tag.
        "uncited_historical_specificity",
        id="hrow_first_since_q3_2023",
    ),
    pytest.param(
        "Gross margin has not been below 60% in five years",
        "uncited_historical_specificity",
        id="five_year_claim",
    ),
]


CASES_HISTORICAL_SPECIFIC_PASS = [
    pytest.param(
        "This is the first meaningfully negative OCF quarter in multiple "
        "quarters *[INFERRED-UNVERIFIED]*",
        id="historical_marked_unverified",
    ),
    pytest.param(
        "OCF was negative this quarter; prior-period comparison not pulled.",
        id="historical_avoided_when_unsourced",
    ),
]


@pytest.mark.parametrize("text,expected_violation", CASES_HISTORICAL_SPECIFIC_FAIL)
def test_gate_historical_specificity_catches_uncited(text, expected_violation):
    pytest.skip("gate_historical_specificity not yet implemented")


@pytest.mark.parametrize("text", CASES_HISTORICAL_SPECIFIC_PASS)
def test_gate_historical_specificity_passes_marked(text):
    pytest.skip("gate_historical_specificity not yet implemented")
