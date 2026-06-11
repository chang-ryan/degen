"""
cons_context_check.py — validate your variant against the consensus distribution

Catches stale models and outlier variants. Example: a model that is 5σ below
the consensus mean on a quarter's EBITDA is usually a pre-guide-cut stale
variant — this check flags it.

Inputs:
    - cons_data: dict of {period: {metric: {mean, std, low, high, n}}}
    - variant_data: dict of {period: {metric: value}}
    - model_date: ISO date string of your model file

Outputs:
    - Per-period, per-metric: position vs cons (LOW / Q1 / median / Q3 / HIGH)
    - Z-score below mean
    - Flag: outlier (>3σ), stale (model > 30 days old AND last guide reset more recent)
    - Audit-gate compatible JSON output

Usage (standalone):
    python cons_context_check.py --variant-json variant.json --cons-json cons_metrics.json

Or programmatic:
    from cons_context_check import check_cons_context
    result = check_cons_context(variant_data, cons_data, model_date='2026-04-28', last_guide_reset='2026-02-24')
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Core checks
# ─────────────────────────────────────────────────────────────────────────────

def position_in_dispersion(value: float, low: float, high: float, mean: float, std: float) -> dict:
    """Return position descriptor for a value within a cons distribution."""
    if std == 0 or std is None:
        z = None
    else:
        z = (value - mean) / std

    # Empirical bottom-quartile via linear interpolation between LOW and median
    # (median ≈ mean for symmetric, but if skewed we have to estimate)
    bottom_quartile_norm = mean - 0.674 * std if std else None  # normal-distribution Q1

    if value < low:
        position = "below_LOW"
    elif value <= bottom_quartile_norm if bottom_quartile_norm is not None else False:
        position = "bottom_quartile"
    elif value <= mean:
        position = "between_Q1_and_median"
    elif value <= mean + 0.674 * std if std else False:
        position = "between_median_and_Q3"
    elif value <= high:
        position = "top_quartile"
    else:
        position = "above_HIGH"

    return {
        "value": value,
        "z_score_below_mean": round(z, 3) if z is not None else None,
        "position": position,
        "vs_low_pct": round(100 * (value - low) / low, 2) if low else None,
        "vs_mean_pct": round(100 * (value - mean) / mean, 2) if mean else None,
    }


def is_outlier(z: float | None, threshold: float = 3.0) -> bool:
    """Z-score outlier check."""
    if z is None:
        return False
    return abs(z) > threshold


def is_stale_model(model_date: str, last_guide_reset: str | None, days_threshold: int = 30) -> bool:
    """Stale = model_date > N days old AND a more recent guide reset exists.

    Example: model dated 1/6/26, guide reset 2/24/26. The model is older than the
    most recent guide event, so cells calibrated to old cons may be stale.
    """
    try:
        md = datetime.fromisoformat(model_date.replace("Z", ""))
    except (ValueError, AttributeError):
        return False
    days_old = (datetime.utcnow() - md).days
    if days_old < days_threshold:
        return False
    if last_guide_reset:
        try:
            grd = datetime.fromisoformat(last_guide_reset.replace("Z", ""))
            return grd > md  # guide reset happened AFTER model date → stale
        except (ValueError, AttributeError):
            pass
    return days_old > days_threshold * 3  # >90 days = stale even without guide reset


# ─────────────────────────────────────────────────────────────────────────────
# Aggregator
# ─────────────────────────────────────────────────────────────────────────────

def check_cons_context(
    variant_data: dict,
    cons_data: dict,
    model_date: str | None = None,
    last_guide_reset: str | None = None,
    outlier_z_threshold: float = 3.0,
) -> dict:
    """
    variant_data: {"Q1_2026": {"revenue": 614.9, "ebitda": 38.3}, "Q2_2026": {...}, "FY_2026": {...}}
    cons_data: {"Q1_2026": {"revenue": {"mean": 616.9, "std": 5.86, "low": 608.4, "high": 632.5, "n": 13},
                            "ebitda": {"mean": 46.4, "std": 4.35, ...}}, ...}
    """
    results = {
        "model_date": model_date,
        "last_guide_reset": last_guide_reset,
        "checked_at": datetime.utcnow().isoformat() + "Z",
        "outlier_z_threshold": outlier_z_threshold,
        "stale_model_flag": False,
        "outliers": [],
        "warnings": [],
        "by_period": {},
    }

    # Stale model check
    if model_date:
        results["stale_model_flag"] = is_stale_model(model_date, last_guide_reset)
        if results["stale_model_flag"]:
            results["warnings"].append({
                "severity": "fail",
                "rule_id": "C-01",
                "issue": f"Model dated {model_date} predates most recent guide reset ({last_guide_reset}). "
                         f"Variant cells may not reflect the new guide regime.",
            })

    # Per-period, per-metric check
    for period, metrics in variant_data.items():
        if period not in cons_data:
            continue
        period_result = {}
        for metric, value in metrics.items():
            if metric not in cons_data[period]:
                continue
            cd = cons_data[period][metric]
            pos = position_in_dispersion(
                value=value,
                low=cd.get("low", 0),
                high=cd.get("high", 0),
                mean=cd.get("mean", 0),
                std=cd.get("std", 0),
            )
            period_result[metric] = pos
            if is_outlier(pos["z_score_below_mean"], outlier_z_threshold):
                z = pos["z_score_below_mean"]
                direction = "above" if z > 0 else "below"
                results["outliers"].append({
                    "severity": "fail",
                    "rule_id": "C-02",
                    "period": period,
                    "metric": metric,
                    "value": value,
                    "cons_mean": cd.get("mean"),
                    "cons_std": cd.get("std"),
                    "z_score": z,
                    "position": pos["position"],
                    "issue": f"Variant {metric} for {period} is {abs(z):.2f}σ "
                             f"{direction} cons mean — outside reasonable cons range. Verify model is not stale.",
                })
        results["by_period"][period] = period_result

    # Final status
    has_failures = bool(results["outliers"]) or results["stale_model_flag"]
    results["status"] = "fail" if has_failures else "pass"
    return results


# ─────────────────────────────────────────────────────────────────────────────
# CLI (loads from JSON files)
# ─────────────────────────────────────────────────────────────────────────────

def _cli() -> int:
    ap = argparse.ArgumentParser(description="Validate your variant against the consensus distribution")
    ap.add_argument("--variant-json", required=True,
                    help="JSON: {period: {metric: value}} — your variant numbers")
    ap.add_argument("--cons-json", required=True,
                    help="JSON: {period: {metric: {mean, std, low, high, n}}} — cons dispersion")
    ap.add_argument("--model-date", default=None, help="ISO date of your model (e.g., 2026-04-28)")
    ap.add_argument("--last-guide-reset", default=None,
                    help="ISO date of most recent guide reset (e.g., 2026-02-24)")
    ap.add_argument("--outlier-z", type=float, default=3.0, help="Z-score outlier threshold")
    ap.add_argument("--out", default=None, help="Output JSON path")
    args = ap.parse_args()

    variant_data = json.loads(Path(args.variant_json).read_text())
    cons_data = json.loads(Path(args.cons_json).read_text())

    result = check_cons_context(
        variant_data=variant_data,
        cons_data=cons_data,
        model_date=args.model_date,
        last_guide_reset=args.last_guide_reset,
        outlier_z_threshold=args.outlier_z,
    )

    text = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)

    return 1 if result["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(_cli())
