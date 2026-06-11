"""
Tests for manifest_backfill.py.

Covers:
  - dry-run reports what would be added
  - real run creates manifest and adds entries when none exist
  - real run is idempotent: skips already-present (tool, metric, period) entries
  - refuses to mix periods (existing manifest's period != config period)
  - error paths: missing config, missing key_metrics.yaml, malformed config
  - pulled_at honestly reflects key_metrics.yaml mtime (not now)
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

import manifest_backfill as mb


@pytest.fixture
def ticker_dir(tmp_path, monkeypatch):
    """Fake single-user workspace. Returns the ticker_dir Path."""
    repo = tmp_path / "repo"
    td = repo / "workspace" / "XYZ"
    td.mkdir(parents=True)
    # Redirect the workspace ticker-dir resolver to our tmp layout.
    monkeypatch.setattr(mb, "_ws_ticker_dir", lambda t: repo / "workspace" / t.upper())
    return td


def _write_config(td: Path, body: str):
    (td / "config.yaml").write_text(body)


def _write_key_metrics(td: Path, body: str = "ticker: XYZ\nperiod: C1Q26\n"):
    (td / "key_metrics.yaml").write_text(body)


# --- error paths ---

def test_no_config_returns_error(ticker_dir):
    r = mb.backfill("XYZ", "user")
    assert r["status"] == "error"
    assert "config.yaml not found" in r["error"]


def test_no_period_in_config_returns_error(ticker_dir):
    _write_config(ticker_dir, "ticker: XYZ\nkey_metrics: [revenue, eps]\n")
    r = mb.backfill("XYZ", "user")
    assert r["status"] == "error"
    assert "fiscal period" in r["error"]


def test_no_key_metrics_returns_error(ticker_dir):
    _write_config(ticker_dir, "ticker: XYZ\nfiscal_period_in_focus: C1Q26\n")
    r = mb.backfill("XYZ", "user")
    assert r["status"] == "error"
    assert "empty" in r["error"] or "list" in r["error"]


def test_no_key_metrics_yaml_returns_error(ticker_dir):
    _write_config(ticker_dir,
                  "ticker: XYZ\nfiscal_period_in_focus: C1Q26\n"
                  "key_metrics: [revenue, eps]\n")
    r = mb.backfill("XYZ", "user")
    assert r["status"] == "error"
    assert "key_metrics.yaml not found" in r["error"]


# --- dry run ---

def test_dry_run_lists_metrics_without_writing(ticker_dir):
    _write_config(ticker_dir,
                  "ticker: XYZ\nfiscal_period_in_focus: C1Q26\n"
                  "key_metrics: [revenue, eps, ebitda]\n")
    _write_key_metrics(ticker_dir)
    r = mb.backfill("XYZ", "user", dry_run=True)
    assert r["status"] == "dry_run"
    assert r["period"] == "C1Q26"
    assert set(r["would_add"]) == {"revenue", "eps", "ebitda"}
    assert r["already_present"] == []
    # Manifest must NOT have been written
    assert not (ticker_dir / "data" / "data_manifest.json").exists()


# --- real run ---

def test_real_run_creates_manifest_and_adds_entries(ticker_dir):
    _write_config(ticker_dir,
                  "ticker: XYZ\nfiscal_period_in_focus: C1Q26\n"
                  "key_metrics: [revenue, eps]\n")
    _write_key_metrics(ticker_dir)
    r = mb.backfill("XYZ", "user")
    assert r["status"] == "complete"
    assert set(r["metrics_added"]) == {"revenue", "eps"}
    assert r["metrics_already_present"] == []
    # Manifest now exists with two entries
    manifest_path = ticker_dir / "data" / "data_manifest.json"
    m = json.loads(manifest_path.read_text())
    assert m["fiscal_period_in_focus"] == "C1Q26"
    assert len(m["entries"]) == 2
    metrics = {e["metric"] for e in m["entries"]}
    assert metrics == {"revenue", "eps"}


def test_real_run_is_idempotent(ticker_dir):
    """Running twice must not duplicate entries."""
    _write_config(ticker_dir,
                  "ticker: XYZ\nfiscal_period_in_focus: C1Q26\n"
                  "key_metrics: [revenue, eps]\n")
    _write_key_metrics(ticker_dir)
    mb.backfill("XYZ", "user")
    r2 = mb.backfill("XYZ", "user")
    assert r2["status"] == "complete"
    assert r2["metrics_added"] == []
    assert set(r2["metrics_already_present"]) == {"revenue", "eps"}
    m = json.loads((ticker_dir / "data" / "data_manifest.json").read_text())
    assert len(m["entries"]) == 2


def test_pulled_at_uses_key_metrics_mtime(ticker_dir):
    """Honest staleness: pulled_at = key_metrics.yaml mtime, NOT now."""
    _write_config(ticker_dir,
                  "ticker: XYZ\nfiscal_period_in_focus: C1Q26\n"
                  "key_metrics: [revenue]\n")
    _write_key_metrics(ticker_dir)
    # Set km mtime to a fixed point in the past
    km = ticker_dir / "key_metrics.yaml"
    past = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    os.utime(km, (past, past))

    mb.backfill("XYZ", "user")
    m = json.loads((ticker_dir / "data" / "data_manifest.json").read_text())
    pulled_at = m["entries"][0]["pulled_at"]
    assert pulled_at == "2026-04-01T12:00:00Z"  # exactly the file mtime, not now


def test_refuses_to_mix_periods(ticker_dir):
    """If an existing manifest is for a different period, refuse to backfill."""
    # First create a manifest for C1Q26
    _write_config(ticker_dir,
                  "ticker: XYZ\nfiscal_period_in_focus: C1Q26\n"
                  "key_metrics: [revenue]\n")
    _write_key_metrics(ticker_dir)
    mb.backfill("XYZ", "user")
    # Now change config to C2Q26 and try to backfill again
    _write_config(ticker_dir,
                  "ticker: XYZ\nfiscal_period_in_focus: C2Q26\n"
                  "key_metrics: [revenue]\n")
    r = mb.backfill("XYZ", "user")
    assert r["status"] == "error"
    assert "does not match" in r["error"]


def test_legacy_period_form_normalized(ticker_dir):
    """Config with `quarter: 1Q26` (legacy form) gets normalized to C1Q26."""
    _write_config(ticker_dir,
                  "ticker: XYZ\nquarter: 1Q26\n"
                  "key_metrics: [revenue]\n")
    _write_key_metrics(ticker_dir)
    r = mb.backfill("XYZ", "user")
    assert r["status"] == "complete"
    assert r["period"] == "C1Q26"


def test_partial_existing_manifest_only_adds_missing(ticker_dir):
    """If manifest already has 1 of N metrics, only the missing ones are added."""
    _write_config(ticker_dir,
                  "ticker: XYZ\nfiscal_period_in_focus: C1Q26\n"
                  "key_metrics: [revenue, eps, ebitda]\n")
    _write_key_metrics(ticker_dir)
    # Pre-create a manifest with only `revenue`
    from data_manifest import init_manifest, append_entry
    data_dir = ticker_dir / "data"
    data_dir.mkdir()
    manifest_path = data_dir / "data_manifest.json"
    init_manifest("XYZ", "user", "C1Q26", manifest_path)
    append_entry(manifest_path, {
        "source_id": "live_pull_revenue", "tool_name": "data_provider_X",
        "ticker": "XYZ", "period": "C1Q26", "metric": "revenue",
        "value": 543.2, "pulled_at": "2026-05-04T12:00:00Z",
    })
    # Now backfill -- should only add `eps` and `ebitda`
    r = mb.backfill("XYZ", "user")
    assert r["status"] == "complete"
    assert set(r["metrics_added"]) == {"eps", "ebitda"}
    assert r["metrics_already_present"] == ["revenue"]


def test_entries_satisfy_d02_coverage_check(ticker_dir):
    """End-to-end: after backfill, find_missing_metrics returns empty."""
    _write_config(ticker_dir,
                  "ticker: XYZ\nfiscal_period_in_focus: C1Q26\n"
                  "key_metrics: [revenue, eps]\n")
    _write_key_metrics(ticker_dir)
    mb.backfill("XYZ", "user")
    from data_manifest import load_manifest, find_missing_metrics
    manifest = load_manifest(ticker_dir / "data" / "data_manifest.json")
    missing = find_missing_metrics(manifest, ["revenue", "eps"], period="C1Q26")
    assert missing == []


# --- v2: config-driven path extraction ---

def test_resolve_dotted_path_simple():
    data = {"a": {"b": {"c": 42}}}
    val, err = mb._resolve_dotted_path(data, "a.b.c")
    assert val == 42
    assert err is None


def test_resolve_dotted_path_missing_component():
    data = {"a": {"b": {}}}
    val, err = mb._resolve_dotted_path(data, "a.b.c")
    assert val is None
    assert "c" in err


def test_resolve_dotted_path_missing_root():
    data = {"x": 1}
    val, err = mb._resolve_dotted_path(data, "y.z")
    assert val is None


def test_resolve_dotted_path_returns_subtree():
    """A path that stops mid-tree returns the dict at that depth."""
    data = {"a": {"b": {"c": 42, "d": 43}}}
    val, err = mb._resolve_dotted_path(data, "a.b")
    assert val == {"c": 42, "d": 43}


def test_resolve_dotted_path_empty_path():
    val, err = mb._resolve_dotted_path({"a": 1}, "")
    assert val is None
    assert "empty" in err


def test_extract_backfill_value_string_mapping():
    km = {"hist": {"Q1_25": {"revenue": 586.0}}}
    val, err = mb._extract_backfill_value(km, "hist.Q1_25.revenue")
    assert val == 586.0
    assert err is None


def test_extract_backfill_value_dict_mapping_default_role():
    km = {"hist": {"Q1_25": {"revenue": 586.0}}, "guide": {"Q1_26": {"rev_mid": 612.5}}}
    mapping = {"current_period": "guide.Q1_26.rev_mid", "prior_year_period": "hist.Q1_25.revenue"}
    val, err = mb._extract_backfill_value(km, mapping, role="current_period")
    assert val == 612.5
    val_prior, _ = mb._extract_backfill_value(km, mapping, role="prior_year_period")
    assert val_prior == 586.0


def test_extract_backfill_value_role_not_present():
    km = {"x": 1}
    mapping = {"current_period": "x"}
    val, err = mb._extract_backfill_value(km, mapping, role="prior_year_period")
    assert val is None
    assert "prior_year_period" in err


def test_v2_backfill_populates_value_when_path_resolves(ticker_dir):
    """End-to-end: config has backfill_paths, key_metrics.yaml has the path,
    backfill writes the actual value (not null) to the manifest."""
    _write_config(ticker_dir, """
ticker: XYZ
fiscal_period_in_focus: C1Q26
key_metrics: [revenue_total, adj_ebitda]
backfill_paths:
  revenue_total:
    current_period: guide.Q1_26.revenue.mid
  adj_ebitda:
    current_period: guide.Q1_26.ebitda.mid
""")
    _write_key_metrics(ticker_dir, """
ticker: XYZ
guide:
  Q1_26:
    revenue: {low: 600.0, mid: 612.5, high: 625.0}
    ebitda: {low: 35.0, mid: 45.0, high: 55.0}
""")
    r = mb.backfill("XYZ", "user")
    assert r["status"] == "complete"
    assert set(r["metrics_with_extracted_values"]) == {"revenue_total", "adj_ebitda"}
    # Verify the manifest entries have the actual values
    m = json.loads((ticker_dir / "data" / "data_manifest.json").read_text())
    by_metric = {e["metric"]: e for e in m["entries"]}
    assert by_metric["revenue_total"]["value"] == 612.5
    assert by_metric["adj_ebitda"]["value"] == 45.0


def test_v2_backfill_falls_back_to_null_when_path_missing(ticker_dir):
    """Path declared but not present in key_metrics.yaml -> value=null,
    extraction error recorded in result."""
    _write_config(ticker_dir, """
ticker: XYZ
fiscal_period_in_focus: C1Q26
key_metrics: [revenue_total]
backfill_paths:
  revenue_total:
    current_period: guide.Q1_26.revenue.mid
""")
    _write_key_metrics(ticker_dir, "ticker: XYZ\n")  # no guide section
    r = mb.backfill("XYZ", "user")
    assert r["status"] == "complete"
    assert r["metrics_with_extracted_values"] == []
    assert len(r["metrics_with_extraction_errors"]) == 1
    assert r["metrics_with_extraction_errors"][0]["metric"] == "revenue_total"
    # Manifest entry exists but value is null
    m = json.loads((ticker_dir / "data" / "data_manifest.json").read_text())
    assert m["entries"][0]["value"] is None


def test_v2_metric_without_backfill_path_uses_null(ticker_dir):
    """A metric not declared in backfill_paths still gets a null entry --
    coverage gap is closed, just no value extracted."""
    _write_config(ticker_dir, """
ticker: XYZ
fiscal_period_in_focus: C1Q26
key_metrics: [revenue_total, eps]
backfill_paths:
  revenue_total:
    current_period: guide.Q1_26.revenue.mid
""")
    _write_key_metrics(ticker_dir, """
ticker: XYZ
guide:
  Q1_26:
    revenue: {mid: 612.5}
""")
    r = mb.backfill("XYZ", "user")
    assert r["status"] == "complete"
    assert r["metrics_with_extracted_values"] == ["revenue_total"]
    m = json.loads((ticker_dir / "data" / "data_manifest.json").read_text())
    by_metric = {e["metric"]: e for e in m["entries"]}
    assert by_metric["revenue_total"]["value"] == 612.5
    assert by_metric["eps"]["value"] is None


def test_v2_no_backfill_paths_v1_behavior(ticker_dir):
    """No backfill_paths in config -> v1 behavior (all values null)."""
    _write_config(ticker_dir,
                  "ticker: XYZ\nfiscal_period_in_focus: C1Q26\n"
                  "key_metrics: [revenue, eps]\n")
    _write_key_metrics(ticker_dir, "guide: {Q1_26: {revenue: {mid: 999}}}\n")
    r = mb.backfill("XYZ", "user")
    assert r["status"] == "complete"
    assert r["metrics_with_extracted_values"] == []
    m = json.loads((ticker_dir / "data" / "data_manifest.json").read_text())
    for e in m["entries"]:
        assert e["value"] is None
