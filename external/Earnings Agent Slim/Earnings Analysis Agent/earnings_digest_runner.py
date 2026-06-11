#!/usr/bin/env python3
"""
earnings_digest_runner.py — post-print earnings digest agent.

Two stages:
  Stage 1 (post-print, pre-call):  digest [TICKER] print
  Stage 2 (transcript-integrated): digest [TICKER] transcript

Implements the workflow defined in DIGEST_AGENT_SPEC.md.

Architecture: this runner does the DETERMINISTIC plumbing. The unstructured
text → structured data step (extract numbers from press release / transcript)
is delegated to the agent by emitting an extraction-prompt JSON that
the agent fills in. The runner picks up the filled JSON and continues.

Phases:
  fetch_baseline         load preview output + cons + positioning + guidance
  fetch_print_materials  pull 8-K via SEC EDGAR + IR site fallback
  request_extraction     emit prompts for the agent to fill actuals.json
  compute_scorecard      beat/miss + guide deltas vs baseline
  draft_skeleton         fill template with deterministic sections, leave
                         narrative sections for the agent to fill
  request_narrative      emit prompts for narrative sections
  audit                  run audit_agent.py against draft
  render                 pandoc + weasyprint → PDF

Usage:
  python earnings_digest_runner.py --ticker XYZ --period C1Q26 \\
      --mode print --phase fetch_baseline
  python earnings_digest_runner.py --ticker XYZ --period C1Q26 \\
      --mode print --phase fetch_print_materials
  ... etc
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_BASE = REPO_ROOT / "workspace"
RUNNER_VERSION = "0.1.0"
AGENT_ID_PRINT = "earnings-analysis-stage-2"
AGENT_ID_TRANSCRIPT = "earnings-analysis-stage-3"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def ticker_root(analyst: str, ticker: str) -> Path:
    # `analyst` is retained only for call-signature compatibility; it no
    # longer affects the path. Everything collapses to workspace/{TICKER}/...
    return WORKSPACE_BASE / ticker.upper()


def outputs_dir(analyst: str, ticker: str) -> Path:
    p = ticker_root(analyst, ticker) / "outputs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def print_materials_dir(analyst: str, ticker: str, period: str) -> Path:
    p = ticker_root(analyst, ticker) / "print_materials" / period
    p.mkdir(parents=True, exist_ok=True)
    return p


def digest_workdir(analyst: str, ticker: str, period: str) -> Path:
    p = ticker_root(analyst, ticker) / "digest_work" / period
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Phase 1 — Baseline assembly
# ---------------------------------------------------------------------------


def find_latest_preview(analyst: str, ticker: str) -> Path | None:
    """Return the highest-versioned preview markdown for the ticker."""
    out = outputs_dir(analyst, ticker)
    candidates: list[tuple[int, Path]] = []
    for p in out.glob("*PREVIEW*V*.md"):
        m = re.search(r"V(\d+)\.md$", p.name)
        if m:
            candidates.append((int(m.group(1)), p))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    return candidates[-1][1]


def parse_kpi_tables_from_preview(md_path: Path) -> dict[str, list[dict]]:
    """Extract the 3 KPI tables (current Q, Q+1, FY) from preview markdown.

    Each KPI table is preceded by a bold period header like `**1Q26**` or
    `**FY26**`. Header row is `| Metric | Co Guide | Variant | y/y | Cons | y/y | Δ vs Cons |`.

    Returns: {period_label: [ {metric, co_guide, variant, variant_yoy, cons, cons_yoy, delta_vs_cons}, ... ]}
    """
    text = md_path.read_text()
    period_pat = re.compile(r"^\s*\*\*(\d+Q\d{2}|FY\d{2})\*\*", re.MULTILINE)
    period_matches = list(period_pat.finditer(text))

    tables: dict[str, list[dict]] = {}
    for i, m in enumerate(period_matches):
        period = m.group(1)
        start = m.end()
        end = (
            period_matches[i + 1].start()
            if i + 1 < len(period_matches)
            else len(text)
        )
        chunk = text[start:end]

        rows: list[dict] = []
        in_table = False
        skipped_separator = False
        for line in chunk.splitlines():
            line = line.rstrip()
            if line.startswith("| Metric"):
                in_table = True
                skipped_separator = False
                continue
            if in_table:
                if line.startswith("|---"):
                    skipped_separator = True
                    continue
                if not line.startswith("|"):
                    if rows:
                        break
                    continue
                if not skipped_separator:
                    continue
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) < 7:
                    continue
                metric, co_guide, variant, variant_yoy, cons, cons_yoy, delta = cells[
                    :7
                ]
                rows.append(
                    {
                        "metric": _strip_md_bold(metric),
                        "co_guide": _strip_md_bold(co_guide),
                        "variant_value": _strip_md_bold(variant),
                        "variant_yoy": _strip_md_bold(variant_yoy),
                        "cons_value": _strip_md_bold(cons),
                        "cons_yoy": _strip_md_bold(cons_yoy),
                        "delta_vs_cons": _strip_md_bold(delta),
                    }
                )
        if rows:
            tables[period] = rows
    return tables


def _strip_md_bold(s: str) -> str:
    return s.replace("**", "").strip()


def load_consensus_csv(csv_path: Path) -> dict[str, dict] | None:
    """Load consensus.csv into {metric: {fy24a, fy25a, fy26e, fy27e, ...}}.

    Skip comment lines starting with #.
    """
    if not csv_path.exists():
        return None
    rows: dict[str, dict] = {}
    headers: list[str] | None = None
    for raw in csv_path.read_text().splitlines():
        if raw.strip().startswith("#") or not raw.strip():
            continue
        cells = [c.strip() for c in raw.split(",")]
        if headers is None:
            headers = cells
            continue
        if len(cells) < 2 or not cells[0]:
            continue
        row = dict(zip(headers, cells))
        rows[cells[0]] = row
    return rows


def load_positioning(analyst: str, ticker: str) -> dict | None:
    p = ticker_root(analyst, ticker) / "positioning.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def load_key_metrics(analyst: str, ticker: str) -> dict | None:
    p = ticker_root(analyst, ticker) / "key_metrics.yaml"
    if not p.exists():
        return None
    try:
        import yaml  # type: ignore

        return yaml.safe_load(p.read_text())
    except ImportError:
        # Lazy fallback: minimal YAML parse for our flat structure
        return {"raw_text": p.read_text()}


def load_guidance_history(analyst: str, ticker: str) -> dict[str, str]:
    """Read all files in /guidance/ — return {filename_stem: text}."""
    out: dict[str, str] = {}
    g = ticker_root(analyst, ticker) / "guidance"
    if not g.exists():
        return out
    for f in sorted(g.iterdir()):
        if f.is_file() and f.suffix in {".md", ".txt", ".json"}:
            try:
                out[f.stem] = f.read_text()
            except Exception:
                pass
    return out


def assemble_baseline(analyst: str, ticker: str, period: str) -> dict:
    """Assemble digest_baseline.json — single source of truth for expectations."""
    preview = find_latest_preview(analyst, ticker)
    kpi_tables = parse_kpi_tables_from_preview(preview) if preview else {}

    cons_csv = load_consensus_csv(
        ticker_root(analyst, ticker) / "consensus.csv"
    )
    positioning = load_positioning(analyst, ticker)
    key_metrics = load_key_metrics(analyst, ticker)
    guidance = load_guidance_history(analyst, ticker)

    baseline = {
        "schema_version": "digest_baseline_v0.1",
        "assembled_at": datetime.utcnow().isoformat() + "Z",
        "ticker": ticker,
        "analyst": analyst,
        "period": period,
        "preview_source": str(preview) if preview else None,
        "kpi_tables": kpi_tables,
        "consensus_csv_loaded": cons_csv is not None,
        "consensus_metrics": cons_csv if cons_csv else {},
        "positioning": positioning,
        "key_metrics_yaml": key_metrics,
        "guidance_files": list(guidance.keys()),
        "guidance_contents": guidance,
    }
    return baseline


# ---------------------------------------------------------------------------
# Phase 2 — Print materials retrieval
# ---------------------------------------------------------------------------


def emit_8k_fetch_request(analyst: str, ticker: str, period: str) -> Path:
    """Emit a JSON request that the agent fulfills via free SEC EDGAR.

    The runner writes an instruction file the agent picks up; the agent runs
    the free EDGAR fetch helper, then writes the press release text back.
    """
    workdir = digest_workdir(analyst, ticker, period)
    today = date.today().isoformat()
    request = {
        "request_type": "fetch_earnings_8k",
        "ticker": ticker,
        "analyst": analyst,
        "period": period,
        "fetch_date_window": {"start": today, "end": today},
        "instructions": [
            "1. Run `python scripts/edgar_fetch.py --ticker {TICKER}` "
            "(free SEC EDGAR). It pulls the latest 8-K / earnings-release "
            "extracts and writes them to workspace/{TICKER}/filings/.".replace(
                "{TICKER}", ticker.upper()
            ),
            "2. Read latest_earnings_8K.txt from "
            "workspace/{TICKER}/filings/ — this is the earnings 8-K "
            "(item 2.02, Results of Operations and Financial Condition).".replace(
                "{TICKER}", ticker.upper()
            ),
            "3. Extract the press-release body text and save raw text to "
            "press_release.txt in this workdir.",
            "4. If a slide deck or prepared remarks were also fetched, "
            "save their bodies too as earnings_deck.txt and "
            "prepared_remarks.txt.",
            "5. Write a manifest.json with: source filing, datefiled, "
            "extract list, file paths, fetch_timestamp.",
            "6. If no 8-K filed today, write manifest.json with "
            "status=no_print_yet and exit.",
        ],
        "expected_outputs": [
            str(workdir / "press_release.txt"),
            str(workdir / "earnings_deck.txt (optional)"),
            str(workdir / "prepared_remarks.txt (optional)"),
            str(workdir / "manifest.json"),
        ],
        "ir_fallback_url_hint": _ir_fallback_url(ticker),
    }
    out = workdir / "fetch_request.json"
    out.write_text(json.dumps(request, indent=2))
    return out


def _ir_fallback_url(ticker: str) -> str:
    """Best-guess IR site fallback for tickers that file PR-only in 8-K.

    No per-ticker IR URL configured; check the company's investor-relations
    site. Callers can override via config.yaml later.
    """
    known: dict[str, str] = {}
    return known.get(ticker, "")


# ---------------------------------------------------------------------------
# Phase 3 — Numerical extraction
# ---------------------------------------------------------------------------


def emit_extraction_request(analyst: str, ticker: str, period: str) -> Path:
    """Emit a prompt instructing the agent to extract actuals.

    The agent reads press_release.txt + (deck, remarks) and writes actuals.json.
    """
    workdir = digest_workdir(analyst, ticker, period)
    pr_path = workdir / "press_release.txt"
    if not pr_path.exists():
        raise FileNotFoundError(
            f"press_release.txt not found at {pr_path}. "
            f"Run fetch_print_materials phase first."
        )
    baseline_path = workdir / "digest_baseline.json"
    baseline = (
        json.loads(baseline_path.read_text()) if baseline_path.exists() else {}
    )
    expectations = baseline.get("kpi_tables", {})

    request = {
        "request_type": "extract_actuals",
        "ticker": ticker,
        "analyst": analyst,
        "period": period,
        "input_file": str(pr_path),
        "extraction_target": {
            "metrics_per_period_label": list(expectations.keys()),
            "current_quarter_label": period.replace("C", "")
            if period.startswith("C")
            else period,
        },
        "instructions": [
            "1. Read press_release.txt verbatim.",
            "2. For the CURRENT QUARTER reported, extract for each metric "
            "in the expectations stack: numerical value, unit, "
            "GAAP-or-non-GAAP flag, raw quote (verbatim from PR), "
            "character_offset_start within press_release.txt.",
            "3. Standard metrics to extract (presence varies by company):",
            "   - Total revenue (Q + segment splits if disclosed)",
            "   - GAAP gross margin",
            "   - Non-GAAP gross margin (if disclosed)",
            "   - GAAP operating margin / operating income",
            "   - Non-GAAP operating margin / operating income",
            "   - GAAP diluted EPS",
            "   - Non-GAAP diluted EPS (if disclosed)",
            "   - Unit KPIs per ticker (cases, scanners, members, "
            "subscriptions, etc.)",
            "   - Cash flow / FCF if disclosed in PR",
            "   - Share count (diluted)",
            "4. Extract guidance for next Q + FY:",
            "   - Range or point",
            "   - Metrics: rev, EPS, GM, OM if guided",
            "   - Note any guidance withdrawals or new metric definitions",
            "5. Write actuals.json with shape:",
            "   {",
            "     'period_reported': '...',",
            "     'metrics': [ {metric, value, unit, gaap_flag, raw_quote, "
            "offset_start, period}, ... ],",
            "     'guidance_new': [ {period, metric, low, high, point, "
            "raw_quote, offset_start}, ... ],",
            "     'guidance_prior_reference_needed': [ {period, metric}, ... ]",
            "   }",
            "6. After writing, the runner's next phase (compute_scorecard) "
            "will consume actuals.json + digest_baseline.json.",
        ],
        "expected_output": str(workdir / "actuals.json"),
    }
    out = workdir / "extraction_request.json"
    out.write_text(json.dumps(request, indent=2))
    return out


# ---------------------------------------------------------------------------
# Phase 4 — Scorecard compute
# ---------------------------------------------------------------------------


def parse_numeric(s: str) -> float | None:
    """Best-effort parse of strings like '1,047.6', '+5.3%', '676.9 thousand', '$2.29'."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip()
    s = s.replace(",", "").replace("$", "").replace("%", "")
    s = s.replace(" thousand", "").replace(" million", "").replace(" billion", "")
    s = s.replace("(", "-").replace(")", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def parse_pct(s: str) -> float | None:
    """Parse a y/y string like '+5.3%' or '-10bps' (returns -0.1 for -10bps as %)."""
    if s is None:
        return None
    s = str(s).strip()
    if "bps" in s:
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if not m:
            return None
        return float(m.group(0)) / 100.0
    return parse_numeric(s)


def classify_beat_miss(
    actual: float, baseline: float, threshold_pct: float = 0.005
) -> str:
    if actual is None or baseline is None or baseline == 0:
        return "n/a"
    delta = (actual - baseline) / abs(baseline)
    if abs(delta) <= threshold_pct:
        return "in_line"
    return "beat" if delta > 0 else "miss"


def compute_scorecard(baseline: dict, actuals: dict) -> dict:
    """Compute beat/miss vs cons + your variant for each metric the
    actuals provide. Light-touch arithmetic only — narrative read happens
    in the drafting phase.
    """
    scorecard = {
        "schema_version": "scorecard_v0.1",
        "computed_at": datetime.utcnow().isoformat() + "Z",
        "ticker": baseline.get("ticker"),
        "period": baseline.get("period"),
        "lines": [],
        "guide_changes": [],
        "warnings": [],
    }

    kpi_tables = baseline.get("kpi_tables", {})
    actuals_metrics = actuals.get("metrics", []) if actuals else []

    for actual in actuals_metrics:
        metric = actual.get("metric", "")
        period = actual.get("period", "")
        actual_value = parse_numeric(actual.get("value"))

        # Look up in KPI tables — fuzzy match metric name
        baseline_row = _match_baseline_row(kpi_tables, period, metric)
        if not baseline_row:
            scorecard["warnings"].append(
                f"No baseline row found for metric={metric!r} period={period!r}"
            )
            continue
        cons_value = parse_numeric(baseline_row.get("cons_value"))
        variant_value = parse_numeric(baseline_row.get("variant_value"))

        line = {
            "metric": metric,
            "period": period,
            "unit": actual.get("unit"),
            "gaap_flag": actual.get("gaap_flag"),
            "actual": actual_value,
            "cons": cons_value,
            "variant": variant_value,
            "delta_vs_cons_abs": (
                actual_value - cons_value
                if actual_value is not None and cons_value is not None
                else None
            ),
            "delta_vs_cons_pct": (
                (actual_value - cons_value) / cons_value * 100
                if actual_value is not None and cons_value
                else None
            ),
            "delta_vs_variant_abs": (
                actual_value - variant_value
                if actual_value is not None and variant_value is not None
                else None
            ),
            "delta_vs_variant_pct": (
                (actual_value - variant_value) / variant_value * 100
                if actual_value is not None and variant_value
                else None
            ),
            "vs_cons_class": classify_beat_miss(actual_value, cons_value),
            "vs_variant_class": classify_beat_miss(actual_value, variant_value),
            "company_guide_text": baseline_row.get("co_guide"),
            "raw_quote": actual.get("raw_quote"),
            "citation_offset": actual.get("offset_start"),
        }
        scorecard["lines"].append(line)

    # Guidance changes — compare actuals.guidance_new vs baseline.kpi_tables
    # (the company guide column captured what the prior guide was)
    for g in (actuals or {}).get("guidance_new", []):
        scorecard["guide_changes"].append(
            {
                "period": g.get("period"),
                "metric": g.get("metric"),
                "new_low": parse_numeric(g.get("low")),
                "new_high": parse_numeric(g.get("high")),
                "new_point": parse_numeric(g.get("point")),
                "raw_quote": g.get("raw_quote"),
                "citation_offset": g.get("offset_start"),
                # Prior guide is harder to parse from the kpi_table guide string
                # (e.g., '$1,010–$1,030 (+3–5%)'). Parse as best-effort.
                "prior_guide_text": _lookup_prior_guide(
                    baseline, g.get("period"), g.get("metric")
                ),
            }
        )

    return scorecard


def _match_baseline_row(
    kpi_tables: dict, period: str, metric: str
) -> dict | None:
    """Match an actuals metric to a row in the baseline KPI table."""
    if period not in kpi_tables:
        # Try common transforms — '1Q26' vs 'C1Q26', etc.
        for k in kpi_tables.keys():
            if k.replace("C", "") == period.replace("C", ""):
                period = k
                break
        else:
            return None
    rows = kpi_tables[period]
    metric_norm = _normalize_metric(metric)
    for r in rows:
        if _normalize_metric(r["metric"]) == metric_norm:
            return r
    # fuzzy: substring
    for r in rows:
        if metric_norm in _normalize_metric(r["metric"]) or _normalize_metric(
            r["metric"]
        ) in metric_norm:
            return r
    return None


def _normalize_metric(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\([^)]*\)", "", s)  # strip parenthetical units
    s = re.sub(r"[^a-z0-9 ]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _lookup_prior_guide(baseline: dict, period: str, metric: str) -> str | None:
    if not period or not metric:
        return None
    kpi_tables = baseline.get("kpi_tables", {})
    if period not in kpi_tables:
        return None
    metric_norm = _normalize_metric(metric)
    for r in kpi_tables[period]:
        if _normalize_metric(r["metric"]) == metric_norm:
            return r.get("co_guide")
    return None


# ---------------------------------------------------------------------------
# Phase 5 — Markdown skeleton
# ---------------------------------------------------------------------------


def draft_skeleton(
    baseline: dict, scorecard: dict, period: str
) -> str:
    """Build the digest markdown skeleton with deterministic sections filled.

    Narrative sections (Takeaways, Narrative Read, Pod Tactical Lens) are
    left as `<!-- LLM_FILL: ... -->` markers for the agent to populate.
    """
    ticker = baseline.get("ticker")
    today = date.today().strftime("%B %d, %Y")
    pos = baseline.get("positioning") or {}

    md_parts: list[str] = []
    md_parts.append(f"# {ticker} — {period} Print Digest")
    md_parts.append("")
    md_parts.append(f"**Print date:** {today}  ")
    md_parts.append(
        f"**Implied move (pre-print):** {pos.get('implied_move_pct', 'n/a')}%  "
    )
    md_parts.append(
        f"**Historical avg abs reaction:** "
        f"{pos.get('historical_avg_abs_price_change_pct', 'n/a')}%  "
    )
    md_parts.append(
        f"**Surprise→price corr (historical):** "
        f"{pos.get('surprise_to_price_correlation', 'n/a')}"
    )
    md_parts.append("")

    # Decision header — production-ready. NO "Pre-Print Decision (from
    # preview)" or "Earnings Preview Score" rows in the digest; those are
    # preview-output fields. NO analyst-named action label; use "Recommended
    # Action". Scaffolding placeholders use the {{ACTION_*}} bracket pattern
    # so production_ready_check matches them and forces fill before render.
    md_parts.append("<table class=\"decision-table\">")
    md_parts.append("<tr><th>Field</th><th>Value</th></tr>")
    md_parts.append(
        "<tr><td><strong>Recommended Action</strong></td>"
        "<td><strong>{{ACTION_VERDICT_AND_RATIONALE_ONE_LINE}}</strong></td></tr>"
    )
    md_parts.append(
        "<tr><td><strong>Headline Read</strong></td>"
        "<td><strong>{{HEADLINE_READ_ONE_LINE}}</strong></td></tr>"
    )
    md_parts.append(
        "<tr><td><strong>Day-of-Trade Triggers</strong></td>"
        "<td>{{DAY_OF_TRADE_TRIGGERS_ONE_LINE}}</td></tr>"
    )
    md_parts.append(
        "<tr><td><strong>Preferred Structure</strong></td>"
        "<td>{{STRUCTURE_ONE_LINE}}</td></tr>"
    )
    md_parts.append("</table>")
    md_parts.append("")

    md_parts.append("### Beat/Miss Scorecard")
    md_parts.append("")
    md_parts.append("| Metric | Period | Actual | Cons | Δ % | Variant | Δ % | Guide | Read |")
    md_parts.append("|---|---|---|---|---|---|---|---|---|")
    for line in scorecard.get("lines", []):
        actual = _fmt(line.get("actual"))
        cons = _fmt(line.get("cons"))
        variant = _fmt(line.get("variant"))
        d_cons = _fmt_pct(line.get("delta_vs_cons_pct"))
        d_senv = _fmt_pct(line.get("delta_vs_variant_pct"))
        cls = line.get("vs_cons_class") or "n/a"
        css_cls = {"beat": "beat", "miss": "miss", "in_line": "inline"}.get(cls, "")
        read_html = (
            f'<span class="{css_cls}">{cls}</span>' if css_cls else cls
        )
        guide = line.get("company_guide_text") or "—"
        md_parts.append(
            f"| {line.get('metric')} | {line.get('period')} | {actual} | "
            f"{cons} | {d_cons} | {variant} | {d_senv} | {guide} | {read_html} |"
        )
    md_parts.append("")
    md_parts.append(
        "<!-- LLM_FILL: Closing gut-check paragraph reconciling implied y/y "
        "growth vs guide vs preview's variant vs alt data, per spec -->"
    )
    md_parts.append("")

    md_parts.append("### Narrative Read — Did the Story Improve?")
    md_parts.append(
        "<!-- LLM_FILL: opening prose framing + 5-6 punchy bullet headers + "
        "explicit comparison to preview's expected setup -->"
    )
    md_parts.append("")

    md_parts.append("### Guide Delta — Did They Take Up the Guide?")
    md_parts.append("")
    md_parts.append("| Period | Metric | Prior Guide | New Guide | Δ vs Prior | Read |")
    md_parts.append("|---|---|---|---|---|---|")
    for g in scorecard.get("guide_changes", []):
        prior = g.get("prior_guide_text") or "—"
        new = _fmt_guide_range(g)
        delta_text = "<!-- LLM_FILL -->"  # prior parsing is heterogeneous
        read_text = "<!-- LLM_FILL: raised / reaffirmed / lowered + magnitude -->"
        md_parts.append(
            f"| {g.get('period')} | {g.get('metric')} | {prior} | {new} | "
            f"{delta_text} | {read_text} |"
        )
    md_parts.append("")
    md_parts.append(
        "<!-- LLM_FILL: Magnitude commentary — quantify bps/% move and "
        "whether it's a 'raise to fix the cons walk-down' vs a 'raise that "
        "pulls forward upside' per spec -->"
    )
    md_parts.append("")

    md_parts.append("### Implied Estimate Moves")
    md_parts.append(
        "<!-- LLM_FILL: direction + magnitude only (no draft revised numbers) "
        "per user preference. State for each forward period (Q+1, FY) which way "
        "cons needs to move and roughly how much. -->"
    )
    md_parts.append("")

    md_parts.append("### Watch-List Reconciliation")
    md_parts.append(
        "<!-- LLM_FILL: For each watch item from the preview, was it addressed "
        "in the press release? Yes/No/Partial + what was disclosed. Items "
        "not yet addressed become call-watch. -->"
    )
    md_parts.append("")

    md_parts.append("### Questions to Pay Attention To On the Call")
    md_parts.append(
        "<!-- LLM_FILL: 5-8 specific questions, each with rationale tied to "
        "the print. Lead with highest-leverage. -->"
    )
    md_parts.append("")

    md_parts.append("### Tactical Lens — Action and Pair Read")
    md_parts.append(
        "<!-- LLM_FILL: idiosyncratic alpha thesis (confirmed/broken/ambiguous), "
        "pair trade view, squeeze direction, action recommendation + sizing math. -->"
    )
    md_parts.append("")

    md_parts.append("### Historical Earnings Reaction Calibration")
    md_parts.append(
        "<!-- LLM_FILL: last 4-Q table from preview + closing line on "
        "whether this print fits the calibration pattern. -->"
    )
    md_parts.append("")

    md_parts.append("---")
    md_parts.append("")
    md_parts.append("## Appendix A — Multi-Manager Quantamental Viewpoint")
    md_parts.append("")
    md_parts.append("### A.1 Options / Implied Move vs Realized")
    md_parts.append("<!-- LLM_FILL -->")
    md_parts.append("")
    md_parts.append("### A.2 Pair Trade Re-Rate")
    md_parts.append("<!-- LLM_FILL -->")
    md_parts.append("")
    md_parts.append("### A.3 Cons Revision Read")
    md_parts.append("<!-- LLM_FILL -->")
    md_parts.append("")
    md_parts.append("### A.4 Squeeze Risk Update")
    md_parts.append("<!-- LLM_FILL -->")
    md_parts.append("")

    return "\n".join(md_parts)


def _fmt(v: float | None) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"{v:,.1f}"
    return f"{v:.2f}" if abs(v) < 100 else f"{v:.1f}"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    return f'{sign}{v:.1f}%'


def _fmt_guide_range(g: dict) -> str:
    lo = g.get("new_low")
    hi = g.get("new_high")
    pt = g.get("new_point")
    if lo is not None and hi is not None:
        return f"{lo:,.1f}–{hi:,.1f}"
    if pt is not None:
        return f"{pt:,.1f}"
    return "—"


# ---------------------------------------------------------------------------
# Stage 2 — Transcript-integrated phases
# ---------------------------------------------------------------------------


# Page-footer pattern that gets interspersed in extracted transcript text
TRANSCRIPT_FOOTER_RE = re.compile(
    r"FINAL TRANSCRIPT \d{4}-\d{2}-\d{2}.*?Page \d+ of \d+",
    re.DOTALL,
)


def parse_transcript(text: str) -> dict:
    """Parse a common-format earnings call transcript into structured form.

    Returns:
        {
          "header": str,                # participant list block
          "prepared_remarks": [
              {"speaker": str, "speaker_bio": str|None, "text": str}
          ],
          "qa": [
              {
                  "round": int,
                  "asker": str,
                  "asker_firm": str|None,
                  "question_text": str,
                  "answer_speaker": str,
                  "answer_text": str
              }
          ]
        }
    """
    # Strip page footers
    text = TRANSCRIPT_FOOTER_RE.sub("", text)

    # Split presentation vs Q&A
    qa_marker = "Questions And Answers"
    qa_idx = text.find(qa_marker)
    if qa_idx == -1:
        # Fallback: look for "Q - " pattern
        m = re.search(r"\n[ ]*Q - [A-Z]", text)
        qa_idx = m.start() if m else len(text)

    pre_section = text[:qa_idx]
    qa_section = text[qa_idx:]

    # Within pre_section, find "Presentation" marker
    presentation_idx = pre_section.find("\nPresentation\n")
    header = pre_section[:presentation_idx] if presentation_idx >= 0 else ""
    prep_text = (
        pre_section[presentation_idx + len("\nPresentation\n"):]
        if presentation_idx >= 0
        else pre_section
    )

    # Parse prepared remarks: split on speaker headers
    # Speaker pattern: name on own line, optionally followed by {BIO ...}
    # Common speakers: CEO, CFO, IR, Operator
    speaker_pattern = re.compile(
        r"^(?P<speaker>(?:[A-Z][a-zA-Z'-]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-zA-Z'-]+)+|Operator))\s*"
        r"(?P<bio>\{BIO\s+[^}]+\})?\s*$",
        re.MULTILINE,
    )
    prepared = _split_by_speaker(prep_text, speaker_pattern)

    # Parse Q&A: split on Q - and A - markers
    qa_split_pattern = re.compile(
        r"\n(?P<role>Q|A)\s*-\s*(?P<speaker>[^\{\n]+?)\s*"
        r"(?P<bio>\{BIO\s+[^}]+\})?\s*\n",
        re.MULTILINE,
    )
    matches = list(qa_split_pattern.finditer(qa_section))
    qa_blocks = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(qa_section)
        qa_blocks.append(
            {
                "role": m.group("role"),
                "speaker": m.group("speaker").strip(),
                "bio": m.group("bio"),
                "text": qa_section[start:end].strip(),
            }
        )

    # Group Q + A pairs into exchanges
    exchanges = []
    current_q = None
    round_num = 0
    for blk in qa_blocks:
        if blk["role"] == "Q":
            if current_q is not None:
                # Q without intervening A — store as malformed exchange
                exchanges.append(
                    {
                        "round": round_num,
                        "asker": current_q["speaker"],
                        "asker_firm": _firm_for_asker(header, current_q["speaker"]),
                        "question_text": current_q["text"],
                        "answer_speaker": None,
                        "answer_text": None,
                        "warning": "no_answer_block",
                    }
                )
            current_q = blk
            round_num += 1
        elif blk["role"] == "A":
            if current_q is None:
                # Standalone A — log
                exchanges.append(
                    {
                        "round": round_num,
                        "asker": None,
                        "asker_firm": None,
                        "question_text": None,
                        "answer_speaker": blk["speaker"],
                        "answer_text": blk["text"],
                        "warning": "answer_without_question",
                    }
                )
            else:
                # Append to most recent Q if a multi-A turn
                if exchanges and exchanges[-1].get("asker") == current_q["speaker"] and (
                    exchanges[-1].get("answer_speaker") is None
                ):
                    # update the exchange we already created (for malformed)
                    exchanges[-1]["answer_speaker"] = blk["speaker"]
                    exchanges[-1]["answer_text"] = blk["text"]
                    exchanges[-1].pop("warning", None)
                else:
                    exchanges.append(
                        {
                            "round": round_num,
                            "asker": current_q["speaker"],
                            "asker_firm": _firm_for_asker(
                                header, current_q["speaker"]
                            ),
                            "question_text": current_q["text"],
                            "answer_speaker": blk["speaker"],
                            "answer_text": blk["text"],
                        }
                    )
                # Don't reset current_q — analysts often get multiple A's
                # Only reset on new Q

    return {
        "header": header.strip(),
        "prepared_remarks": prepared,
        "qa": exchanges,
        "stats": {
            "char_count_total": len(text),
            "char_count_prepared": len(prep_text),
            "char_count_qa": len(qa_section),
            "qa_exchange_count": len(exchanges),
            "qa_unique_askers": len({e.get("asker") for e in exchanges if e.get("asker")}),
        },
    }


def _split_by_speaker(text: str, pattern: re.Pattern) -> list[dict]:
    """Split a block of text by a speaker-line regex."""
    matches = list(pattern.finditer(text))
    out: list[dict] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if not body:
            continue
        out.append(
            {
                "speaker": m.group("speaker").strip(),
                "speaker_bio": m.group("bio"),
                "text": body,
            }
        )
    return out


def _firm_for_asker(header: str, asker: str) -> str | None:
    """Look up an analyst's firm from the participant header block."""
    if not asker:
        return None
    # Header typically has lines like "Analyst, Broker Name" pre-name
    # or "First Last, Analyst, Broker Name"
    # Search for asker name in header context
    idx = header.find(asker)
    if idx == -1:
        return None
    # Look at the line context
    line_start = header.rfind("\n", 0, idx)
    line_end = header.find("\n", idx)
    line = header[line_start:line_end] if line_end > line_start else header[line_start:]
    # Try to extract firm after "Analyst,"
    m = re.search(r"Analyst,\s*([A-Z][^,\n]+)", line)
    if m:
        return m.group(1).strip().rstrip(".")
    return None


def emit_transcript_extraction_request(
    analyst: str, ticker: str, period: str
) -> Path:
    """Emit a request for the agent to extract incremental disclosures
    from the parsed transcript.
    """
    workdir = digest_workdir(analyst, ticker, period)
    parsed_path = workdir / "transcript_parsed.json"
    if not parsed_path.exists():
        raise FileNotFoundError(
            f"transcript_parsed.json not found at {parsed_path}. "
            f"Run load_transcript phase first."
        )

    request = {
        "request_type": "extract_qa_disclosures",
        "ticker": ticker,
        "analyst": analyst,
        "period": period,
        "input_files": {
            "transcript_parsed": str(parsed_path),
            "digest_v1_md": _find_digest_v1_md(analyst, ticker, period),
            "actuals_json": str(workdir / "actuals.json"),
            "digest_baseline_json": str(workdir / "digest_baseline.json"),
        },
        "instructions": [
            "1. Read transcript_parsed.json (prepared_remarks + qa[]).",
            "2. For each metric in the expectations stack: did the call "
            "add color the press release didn't? Note source — prepared "
            "remarks vs Q&A — and quote.",
            "3. For each watch list item from digest_v1: addressed where "
            "(prepared / Q&A / not at all)? Confirms / threatens / neutral "
            "to the variant thesis?",
            "4. For each Q&A exchange: tag question type (volume / margin "
            "/ guide / capital allocation / competitive / strategic / model) "
            "and answer quality (substantive / hedged / dodged / refused).",
            "5. Identify language changes vs prior 2 transcripts — words "
            "or phrases mgmt used that they didn't last quarter, OR phrases "
            "they used last quarter that are absent now.",
            "6. Compute deltas vs digest_v1 — did the call confirm, modify, "
            "or contradict each section's read? Specifically: action "
            "recommendation (HOLD/ADD/TRIM/EXIT), guide read, narrative read.",
            "7. Write digest_v2_inputs.json with the structured output.",
        ],
        "expected_output": str(workdir / "digest_v2_inputs.json"),
    }
    out = workdir / "transcript_extraction_request.json"
    out.write_text(json.dumps(request, indent=2))
    return out


def _find_digest_v1_md(analyst: str, ticker: str, period: str) -> str:
    out = outputs_dir(analyst, ticker)
    candidates = sorted(
        out.glob(f"digest_v1_print_{period}_*.md"),
        key=os.path.getmtime,
        reverse=True,
    )
    return str(candidates[0]) if candidates else ""


def draft_v2_skeleton(
    digest_v1_md: str, transcript_parsed: dict, baseline: dict, period: str
) -> str:
    """Build the Stage 2 markdown skeleton — delta-focused, references v1."""
    ticker = baseline.get("ticker", "")
    today = date.today().strftime("%B %d, %Y")
    qa_count = len(transcript_parsed.get("qa", []))
    askers = sorted(
        {
            e.get("asker")
            for e in transcript_parsed.get("qa", [])
            if e.get("asker")
        }
    )

    parts: list[str] = []
    parts.append(f"# {ticker} — {period} Post-Call Digest")
    parts.append("")
    parts.append(f"**Stage 1 reference:** `{Path(digest_v1_md).name}`  ")
    parts.append(f"**Call date:** {today}  ")
    parts.append(f"**Q&A exchanges:** {qa_count}  ")
    parts.append(f"**Analyst firms on Q&A:** {len(askers)}")
    parts.append("")

    parts.append("### Delta vs Stage 1")
    parts.append(
        "<!-- LLM_FILL: 4-6 bullets covering what the call CHANGED in our read. "
        "Lead bullet: did the action recommendation (HOLD/ADD/TRIM/EXIT) shift, "
        "and why. -->"
    )
    parts.append("")

    parts.append("### Q&A Highlights — Top 5 Exchanges")
    parts.append("")
    parts.append("| # | Asker / Firm | Topic | Answer Quality | Key Takeaway |")
    parts.append("|---|---|---|---|---|")
    parts.append(
        "<!-- LLM_FILL: top 5 exchanges by importance to the variant thesis, "
        "tagged by topic and answer quality. Use class='qa-substantive', "
        "'qa-hedged', or 'qa-dodged' on the answer-quality cell. -->"
    )
    parts.append("")

    parts.append("### Updated Beat/Miss + Guide Read")
    parts.append(
        "<!-- LLM_FILL: same scorecard as Stage 1 — flag any line where Q&A "
        "added color that changed the read. Use a Δ vs Stage 1 column. -->"
    )
    parts.append("")

    parts.append("### Watch-List Reconciliation (Updated)")
    parts.append(
        "<!-- LLM_FILL: For each watch item from the preview, where addressed: "
        "prepared remarks / Q&A / not at all. Flag items where Q&A added "
        "direction the press release didn't. Use class='addressed-topic', "
        "'partial-topic', or 'absent-topic'. -->"
    )
    parts.append("")

    parts.append("### Language Change Log")
    parts.append(
        "<!-- LLM_FILL: 3 sub-sections. CHANGED: tone shifts vs prior 2 calls. "
        "NEW: topics introduced this quarter. ABSENT: topics expected from "
        "preview that mgmt did NOT address (signal, not neutral). -->"
    )
    parts.append("")

    parts.append("### Management Tone Read")
    parts.append(
        "<!-- LLM_FILL: plain-English read on prepared remarks tone vs prior. "
        "Q&A defensiveness / openness on key topics. Specific examples — e.g., "
        "'On X, mgmt gave a 12-word answer to a substantive question — flagged.' -->"
    )
    parts.append("")

    parts.append("### Updated Tactical Lens")
    parts.append(
        "<!-- LLM_FILL: did the call confirm or shift the post-print "
        "HOLD/ADD/TRIM/EXIT recommendation. Pair trade view update. Squeeze "
        "read update. Sizing math if action changed. -->"
    )
    parts.append("")

    parts.append("### Stage 1 Items the Call Did NOT Resolve")
    parts.append(
        "<!-- LLM_FILL: watch items still open. Set up for next data drop / "
        "catalyst calendar. -->"
    )
    parts.append("")

    parts.append("---")
    parts.append("")
    parts.append("## Appendix A — Multi-Manager Quantamental Update")
    parts.append("")
    parts.append("### A.1 Options / Implied Move vs Realized (post-call)")
    parts.append("<!-- LLM_FILL -->")
    parts.append("")
    parts.append("### A.2 Pair Trade Re-Rate (post-call)")
    parts.append("<!-- LLM_FILL -->")
    parts.append("")
    parts.append("### A.3 Cons Revision Read (post-call)")
    parts.append("<!-- LLM_FILL -->")
    parts.append("")
    parts.append("### A.4 Squeeze Risk Update (post-call)")
    parts.append("<!-- LLM_FILL -->")
    parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Phase 6 — Render
# ---------------------------------------------------------------------------


def render_pdf(md_path: Path, css_path: Path, pdf_path: Path) -> tuple[bool, str]:
    """Render markdown → HTML → PDF via pandoc + weasyprint.

    Uses --from markdown-tex_math_dollars to avoid the $ math bug.
    """
    import subprocess

    html_path = md_path.with_suffix(".html")
    cmd_pandoc = [
        "pandoc",
        str(md_path),
        "-o",
        str(html_path),
        "--standalone",
        "--css",
        str(css_path),
        "--from",
        "markdown-tex_math_dollars",
    ]
    r = subprocess.run(cmd_pandoc, capture_output=True, text=True)
    if r.returncode != 0:
        return False, f"pandoc failed: {r.stderr}"

    try:
        from weasyprint import HTML, CSS
    except ImportError:
        return False, "weasyprint not installed (pip install weasyprint --break-system-packages)"

    try:
        HTML(str(html_path)).write_pdf(
            str(pdf_path), stylesheets=[CSS(str(css_path))]
        )
    except Exception as e:
        return False, f"weasyprint failed: {e}"

    try:
        html_path.unlink()
    except OSError:
        pass
    return True, str(pdf_path)


# ---------------------------------------------------------------------------
# Phase 7 — Audit hook
# ---------------------------------------------------------------------------


def run_audit(md_path: Path, baseline_path: Path, actuals_path: Path) -> dict:
    """Programmatic audit pass — deterministic checks on the rendered draft.

    Checks for digest-specific failure modes:
      - LLM_FILL markers all replaced
      - PERIOD-AVERAGE DENOMINATOR ALIGNMENT (catches apples-to-oranges
        comparisons: e.g. a 3-quarter vs 2-quarter average)
      - DERIVED MARGIN SOURCE-TIER (actuals.json estimated_flag must
        propagate as hedge-language in body, not citation as if stated)
      - Calculation-persistence on consequential numbers (input/formula/result)
    """
    md_text_raw = md_path.read_text() if md_path.exists() else ""
    # Strip HTML comments before checking for forbidden tokens — comments
    # don't render in the PDF, so words inside them shouldn't fail audit.
    md_text_visible = re.sub(r"<!--.*?-->", "", md_text_raw, flags=re.DOTALL)
    baseline = (
        json.loads(baseline_path.read_text()) if baseline_path.exists() else {}
    )
    actuals = (
        json.loads(actuals_path.read_text()) if actuals_path.exists() else {}
    )

    findings: list[dict] = []

    if "LLM_FILL" in md_text_raw:
        findings.append(
            {
                "level": "error",
                "msg": "LLM_FILL markers remain — narrative sections "
                "not yet populated",
            }
        )

    findings.extend(_check_period_denominators(md_text_visible))
    findings.extend(_check_derived_margin_source_tier(md_text_visible, actuals))
    findings.extend(_check_calc_persistence(md_text_visible))

    return {
        "audit_at": datetime.utcnow().isoformat() + "Z",
        "ticker": baseline.get("ticker"),
        "period": baseline.get("period"),
        "findings": findings,
        "pass": all(f.get("level") != "error" for f in findings),
    }


# ---------------------------------------------------------------------------
# Programmatic audit checks for OM / margin math errors
# ---------------------------------------------------------------------------


# Match patterns that COMPARE two period averages.
# Examples that should be flagged when denominators differ:
#   "2H'26 averaging 25.9% vs 2Q-4Q'26 averaging 25.0% = step-up of 100bps"
#   "Q4'25 22.5% step-up to 2H'26 26%"
# We flag if a sentence contains BOTH a "2H" reference AND a "2Q-4Q" or
# "3-quarter" or similar 3-quarter-window reference, paired with a
# comparison/step-up phrase.
_PERIOD_AVG_HINT = re.compile(
    r"(?i)(step.?up|step.?down|averaging|avg\.?|vs|compare)"
)
_TWO_QUARTER_REF = re.compile(
    r"(?i)(2H[''] ?\d{2}|second\s+half|2-?quarter\s+(?:avg|average))"
)
_THREE_QUARTER_REF = re.compile(
    r"(?i)(2Q-4Q[''] ?\d{2}|3-?quarter\s+(?:avg|average)|three-?quarter)"
)


def _check_period_denominators(md_text: str) -> list[dict]:
    """Flag sentences that compare period averages with mismatched denominators.

    Catches the failure mode of comparing a 3-quarter pre-print average to a
    2-quarter post-print average and treating them as comparable.

    This is a HEURISTIC check — false positives are possible (a sentence may
    legitimately reference both 2H and 2Q-4Q in different contexts). The
    audit emits a WARNING (not an error) so the analyst can review.
    """
    findings: list[dict] = []
    # Split into sentences (rough)
    sentences = re.split(r"(?<=[.!?])\s+", md_text)
    for s in sentences:
        if not _PERIOD_AVG_HINT.search(s):
            continue
        has_2q = bool(_TWO_QUARTER_REF.search(s))
        has_3q = bool(_THREE_QUARTER_REF.search(s))
        if has_2q and has_3q:
            findings.append(
                {
                    "level": "warning",
                    "msg": (
                        "PERIOD-DENOMINATOR MISMATCH suspected: sentence references "
                        "both 2H (2-quarter avg) and 2Q-4Q / 3-quarter window. "
                        "Verify both sides of the comparison use the same number "
                        "of quarters."
                    ),
                    "sentence": s.strip()[:300],
                }
            )
    return findings


# Detect references to non-GAAP OM percentages in body prose (not comments)
_NONGAAP_OM_REF = re.compile(
    r"(?i)Q\d['']?\d{2}\s+(?:non-?GAAP\s+OM|non-?GAAP\s+operating\s+margin)\s+"
    r"(?:was|of|at|=)?\s*~?(\d+(?:\.\d+)?)\s?%"
)


def _check_derived_margin_source_tier(md_text: str, actuals: dict) -> list[dict]:
    """Flag any non-GAAP OM percentage cited in body that's flagged as
    DERIVED in actuals.json without being explicitly hedged.

    Catches the failure mode of a derived margin value cited as if stated,
    when the actual stated value differs (e.g. per the slide deck).
    """
    findings: list[dict] = []
    # Build a dict of derived margin metrics from actuals
    derived_metrics: dict[str, dict] = {}
    for m in actuals.get("metrics", []) or []:
        if (
            m.get("estimated_flag")
            or m.get("source") in ("derived", "DERIVED", "estimate")
            or "derived" in str(m.get("raw_quote", "")).lower()
        ):
            metric_name = m.get("metric", "")
            if "OM" in metric_name or "Margin" in metric_name:
                derived_metrics[metric_name] = m

    if not derived_metrics:
        return findings

    # Look for any margin % in the body and check if it matches a derived value
    for m in derived_metrics.values():
        v = m.get("value")
        if v is None:
            continue
        # Search for the value in the body within a margin context
        pat = re.compile(
            rf"(?i)(?:non-?GAAP\s+OM|non-?GAAP\s+operating\s+margin|margin)"
            rf"[^.]*?{re.escape(str(v))}\s?%"
        )
        for match in pat.finditer(md_text):
            ctx = md_text[max(0, match.start() - 100): match.end() + 100]
            # Check if there's hedging language nearby
            hedged = any(
                h in ctx.lower()
                for h in [
                    "derived",
                    "estimated",
                    "implied",
                    "approximate",
                    "not directly disclosed",
                    "see deck",
                    "see 10-q",
                    "[inferred",
                    "[speculative",
                ]
            )
            if not hedged:
                findings.append(
                    {
                        "level": "error",
                        "msg": (
                            f"DERIVED MARGIN cited as if stated: '{m.get('metric')}' "
                            f"value {v}% is flagged as derived/estimated in "
                            f"actuals.json but appears in body without hedge language. "
                            f"Either pull actual value from deck/10-Q or add explicit "
                            f"hedge ([INFERRED] / 'derived' / 'see deck for actual')."
                        ),
                        "context": ctx.strip()[:300],
                    }
                )
    return findings


# Match consequential-number patterns in narrative claims
_CONSEQ_CLAIM = re.compile(
    r"(?i)(?:step.?up|step.?down|cushion|gap)\s+(?:of\s+)?~?(\d+(?:\.\d+)?)\s?(?:bps|%|pts?)"
)


def _check_calc_persistence(md_text: str) -> list[dict]:
    """Flag consequential numerical claims (step-ups, gaps, cushions in bps/%)
    that don't have a nearby calculation walk (input / formula / result).

    A 'calculation walk' is detected by proximity to: '×', 'mid', '$X × Y%',
    'formula', 'math:', or explicit arithmetic operators near the claim.
    """
    findings: list[dict] = []
    for match in _CONSEQ_CLAIM.finditer(md_text):
        ctx = md_text[max(0, match.start() - 250): match.end() + 250]
        has_walk = any(
            indicator in ctx
            for indicator in ["×", "*", "math:", "Math:", " = $", "formula"]
        ) or bool(re.search(r"\$[\d,]+\s*[×*]\s*\d+(?:\.\d+)?\s?%", ctx))
        if not has_walk:
            findings.append(
                {
                    "level": "warning",
                    "msg": (
                        "CALCULATION PERSISTENCE: consequential numerical claim "
                        f"({match.group(0)}) lacks nearby input/formula/result "
                        "math walk. Add explicit arithmetic or remove the claim."
                    ),
                    "context": ctx.strip()[:200],
                }
            )
    return findings


# ---------------------------------------------------------------------------
# Main / CLI
# ---------------------------------------------------------------------------


def cmd_fetch_baseline(args: argparse.Namespace) -> int:
    baseline = assemble_baseline(args.analyst, args.ticker, args.period)
    workdir = digest_workdir(args.analyst, args.ticker, args.period)
    out = workdir / "digest_baseline.json"
    out.write_text(json.dumps(baseline, indent=2, default=str))
    print(f"[ok] baseline assembled → {out}")
    print(
        f"  preview: {baseline.get('preview_source')}\n"
        f"  kpi_tables: {list(baseline.get('kpi_tables', {}).keys())}\n"
        f"  cons_csv: {baseline.get('consensus_csv_loaded')}\n"
        f"  positioning: {bool(baseline.get('positioning'))}"
    )
    return 0


def cmd_fetch_print_materials(args: argparse.Namespace) -> int:
    req = emit_8k_fetch_request(args.analyst, args.ticker, args.period)
    print(f"[next] agent: fulfill {req}")
    print(
        "  - Read fetch_request.json instructions\n"
        "  - Run `python scripts/edgar_fetch.py --ticker {TICKER}` (free SEC EDGAR)\n"
        "  - Save press_release.txt + manifest.json to the workdir"
    )
    return 0


def cmd_request_extraction(args: argparse.Namespace) -> int:
    req = emit_extraction_request(args.analyst, args.ticker, args.period)
    print(f"[next] agent: fulfill {req}")
    print(
        "  - Read press_release.txt\n"
        "  - Extract numerical actuals + guidance per the prompt\n"
        "  - Save actuals.json to the workdir"
    )
    return 0


def cmd_compute_scorecard(args: argparse.Namespace) -> int:
    workdir = digest_workdir(args.analyst, args.ticker, args.period)
    baseline = json.loads((workdir / "digest_baseline.json").read_text())
    actuals_path = workdir / "actuals.json"
    if not actuals_path.exists():
        print(
            f"[error] actuals.json not found at {actuals_path}. "
            f"Run extract phase first."
        )
        return 2
    actuals = json.loads(actuals_path.read_text())
    sc = compute_scorecard(baseline, actuals)
    out = workdir / "scorecard.json"
    out.write_text(json.dumps(sc, indent=2))
    print(
        f"[ok] scorecard → {out}\n"
        f"  lines: {len(sc['lines'])}\n"
        f"  guide_changes: {len(sc['guide_changes'])}\n"
        f"  warnings: {len(sc['warnings'])}"
    )
    if sc["warnings"]:
        for w in sc["warnings"]:
            print(f"  warn: {w}")
    return 0


def cmd_draft_skeleton(args: argparse.Namespace) -> int:
    workdir = digest_workdir(args.analyst, args.ticker, args.period)
    baseline = json.loads((workdir / "digest_baseline.json").read_text())
    sc = json.loads((workdir / "scorecard.json").read_text())
    md = draft_skeleton(baseline, sc, args.period)
    out = outputs_dir(args.analyst, args.ticker) / (
        f"digest_v1_print_{args.period}_{date.today().strftime('%Y%m%d')}.md"
    )
    out.write_text(md)
    print(f"[ok] skeleton → {out}")
    print("[next] agent: replace each <!-- LLM_FILL: ... --> with prose")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    md = Path(args.md)
    css = Path(args.css)
    pdf = md.with_suffix(".pdf")
    ok, msg = render_pdf(md, css, pdf)
    if ok:
        print(f"[ok] PDF → {msg}")
        return 0
    print(f"[error] {msg}")
    return 2


def cmd_load_transcript(args: argparse.Namespace) -> int:
    workdir = digest_workdir(args.analyst, args.ticker, args.period)
    # Default transcript path
    transcript_path = (
        Path(args.transcript)
        if args.transcript
        else ticker_root(args.analyst, args.ticker)
        / "transcripts"
        / f"{args.ticker}_{args.period}_transcript.txt"
    )
    if not transcript_path.exists():
        print(f"[error] transcript not found at {transcript_path}")
        return 2
    text = transcript_path.read_text()
    parsed = parse_transcript(text)
    out = workdir / "transcript_parsed.json"
    out.write_text(json.dumps(parsed, indent=2, default=str))
    stats = parsed["stats"]
    print(f"[ok] parsed → {out}")
    print(
        f"  prepared_remarks: {len(parsed['prepared_remarks'])} speaker turns\n"
        f"  qa_exchanges: {stats['qa_exchange_count']}\n"
        f"  unique_askers: {stats['qa_unique_askers']}\n"
        f"  total_chars: {stats['char_count_total']:,}"
    )
    return 0


def cmd_request_transcript_extraction(args: argparse.Namespace) -> int:
    req = emit_transcript_extraction_request(args.analyst, args.ticker, args.period)
    print(f"[next] agent: fulfill {req}")
    print(
        "  - Read transcript_parsed.json + digest_v1 + actuals\n"
        "  - Extract Q&A disclosures, watch list updates, language changes\n"
        "  - Save digest_v2_inputs.json to the workdir"
    )
    return 0


def cmd_draft_v2_skeleton(args: argparse.Namespace) -> int:
    workdir = digest_workdir(args.analyst, args.ticker, args.period)
    baseline = json.loads((workdir / "digest_baseline.json").read_text())
    transcript = json.loads((workdir / "transcript_parsed.json").read_text())
    digest_v1 = _find_digest_v1_md(args.analyst, args.ticker, args.period)
    md = draft_v2_skeleton(digest_v1, transcript, baseline, args.period)
    out = outputs_dir(args.analyst, args.ticker) / (
        f"digest_v2_transcript_{args.period}_{date.today().strftime('%Y%m%d')}.md"
    )
    out.write_text(md)
    print(f"[ok] v2 skeleton → {out}")
    print("[next] agent: replace each <!-- LLM_FILL --> with prose")
    return 0


def cmd_adversarial_emit(args: argparse.Namespace) -> int:
    """Emit adversarial verification prompt for the agent to dispatch."""
    import subprocess

    here = Path(__file__).parent
    r = subprocess.run(
        [
            sys.executable,
            str(here / "digest_adversarial.py"),
            "emit",
            "--ticker", args.ticker,
            "--analyst", args.analyst,
            "--period", args.period,
            "--mode", args.mode,
        ],
        capture_output=True,
        text=True,
    )
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


def cmd_adversarial_ingest(args: argparse.Namespace) -> int:
    """Ingest adversarial findings + classify."""
    import subprocess

    here = Path(__file__).parent
    r = subprocess.run(
        [
            sys.executable,
            str(here / "digest_adversarial.py"),
            "ingest",
            "--ticker", args.ticker,
            "--analyst", args.analyst,
            "--period", args.period,
            "--mode", args.mode,
        ],
        capture_output=True,
        text=True,
    )
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


def cmd_audit(args: argparse.Namespace) -> int:
    workdir = digest_workdir(args.analyst, args.ticker, args.period)
    md_path = Path(args.md) if args.md else None
    if md_path is None:
        # find latest digest_v1_print
        out = outputs_dir(args.analyst, args.ticker)
        latest = max(
            out.glob(f"digest_v1_print_{args.period}_*.md"),
            default=None,
            key=os.path.getmtime,
        )
        md_path = latest
    if md_path is None or not md_path.exists():
        print("[error] no digest markdown found to audit")
        return 2
    res = run_audit(
        md_path,
        workdir / "digest_baseline.json",
        workdir / "actuals.json",
    )
    out = md_path.with_suffix(".audit.json")
    out.write_text(json.dumps(res, indent=2))
    status = "PASS" if res["pass"] else "FAIL"
    print(f"[{status.lower()}] audit → {out}")
    for f in res["findings"]:
        print(f"  {f['level']}: {f['msg']}")
    return 0 if res["pass"] else 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Earnings Digest Runner")
    p.add_argument("--ticker", required=True)
    p.add_argument("--analyst", default="user")
    p.add_argument(
        "--period",
        required=True,
        help="e.g. C1Q26 (matches preview filename convention)",
    )
    p.add_argument(
        "--mode",
        choices=["print", "transcript"],
        default="print",
    )
    p.add_argument(
        "--phase",
        required=True,
        choices=[
            "fetch_baseline",
            "fetch_print_materials",
            "request_extraction",
            "compute_scorecard",
            "draft_skeleton",
            "render",
            "audit",
            "load_transcript",
            "request_transcript_extraction",
            "draft_v2_skeleton",
            "adversarial_emit",
            "adversarial_ingest",
        ],
    )
    p.add_argument("--md", help="markdown path (for render / audit phases)")
    p.add_argument("--css", help="CSS path (for render phase)")
    p.add_argument(
        "--transcript",
        help="explicit transcript path (load_transcript phase). If omitted, "
        "defaults to /transcripts/{TICKER}_{period}_transcript.txt",
    )
    args = p.parse_args(argv)

    handlers = {
        "fetch_baseline": cmd_fetch_baseline,
        "fetch_print_materials": cmd_fetch_print_materials,
        "request_extraction": cmd_request_extraction,
        "compute_scorecard": cmd_compute_scorecard,
        "draft_skeleton": cmd_draft_skeleton,
        "render": cmd_render,
        "audit": cmd_audit,
        "load_transcript": cmd_load_transcript,
        "request_transcript_extraction": cmd_request_transcript_extraction,
        "draft_v2_skeleton": cmd_draft_v2_skeleton,
        "adversarial_emit": cmd_adversarial_emit,
        "adversarial_ingest": cmd_adversarial_ingest,
    }
    return handlers[args.phase](args)


if __name__ == "__main__":
    sys.exit(main())
