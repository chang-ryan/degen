"""
Tests for preview_runner.py manifest integration.

Covers:
  - _normalize_fiscal_period handles canonical, 1Q26, 1Q2026, 2026/1F forms
  - _normalize_fiscal_period rejects unparseable inputs with a reason
  - _read_fiscal_period_from_config probes the three field-name candidates
  - stage_pull_data initializes the manifest when config has a parseable period
  - stage_pull_data skips manifest init (with explanation) when period missing
"""
from __future__ import annotations

from pathlib import Path

import pytest

import preview_runner as pr


# --- _normalize_fiscal_period ---

@pytest.fixture
def runner(tmp_path, monkeypatch):
    """Build a runner instance with paths under tmp_path.

    The runner resolves its ticker_dir via _paths.ticker_dir at __init__,
    imported into the preview_runner namespace. Monkeypatch that name so all
    derived paths land under tmp_path/workspace/{TICKER}.
    """
    monkeypatch.setattr(pr, "ticker_dir", lambda t: tmp_path / "workspace" / t.upper())
    monkeypatch.setattr(pr, "REFERENCE_BASE", tmp_path / "Reference Files")
    return pr.PreviewRunner(ticker="XYZ", analyst="user", mode="symbiotic")


def test_normalize_canonical_passthrough(runner):
    canonical, warn = runner._normalize_fiscal_period("C1Q26")
    assert canonical == "C1Q26"
    assert warn is None


def test_normalize_canonical_lowercase_input(runner):
    canonical, warn = runner._normalize_fiscal_period("c1q26")
    assert canonical == "C1Q26"
    assert warn is None


def test_normalize_1q26_form(runner):
    canonical, warn = runner._normalize_fiscal_period("1Q26")
    assert canonical == "C1Q26"
    assert warn is not None and "1Q26 form" in warn


def test_normalize_1q2026_form(runner):
    canonical, warn = runner._normalize_fiscal_period("1Q2026")
    assert canonical == "C1Q26"
    assert warn is not None and "1Q2026 form" in warn


def test_normalize_2026_1f_form(runner):
    canonical, warn = runner._normalize_fiscal_period("2026/1F")
    assert canonical == "C1Q26"
    assert warn is not None and "2026/1F form" in warn


def test_normalize_rejects_garbage(runner):
    canonical, warn = runner._normalize_fiscal_period("not a quarter")
    assert canonical is None
    assert warn is not None and "could not normalize" in warn


def test_normalize_rejects_empty(runner):
    canonical, warn = runner._normalize_fiscal_period("")
    assert canonical is None


def test_normalize_rejects_none(runner):
    canonical, warn = runner._normalize_fiscal_period(None)
    assert canonical is None


def test_normalize_rejects_q5(runner):
    canonical, warn = runner._normalize_fiscal_period("5Q26")
    assert canonical is None


# --- _read_fiscal_period_from_config ---

def _setup_config(runner, content: str):
    runner.ticker_dir.mkdir(parents=True, exist_ok=True)
    runner.config_path.write_text(content)


def test_read_fiscal_period_no_config(runner):
    canonical, warn = runner._read_fiscal_period_from_config()
    assert canonical is None
    assert "config.yaml not found" in warn


def test_read_fiscal_period_in_focus_canonical(runner):
    _setup_config(runner, "fiscal_period_in_focus: C1Q26\n")
    canonical, warn = runner._read_fiscal_period_from_config()
    assert canonical == "C1Q26"
    assert warn is None


def test_read_fiscal_period_quarter_field_legacy_form(runner):
    """Legacy configs use `quarter: 1Q26` — must be normalized."""
    _setup_config(runner, "quarter: 1Q26\n")
    canonical, warn = runner._read_fiscal_period_from_config()
    assert canonical == "C1Q26"
    assert warn is not None  # a normalization note


def test_read_fiscal_period_2026_1f_form(runner):
    """Some configs use `fiscal_period_in_focus: 2026/1F`."""
    _setup_config(runner, "fiscal_period_in_focus: 2026/1F\n")
    canonical, warn = runner._read_fiscal_period_from_config()
    assert canonical == "C1Q26"
    assert warn is not None


def test_read_fiscal_period_unparseable(runner):
    _setup_config(runner, "fiscal_period_in_focus: garbage\n")
    canonical, warn = runner._read_fiscal_period_from_config()
    assert canonical is None
    assert "garbage" in warn


def test_read_fiscal_period_no_fields(runner):
    _setup_config(runner, "ticker: XYZ\n")
    canonical, warn = runner._read_fiscal_period_from_config()
    assert canonical is None
    assert "no fiscal period declared" in warn


def test_read_fiscal_period_malformed_yaml(runner):
    _setup_config(runner, "fiscal_period: : :\n")
    canonical, warn = runner._read_fiscal_period_from_config()
    assert canonical is None
    assert "parse error" in warn or "could not normalize" in warn


# --- stage_pull_data manifest init ---

def test_pull_data_initializes_manifest_when_period_available(runner):
    runner.ticker_dir.mkdir(parents=True, exist_ok=True)
    runner.data_dir.mkdir(parents=True, exist_ok=True)
    runner.config_path.write_text("fiscal_period_in_focus: C1Q26\n")
    result = runner.stage_pull_data()
    assert runner.manifest_path.exists()
    assert "manifest_initialized" in result.metadata


def test_pull_data_skips_manifest_init_when_period_missing(runner):
    runner.ticker_dir.mkdir(parents=True, exist_ok=True)
    runner.data_dir.mkdir(parents=True, exist_ok=True)
    # No config.yaml at all
    result = runner.stage_pull_data()
    assert not runner.manifest_path.exists()
    assert "manifest_init_skipped" in result.metadata
    assert "config.yaml not found" in result.metadata["manifest_init_skipped"]


def test_pull_data_skips_manifest_init_when_period_unparseable(runner):
    runner.ticker_dir.mkdir(parents=True, exist_ok=True)
    runner.data_dir.mkdir(parents=True, exist_ok=True)
    runner.config_path.write_text("quarter: garbage\n")
    result = runner.stage_pull_data()
    assert not runner.manifest_path.exists()
    assert "manifest_init_skipped" in result.metadata


def test_pull_data_normalizes_legacy_period_form(runner):
    """Legacy configs have `quarter: 1Q26`. The runner must normalize this
    to canonical C1Q26 before initializing the manifest.

    The normalization warning lives in the fiscal_period_resolution dict
    (config_warning field) — the test reads from there."""
    runner.ticker_dir.mkdir(parents=True, exist_ok=True)
    runner.data_dir.mkdir(parents=True, exist_ok=True)
    runner.config_path.write_text("quarter: 1Q26\n")
    result = runner.stage_pull_data()
    assert runner.manifest_path.exists()
    # Verify the persisted manifest has the canonical form
    import json as _json
    manifest = _json.loads(runner.manifest_path.read_text())
    assert manifest["fiscal_period_in_focus"] == "C1Q26"
    # The normalization warning lives in the resolution dict's config_warning.
    resolution = result.metadata["fiscal_period_resolution"]
    assert resolution["config_period"] == "C1Q26"
    assert resolution["config_warning"] is not None
    assert "1Q26 form" in resolution["config_warning"]
    # Source-of-truth is config (the only source the runner reads now).
    assert result.metadata["manifest_init_source"] == "config"
