"""
data_manifest.py — provenance manifest for the earnings preview pipeline.

Per PREVIEW_AGENT_SPEC.md §2 step [3], every metric used in an analysis
(SEC filings, manual entry, Yahoo Finance, etc.) is recorded in a JSON
manifest at:

    workspace/{TICKER}/data/data_manifest.json

The manifest backs three accuracy guarantees:

  1. **Provenance** — every figure in the rendered preview traces back to
     an entry recording the source, ticker, period, metric, value, and
     pulled_at timestamp. If you can't tie a number in the preview to a
     manifest entry, the audit flags it.
  2. **Freshness gate (D-01-FRESH)** — audit_agent.py blocks delivery if
     any required-metric entry is older than `max_age_hours` (default 24).
     This addresses the spec's explicit "stale data" risk: a consensus
     value pulled three weeks ago is not consensus.
  3. **Coverage gate (D-02-MANIFEST-COVERAGE)** — every metric listed in
     `config.yaml.key_metrics` for the focus fiscal period must have at
     least one manifest entry. Missing coverage blocks delivery.

The schema is defined in
    /Earnings Analysis Agent/schemas/data_manifest.schema.json
and validated on every load and append.

Determinism note: this module accepts an explicit `now` parameter on
freshness checks so tests can freeze "current time." Internal append
operations record `pulled_at` in UTC ISO-8601 from the system clock —
that timestamp IS time-dependent by design (the freshness gate's
correctness depends on a wall-clock reference), but it is honest about
what time the pull happened.

Public API:
    init_manifest(ticker, analyst, fiscal_period, manifest_path, *, now=None) -> dict
    load_manifest(manifest_path) -> dict
    append_entry(manifest_path, entry, *, now=None) -> dict
    validate_manifest(manifest) -> list[str]      # empty if valid
    find_stale_entries(manifest, max_age_hours=24, *, now=None) -> list[dict]
    find_missing_metrics(manifest, required_metrics, period=None) -> list[str]
    most_recent_entry_per_key(manifest) -> dict[(tool, metric, period), entry]
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from _paths import earnings_agent_dir

SCHEMA_PATH = earnings_agent_dir() / "schemas" / "data_manifest.schema.json"
MANIFEST_VERSION = "v1"


# ─────────────────────────────────────────────────────────────────────────────
# Time helpers — every time-dependent function accepts an injected `now`
# so tests can freeze the reference clock.
# ─────────────────────────────────────────────────────────────────────────────

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    """ISO-8601 UTC, second precision, `Z` suffix. Stable round-trip with
    `_parse_iso`."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(s: str) -> datetime | None:
    """Parse ISO-8601, returning timezone-aware UTC datetime. Returns None
    if the string isn't a recognizable ISO timestamp."""
    if not isinstance(s, str) or not s:
        return None
    try:
        # Accept both "+00:00" and "Z" terminators
        canonical = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(canonical)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Schema loading + validation
# ─────────────────────────────────────────────────────────────────────────────

_schema_cache: dict | None = None


def _schema() -> dict:
    """Load the JSON Schema from disk, cached for the process lifetime."""
    global _schema_cache
    if _schema_cache is None:
        try:
            _schema_cache = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError as e:
            raise RuntimeError(
                f"data_manifest schema not found at {SCHEMA_PATH}. "
                f"This is a packaging error — the schema must ship with the codebase."
            ) from e
    return _schema_cache


def validate_manifest(manifest: dict) -> list[str]:
    """Return a list of human-readable validation error strings.

    Empty list = valid. Non-empty list means the manifest is malformed and
    callers should reject it.
    """
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema package not installed — cannot validate manifest"]
    try:
        jsonschema.validate(manifest, _schema())
        return []
    except jsonschema.ValidationError as e:
        # ValidationError.path can be empty; build a readable locator.
        loc = "/".join(str(p) for p in e.absolute_path) or "<root>"
        return [f"{loc}: {e.message}"]
    except jsonschema.SchemaError as e:
        return [f"schema is itself invalid: {e.message}"]


# ─────────────────────────────────────────────────────────────────────────────
# Init / load / append
# ─────────────────────────────────────────────────────────────────────────────

def init_manifest(
    ticker: str,
    analyst: str,
    fiscal_period: str,
    manifest_path: str | Path,
    *,
    now: datetime | None = None,
) -> dict:
    """Create a new manifest at `manifest_path` if none exists; otherwise
    return the existing manifest unchanged.

    NEVER overwrites an existing manifest — the existing one is the
    audit-trail-of-record for this preview cycle. If the analyst wants to
    start fresh, the file must be deleted manually.
    """
    p = Path(manifest_path)
    if p.exists():
        return load_manifest(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    iso_now = _iso(now or _utc_now())
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "ticker": ticker,
        "analyst": analyst,
        "fiscal_period_in_focus": fiscal_period,
        "created_at": iso_now,
        "updated_at": iso_now,
        "entries": [],
    }
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError(
            f"init_manifest produced an invalid manifest. "
            f"Likely a bad ticker/period/analyst input. Errors: {errors}"
        )
    p.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def load_manifest(manifest_path: str | Path) -> dict:
    """Read + parse + validate the manifest at the given path.

    Raises FileNotFoundError if the manifest does not exist (the audit
    gate translates this into a coverage failure). Raises ValueError if
    the manifest exists but is malformed.
    """
    p = Path(manifest_path)
    text = p.read_text(encoding="utf-8")
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"manifest at {p} is not valid JSON: {e}") from e
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError(f"manifest at {p} fails schema validation: {errors}")
    return manifest


def append_entry(
    manifest_path: str | Path,
    entry: dict,
    *,
    now: datetime | None = None,
) -> dict:
    """Append `entry` to the manifest's entries list, validate, and write.

    The entry is validated against the schema BEFORE write. If the entry
    is malformed, ValueError is raised and the on-disk manifest is not
    touched. This is intentionally strict — silently dropping a bad
    entry would let an upstream bug accumulate.

    Each call updates `updated_at`. `pulled_at` on the entry is the
    caller's responsibility (typically set to the time the MCP tool
    returned, NOT the time append_entry is called). If the caller omits
    `pulled_at`, this function sets it to `now` for convenience — but
    the contract is: the caller should set it explicitly to be honest
    about freshness.
    """
    manifest = load_manifest(manifest_path)
    entry = dict(entry)
    entry.setdefault("pulled_at", _iso(now or _utc_now()))
    manifest["entries"].append(entry)
    manifest["updated_at"] = _iso(now or _utc_now())
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError(
            f"append_entry produced an invalid manifest after adding entry "
            f"{entry.get('source_id', '<unknown>')}. Errors: {errors}"
        )
    Path(manifest_path).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


# ─────────────────────────────────────────────────────────────────────────────
# Query helpers — used by audit_agent.py
# ─────────────────────────────────────────────────────────────────────────────

def most_recent_entry_per_key(manifest: dict) -> dict:
    """Return a dict keyed by (tool_name, metric, period) → most recent entry.

    When the calling agent re-pulls the same metric (e.g., refresh consensus
    mid-flow), append_entry creates a new entry rather than overwriting —
    audit trail is preserved. The freshness gate then looks at the most
    recent entry per (tool, metric, period) tuple, ignoring older
    superseded entries.
    """
    out: dict = {}
    for e in manifest.get("entries", []):
        key = (e.get("tool_name"), e.get("metric"), e.get("period"))
        existing = out.get(key)
        if existing is None:
            out[key] = e
            continue
        existing_at = _parse_iso(existing.get("pulled_at", ""))
        new_at = _parse_iso(e.get("pulled_at", ""))
        # Prefer the entry with a parseable, later timestamp. Unparseable
        # timestamps lose to parseable ones — they shouldn't be in the
        # manifest at all (schema validates the field as a string, but
        # date-time format isn't enforced by jsonschema 3.x in safe mode).
        if existing_at is None and new_at is not None:
            out[key] = e
        elif new_at is not None and existing_at is not None and new_at > existing_at:
            out[key] = e
    return out


def find_stale_entries(
    manifest: dict,
    max_age_hours: float = 24.0,
    *,
    now: datetime | None = None,
) -> list[dict]:
    """Return the most-recent entry per (tool, metric, period) that is
    older than `max_age_hours`.

    Tests inject `now` to freeze the comparison reference. In production,
    `now` defaults to `datetime.now(UTC)`.

    An entry with an unparseable `pulled_at` is also returned — a
    corrupted timestamp can't be honestly aged, so we treat it as stale
    and let the audit fail loudly.
    """
    ref = now or _utc_now()
    most_recent = most_recent_entry_per_key(manifest)
    stale = []
    for key, entry in most_recent.items():
        ts = _parse_iso(entry.get("pulled_at", ""))
        if ts is None:
            stale.append(entry)
            continue
        age_hours = (ref - ts).total_seconds() / 3600.0
        if age_hours > max_age_hours:
            stale.append(entry)
    return stale


def find_missing_metrics(
    manifest: dict,
    required_metrics: Iterable[str],
    period: str | None = None,
) -> list[str]:
    """Return the subset of `required_metrics` that have no manifest entry
    for the focus `period`.

    Matching rule:
      For each required metric M and period P (defaults to manifest's
      `fiscal_period_in_focus` if None):
        - Match exact: any entry with metric == M and (period == P or
          entry.period == P or entry.period is None for period-agnostic
          metrics).
        - Match period-suffixed: any entry with metric == f"{M}_{P}".

    A metric counts as covered if at least one entry matches.
    """
    if period is None:
        period = manifest.get("fiscal_period_in_focus")
    entries = manifest.get("entries", [])
    missing: list[str] = []
    for m in required_metrics:
        if not m:
            continue
        period_suffixed = f"{m}_{period}" if period else None
        covered = False
        for e in entries:
            metric = e.get("metric")
            entry_period = e.get("period")
            if metric == m:
                # Period-agnostic match (entry.period None) OR period-aligned
                if entry_period is None or entry_period == period:
                    covered = True
                    break
            elif period_suffixed and metric == period_suffixed:
                covered = True
                break
        if not covered:
            missing.append(m)
    return missing


# ─────────────────────────────────────────────────────────────────────────────
# CLI — primarily for ad-hoc inspection / debugging
# ─────────────────────────────────────────────────────────────────────────────

def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="data_manifest helper CLI")
    ap.add_argument("manifest", help="path to data_manifest.json")
    ap.add_argument("--validate", action="store_true", help="validate against schema")
    ap.add_argument("--stale", type=float, default=None,
                    help="report stale entries older than N hours")
    ap.add_argument("--missing", nargs="+", default=None,
                    help="check coverage for these metric names")
    args = ap.parse_args()

    manifest = load_manifest(args.manifest)
    if args.validate:
        errors = validate_manifest(manifest)
        if errors:
            print(json.dumps({"status": "invalid", "errors": errors}, indent=2))
            return 1
        print(json.dumps({"status": "valid"}))
    if args.stale is not None:
        stale = find_stale_entries(manifest, max_age_hours=args.stale)
        print(json.dumps({"stale_count": len(stale), "stale": stale}, indent=2, default=str))
    if args.missing:
        missing = find_missing_metrics(manifest, args.missing)
        print(json.dumps({"missing": missing}, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
