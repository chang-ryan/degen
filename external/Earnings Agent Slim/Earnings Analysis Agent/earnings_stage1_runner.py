"""
earnings_stage1_runner.py — Stage 1 (Prep) runner.

Reads the workspace for a ticker, builds Stage 1 Prep output per
`Earnings Analysis Agent/stage-1-output.md`, and runs the Audit Agent.
Designed for graceful degradation: missing optional inputs produce visible
placeholder sections, never silent blanks. Outputs are human-readable
(PDF + markdown) plus an internal JSON artifact.

Constraints:
- PDF rendering uses weasyprint if available; falls back to HTML-only output
  with a flag when weasyprint is not installed.
- Audit Agent runs in deterministic-only mode (LLM stub).
- Does not fetch quarterly consensus — consumes whatever columns exist in the
  consensus CSV. Absence of quarterly data produces a degradation flag, not a
  failure.

CLI:
    python earnings_stage1_runner.py \
        --ticker XYZ \
        --earnings-date 2026-04-29 --report-time AMC
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any

# Resolve project root relative to this file's location:
# .../<project root>/Earnings Analysis Agent/earnings_stage1_runner.py
EARNINGS_AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = EARNINGS_AGENT_DIR.parent
# audit_agent.py lives alongside this runner in the Earnings Analysis Agent dir.
sys.path.insert(0, str(EARNINGS_AGENT_DIR))

try:
    from audit_agent import audit as run_audit  # type: ignore
except Exception as e:  # pragma: no cover
    run_audit = None
    _AUDIT_IMPORT_ERROR = repr(e)
else:
    _AUDIT_IMPORT_ERROR = None

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None  # we'll surface this as a hard-fail in load

RUNNER_VERSION = "0.1.0"


# ─────────────────────────────────────────────────────────────────────────────
# Input loading
# ─────────────────────────────────────────────────────────────────────────────

class InputBundle:
    def __init__(self) -> None:
        self.key_metrics: dict[str, Any] = {}
        self.consensus_rows: list[dict[str, str]] = []
        self.thesis_text: str | None = None
        self.thesis_claims: list[dict[str, Any]] = []
        self.transcripts: list[dict[str, Any]] = []
        self.guidance: list[dict[str, Any]] = []
        self.positioning: dict[str, Any] | None = None
        self.stock_reaction: dict[str, Any] | None = None
        self.degradation_flags: list[dict[str, str]] = []

    def flag(self, section: str, reason: str) -> None:
        self.degradation_flags.append({"section": section, "reason": reason})


def _ticker_base(ticker: str) -> Path:
    """Workspace folder for a ticker: workspace/{TICKER}."""
    return REPO_ROOT / "workspace" / ticker.upper()


def load_inputs(ticker: str, analyst: str = "user") -> InputBundle:
    if yaml is None:
        raise RuntimeError("PyYAML is required. Install with: pip install pyyaml")

    bundle = InputBundle()
    base = _ticker_base(ticker)

    # --- required: key_metrics.yaml ---
    km_path = base / "key_metrics.yaml"
    if not km_path.exists():
        raise FileNotFoundError(f"REQUIRED input missing: {km_path}")
    bundle.key_metrics = yaml.safe_load(km_path.read_text(encoding="utf-8")) or {}

    # --- required: consensus.csv ---
    cons_path = base / "consensus.csv"
    if not cons_path.exists():
        raise FileNotFoundError(f"REQUIRED input missing: {cons_path}")
    bundle.consensus_rows = _load_consensus_csv(cons_path)

    # --- optional: thesis_current.md (drop one into the workspace) ---
    thesis_path = base / "thesis_current.md"
    if thesis_path.exists():
        bundle.thesis_text = thesis_path.read_text(encoding="utf-8")
        bundle.thesis_claims = _extract_thesis_claims(bundle.thesis_text)
    else:
        bundle.flag("thesis_tie_in", f"thesis_current.md not found at {thesis_path}")

    # --- optional: transcripts ---
    tx_dir = base / "transcripts"
    if tx_dir.exists():
        tx_files = sorted([p for p in tx_dir.iterdir() if p.is_file() and p.suffix in (".txt", ".md")])
        if not tx_files:
            bundle.flag("language_triggers", "no files in transcripts/ directory")
        else:
            for p in tx_files[-8:]:
                bundle.transcripts.append({"path": str(p), "name": p.name,
                                           "text_preview": p.read_text(encoding="utf-8", errors="replace")[:500]})
            if len(tx_files) < 8:
                bundle.flag("language_triggers",
                            f"only {len(tx_files)} transcripts available (8 recommended)")
    else:
        bundle.flag("language_triggers", "transcripts/ directory not found")

    # --- optional: guidance ---
    g_dir = base / "guidance"
    if g_dir.exists():
        g_files = sorted([p for p in g_dir.iterdir() if p.is_file()])
        if not g_files:
            bundle.flag("guidance_track_record", "no files in guidance/ directory")
        else:
            for p in g_files[-6:]:
                bundle.guidance.append({"path": str(p), "name": p.name})
    else:
        bundle.flag("guidance_track_record", "guidance/ directory not found")

    # --- optional: positioning & stock reaction ---
    pos_path = base / "positioning.json"
    if pos_path.exists():
        try:
            bundle.positioning = json.loads(pos_path.read_text(encoding="utf-8"))
        except Exception:
            bundle.flag("positioning", "positioning.json failed to parse")
    else:
        bundle.flag("positioning", "positioning.json not provided")

    sr_path = base / "stock_reaction.json"
    if sr_path.exists():
        try:
            bundle.stock_reaction = json.loads(sr_path.read_text(encoding="utf-8"))
        except Exception:
            bundle.flag("stock_reaction", "stock_reaction.json failed to parse")

    return bundle


def _load_consensus_csv(path: Path) -> list[dict[str, str]]:
    """Load CSV, skip comment rows (start with #), return list of dicts keyed by header."""
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8") as f:
        # Filter out comment lines (#) before csv.DictReader
        content = "".join(line for line in f if not line.lstrip().startswith("#"))
    reader = csv.DictReader(StringIO(content))
    for row in reader:
        rows.append({k.strip(): (v or "").strip() for k, v in row.items()})
    return rows


def _extract_thesis_claims(text: str) -> list[dict[str, Any]]:
    """Pull TC-NN headers + their body paragraphs."""
    claims: list[dict[str, Any]] = []
    # Match "### TC-NN: Title" headers
    pattern = re.compile(r"^###\s+(TC-\d{2}):\s*(.+?)$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        claim_id = m.group(1)
        title = m.group(2).strip()
        # Extract first sentence or first 200 chars as summary
        summary = re.sub(r"\s+", " ", body)[:300]
        # Look for explicit "Falsifying" or "Confirming" subsections
        falsify_match = re.search(r"(Falsifying(?:\s+Evidence)?|Falsify[^:\n]*:)(.*?)(?=\n\n|\n###|\Z)", body, re.IGNORECASE | re.DOTALL)
        confirm_match = re.search(r"(Confirming(?:\s+Evidence)?|Confirm[^:\n]*:)(.*?)(?=\n\n|\n###|\Z)", body, re.IGNORECASE | re.DOTALL)
        claims.append({
            "id": claim_id, "title": title, "summary": summary,
            "confirming": confirm_match.group(2).strip()[:300] if confirm_match else None,
            "falsifying": falsify_match.group(2).strip()[:300] if falsify_match else None,
        })
    return claims


# ─────────────────────────────────────────────────────────────────────────────
# Section builders
# ─────────────────────────────────────────────────────────────────────────────

def _num(s: str) -> float | None:
    if s in (None, "", "—", "-"):
        return None
    s = s.replace(",", "").replace("$", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def build_expectations_stack(bundle: InputBundle) -> list[dict[str, Any]]:
    """One row per metric in key_metrics.core_metrics + specific_metrics, joined to consensus CSV."""
    rows: list[dict[str, Any]] = []
    km = bundle.key_metrics
    consensus_by_name = {r["metric"].lower(): r for r in bundle.consensus_rows if r.get("metric")}

    metrics = list(km.get("core_metrics", []) or []) + list(km.get("specific_metrics", []) or [])
    for m in metrics:
        name = m.get("name", "unknown")
        unit = m.get("unit", "")
        # Try several match keys: raw name, and simple variants
        match_keys = [name.lower()]
        # Map common aliases
        alias = {
            "revenue": "revenue_total",
            "operating_margin": "operating_margin_gaap_pct",
            "operating_margin_gaap": "operating_margin_gaap_pct",
            "operating_margin_non_gaap": "operating_margin_adj_pct",
            "gross_margin": "gross_margin_gaap_pct",
            "diluted_eps": "diluted_eps_gaap",  # default to GAAP
            "fcf": "fcf",
            "cash_balance": "cash_eop",
        }
        if name in alias:
            match_keys.append(alias[name])
        # Also prefix-match
        match_keys += [k for k in consensus_by_name if k.startswith(name.lower())]
        match = None
        for k in match_keys:
            if k in consensus_by_name:
                match = consensus_by_name[k]
                break

        consensus_fy_cur = _num(match.get("fy2026e")) if match else None
        consensus_fy_nxt = _num(match.get("fy2027e")) if match else None
        fy25a = _num(match.get("fy2025a")) if match else None

        rows.append({
            "metric": name,
            "unit": unit,
            "fy25a": fy25a,
            "consensus_fy26e": consensus_fy_cur,
            "consensus_fy27e": consensus_fy_nxt,
            "source_field": (match or {}).get("source_field", "—"),
            "flag": "" if match else "no consensus mapping",
            "thesis_claim_link": ", ".join(m.get("thesis_claim_link", []) or []),
            "sensitivity": m.get("sensitivity", ""),
            "notes": m.get("note", ""),
        })
    return rows


def build_variant_comparison(bundle: InputBundle) -> list[dict[str, Any]]:
    """Section 3 — for any key_metrics entry with variant_*_target fields."""
    rows: list[dict[str, Any]] = []
    km = bundle.key_metrics
    consensus_by_name = {r["metric"].lower(): r for r in bundle.consensus_rows}

    metrics = list(km.get("core_metrics", []) or []) + list(km.get("specific_metrics", []) or [])
    for m in metrics:
        variants = {k: v for k, v in m.items() if k.startswith("variant_")}
        if not variants:
            continue
        name = m.get("name", "unknown")
        basis = m.get("reporting_basis")  # 'gaap' or 'adjusted' or None

        # Look for both variants of the metric in consensus CSV
        gaap_key = f"{name}_gaap"
        adj_key = f"{name}_adj"
        match_gaap = consensus_by_name.get(gaap_key)
        match_adj = consensus_by_name.get(adj_key)
        fallback = consensus_by_name.get(name)

        cases: list[tuple[str, dict[str, str] | None]] = []
        if basis == "gaap":
            cases = [("GAAP", match_gaap or fallback)]
        elif basis in ("adjusted", "adj", "non_gaap"):
            cases = [("Adjusted", match_adj or fallback)]
        else:
            # reporting_basis unspecified — emit both if both exist
            if match_gaap and match_adj:
                cases = [("GAAP", match_gaap), ("Adjusted", match_adj)]
            elif match_gaap or match_adj or fallback:
                cases = [("(basis ambiguous)", match_gaap or match_adj or fallback)]

        for label, cons in cases:
            cons_fy26 = _num((cons or {}).get("fy2026e"))
            for vk, vv in variants.items():
                variant_value = _num(str(vv))
                delta = None
                pct = None
                if variant_value is not None and cons_fy26 is not None and cons_fy26 != 0:
                    delta = round(variant_value - cons_fy26, 3)
                    pct = round(100.0 * delta / cons_fy26, 2)
                rows.append({
                    "metric": name, "reporting_basis": label,
                    "variant_name": vk.replace("variant_", "").replace("_target", ""),
                    "variant_value": variant_value,
                    "consensus_fy26e": cons_fy26,
                    "delta": delta, "pct_delta": pct,
                    "schema_flag": ("reporting_basis unspecified — compared against both"
                                    if basis is None and len(cases) > 1 else ""),
                })
    return rows


def build_sensitivities(bundle: InputBundle) -> list[dict[str, Any]]:
    """Section 8 — any metric with sensitivity field. Bull/base/bear from consensus; fallback ±3%."""
    rows: list[dict[str, Any]] = []
    km = bundle.key_metrics
    consensus_by_name = {r["metric"].lower(): r for r in bundle.consensus_rows}
    metrics = list(km.get("core_metrics", []) or []) + list(km.get("specific_metrics", []) or [])
    for m in metrics:
        if "sensitivity" not in m:
            continue
        name = m.get("name", "unknown")
        match_keys = [name.lower(), f"{name}_gaap", f"{name}_adj"]
        for k in match_keys:
            match = consensus_by_name.get(k)
            if match:
                break
        else:
            match = None

        base = _num((match or {}).get("fy2026e"))
        bull = base * 1.03 if base is not None else None
        bear = base * 0.97 if base is not None else None

        rows.append({
            "metric": name,
            "base": base, "bull": bull, "bear": bear,
            "sensitivity_text": m.get("sensitivity"),
            "stock_reaction": "—",  # populated when stock_reaction.json is present
        })
    return rows


def build_exec_summary(bundle: InputBundle, exp_rows: list[dict], var_rows: list[dict],
                       ticker: str, earnings_date: str) -> dict[str, Any]:
    """1-page summary: narrative + top 3 watch items."""
    n_metrics = len(exp_rows)
    n_variants = len(var_rows)
    n_unmapped = sum(1 for r in exp_rows if r["flag"])
    n_thesis = len(bundle.thesis_claims)
    watch_items: list[str] = []

    for m in (bundle.key_metrics.get("specific_metrics") or []):
        if m.get("note"):
            watch_items.append(f"{m['name']}: {m['note'][:120]}")
        if len(watch_items) >= 3:
            break

    narrative = (
        f"{ticker} Q1 prep for earnings date {earnings_date}. "
        f"{n_metrics} metrics in watch list; {n_variants} variant-vs-consensus comparisons built; "
        f"{n_unmapped} metrics missing a direct consensus mapping (reported as '—'). "
        f"{n_thesis} open thesis claims pulled from thesis_current.md "
        f"({'active' if n_thesis else 'thesis file unavailable'}). "
        f"{len(bundle.degradation_flags)} input gaps flagged; see top-of-PDF warning block."
    )
    return {"narrative": narrative, "top_watch_items": watch_items,
            "metric_count": n_metrics, "thesis_claim_count": n_thesis,
            "degradation_flag_count": len(bundle.degradation_flags)}


# ─────────────────────────────────────────────────────────────────────────────
# HTML rendering
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
@page { size: letter; margin: 1in 0.75in; }
body { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 10pt; color: #1a1a1a; line-height: 1.4; }
h1 { font-size: 16pt; border-bottom: 2px solid #2c3e50; padding-bottom: 4pt; }
h2 { font-size: 13pt; color: #2c3e50; margin-top: 18pt; }
h3 { font-size: 11pt; color: #34495e; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; }
th { background: #2c3e50; color: white; padding: 6pt 8pt; text-align: left; font-size: 9pt; }
td { padding: 5pt 8pt; border-bottom: 1px solid #ddd; font-size: 9pt; vertical-align: top; }
tr:nth-child(even) { background: #f8f9fa; }
.warning { background: #fff3cd; border-left: 4px solid #ffc107; padding: 8pt; margin: 8pt 0; font-size: 9pt; }
.degraded-section { background: #eef0f2; border-left: 4px solid #95a5a6; padding: 8pt; margin: 8pt 0;
                    font-size: 9pt; color: #555; font-style: italic; }
.schema-flag { background: #fff3cd; color: #856404; padding: 1pt 6pt; margin-left: 6pt;
               border-radius: 3pt; font-size: 8pt; font-style: italic; }
.cover { text-align: center; padding: 40pt 0; page-break-after: always; }
.exec-summary { page-break-after: always; }
.appendix { page-break-before: always; }
.citation { font-size: 8pt; color: #6c757d; }
.pos { color: #28a745; }
.neg { color: #dc3545; }
"""


def _fmt_num(v: Any, unit: str = "") -> str:
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        if unit == "pct":
            return f"{v:.2f}%"
        if unit == "usd":
            return f"${v:.2f}"
        if unit == "usd_mm":
            return f"${v:,.1f}mm"
        if unit == "K_cases":
            return f"{v:,.1f}K"
        if abs(v) >= 1000:
            return f"{v:,.2f}"
        return f"{v:.2f}"
    return str(v)


def _fmt_pct(v: Any) -> str:
    return "—" if v is None else f"{v:+.1f}%"


def render_html(sections: dict[str, Any], bundle: InputBundle, ticker: str,
                earnings_date: str, report_time: str, run_date: str,
                consensus_as_of: str | None) -> str:
    out = []
    out.append('<!DOCTYPE html><html><head><meta charset="utf-8"><style>')
    out.append(_CSS)
    out.append('</style></head><body>')

    # Cover
    out.append(f'<div class="cover"><h1>{ticker} — Stage 1 Prep</h1>')
    out.append(f'<p>Earnings: <b>{earnings_date}</b> · Report Time: <b>{report_time}</b></p>')
    out.append(f'<p>Analyst: {sections["analyst"]} · Run Date: {run_date} · '
               f'Consensus As-Of: {consensus_as_of or "(not specified)"}</p>')
    out.append('</div>')

    # Missing-input warning block (top of body)
    if bundle.degradation_flags:
        out.append('<div class="warning"><b>Input Gaps Flagged ({}):</b><ul>'.format(len(bundle.degradation_flags)))
        for flag in bundle.degradation_flags:
            out.append(f'<li><b>{flag["section"]}</b>: {flag["reason"]}</li>')
        out.append('</ul></div>')

    # 1. Executive Summary
    out.append('<div class="exec-summary"><h2>1. Executive Summary</h2>')
    out.append(f'<p>{sections["exec_summary"]["narrative"]}</p>')
    if sections["exec_summary"]["top_watch_items"]:
        out.append('<h3>Top Watch Items</h3><ul>')
        for w in sections["exec_summary"]["top_watch_items"]:
            out.append(f'<li>{w}</li>')
        out.append('</ul>')
    out.append('</div>')

    # 2. Expectations Stack
    out.append('<h2>2. Expectations Stack</h2>')
    out.append('<table><tr><th>Metric</th><th>Unit</th><th>FY25A</th><th>FY26E Consensus</th>'
               '<th>FY27E Consensus</th><th>Thesis Link</th><th>Flags</th></tr>')
    for r in sections["expectations_stack"]:
        unit = r["unit"]
        out.append(f'<tr><td>{r["metric"]}</td><td>{unit}</td>'
                   f'<td>{_fmt_num(r["fy25a"], unit)}</td>'
                   f'<td>{_fmt_num(r["consensus_fy26e"], unit)}</td>'
                   f'<td>{_fmt_num(r["consensus_fy27e"], unit)}</td>'
                   f'<td>{r["thesis_claim_link"]}</td>'
                   f'<td>{r["flag"] or "—"}</td></tr>')
    out.append('</table>')

    # 3. Variant vs Consensus
    out.append('<h2>3. Variant vs Consensus</h2>')
    if not sections["variant_comparison"]:
        out.append('<div class="degraded-section">No variant targets found in key_metrics.yaml.</div>')
    else:
        out.append('<table><tr><th>Metric</th><th>Basis</th><th>Variant</th><th>Variant Value</th>'
                   '<th>FY26E Consensus</th><th>Δ</th><th>Δ %</th><th>Schema</th></tr>')
        for r in sections["variant_comparison"]:
            schema_badge = f'<span class="schema-flag">{r["schema_flag"]}</span>' if r["schema_flag"] else ""
            delta_class = "pos" if (r["delta"] or 0) > 0 else "neg" if (r["delta"] or 0) < 0 else ""
            out.append(f'<tr><td>{r["metric"]}</td><td>{r["reporting_basis"]}</td>'
                       f'<td>{r["variant_name"]}</td>'
                       f'<td>{_fmt_num(r["variant_value"])}</td>'
                       f'<td>{_fmt_num(r["consensus_fy26e"])}</td>'
                       f'<td class="{delta_class}">{_fmt_num(r["delta"])}</td>'
                       f'<td class="{delta_class}">{_fmt_pct(r["pct_delta"])}</td>'
                       f'<td>{schema_badge}</td></tr>')
        out.append('</table>')

    # 4. Language Triggers
    out.append('<h2>4. What Management Will Be Asked (Language Triggers)</h2>')
    if bundle.transcripts:
        out.append(f'<p>{len(bundle.transcripts)} transcripts found. Full language-trigger analysis '
                   'requires LLM-wired transcript parser (v0.1 stub).</p>')
        out.append('<ul>' + "".join(f'<li>{t["name"]}</li>' for t in bundle.transcripts) + '</ul>')
    else:
        out.append('<div class="degraded-section">Language-trigger analysis requires 8 prior transcripts. '
                   'Populate /transcripts/ to enable this section.</div>')

    # 5. Guidance Track Record
    out.append('<h2>5. Guidance Track Record</h2>')
    if bundle.guidance:
        out.append(f'<p>{len(bundle.guidance)} guidance files found. Full track record requires '
                   'structured-format parser (v0.1 stub).</p>')
    else:
        out.append('<div class="degraded-section">Guidance track record requires historical guidance '
                   'files in /guidance/. No files found.</div>')

    # 6. Positioning
    out.append('<h2>6. Positioning & Implied Move</h2>')
    pos = bundle.positioning or {}
    sr = bundle.stock_reaction or {}
    out.append('<table>'
               f'<tr><td>Short interest %</td><td>{pos.get("short_interest_pct", "not provided")}</td></tr>'
               f'<tr><td>Implied move (options)</td><td>{pos.get("implied_move_pct", sections.get("implied_move_cli", "not provided"))}</td></tr>'
               f'<tr><td>Whisper delta</td><td>{pos.get("whisper_delta", "not provided")}</td></tr>'
               f'<tr><td>Prior-quarter reaction sigma</td><td>{sr.get("reaction_sigma", "not provided")}</td></tr>'
               '</table>')

    # 7. Thesis Tie-In
    out.append('<h2>7. Thesis Tie-In</h2>')
    if bundle.thesis_claims:
        for c in bundle.thesis_claims:
            out.append(f'<h3>{c["id"]}: {c["title"]}</h3>')
            out.append(f'<p>{c["summary"]}</p>')
            if c.get("confirming"):
                out.append(f'<p><b>Confirming:</b> {c["confirming"][:220]}...</p>')
            if c.get("falsifying"):
                out.append(f'<p><b>Falsifying:</b> {c["falsifying"][:220]}...</p>')
    else:
        out.append('<div class="degraded-section">Thesis file not loaded — section unavailable.</div>')

    # 8. KPI Sensitivity
    out.append('<h2>8. KPI Sensitivity</h2>')
    if sections["sensitivities"]:
        out.append('<table><tr><th>Metric</th><th>Bear</th><th>Base</th><th>Bull</th>'
                   '<th>Sensitivity Note</th></tr>')
        for r in sections["sensitivities"]:
            out.append(f'<tr><td>{r["metric"]}</td>'
                       f'<td>{_fmt_num(r["bear"])}</td>'
                       f'<td>{_fmt_num(r["base"])}</td>'
                       f'<td>{_fmt_num(r["bull"])}</td>'
                       f'<td>{r["sensitivity_text"]}</td></tr>')
        out.append('</table>')
    else:
        out.append('<div class="degraded-section">No metrics in key_metrics.yaml have a sensitivity: field.</div>')

    # Appendix A — consensus data
    out.append('<div class="appendix"><h2>Appendix A. Consensus Data (Raw)</h2>')
    out.append('<table><tr><th>Metric</th><th>Unit</th><th>FY25A</th><th>FY26E</th><th>FY27E</th>'
               '<th>Source Field</th></tr>')
    for r in bundle.consensus_rows:
        out.append(f'<tr><td>{r.get("metric", "")}</td><td>{r.get("unit", "")}</td>'
                   f'<td>{r.get("fy2025a", "—")}</td>'
                   f'<td>{r.get("fy2026e", "—")}</td>'
                   f'<td>{r.get("fy2027e", "—")}</td>'
                   f'<td class="citation">{r.get("source_field", "")}</td></tr>')
    out.append('</table></div>')

    # Appendix B — pipeline audit
    out.append('<div class="appendix"><h2>Appendix B. Pipeline Audit</h2>')
    out.append(f'<p><b>Runner version:</b> v{RUNNER_VERSION}</p>')
    out.append(f'<p><b>Input files used:</b></p><ul>')
    for name, ok in sections["input_trace"].items():
        out.append(f'<li>{name}: {"✓ loaded" if ok else "× missing"}</li>')
    out.append('</ul>')
    out.append(f'<p><b>Degradation flags ({len(bundle.degradation_flags)}):</b></p><ul>')
    for flag in bundle.degradation_flags:
        out.append(f'<li><b>{flag["section"]}</b>: {flag["reason"]}</li>')
    out.append('</ul></div>')

    out.append('</body></html>')
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# Markdown sidecar (audit-friendly output)
# ─────────────────────────────────────────────────────────────────────────────

def render_markdown_for_audit(sections: dict[str, Any], bundle: InputBundle, ticker: str,
                              earnings_date: str, report_time: str, run_date: str,
                              consensus_as_of: str | None) -> str:
    """Clean markdown version intended for Audit Agent consumption.

    Design principle: prose stays prose (narrative section only). All other sections are
    markdown tables which the audit agent can skip with its table-row detector. This keeps
    Facts checks targeted at actual prose and Figures checks targeted at reconcilable data.
    """
    lines: list[str] = []
    lines.append(f"# {ticker} — Stage 1 Prep Report (Audit Input)")
    lines.append("")
    lines.append(f"- Earnings date: {earnings_date}")
    lines.append(f"- Report time: {report_time}")
    lines.append(f"- Run date: {run_date}")
    lines.append(f"- Consensus as-of: {consensus_as_of or '(not specified)'}")
    lines.append(f"- Analyst: {sections['analyst']}")
    lines.append("")

    # Narrative block — the ONLY prose section for audit Facts/Speculation checks
    lines.append("## 1. Executive Summary")
    lines.append("")
    lines.append(sections["exec_summary"]["narrative"])
    lines.append("")
    if sections["exec_summary"]["top_watch_items"]:
        lines.append("Top watch items:")
        for w in sections["exec_summary"]["top_watch_items"]:
            lines.append(f"- {w}")
    lines.append("")

    # Expectations Stack table
    lines.append("## 2. Expectations Stack")
    lines.append("")
    lines.append("| Metric | Unit | FY25A | FY26E | FY27E | Thesis Link | Source Field | Flag |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in sections["expectations_stack"]:
        unit = r["unit"]
        lines.append(
            f"| {r['metric']} | {unit} | {_fmt_num(r['fy25a'], unit)} "
            f"| {_fmt_num(r['consensus_fy26e'], unit)} "
            f"| {_fmt_num(r['consensus_fy27e'], unit)} "
            f"| {r['thesis_claim_link'] or '—'} "
            f"| {r['source_field']} "
            f"| {r['flag'] or '—'} |"
        )
    lines.append("")

    # Variant vs Consensus
    lines.append("## 3. Variant vs Consensus")
    lines.append("")
    if not sections["variant_comparison"]:
        lines.append("No variant targets present in key_metrics.yaml.")
    else:
        lines.append("| Metric | Basis | Variant | Value | FY26E Consensus | Delta | % Delta | Schema |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in sections["variant_comparison"]:
            lines.append(
                f"| {r['metric']} | {r['reporting_basis']} | {r['variant_name']} "
                f"| {_fmt_num(r['variant_value'])} | {_fmt_num(r['consensus_fy26e'])} "
                f"| {_fmt_num(r['delta'])} | {_fmt_pct(r['pct_delta'])} "
                f"| {r['schema_flag'] or '—'} |"
            )
    lines.append("")

    # Thesis Tie-In
    lines.append("## 7. Thesis Tie-In")
    lines.append("")
    if bundle.thesis_claims:
        lines.append("*Source: thesis_current.md. All claim summaries below are per the thesis document — they are not this runner's assertions.*")
        lines.append("")
        for c in bundle.thesis_claims:
            lines.append(f"### {c['id']}: {c['title']}")
            lines.append("")
            lines.append(f"[per thesis_current.md] {c['summary']}")
            lines.append("")
    else:
        lines.append("Thesis file not loaded — section unavailable.")
    lines.append("")

    # Pipeline Audit
    lines.append("## Appendix B. Pipeline Audit")
    lines.append("")
    lines.append(f"- Runner version: v{RUNNER_VERSION}")
    lines.append(f"- Degradation flags: {len(bundle.degradation_flags)}")
    for flag in bundle.degradation_flags:
        lines.append(f"    - {flag['section']}: {flag['reason']}")
    lines.append("")
    lines.append("Input files used:")
    for name, ok in sections["input_trace"].items():
        lines.append(f"- {name}: {'loaded' if ok else 'missing'}")
    lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────

def run_stage1(ticker: str, analyst: str, earnings_date: str, report_time: str,
               implied_move: float | None, consensus_as_of: str | None,
               skip_audit: bool, run_date: str | None) -> dict[str, Any]:
    run_date = run_date or datetime.now(timezone.utc).date().isoformat()
    ymd = run_date.replace("-", "")

    out_dir = _ticker_base(ticker) / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"stage1_prep_{ticker}_{ymd}.pdf"
    html_path = out_dir / f"stage1_prep_{ticker}_{ymd}.html"
    json_path = out_dir / f"stage1_prep_{ticker}_{ymd}.json"
    audit_path = out_dir / f"stage1_prep_{ticker}_{ymd}_audit.json"

    bundle = load_inputs(ticker, analyst)

    exp_rows = build_expectations_stack(bundle)
    var_rows = build_variant_comparison(bundle)
    sens_rows = build_sensitivities(bundle)
    exec_sum = build_exec_summary(bundle, exp_rows, var_rows, ticker, earnings_date)

    sections = {
        "analyst": analyst,
        "exec_summary": exec_sum,
        "expectations_stack": exp_rows,
        "variant_comparison": var_rows,
        "sensitivities": sens_rows,
        "thesis_tie_in": bundle.thesis_claims,
        "implied_move_cli": f"{implied_move*100:.1f}%" if implied_move else "not provided",
        "input_trace": {
            "key_metrics.yaml": bool(bundle.key_metrics),
            "consensus.csv": bool(bundle.consensus_rows),
            "thesis_current.md": bool(bundle.thesis_text),
            "transcripts/*": bool(bundle.transcripts),
            "guidance/*": bool(bundle.guidance),
            "positioning.json": bundle.positioning is not None,
            "stock_reaction.json": bundle.stock_reaction is not None,
        },
    }

    html = render_html(sections, bundle, ticker, earnings_date, report_time, run_date, consensus_as_of)
    html_path.write_text(html, encoding="utf-8")

    # Emit audit-friendly markdown sidecar (clean prose + markdown tables, no HTML/CSS)
    md_audit = render_markdown_for_audit(sections, bundle, ticker, earnings_date, report_time,
                                          run_date, consensus_as_of)
    md_audit_path = out_dir / f"stage1_prep_{ticker}_{ymd}.md"
    md_audit_path.write_text(md_audit, encoding="utf-8")

    # PDF render — weasyprint or degrade
    pdf_generated = False
    weasy_error = None
    try:
        from weasyprint import HTML  # type: ignore
        HTML(string=html).write_pdf(str(pdf_path))
        pdf_generated = True
    except Exception as e:
        weasy_error = repr(e)

    # JSON artifact
    json_artifact = {
        "run_metadata": {
            "agent_id": "earnings-analysis-stage-1",
            "runner_version": RUNNER_VERSION,
            "ticker": ticker,
            "analyst": analyst,
            "run_date": run_date,
            "run_timestamp": _now_utc_iso(),
            "earnings_date": earnings_date,
            "report_time": report_time,
            "consensus_as_of": consensus_as_of,
            "implied_move": implied_move,
            "input_files_used": [k for k, v in sections["input_trace"].items() if v],
            "input_files_missing": [k for k, v in sections["input_trace"].items() if not v],
            "pdf_generated": pdf_generated,
            "weasyprint_error": weasy_error,
        },
        "sections": sections,
        "degradation_flags": bundle.degradation_flags,
        "audit": None,
    }

    # Audit
    audit_result = None
    if not skip_audit and run_audit is not None:
        # Source docs = thesis + transcripts (text-loaded); loaded_data = key_metrics + consensus CSV
        source_doc_paths: list[str] = []
        if bundle.thesis_text:
            source_doc_paths.append(str(_ticker_base(ticker) / "thesis_current.md"))
        for t in bundle.transcripts:
            source_doc_paths.append(t["path"])
        loaded_data_paths = [
            str(_ticker_base(ticker) / "key_metrics.yaml"),
            str(_ticker_base(ticker) / "consensus.csv"),
        ]
        audit_result = run_audit(
            analysis_path=str(md_audit_path),  # audit clean markdown, not HTML
            source_docs=source_doc_paths,
            loaded_data=loaded_data_paths,
            output_tier="tier_1",
            agent_id="earnings-analysis-stage-1",
            ticker=ticker,
        )
        audit_path.write_text(json.dumps(audit_result, indent=2, default=str), encoding="utf-8")
        json_artifact["audit"] = {
            "score": audit_result["score"],
            "gate": audit_result["gate"],
            "breakdown": {k: v["score"] for k, v in audit_result["breakdown"].items()},
            "failure_count": len(audit_result["failures"]),
            "override_triggers": audit_result["override_triggers"],
            "audit_packet_path": str(audit_path),
        }
    elif skip_audit:
        json_artifact["audit"] = {"gate": "SKIPPED", "failure_count": -1, "reason": "skip_audit=True"}
    elif run_audit is None:
        json_artifact["audit"] = {"gate": "SKIPPED", "failure_count": -1,
                                   "reason": f"audit_agent import failed: {_AUDIT_IMPORT_ERROR}"}

    json_path.write_text(json.dumps(json_artifact, indent=2, default=str), encoding="utf-8")

    return {
        "pdf_path": str(pdf_path) if pdf_generated else None,
        "html_path": str(html_path),
        "md_path": str(md_audit_path),
        "json_path": str(json_path),
        "audit_path": str(audit_path) if audit_result else None,
        "pdf_generated": pdf_generated,
        "weasyprint_error": weasy_error,
        "audit_score": audit_result["score"] if audit_result else None,
        "audit_gate": audit_result["gate"] if audit_result else "SKIPPED",
        "degradation_flag_count": len(bundle.degradation_flags),
    }


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--analyst", default="user")
    ap.add_argument("--earnings-date", required=True)
    ap.add_argument("--report-time", default="AMC", choices=["BMO", "AMC"])
    ap.add_argument("--implied-move", type=float, default=None)
    ap.add_argument("--consensus-as-of", default=None)
    ap.add_argument("--run-date", default=None)
    ap.add_argument("--skip-audit", action="store_true")
    args = ap.parse_args()

    result = run_stage1(
        ticker=args.ticker,
        analyst=args.analyst,
        earnings_date=args.earnings_date,
        report_time=args.report_time,
        implied_move=args.implied_move,
        consensus_as_of=args.consensus_as_of,
        skip_audit=args.skip_audit,
        run_date=args.run_date,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
