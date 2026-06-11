"""
Tests for the AUTO_GENERATE_CONFIG stage in preview_runner.

Covers:
  - Existing config → stage PASS-skips (never overwrites)
  - Missing business text → NEEDS_INPUT with dispatch_instructions
  - Business text present → generates config.yaml, PASSes
  - Generated config has _auto_generated: true, _analyst_reviewed: false
  - Stage advances next_stage = DEEP_READ on success
  - Stage ordering in STAGES
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import preview_runner as pr


@pytest.fixture
def fresh_runner(tmp_path, monkeypatch):
    """Build a runner instance for a brand-new ticker. No config exists."""
    monkeypatch.setattr(pr, "ticker_dir", lambda t: tmp_path / "workspace" / t.upper())
    monkeypatch.setattr(pr, "REFERENCE_BASE", tmp_path / "Reference Files")
    r = pr.PreviewRunner(ticker="ZZZZ", analyst="user", mode="symbiotic")
    # Create the ticker dir + filings dir so the stage can read/write inputs
    r.ticker_dir.mkdir(parents=True, exist_ok=True)
    r.filings_dir.mkdir(parents=True, exist_ok=True)
    return r


def _write_business_text(runner):
    """Populate the single seed input used by standalone_config_gen:
    the 10-K business description under filings/latest_10K_business.txt."""
    (runner.filings_dir / "latest_10K_business.txt").write_text(
        "Acme provides an enterprise software platform delivered as SaaS. "
        "Annual recurring revenue (ARR) and net retention drive growth. "
        "Billings provide visibility into future revenue. Software platform serves enterprises."
    )


# --- PASS-skip: existing config ---

def test_existing_config_is_not_overwritten(fresh_runner):
    fresh_runner.config_path.write_text("ticker: ZZZZ\nfiscal_period_in_focus: C1Q26\n")
    result = fresh_runner.stage_auto_generate_config()
    assert result.status == "PASS"
    assert result.next_stage == "DEEP_READ"
    assert "skipped" in result.metadata
    # File contents preserved
    assert "fiscal_period_in_focus: C1Q26" in fresh_runner.config_path.read_text()


# --- NEEDS_INPUT: no business text ---

def test_no_business_text_yields_needs_input(fresh_runner):
    result = fresh_runner.stage_auto_generate_config()
    assert result.status == "NEEDS_INPUT"
    assert result.next_stage is None  # NEEDS_INPUT halts the chain
    assert len(result.dispatch_instructions) == 1
    instr = result.dispatch_instructions[0]
    assert instr["type"] == "auto_generate_config_inputs"
    # Missing list points at the business-text seed file
    assert any("latest_10K_business" in m for m in instr["missing"])


def test_too_small_business_text_still_needs_input(fresh_runner):
    """A trivially short business file (<200 bytes) isn't enough to seed
    the generator."""
    (fresh_runner.filings_dir / "latest_10K_business.txt").write_text("tiny")
    result = fresh_runner.stage_auto_generate_config()
    assert result.status == "NEEDS_INPUT"


# --- PASS: business text present ---

def test_business_text_generates_config(fresh_runner):
    _write_business_text(fresh_runner)
    result = fresh_runner.stage_auto_generate_config()
    assert result.status == "PASS"
    assert result.next_stage == "DEEP_READ"
    # Config file written
    assert fresh_runner.config_path.exists()
    text = fresh_runner.config_path.read_text()
    # Auto-gen markers present
    assert "_auto_generated: true" in text.lower()
    assert "_analyst_reviewed: false" in text.lower()
    # Business class detected as software_saas (rich SaaS keywords in business text)
    assert "business_model_class: software_saas" in text


def test_generated_config_has_no_fiscal_period(fresh_runner):
    """The free build doesn't derive a fiscal period from a paid calendar
    feed — the analyst fills it into config.yaml. So preview_path stays
    UNKNOWN until a period is authored."""
    assert fresh_runner.preview_path.name == "UNKNOWN_PREVIEW.md"
    _write_business_text(fresh_runner)
    fresh_runner.stage_auto_generate_config()
    assert fresh_runner.preview_path.name == "UNKNOWN_PREVIEW.md"


# --- stage chain integration ---

def test_auto_discover_next_stage_is_auto_generate_config(fresh_runner):
    """Pipeline order: AUTO_DISCOVER → AUTO_GENERATE_CONFIG → DEEP_READ.
    AUTO_DISCOVER inventories the workspace and PASSes (no hard gate)."""
    result = fresh_runner.stage_auto_discover()
    assert result.status == "PASS"
    assert result.next_stage == "AUTO_GENERATE_CONFIG"


def test_stages_list_contains_new_stage():
    """Sanity: STAGES list has AUTO_GENERATE_CONFIG between AUTO_DISCOVER
    and DEEP_READ in the right position."""
    assert "AUTO_GENERATE_CONFIG" in pr.STAGES
    discover_idx = pr.STAGES.index("AUTO_DISCOVER")
    auto_idx = pr.STAGES.index("AUTO_GENERATE_CONFIG")
    deep_idx = pr.STAGES.index("DEEP_READ")
    assert discover_idx < auto_idx < deep_idx


def test_stages_list_has_pull_data_not_pull_factset():
    """The data-pull stage was renamed from PULL_FACTSET_DATA to PULL_DATA."""
    assert "PULL_DATA" in pr.STAGES
    assert "PULL_FACTSET_DATA" not in pr.STAGES
