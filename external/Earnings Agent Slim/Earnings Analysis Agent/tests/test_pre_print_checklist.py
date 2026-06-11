"""
Tests for pre_print_checklist.py.

Focus areas:
  1. _resolve_item_templates correctly substitutes {ticker} and passes through
     untemplated fields unchanged.
  2. The default checklist's positioning_read entry keys off a fixed
     positioning_read.tilt field path (no analyst templating).
  3. run_checklist resolves paths under the single-user workspace
     (workspace/{TICKER}) and PASSes the positioning_read item when present.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import pre_print_checklist as ppc


def test_resolve_item_templates_substitutes_ticker():
    raw = {
        "id": "x", "label": "x", "required": True, "auto_fetch": False,
        "check_path": "{ticker}_specific.json",
        "check_method": "file_exists",
    }
    out = ppc._resolve_item_templates(raw, "user", "XYZ")
    assert out["check_path"] == "XYZ_specific.json"
    # Original dict must not be mutated (the checklist is module-level).
    assert raw["check_path"] == "{ticker}_specific.json"


def test_resolve_item_templates_passthrough_when_no_placeholder():
    raw = {
        "id": "x", "label": "x", "required": True, "auto_fetch": False,
        "check_path": "config.yaml",
        "check_method": "yaml_field_exists",
        "field_name": "salient_kpis",
    }
    out = ppc._resolve_item_templates(raw, "user", "XYZ")
    assert out["check_path"] == "config.yaml"
    assert out["field_name"] == "salient_kpis"


def test_default_checklist_positioning_read_uses_literal_field_path():
    """The positioning_read item references a fixed field path, not an
    analyst-templated one."""
    item = next(i for i in ppc.DEFAULT_CHECKLIST if i["id"] == "positioning_read")
    assert item["field_path"] == "positioning_read.tilt"


def test_no_analyst_template_in_default_checklist():
    """Defense in depth: no string in the default checklist embeds an
    {analyst} placeholder (the positioning field no longer keys off analyst)."""
    for item in ppc.DEFAULT_CHECKLIST:
        for k, v in item.items():
            if isinstance(v, str):
                assert "{analyst}" not in v, f"item {item.get('id')} field {k} contains '{{analyst}}': {v!r}"


def test_run_checklist_positioning_read_passes_when_present(tmp_path, monkeypatch):
    """End-to-end: build a workspace ticker dir, drop a positioning.json with
    positioning_read.tilt set, and verify the positioning_read item PASSES."""
    workspace = tmp_path / "workspace"
    ticker_dir = workspace / "XYZ"
    ticker_dir.mkdir(parents=True)
    monkeypatch.setattr(ppc, "WORKSPACE_BASE", workspace)

    import json as _json
    (ticker_dir / "positioning.json").write_text(_json.dumps({
        "positioning_read": {"tilt": "long bias"},
    }))

    # Run only the positioning_read item to keep the test focused
    minimal_checklist = [i for i in ppc.DEFAULT_CHECKLIST if i["id"] == "positioning_read"]
    report = ppc.run_checklist("user", "XYZ", minimal_checklist)
    assert report["status"] == "READY", f"expected READY, got: {report}"
    item_result = next(r for r in report["results"] if r["id"] == "positioning_read")
    assert item_result["status"] == "OK", f"expected OK, got: {item_result}"


def test_run_checklist_positioning_read_optional_missing_when_absent(tmp_path, monkeypatch):
    """When positioning.json lacks the positioning_read.tilt field, the
    (optional) item reports OPTIONAL_MISSING rather than blocking."""
    workspace = tmp_path / "workspace"
    ticker_dir = workspace / "XYZ"
    ticker_dir.mkdir(parents=True)
    monkeypatch.setattr(ppc, "WORKSPACE_BASE", workspace)

    import json as _json
    (ticker_dir / "positioning.json").write_text(_json.dumps({
        "something_else": {"tilt": "long bias"},
    }))

    minimal_checklist = [i for i in ppc.DEFAULT_CHECKLIST if i["id"] == "positioning_read"]
    report = ppc.run_checklist("user", "XYZ", minimal_checklist)
    item_result = next(r for r in report["results"] if r["id"] == "positioning_read")
    assert item_result["status"] == "OPTIONAL_MISSING"
