"""
Tests for provenance.py (P1-6) and PreviewRunner provenance integration.

Covers:
  - make_record returns a well-formed initial record with env capture
  - add_stage_outcome appends to stages list
  - add_artifact captures size, mtime, sha256
  - finalize sets ended_at and audit-summary fields
  - write persists to disk
  - PreviewRunner.run_stage automatically appends to provenance
  - PreviewRunner.write_provenance produces the file with full content
  - Best-effort: failures inside helpers don't propagate
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import provenance as prov
import preview_runner as pr


# ─── make_record ────────────────────────────────────────────────────────

def test_make_record_initializes_fields():
    t = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
    r = prov.make_record("XYZ", "user", "symbiotic", "RUN-1", started_at=t)
    assert r["schema_version"] == "v1"
    assert r["ticker"] == "XYZ"
    assert r["analyst"] == "user"
    assert r["mode"] == "symbiotic"
    assert r["run_id"] == "RUN-1"
    assert r["started_at"] == "2026-05-04T12:00:00Z"
    assert r["ended_at"] is None
    assert r["stages"] == []
    assert r["artifacts"] == []
    assert r["audit_score"] is None
    assert r["gate"] is None
    assert isinstance(r["env"], dict)
    assert r["env"]["python_version"]
    assert r["env"]["platform"]


# ─── stages ─────────────────────────────────────────────────────────────

def test_add_stage_outcome_appends():
    r = prov.make_record("X", "a", "symbiotic", "RUN")
    stage_dict = {
        "stage": "AUTO_DISCOVER", "status": "PASS",
        "block_reason": None, "next_stage": "DEEP_READ",
        "artifacts": ["/tmp/a", "/tmp/b"],
    }
    t = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
    prov.add_stage_outcome(r, stage_dict, completed_at=t)
    assert len(r["stages"]) == 1
    s = r["stages"][0]
    assert s["stage"] == "AUTO_DISCOVER"
    assert s["status"] == "PASS"
    assert s["next_stage"] == "DEEP_READ"
    assert s["artifact_count"] == 2
    assert s["completed_at"] == "2026-05-04T12:00:00Z"


def test_add_stage_outcome_failures_dont_propagate():
    """A malformed stage_result dict must not raise; record _record_errors."""
    r = prov.make_record("X", "a", "symbiotic", "RUN")
    # Pass a non-dict — would normally raise on `.get`
    prov.add_stage_outcome(r, "not a dict")  # type: ignore
    # The accumulator may have logged or no-op'd; either way, no exception
    assert isinstance(r.get("_record_errors", []), list)


# ─── artifacts ──────────────────────────────────────────────────────────

def test_add_artifact_captures_sha256_and_size(tmp_path):
    r = prov.make_record("X", "a", "symbiotic", "RUN")
    f = tmp_path / "data.bin"
    payload = b"hello provenance"
    f.write_bytes(payload)
    prov.add_artifact(r, f)
    assert len(r["artifacts"]) == 1
    a = r["artifacts"][0]
    assert a["path"] == str(f)
    assert a["size_bytes"] == len(payload)
    assert a["sha256"] == hashlib.sha256(payload).hexdigest()
    assert a["mtime_utc"]


def test_add_artifact_skips_nonexistent_path():
    r = prov.make_record("X", "a", "symbiotic", "RUN")
    prov.add_artifact(r, "/this/path/does/not/exist")
    assert r["artifacts"] == []


def test_add_artifact_failures_dont_propagate(monkeypatch):
    r = prov.make_record("X", "a", "symbiotic", "RUN")
    # Provide a path that exists but is unreadable. Simplest: monkeypatch
    # _file_sha256 to raise.
    def explode(path, max_bytes=0):
        raise RuntimeError("simulated")
    monkeypatch.setattr(prov, "_file_sha256", explode)
    # Even if the helper raises, add_artifact must not propagate
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"x")
        path = f.name
    prov.add_artifact(r, path)
    Path(path).unlink()
    # A _record_errors entry is recorded
    assert any("simulated" in e or "RuntimeError" in e
               for e in r.get("_record_errors", []))


# ─── finalize / write ───────────────────────────────────────────────────

def test_finalize_sets_summary_fields():
    r = prov.make_record("X", "a", "symbiotic", "RUN")
    t = datetime(2026, 5, 4, 12, 30, 0, tzinfo=timezone.utc)
    prov.finalize(r, audit_score=92, gate="GREEN",
                  fail_severity_count=0, ended_at=t)
    assert r["ended_at"] == "2026-05-04T12:30:00Z"
    assert r["audit_score"] == 92
    assert r["gate"] == "GREEN"
    assert r["fail_severity_count"] == 0


def test_finalize_hashes_manifest(tmp_path):
    r = prov.make_record("X", "a", "symbiotic", "RUN")
    m = tmp_path / "manifest.json"
    m.write_text('{"manifest_version": "v1"}')
    prov.finalize(r, manifest_path=m)
    assert r["manifest_path"] == str(m)
    assert r["manifest_sha256"] == hashlib.sha256(m.read_bytes()).hexdigest()


def test_write_persists_record(tmp_path):
    r = prov.make_record("X", "a", "symbiotic", "RUN")
    out = tmp_path / "deep" / "nested" / "_provenance.json"
    written = prov.write(r, out)
    assert written == out
    loaded = json.loads(out.read_text())
    assert loaded["run_id"] == "RUN"


# ─── PreviewRunner integration ──────────────────────────────────────────

@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "ticker_dir", lambda t: tmp_path / "workspace" / t.upper())
    monkeypatch.setattr(pr, "REFERENCE_BASE", tmp_path / "Reference Files")
    r = pr.PreviewRunner(ticker="XYZ", analyst="user", mode="symbiotic")
    return r


def test_runner_provenance_initialized_on_init(runner):
    p = runner._provenance
    assert p["ticker"] == "XYZ"
    assert p["analyst"] == "user"
    assert p["mode"] == "symbiotic"
    assert p["run_id"] == runner.run_id
    assert p["stages"] == []


def test_runner_run_stage_appends_to_provenance(runner):
    """run_stage must record the outcome in provenance regardless of status."""
    # AUTO_DISCOVER inventories the workspace and PASSes (no hard gate now).
    r = runner.run_stage("AUTO_DISCOVER")
    assert r.status == "PASS"
    assert len(runner._provenance["stages"]) == 1
    assert runner._provenance["stages"][0]["stage"] == "AUTO_DISCOVER"
    assert runner._provenance["stages"][0]["status"] == "PASS"


def test_runner_write_provenance_writes_to_default_path(runner):
    runner.run_stage("AUTO_DISCOVER")
    out = runner.write_provenance()
    assert out.name == f"_provenance_{runner.run_id}.json"
    assert out.parent == runner.outputs_dir
    loaded = json.loads(out.read_text())
    assert loaded["run_id"] == runner.run_id
    assert len(loaded["stages"]) == 1
    assert loaded["ended_at"] is not None  # finalize ran


def test_runner_write_provenance_explicit_path(runner, tmp_path):
    runner.run_stage("AUTO_DISCOVER")
    explicit = tmp_path / "custom_prov.json"
    out = runner.write_provenance(explicit)
    assert out == explicit
    assert explicit.exists()


def test_runner_write_provenance_picks_up_audit_json(runner, tmp_path):
    """When _audit.json exists, write_provenance reads gate/score/fail_count from it."""
    runner.outputs_dir.mkdir(parents=True, exist_ok=True)
    audit_json = runner.outputs_dir / "_audit.json"
    audit_json.write_text(json.dumps({
        "score": 95, "gate": "BLOCK", "fail_severity_count": 11,
    }))
    # Synthesize a stage record so the look-up triggers
    runner._provenance["stages"].append({"stage": "AUDIT"})
    out = runner.write_provenance()
    loaded = json.loads(out.read_text())
    assert loaded["audit_score"] == 95
    assert loaded["gate"] == "BLOCK"
    assert loaded["fail_severity_count"] == 11
