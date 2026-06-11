"""
Tests for sell_side_synthesizer schema validation (P1-1).

Covers:
  - Per-note schema validation: malformed JSON, missing required fields,
    bad date format, top-level non-object -- all surfaced as validation_failures
  - Thin-extraction detection: a note with no thesis/data content is INCLUDED
    in ratings aggregation but flagged in thin_extractions
  - _dispatch_plan.json (and other underscore-prefixed files) excluded
    from per-note validation
  - Successful aggregation when notes pass schema
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import sell_side_synthesizer as sss


@pytest.fixture
def synth_dir(tmp_path, monkeypatch):
    """Create a fake workspace synthesis directory and rebind ticker_dir."""
    repo = tmp_path / "repo"
    syn = repo / "workspace" / "ZZZZ" / "synthesis"
    syn.mkdir(parents=True)
    monkeypatch.setattr(sss, "ticker_dir", lambda t: repo / "workspace" / t.upper())
    return syn


def _valid_note(broker="BofA", date="20260402", **kwargs) -> dict:
    base = {
        "broker": broker,
        "date": date,
        "rating": "Buy",
        "price_target": 50.0,
        "bear_thesis_components": ["compression risk", "competition intensifying"],
        "bull_thesis_components": ["GLP-1 tailwind", "recurring subs"],
        "key_data_points": [
            {"metric": "subscribers", "value": "2.4mm", "source": "10-Q"}
        ],
        "notable_arguments": ["unique partnership angle"],
        "key_quotes": ["The Q1 print is achievable"],
        "topic_summary": "Q1 preview update",
    }
    base.update(kwargs)
    return base


def _write_note(syn: Path, filename: str, data) -> Path:
    p = syn / filename
    p.write_text(json.dumps(data) if not isinstance(data, str) else data)
    return p


# --- schema validation function ---

def test_validate_note_passes_well_formed():
    errors = sss._validate_note_against_schema(_valid_note())
    assert errors == []


def test_validate_note_fails_missing_broker():
    bad = _valid_note()
    del bad["broker"]
    errors = sss._validate_note_against_schema(bad)
    assert errors  # at least one error
    assert any("broker" in e for e in errors)


def test_validate_note_fails_bad_date_format():
    bad = _valid_note(date="2026/04/02")  # not YYYYMMDD
    errors = sss._validate_note_against_schema(bad)
    assert errors


def test_validate_note_passes_when_optional_fields_null():
    """Schema permits null for many optional fields. Missing is also fine."""
    minimal = {"broker": "X", "date": "20260101"}
    assert sss._validate_note_against_schema(minimal) == []


# --- thin-extraction heuristic ---

def test_thin_extraction_detects_empty_thesis():
    note = {"broker": "X", "date": "20260101", "rating": "Buy", "price_target": 50}
    assert sss._is_thin_extraction(note) is True


def test_thin_extraction_false_when_bear_present():
    note = _valid_note(bull_thesis_components=None, key_data_points=None,
                       notable_arguments=None, key_quotes=None)
    # Has bear_thesis_components from _valid_note
    assert sss._is_thin_extraction(note) is False


def test_thin_extraction_false_when_only_quotes_present():
    note = {"broker": "X", "date": "20260101", "key_quotes": ["a quote"]}
    assert sss._is_thin_extraction(note) is False


# --- aggregator behavior ---

def test_aggregate_clean_notes_no_failures(synth_dir):
    _write_note(synth_dir, "BofA_20260402.json", _valid_note(broker="BofA"))
    _write_note(synth_dir, "Morgan_20260408.json", _valid_note(broker="Morgan", date="20260408"))
    result = sss.aggregate("ZZZZ")
    assert result["status"] == "complete"
    assert result["notes_synthesized"] == 2
    assert result["validation_failures"] == []
    assert result["thin_extractions"] == []
    assert result["summary"]["bear_components_count"] >= 2
    assert result["summary"]["bull_components_count"] >= 2


def test_aggregate_skips_dispatch_plan(synth_dir):
    """The orchestrator's _dispatch_plan.json must not be treated as a note."""
    _write_note(synth_dir, "_dispatch_plan.json", {"ticker": "ZZZZ", "tasks": []})
    _write_note(synth_dir, "BofA_20260402.json", _valid_note())
    result = sss.aggregate("ZZZZ")
    assert result["status"] == "complete"
    assert result["notes_synthesized"] == 1
    # _dispatch_plan should NOT appear in validation_failures either
    assert all("_dispatch_plan" not in v.get("file", "") for v in result["validation_failures"])


def test_aggregate_surfaces_malformed_json(synth_dir):
    _write_note(synth_dir, "good.json", _valid_note())
    _write_note(synth_dir, "bad.json", "{not valid json")
    result = sss.aggregate("ZZZZ")
    assert result["notes_synthesized"] == 1
    assert len(result["validation_failures"]) == 1
    assert result["validation_failures"][0]["file"] == "bad.json"
    assert result["validation_failures"][0]["kind"] == "json_parse"


def test_aggregate_surfaces_schema_violations(synth_dir):
    bad = _valid_note()
    del bad["broker"]
    _write_note(synth_dir, "bad.json", bad)
    _write_note(synth_dir, "good.json", _valid_note())
    result = sss.aggregate("ZZZZ")
    assert result["notes_synthesized"] == 1
    schema_failures = [v for v in result["validation_failures"] if v["kind"] == "schema"]
    assert len(schema_failures) == 1
    assert "broker" in schema_failures[0]["error"]


def test_aggregate_surfaces_top_level_array(synth_dir):
    _write_note(synth_dir, "wrong.json", ["not", "an", "object"])
    _write_note(synth_dir, "good.json", _valid_note())
    result = sss.aggregate("ZZZZ")
    assert result["notes_synthesized"] == 1
    assert len(result["validation_failures"]) == 1
    assert result["validation_failures"][0]["kind"] == "schema"


def test_aggregate_thin_extraction_included_but_flagged(synth_dir):
    thin = {"broker": "BofA", "date": "20260101", "rating": "Buy", "price_target": 50.0}
    _write_note(synth_dir, "thin.json", thin)
    _write_note(synth_dir, "thick.json", _valid_note(broker="Morgan"))
    result = sss.aggregate("ZZZZ")
    # Both included
    assert result["notes_synthesized"] == 2
    assert len(result["thin_extractions"]) == 1
    assert result["thin_extractions"][0]["file"] == "thin.json"
    # Markdown should mention thin_extractions
    md_path = Path(result["synthesis_path"])
    md = md_path.read_text()
    assert "Thin Extractions" in md


def test_aggregate_no_valid_notes_returns_error(synth_dir):
    _write_note(synth_dir, "bad1.json", "{not json")
    _write_note(synth_dir, "bad2.json", {"missing": "broker"})
    result = sss.aggregate("ZZZZ")
    assert result["status"] == "error"
    assert "validation_failures" in result
    assert len(result["validation_failures"]) == 2


def test_aggregate_handles_null_array_fields(synth_dir):
    """Schema permits null for bear_thesis_components etc. The aggregator's
    _safe_list helper must coerce None -> [] before iterating."""
    _write_note(synth_dir, "nullified.json", _valid_note(
        bear_thesis_components=None,
        bull_thesis_components=None,
        key_data_points=None,
        notable_arguments=None,
        key_quotes=None,
    ))
    result = sss.aggregate("ZZZZ")
    assert result["status"] == "complete"
    # All-null arrays make this a thin extraction
    assert len(result["thin_extractions"]) == 1


def test_aggregate_synthesis_md_lists_validation_failures(synth_dir):
    _write_note(synth_dir, "BofA_20260402.json", _valid_note())
    _write_note(synth_dir, "broken.json", "{")
    result = sss.aggregate("ZZZZ")
    md = Path(result["synthesis_path"]).read_text()
    assert "Validation Failures" in md
    assert "broken.json" in md
