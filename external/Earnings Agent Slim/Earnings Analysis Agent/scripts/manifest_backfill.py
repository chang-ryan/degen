"""
manifest_backfill.py — synthesize manifest entries from existing data
artifacts so previously-rendered previews can pass D-02-MANIFEST-COVERAGE.

Background: data_manifest.json is the provenance gate backing D-01-FRESH
and D-02-MANIFEST-COVERAGE. New runs populate the manifest as data is
gathered. But previews rendered before a manifest existed have empty
manifests — every required metric in config.yaml fails the coverage
check, so those previews permanently BLOCK.

This helper bridges that gap. It walks `workspace/{TICKER}/` for evidence
that a metric was gathered (presence of `key_metrics.yaml` is the most
reliable proxy) and writes a manifest entry for each config.key_metric.

The entries are HONEST about staleness: `pulled_at` is set to the file's
mtime in UTC. The freshness gate (D-01-FRESH, default 24h) will then
correctly BLOCK old data, signaling that a re-pull is needed before
delivery. The backfill does NOT manufacture fresh timestamps to make
stale data appear current.

Idempotent: if the manifest already has an entry for a (tool, metric,
period) tuple, the backfill skips it. Safe to re-run.

Usage:
    python3 manifest_backfill.py --ticker XYZ
    python3 manifest_backfill.py --ticker XYZ --dry-run

Exit codes:
    0 = success (manifest backfilled or already complete)
    1 = error (config missing, invalid period, no key_metrics)
    2 = manifest write failed
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _paths import ticker_dir as _ws_ticker_dir
from data_manifest import (
    init_manifest, load_manifest, append_entry, _iso, find_missing_metrics,
)
from fiscal_period import normalize_fiscal_period


_BACKFILL_TOOL_NAME = "key_metrics.yaml_backfill"


def _read_config(ticker_dir: Path) -> tuple[str | None, list[str], dict, str | None]:
    """Read fiscal_period_in_focus + key_metrics + backfill_paths from config.yaml.

    Returns (canonical_period, key_metrics_list, backfill_paths_dict, error_or_None).

    `backfill_paths` is the optional opt-in v2 mapping. Shape:

        backfill_paths:
          revenue_total:
            current_period: guidance_issued_2026_02_24.Q1_2026.revenue.mid
            prior_year_period: historical_actuals.Q1_2025.revenue
          adj_ebitda_margin:
            current_period: guidance_issued_2026_02_24.Q1_2026.ebitda_margin_at_mid_pct

    Each entry is a dict mapping role-name (current_period, prior_year_period, ...)
    to a dotted path in key_metrics.yaml. Backfill resolves the path and uses
    the extracted value in the manifest entry. Without backfill_paths,
    backfill writes value=null (v1 behavior).
    """
    cfg = ticker_dir / "config.yaml"
    if not cfg.exists():
        return None, [], {}, f"config.yaml not found at {cfg}"
    try:
        import yaml
    except ImportError:
        return None, [], {}, "PyYAML not installed"
    try:
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except Exception as e:
        return None, [], {}, f"config.yaml parse error: {e}"
    # Period
    canonical = None
    for key in ("fiscal_period_in_focus", "fiscal_period", "quarter"):
        if key in data and data[key]:
            canonical, _ = normalize_fiscal_period(str(data[key]))
            if canonical:
                break
    if not canonical:
        return None, [], {}, "no parseable fiscal period in config.yaml"
    # Key metrics
    kms_raw = data.get("key_metrics", [])
    if not isinstance(kms_raw, list):
        return canonical, [], {}, f"config.yaml.key_metrics is {type(kms_raw).__name__}, expected list"
    kms = [str(m).strip() for m in kms_raw if m and str(m).strip()]
    if not kms:
        return canonical, [], {}, "config.yaml.key_metrics is empty"
    # Optional backfill_paths
    bp_raw = data.get("backfill_paths", {}) or {}
    if not isinstance(bp_raw, dict):
        bp_raw = {}
    return canonical, kms, bp_raw, None


def _resolve_dotted_path(data: Any, path: str) -> tuple[Any, str | None]:
    """Walk a dotted path through a nested dict/list. Returns (value, error).

    Examples:
        guidance_issued_2026_02_24.Q1_2026.revenue.mid → walks 4 levels
        historical_actuals.Q1_2025.revenue            → walks 3 levels

    Returns (None, "path component X not found at level Y") on miss.
    Returns (value, None) on hit. The value is whatever the YAML parsed —
    typically number, string, or dict (when the path stops at a sub-tree).
    """
    if not path or not isinstance(path, str):
        return None, "path is empty or non-string"
    parts = path.split(".")
    cur: Any = data
    for i, p in enumerate(parts):
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
            continue
        return None, f"path component {p!r} not found at depth {i + 1} (full path: {path!r})"
    return cur, None


def _extract_backfill_value(km_yaml: dict, mapping: Any, role: str = "current_period") -> tuple[Any, str | None]:
    """Given a key_metrics.yaml dict and the per-metric mapping for a single
    metric, resolve the path for `role` and return (value, error).

    `mapping` may be a string (treated as the path for the default role)
    or a dict {role: path}. Returns (None, "no path declared") if the
    role isn't present.
    """
    if isinstance(mapping, str):
        path = mapping
    elif isinstance(mapping, dict):
        path = mapping.get(role)
        if not path:
            return None, f"no '{role}' path declared in mapping"
    else:
        return None, f"mapping is {type(mapping).__name__}, expected str or dict"
    return _resolve_dotted_path(km_yaml, path)


def _file_mtime_iso(path: Path) -> str:
    return _iso(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))


def backfill(ticker: str, analyst: str = "user", *, dry_run: bool = False) -> dict:
    """Backfill the manifest from key_metrics.yaml for the given ticker.

    Returns a result dict with: status, ticker, analyst, period, manifest_path,
    metrics_added, metrics_already_present, mtime_anchor, error (if any).
    """
    ticker = ticker.upper()
    tdir = _ws_ticker_dir(ticker)
    data_dir = tdir / "data"
    manifest_path = data_dir / "data_manifest.json"
    km_path = tdir / "key_metrics.yaml"

    period, key_metrics, backfill_paths, err = _read_config(tdir)
    if err:
        return {
            "status": "error", "error": err,
            "ticker": ticker, "analyst": analyst,
        }

    if not km_path.exists():
        return {
            "status": "error",
            "error": f"key_metrics.yaml not found at {km_path} — nothing to back-fill from",
            "ticker": ticker, "analyst": analyst, "period": period,
        }

    pulled_at = _file_mtime_iso(km_path)

    # v2: load key_metrics.yaml so we can resolve dotted paths from
    # config.yaml.backfill_paths. Tolerant on parse failure — falls back
    # to v1 behavior (value=null per entry).
    km_yaml: dict = {}
    if backfill_paths:
        try:
            import yaml
            parsed = yaml.safe_load(km_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                km_yaml = parsed
        except Exception:
            km_yaml = {}

    if dry_run:
        # Simulate: load (or simulate) the manifest, compute what would be added.
        existing_metrics: list[str] = []
        if manifest_path.exists():
            try:
                m = load_manifest(manifest_path)
                # Find which key_metrics are already covered for the focus period
                missing = find_missing_metrics(m, key_metrics, period=period)
                existing_metrics = [km for km in key_metrics if km not in missing]
                to_add = missing
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"existing manifest at {manifest_path} is unloadable: {e}",
                    "ticker": ticker, "analyst": analyst, "period": period,
                }
        else:
            to_add = list(key_metrics)
        return {
            "status": "dry_run", "ticker": ticker, "analyst": analyst,
            "period": period, "manifest_path": str(manifest_path),
            "mtime_anchor": pulled_at, "key_metrics_count": len(key_metrics),
            "would_add": to_add, "already_present": existing_metrics,
        }

    # Real run: ensure manifest exists, then append missing entries.
    data_dir.mkdir(parents=True, exist_ok=True)
    if not manifest_path.exists():
        init_manifest(ticker, analyst, period, manifest_path)
    else:
        # Validate the existing manifest first
        try:
            m_existing = load_manifest(manifest_path)
        except Exception as e:
            return {
                "status": "error",
                "error": f"existing manifest at {manifest_path} fails validation: {e}",
                "ticker": ticker, "analyst": analyst, "period": period,
            }
        if m_existing.get("fiscal_period_in_focus") != period:
            return {
                "status": "error",
                "error": (
                    f"existing manifest fiscal_period={m_existing.get('fiscal_period_in_focus')!r} "
                    f"does not match config period={period!r}; backfill refuses to mix periods"
                ),
                "ticker": ticker, "analyst": analyst, "period": period,
            }

    # Append entries for metrics not yet covered
    manifest = load_manifest(manifest_path)
    missing = find_missing_metrics(manifest, key_metrics, period=period)
    metrics_already_present = [km for km in key_metrics if km not in missing]
    metrics_added: list[str] = []
    metrics_with_extracted_values: list[str] = []
    metrics_with_extraction_errors: list[dict] = []

    for metric in missing:
        # v2: try to extract a real value from key_metrics.yaml via the
        # config-declared path. If extraction succeeds, use the value;
        # if it fails (or no path declared), fall back to value=null.
        extracted_value = None
        extraction_note = ""
        if backfill_paths and metric in backfill_paths:
            mapping = backfill_paths[metric]
            value, err = _extract_backfill_value(km_yaml, mapping, role="current_period")
            if value is not None and err is None:
                extracted_value = value
                metrics_with_extracted_values.append(metric)
                extraction_note = f" Value extracted from key_metrics.yaml at config-declared path."
            elif err:
                metrics_with_extraction_errors.append({"metric": metric, "error": err})
                extraction_note = f" Path extraction failed: {err}; fell back to value=null."

        entry = {
            "source_id": f"backfill_{metric}_{period}_{pulled_at}",
            "tool_name": _BACKFILL_TOOL_NAME,
            "ticker": ticker,
            "period": period,
            "metric": metric,
            "value": extracted_value,
            "unit": None,
            "pulled_at": pulled_at,
            "source_url": str(km_path),
            "notes": (
                "Backfilled by manifest_backfill.py from key_metrics.yaml file mtime. "
                "The file's mtime anchors D-01-FRESH honestly — if the file is stale, "
                "the audit will BLOCK and the data should be refreshed."
                + extraction_note
            ),
        }
        try:
            append_entry(manifest_path, entry)
            metrics_added.append(metric)
        except ValueError as e:
            return {
                "status": "error",
                "error": f"append_entry failed for metric {metric!r}: {e}",
                "ticker": ticker, "analyst": analyst, "period": period,
                "metrics_added": metrics_added,
            }

    return {
        "status": "complete", "ticker": ticker, "analyst": analyst,
        "period": period, "manifest_path": str(manifest_path),
        "mtime_anchor": pulled_at,
        "key_metrics_count": len(key_metrics),
        "metrics_added": metrics_added,
        "metrics_already_present": metrics_already_present,
        "metrics_with_extracted_values": metrics_with_extracted_values,
        "metrics_with_extraction_errors": metrics_with_extraction_errors,
        "backfill_paths_declared": len(backfill_paths),
    }


def _cli() -> int:
    ap = argparse.ArgumentParser(description=(
        "Backfill data_manifest.json from existing data artifacts so pre-existing "
        "previews pass D-02-MANIFEST-COVERAGE. Honest about staleness — "
        "pulled_at = file mtime, so D-01-FRESH still BLOCKs old data."
    ))
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--analyst", default="user")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be added without writing.")
    args = ap.parse_args()

    result = backfill(args.ticker, args.analyst, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    if result["status"] == "error":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
