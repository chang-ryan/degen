"""
provenance.py — per-run audit-trail capture for the earnings preview pipeline.

Why this exists: after a preview is rendered and the user overrides
something, there is otherwise no central record of what data went into the
run. The manifest captures upstream pulls; the audit captures gate decisions.
Provenance ties them together with: which stages ran, what artifacts they
produced, when each ran, what their gate outcomes were, and the environment
versions.

Public API:
    make_record(ticker, analyst, mode, run_id, *, started_at=None) -> dict
    add_stage_outcome(record, stage_result_dict) -> None     (in-place)
    add_artifact(record, path) -> None                       (in-place; computes sha256+mtime)
    finalize(record, *, audit_score=None, gate=None,
             fail_severity_count=None, manifest_path=None,
             ended_at=None) -> None                          (in-place)
    write(record, output_path) -> Path

The record schema (informal):

    {
      "schema_version": "v1",
      "run_id": "XYZ_user_20260504_193847",
      "ticker": "XYZ",
      "analyst": "user",
      "mode": "symbiotic",
      "started_at": "2026-05-04T19:38:47Z",
      "ended_at": "2026-05-04T19:42:11Z",
      "env": {
        "python_version": "3.10.12",
        "jsonschema_version": "...",
        "pyyaml_version": "...",
        "platform": "linux"
      },
      "stages": [
        {"stage": "AUTO_DISCOVER", "status": "PASS", "block_reason": null,
         "next_stage": "DEEP_READ", "completed_at": "..."},
        ...
      ],
      "artifacts": [
        {"path": ".../sources/price_targets.json", "size": 1234,
         "mtime": "2026-05-04T19:30:00Z", "sha256": "..."},
        ...
      ],
      "audit_score": 95,
      "gate": "BLOCK",
      "fail_severity_count": 11,
      "manifest_path": "...",
      "manifest_sha256": "..."
    }

Provenance is best-effort: failures inside provenance helpers (e.g., a file
becoming unreadable mid-run) NEVER propagate. The accumulator stores a
"_record_errors" list with any incidents so the operator can investigate
without losing the rest of the audit trail.

Determinism: every timestamp is derived from `now_utc=` injection or
`datetime.now(UTC)`. SHA-256 hashes are deterministic given the same input.
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "v1"


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_lib_version(module_name: str) -> str | None:
    try:
        mod = __import__(module_name)
    except ImportError:
        return None
    for attr in ("__version__", "version", "VERSION"):
        v = getattr(mod, attr, None)
        if v:
            return str(v)
    return None


def _make_env_entry() -> dict:
    return {
        "python_version": ".".join(str(p) for p in sys.version_info[:3]),
        "jsonschema_version": _safe_lib_version("jsonschema"),
        "pyyaml_version": _safe_lib_version("yaml"),
        "platform": platform.system().lower(),
    }


def make_record(
    ticker: str,
    analyst: str,
    mode: str,
    run_id: str,
    *,
    started_at: datetime | None = None,
) -> dict:
    """Return an initial provenance record. Mutate in-place via add_*/finalize."""
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "ticker": ticker,
        "analyst": analyst,
        "mode": mode,
        "started_at": _iso(started_at or _utc_now()),
        "ended_at": None,
        "env": _make_env_entry(),
        "stages": [],
        "artifacts": [],
        "audit_score": None,
        "gate": None,
        "fail_severity_count": None,
        "manifest_path": None,
        "manifest_sha256": None,
        "_record_errors": [],
    }


def add_stage_outcome(
    record: dict,
    stage_result: dict,
    *,
    completed_at: datetime | None = None,
) -> None:
    """Append a stage's outcome to record["stages"].

    `stage_result` is the StageResult.asdict() output from preview_runner.
    We capture the small set of fields useful for audit trail and skip
    bulky fields (dispatch_instructions can be tens of KB; questions
    are interactive only).
    """
    try:
        record["stages"].append({
            "stage": stage_result.get("stage"),
            "status": stage_result.get("status"),
            "block_reason": stage_result.get("block_reason"),
            "next_stage": stage_result.get("next_stage"),
            "artifact_count": len(stage_result.get("artifacts", []) or []),
            "completed_at": _iso(completed_at or _utc_now()),
        })
    except Exception as e:
        record.setdefault("_record_errors", []).append(
            f"add_stage_outcome failed: {type(e).__name__}: {e}"
        )


def _file_sha256(path: Path, *, max_bytes: int = 50_000_000) -> str | None:
    """Compute sha256 of a file. Returns None if unreadable.

    `max_bytes` caps the read to avoid hashing very large files (we don't
    care about the audit trail of a 500MB attachment in the synthesis
    folder, for example).
    """
    try:
        h = hashlib.sha256()
        read = 0
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                if read + len(chunk) > max_bytes:
                    h.update(chunk[: max_bytes - read])
                    break
                h.update(chunk)
                read += len(chunk)
        return h.hexdigest()
    except OSError:
        return None


def add_artifact(record: dict, path: str | Path) -> None:
    """Append an artifact entry for `path` (path, size, mtime, sha256).

    Silently no-ops if the file doesn't exist. Errors are captured in
    record["_record_errors"] without propagating.
    """
    try:
        p = Path(path)
        if not p.is_file():
            return
        st = p.stat()
        record["artifacts"].append({
            "path": str(p),
            "size_bytes": st.st_size,
            "mtime_utc": _iso(datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)),
            "sha256": _file_sha256(p),
        })
    except Exception as e:
        record.setdefault("_record_errors", []).append(
            f"add_artifact({path}) failed: {type(e).__name__}: {e}"
        )


def finalize(
    record: dict,
    *,
    audit_score: int | float | None = None,
    gate: str | None = None,
    fail_severity_count: int | None = None,
    manifest_path: str | Path | None = None,
    ended_at: datetime | None = None,
) -> None:
    """Set ended_at and audit-summary fields. Hashes the manifest if given."""
    try:
        record["ended_at"] = _iso(ended_at or _utc_now())
        if audit_score is not None:
            record["audit_score"] = audit_score
        if gate is not None:
            record["gate"] = gate
        if fail_severity_count is not None:
            record["fail_severity_count"] = fail_severity_count
        if manifest_path is not None:
            record["manifest_path"] = str(manifest_path)
            mp = Path(manifest_path)
            if mp.is_file():
                record["manifest_sha256"] = _file_sha256(mp)
    except Exception as e:
        record.setdefault("_record_errors", []).append(
            f"finalize failed: {type(e).__name__}: {e}"
        )


def write(record: dict, output_path: str | Path) -> Path:
    """Serialize `record` to JSON at output_path. Creates parent dirs.

    Returns the resolved path. Raises only if the underlying write fails;
    the in-memory record is not consumed.
    """
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return p
