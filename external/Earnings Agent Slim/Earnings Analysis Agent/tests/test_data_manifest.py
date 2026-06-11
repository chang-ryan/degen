"""
Tests for data_manifest.py — provenance manifest helper.

Covers:
  - init_manifest creates a valid empty manifest and refuses to overwrite
  - load_manifest validates against schema and raises on malformed inputs
  - append_entry validates the entry, updates updated_at, and persists
  - find_stale_entries respects max_age_hours, uses most_recent_entry_per_key,
    and correctly handles unparseable timestamps
  - find_missing_metrics handles exact match, period-suffixed match, and
    period-agnostic entries
  - Schema rejects malformed entries (bad ticker, bad period, missing fields)

Determinism: every time-sensitive test injects an explicit `now` so the
results don't depend on wall-clock state.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import data_manifest as dm


# ─── init / load ─────────────────────────────────────────────────────────

def test_init_manifest_creates_valid_empty_manifest(tmp_path):
    p = tmp_path / "data" / "data_manifest.json"
    now = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
    manifest = dm.init_manifest("XYZ", "user", "C1Q26", p, now=now)
    assert manifest["manifest_version"] == "v1"
    assert manifest["ticker"] == "XYZ"
    assert manifest["analyst"] == "user"
    assert manifest["fiscal_period_in_focus"] == "C1Q26"
    assert manifest["entries"] == []
    assert manifest["created_at"] == "2026-05-04T12:00:00Z"
    assert manifest["updated_at"] == "2026-05-04T12:00:00Z"
    assert p.exists()
    assert dm.validate_manifest(manifest) == []


def test_init_manifest_does_not_overwrite_existing(tmp_path):
    p = tmp_path / "data_manifest.json"
    t0 = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 5, 4, 13, 0, 0, tzinfo=timezone.utc)
    first = dm.init_manifest("XYZ", "user", "C1Q26", p, now=t0)
    # Append something to make the existing manifest distinguishable
    dm.append_entry(p, {
        "source_id": "x1", "tool_name": "provider_X", "ticker": "XYZ",
        "metric": "revenue", "value": 100.0, "pulled_at": dm._iso(t0),
    }, now=t0)
    # Re-init must NOT clobber. It must return the existing manifest.
    second = dm.init_manifest("XYZ", "user", "C1Q26", p, now=t1)
    assert len(second["entries"]) == 1
    assert second["entries"][0]["source_id"] == "x1"


def test_init_manifest_rejects_invalid_ticker(tmp_path):
    p = tmp_path / "data_manifest.json"
    with pytest.raises(ValueError):
        dm.init_manifest("not-a-ticker", "user", "C1Q26", p)


def test_init_manifest_rejects_invalid_period(tmp_path):
    p = tmp_path / "data_manifest.json"
    with pytest.raises(ValueError):
        dm.init_manifest("XYZ", "user", "1Q26", p)  # missing C-prefix
    with pytest.raises(ValueError):
        dm.init_manifest("XYZ", "user", "C5Q26", p)  # invalid quarter


def test_load_manifest_raises_on_malformed_json(tmp_path):
    p = tmp_path / "data_manifest.json"
    p.write_text("{this is not valid json")
    with pytest.raises(ValueError, match="not valid JSON"):
        dm.load_manifest(p)


def test_load_manifest_raises_on_schema_violation(tmp_path):
    p = tmp_path / "data_manifest.json"
    p.write_text(json.dumps({"manifest_version": "v1"}))  # missing required fields
    with pytest.raises(ValueError, match="schema validation"):
        dm.load_manifest(p)


# ─── append ──────────────────────────────────────────────────────────────

def test_append_entry_validates_and_persists(tmp_path):
    p = tmp_path / "manifest.json"
    t0 = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 5, 4, 13, 30, 0, tzinfo=timezone.utc)
    dm.init_manifest("XYZ", "user", "C1Q26", p, now=t0)
    entry = {
        "source_id": "cons-rev-c1q26-1",
        "tool_name": "provider_EstimatesConsensus",
        "ticker": "XYZ",
        "period": "C1Q26",
        "metric": "consensus_revenue",
        "value": 543.2,
        "unit": "$mm",
        "pulled_at": dm._iso(t1),
    }
    manifest = dm.append_entry(p, entry, now=t1)
    assert len(manifest["entries"]) == 1
    assert manifest["updated_at"] == "2026-05-04T13:30:00Z"
    assert manifest["created_at"] == "2026-05-04T12:00:00Z"  # untouched
    # Re-load from disk and verify persistence.
    reloaded = dm.load_manifest(p)
    assert reloaded["entries"][0]["source_id"] == entry["source_id"]


def test_append_entry_rejects_missing_required_fields(tmp_path):
    p = tmp_path / "manifest.json"
    dm.init_manifest("XYZ", "user", "C1Q26", p)
    bad = {"source_id": "x", "tool_name": "y"}  # missing ticker, metric, value, pulled_at
    with pytest.raises(ValueError):
        dm.append_entry(p, bad)
    # On-disk manifest must be untouched.
    assert dm.load_manifest(p)["entries"] == []


def test_append_entry_sets_pulled_at_when_omitted(tmp_path):
    p = tmp_path / "manifest.json"
    t0 = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
    dm.init_manifest("XYZ", "user", "C1Q26", p, now=t0)
    entry = {
        "source_id": "x", "tool_name": "y", "ticker": "XYZ",
        "metric": "consensus_revenue", "value": 100.0,
        # pulled_at omitted on purpose
    }
    manifest = dm.append_entry(p, entry, now=t0)
    assert manifest["entries"][0]["pulled_at"] == dm._iso(t0)


# ─── most_recent_entry_per_key ──────────────────────────────────────────

def test_most_recent_entry_per_key_picks_latest(tmp_path):
    p = tmp_path / "manifest.json"
    t0 = datetime(2026, 5, 4, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 5, 4, 11, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
    dm.init_manifest("XYZ", "user", "C1Q26", p, now=t0)
    base = {"tool_name": "provider_EstimatesConsensus", "ticker": "XYZ",
            "metric": "consensus_revenue", "period": "C1Q26", "value": 0.0}
    dm.append_entry(p, {**base, "source_id": "v1", "value": 100.0, "pulled_at": dm._iso(t0)})
    dm.append_entry(p, {**base, "source_id": "v2", "value": 105.0, "pulled_at": dm._iso(t1)})
    dm.append_entry(p, {**base, "source_id": "v3", "value": 110.0, "pulled_at": dm._iso(t2)})
    manifest = dm.load_manifest(p)
    most_recent = dm.most_recent_entry_per_key(manifest)
    key = ("provider_EstimatesConsensus", "consensus_revenue", "C1Q26")
    assert most_recent[key]["source_id"] == "v3"
    assert most_recent[key]["value"] == 110.0


# ─── find_stale_entries ─────────────────────────────────────────────────

def test_find_stale_returns_empty_when_all_fresh(tmp_path):
    p = tmp_path / "manifest.json"
    t0 = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
    dm.init_manifest("XYZ", "user", "C1Q26", p, now=t0)
    dm.append_entry(p, {
        "source_id": "x", "tool_name": "provider_X", "ticker": "XYZ",
        "metric": "consensus_revenue", "period": "C1Q26", "value": 100.0,
        "pulled_at": dm._iso(t0),
    })
    manifest = dm.load_manifest(p)
    # Reference time = 12 hours later. Default max_age_hours=24.
    ref = t0 + timedelta(hours=12)
    assert dm.find_stale_entries(manifest, now=ref) == []


def test_find_stale_returns_entries_older_than_threshold(tmp_path):
    p = tmp_path / "manifest.json"
    t0 = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
    dm.init_manifest("XYZ", "user", "C1Q26", p, now=t0)
    dm.append_entry(p, {
        "source_id": "old", "tool_name": "provider_X", "ticker": "XYZ",
        "metric": "consensus_revenue", "period": "C1Q26", "value": 100.0,
        "pulled_at": dm._iso(t0),
    })
    manifest = dm.load_manifest(p)
    # Reference time = 25 hours later. 25 > 24h → stale.
    ref = t0 + timedelta(hours=25)
    stale = dm.find_stale_entries(manifest, max_age_hours=24, now=ref)
    assert len(stale) == 1
    assert stale[0]["source_id"] == "old"


def test_find_stale_uses_most_recent_per_key(tmp_path):
    """A stale earlier entry that's been superseded by a fresh later
    entry should NOT be flagged as stale."""
    p = tmp_path / "manifest.json"
    t0 = datetime(2026, 5, 4, 0, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 5, 5, 23, 0, 0, tzinfo=timezone.utc)  # 47h later
    dm.init_manifest("XYZ", "user", "C1Q26", p, now=t0)
    base = {"tool_name": "provider_X", "ticker": "XYZ",
            "metric": "consensus_revenue", "period": "C1Q26", "value": 0.0}
    dm.append_entry(p, {**base, "source_id": "old", "value": 100.0, "pulled_at": dm._iso(t0)})
    dm.append_entry(p, {**base, "source_id": "fresh", "value": 105.0, "pulled_at": dm._iso(t1)})
    manifest = dm.load_manifest(p)
    # Reference = t1 + 1h. Fresh entry is 1h old → not stale even though
    # the older entry is 48h old.
    ref = t1 + timedelta(hours=1)
    stale = dm.find_stale_entries(manifest, max_age_hours=24, now=ref)
    assert stale == [], f"unexpected stale entries: {stale}"


def test_find_stale_treats_unparseable_pulled_at_as_stale(tmp_path):
    """An entry with a corrupt timestamp should be flagged as stale —
    we can't honestly age it, so it must not pass the gate."""
    p = tmp_path / "manifest.json"
    t0 = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
    dm.init_manifest("XYZ", "user", "C1Q26", p, now=t0)
    # Bypass append_entry validation by writing directly. The schema
    # accepts any string for pulled_at; we want to verify the freshness
    # function is defensive against garbage that the schema lets through.
    manifest = dm.load_manifest(p)
    manifest["entries"].append({
        "source_id": "garbage",
        "tool_name": "provider_X",
        "ticker": "XYZ",
        "metric": "consensus_revenue",
        "period": "C1Q26",
        "value": 100.0,
        "pulled_at": "not-an-iso-timestamp",
    })
    p.write_text(json.dumps(manifest, indent=2))
    reloaded = dm.load_manifest(p)
    stale = dm.find_stale_entries(reloaded, max_age_hours=24, now=t0)
    assert len(stale) == 1
    assert stale[0]["source_id"] == "garbage"


# ─── find_missing_metrics ───────────────────────────────────────────────

def test_find_missing_metrics_exact_match(tmp_path):
    p = tmp_path / "manifest.json"
    dm.init_manifest("XYZ", "user", "C1Q26", p)
    dm.append_entry(p, {
        "source_id": "x", "tool_name": "provider_X", "ticker": "XYZ",
        "metric": "consensus_revenue", "period": "C1Q26", "value": 100.0,
        "pulled_at": "2026-05-04T12:00:00Z",
    })
    manifest = dm.load_manifest(p)
    required = ["consensus_revenue", "consensus_eps"]
    missing = dm.find_missing_metrics(manifest, required)
    assert missing == ["consensus_eps"]


def test_find_missing_metrics_period_suffixed_match(tmp_path):
    p = tmp_path / "manifest.json"
    dm.init_manifest("XYZ", "user", "C1Q26", p)
    dm.append_entry(p, {
        "source_id": "x", "tool_name": "provider_X", "ticker": "XYZ",
        # Suffixed metric name; period field also set
        "metric": "consensus_revenue_C1Q26", "period": "C1Q26", "value": 100.0,
        "pulled_at": "2026-05-04T12:00:00Z",
    })
    manifest = dm.load_manifest(p)
    missing = dm.find_missing_metrics(manifest, ["consensus_revenue"])
    # Should match via the period-suffixed convention.
    assert missing == []


def test_find_missing_metrics_period_agnostic_entry(tmp_path):
    p = tmp_path / "manifest.json"
    dm.init_manifest("XYZ", "user", "C1Q26", p)
    # period=None means "applies to any period"
    dm.append_entry(p, {
        "source_id": "x", "tool_name": "provider_X", "ticker": "XYZ",
        "metric": "company_fiscal_year_end_month", "period": None, "value": 12,
        "pulled_at": "2026-05-04T12:00:00Z",
    })
    manifest = dm.load_manifest(p)
    missing = dm.find_missing_metrics(manifest, ["company_fiscal_year_end_month"])
    assert missing == []


def test_find_missing_metrics_period_mismatch(tmp_path):
    """A manifest entry for C2Q26 should NOT cover a C1Q26 required metric."""
    p = tmp_path / "manifest.json"
    dm.init_manifest("XYZ", "user", "C1Q26", p)
    dm.append_entry(p, {
        "source_id": "x", "tool_name": "provider_X", "ticker": "XYZ",
        "metric": "consensus_revenue", "period": "C2Q26", "value": 100.0,
        "pulled_at": "2026-05-04T12:00:00Z",
    })
    manifest = dm.load_manifest(p)
    missing = dm.find_missing_metrics(manifest, ["consensus_revenue"], period="C1Q26")
    assert missing == ["consensus_revenue"]


# ─── schema rejection cases ─────────────────────────────────────────────

def test_schema_rejects_lowercase_ticker(tmp_path):
    p = tmp_path / "m.json"
    with pytest.raises(ValueError):
        dm.init_manifest("xyz", "user", "C1Q26", p)


def test_schema_rejects_unknown_top_level_field(tmp_path):
    p = tmp_path / "m.json"
    dm.init_manifest("XYZ", "user", "C1Q26", p)
    manifest = dm.load_manifest(p)
    manifest["bonus_field"] = "should_be_rejected"
    errors = dm.validate_manifest(manifest)
    assert errors  # additionalProperties=false should reject this


def test_schema_rejects_unknown_entry_field(tmp_path):
    p = tmp_path / "m.json"
    dm.init_manifest("XYZ", "user", "C1Q26", p)
    bad_entry = {
        "source_id": "x", "tool_name": "provider_X", "ticker": "XYZ",
        "metric": "consensus_revenue", "value": 100.0,
        "pulled_at": "2026-05-04T12:00:00Z",
        "rogue_field": "should_be_rejected",
    }
    with pytest.raises(ValueError):
        dm.append_entry(p, bad_entry)
