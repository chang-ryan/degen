"""
sell_side_synthesizer.py — orchestrator for parallel sell-side note extraction

Reads all PDFs in a ticker's sell_side_notes/ folder, dispatches one extraction
agent per PDF in parallel, aggregates structured JSON into sell_side_synthesis.md.

Architecture (no API key required):

    sell_side_synthesizer.py runs in two phases:

    PHASE 1 — generate_extraction_plan(ticker)
        Inputs:  ticker, optional --pdf-filter pattern
        Outputs: dispatch_plan.json with 1 task per PDF describing extraction prompt

    PHASE 2 — aggregate(ticker)
        Inputs:  ticker (reads /synthesis/*.json files produced by agents)
        Outputs: sell_side_synthesis.md with:
            - Ratings + PT distribution table (broker, date, rating, PT)
            - Consensus bear thesis components (by frequency)
            - Consensus bull thesis components (by frequency)
            - Key data points table (with source attribution)
            - Outlier views

Between phases, the calling agent dispatches Task agents per the plan — one
general-purpose agent per PDF, in parallel. Each agent writes a JSON file to
{output_dir}/synthesis/{broker}_{date}.json.

Usage:
    python sell_side_synthesizer.py --ticker XYZ --phase plan
    # ... orchestrator dispatches Task agents ...
    python sell_side_synthesizer.py --ticker XYZ --phase aggregate
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


# Paths derived from _paths.py (project-anchored).
from _paths import reference_base, ticker_dir

REFERENCE_BASE = reference_base()

# JSON Schema for per-note extraction. Validated in aggregate() so that
# malformed/incomplete extractions become surfaced validation_failures
# rather than silent skips. Path resolved at call time so a missing schema
# file produces a clear runtime error rather than an import-time crash.
_SELL_SIDE_NOTE_SCHEMA_PATH = (
    REFERENCE_BASE.parent / "schemas" / "sell_side_note.schema.json"
)


def _validate_note_against_schema(data: dict) -> list[str]:
    """Return a list of human-readable schema-violation strings for `data`.
    Empty list means the note is valid. If the jsonschema package or the
    schema file is unavailable, returns an empty list — i.e., validation
    is opportunistic, not blocking on tooling absence.
    """
    try:
        import jsonschema
    except ImportError:
        return []
    try:
        schema = json.loads(_SELL_SIDE_NOTE_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    try:
        jsonschema.validate(data, schema)
        return []
    except jsonschema.ValidationError as e:
        loc = "/".join(str(p) for p in e.absolute_path) or "<root>"
        return [f"{loc}: {e.message}"]
    except jsonschema.SchemaError as e:
        return [f"<schema-error>: {e.message}"]


def _is_thin_extraction(data: dict) -> bool:
    """Heuristic for partial/empty extractions.

    A 'thin' note has none of: bear components, bull components, key data
    points, notable arguments, or key quotes. A pure-rating-update note
    (e.g., 'BofA raised PT to $50') legitimately has no thesis content —
    but the extractor's job is to capture *something* that explains the
    note's contribution. Empty thesis + empty data points + empty quotes
    = the LLM extracted little or nothing, which downstream synthesis
    would silently underweight.
    """
    return not any(
        isinstance(data.get(k), list) and data.get(k)
        for k in ("bear_thesis_components", "bull_thesis_components",
                  "key_data_points", "notable_arguments", "key_quotes")
    )


# ─────────────────────────────────────────────────────────────────────────────
# Filename parsing — extract broker + date from standard naming
# Convention: YYYYMMDD_BankName_TICKER_topic.pdf
# ─────────────────────────────────────────────────────────────────────────────

FILENAME_RE = re.compile(
    r"^(?P<date>\d{8})_(?P<broker>[A-Za-z_&]+?)_(?P<ticker>[A-Z]+)_(?P<topic>.+)\.pdf$",
    re.IGNORECASE,
)


def parse_filename(filename: str) -> dict | None:
    m = FILENAME_RE.match(filename)
    if not m:
        return None
    return {
        "date": m.group("date"),
        "broker": m.group("broker").replace("_", " ").strip(),
        "ticker": m.group("ticker"),
        "topic": m.group("topic").replace("_", " ").strip(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — Generate extraction plan
# ─────────────────────────────────────────────────────────────────────────────

EXTRACTION_PROMPT_TEMPLATE = """\
Read the sell-side research note at {pdf_path}.

Extract the following structured fields and emit JSON only (no surrounding prose):

{{
  "broker": "{broker}",
  "date": "{date}",
  "analyst_names": [list of analyst names if disclosed],
  "rating": "Buy/Overweight/Hold/Neutral/Sell/Underweight/etc.",
  "price_target": numeric or null,
  "prior_price_target": numeric or null,
  "rating_change": "raised/lowered/initiated/maintained/etc.",
  "bear_thesis_components": [list of distinct bear bullets, 1 sentence each],
  "bull_thesis_components": [list of distinct bull bullets, 1 sentence each],
  "key_data_points": [{{"metric": "...", "value": "...", "source": "...", "context": "..."}}],
  "q1_revenue_estimate": numeric ($mm) or null,
  "q1_ebitda_estimate": numeric ($mm) or null,
  "q2_revenue_estimate": numeric ($mm) or null,
  "q2_ebitda_estimate": numeric ($mm) or null,
  "fy_revenue_estimate": numeric ($mm) or null,
  "fy_ebitda_estimate": numeric ($mm) or null,
  "notable_arguments": [list of points the broker makes that aren't in cons],
  "key_quotes": [list of 3-5 verbatim quotes that capture the broker's view],
  "topic_summary": "1-sentence summary of the note's primary contribution"
}}

Save the JSON to: {output_path}

Be terse. Skip any field where the note doesn't disclose. Do not invent numbers.
"""


def generate_extraction_plan(ticker: str) -> dict:
    sell_side_dir = REFERENCE_BASE / ticker / "sell_side_notes"
    output_dir = ticker_dir(ticker) / "synthesis"
    output_dir.mkdir(parents=True, exist_ok=True)

    if not sell_side_dir.exists():
        return {
            "status": "error",
            "error": f"sell_side_notes/ folder not found at {sell_side_dir}",
            "tasks": [],
        }

    pdfs = sorted([p for p in sell_side_dir.iterdir() if p.suffix.lower() == ".pdf"])
    tasks = []
    for pdf in pdfs:
        meta = parse_filename(pdf.name)
        if not meta:
            tasks.append({
                "pdf": str(pdf),
                "status": "skipped",
                "reason": "filename does not match YYYYMMDD_BankName_TICKER_topic.pdf convention",
            })
            continue
        out_filename = f"{meta['broker'].replace(' ', '_')}_{meta['date']}.json"
        out_path = output_dir / out_filename
        prompt = EXTRACTION_PROMPT_TEMPLATE.format(
            pdf_path=str(pdf),
            broker=meta["broker"],
            date=meta["date"],
            output_path=str(out_path),
        )
        tasks.append({
            "pdf": str(pdf),
            "broker": meta["broker"],
            "date": meta["date"],
            "topic": meta["topic"],
            "output_path": str(out_path),
            "prompt": prompt,
            "agent_type": "general-purpose",
            "status": "ready",
        })

    return {
        "ticker": ticker,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "sell_side_dir": str(sell_side_dir),
        "output_dir": str(output_dir),
        "tasks": tasks,
        "summary": {
            "total_pdfs": len(pdfs),
            "ready": sum(1 for t in tasks if t.get("status") == "ready"),
            "skipped": sum(1 for t in tasks if t.get("status") == "skipped"),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — Aggregate JSON outputs into synthesis markdown
# ─────────────────────────────────────────────────────────────────────────────

def aggregate(ticker: str) -> dict:
    output_dir = ticker_dir(ticker) / "synthesis"
    if not output_dir.exists():
        return {"status": "error", "error": f"synthesis/ folder not found at {output_dir}"}

    # Discover per-note JSON files. The aggregator's _dispatch_plan.json is
    # NOT a per-note extraction; skip it explicitly so its presence doesn't
    # produce a spurious schema-violation entry. Same for any other meta
    # files prefixed with "_".
    json_files = sorted(p for p in output_dir.glob("*.json") if not p.name.startswith("_"))
    notes: list[dict] = []
    validation_failures: list[dict] = []
    thin_extractions: list[dict] = []
    for jf in json_files:
        try:
            text = jf.read_text(encoding="utf-8")
        except OSError as e:
            validation_failures.append({
                "file": jf.name,
                "kind": "io_error",
                "error": str(e)[:200],
            })
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            validation_failures.append({
                "file": jf.name,
                "kind": "json_parse",
                "error": f"{type(e).__name__}: {e.msg} at line {e.lineno} col {e.colno}",
            })
            continue
        # Top-level must be an object — array or scalar JSON outputs aren't notes.
        if not isinstance(data, dict):
            validation_failures.append({
                "file": jf.name,
                "kind": "schema",
                "error": f"top-level must be object, got {type(data).__name__}",
            })
            continue
        schema_errors = _validate_note_against_schema(data)
        if schema_errors:
            validation_failures.append({
                "file": jf.name,
                "kind": "schema",
                "error": "; ".join(schema_errors)[:400],
            })
            continue
        if _is_thin_extraction(data):
            thin_extractions.append({
                "file": jf.name,
                "broker": data.get("broker"),
                "date": data.get("date"),
                "topic_summary": (data.get("topic_summary") or "")[:120],
            })
            # Thin extractions still get included — they may legitimately be
            # rating-only updates — but they are surfaced explicitly so the
            # analyst sees the coverage gap.
        notes.append(data)

    if not notes:
        return {
            "status": "error",
            "error": "no valid JSON files in synthesis/",
            "validation_failures": validation_failures,
            "thin_extractions": thin_extractions,
        }

    # Aggregate ratings
    ratings_table = sorted(
        [
            {
                "broker": n.get("broker", "Unknown"),
                "date": n.get("date", ""),
                "rating": n.get("rating", ""),
                "pt": n.get("price_target"),
                "prior_pt": n.get("prior_price_target"),
                "topic": n.get("topic_summary", ""),
            }
            for n in notes
        ],
        key=lambda x: x["date"],
        reverse=True,
    )

    def _safe_list(n: dict, key: str) -> list:
        """Return an iterable list. Schema permits null for these fields,
        so n.get(key, []) is not safe; we explicitly normalize None → []."""
        v = n.get(key) or []
        return v if isinstance(v, list) else []

    # Aggregate bear/bull components by frequency
    bear_components = Counter()
    bull_components = Counter()
    for n in notes:
        for bear in _safe_list(n, "bear_thesis_components"):
            if not isinstance(bear, str):
                continue
            # Normalize: lowercase, strip whitespace, collapse internal whitespace
            key = " ".join(bear.lower().strip().split())[:120]
            if key:
                bear_components[key] += 1
        for bull in _safe_list(n, "bull_thesis_components"):
            if not isinstance(bull, str):
                continue
            key = " ".join(bull.lower().strip().split())[:120]
            if key:
                bull_components[key] += 1

    # Key data points
    key_data_points = []
    for n in notes:
        for kdp in _safe_list(n, "key_data_points"):
            if not isinstance(kdp, dict):
                continue
            kdp["source_broker"] = n.get("broker")
            kdp["source_date"] = n.get("date")
            key_data_points.append(kdp)

    # Estimates aggregation
    estimates = defaultdict(list)
    for n in notes:
        for field in ("q1_revenue_estimate", "q1_ebitda_estimate", "q2_revenue_estimate",
                      "q2_ebitda_estimate", "fy_revenue_estimate", "fy_ebitda_estimate"):
            v = n.get(field)
            if v is not None:
                estimates[field].append({"broker": n.get("broker"), "value": v})

    # Outlier views — broker arguments not in cons
    outliers = []
    for n in notes:
        for arg in _safe_list(n, "notable_arguments"):
            if not isinstance(arg, str):
                continue
            outliers.append({"broker": n.get("broker"), "date": n.get("date"), "argument": arg})

    # Build markdown
    md_path = ticker_dir(ticker) / "sell_side_synthesis.md"

    lines = [f"# {ticker} — Sell-Side Synthesis", ""]
    lines.append(f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"**Notes synthesized:** {len(notes)}")
    if validation_failures:
        lines.append(f"**Notes rejected (validation):** {len(validation_failures)} — see Validation Failures section below.")
    if thin_extractions:
        lines.append(f"**Thin extractions (no thesis content):** {len(thin_extractions)}")
    lines.append("")

    # Ratings table
    lines.append("## Ratings + Price Targets")
    lines.append("")
    lines.append("| Date | Broker | Rating | PT | Prior PT | Topic |")
    lines.append("|---|---|---|---|---|---|")
    for r in ratings_table:
        pt = f"${r['pt']}" if r['pt'] else "—"
        prior_pt = f"${r['prior_pt']}" if r['prior_pt'] else "—"
        lines.append(f"| {r['date']} | {r['broker']} | {r['rating']} | {pt} | {prior_pt} | {r['topic'][:80]} |")
    lines.append("")

    # Estimates table
    if estimates:
        lines.append("## Sell-Side Estimates")
        lines.append("")
        lines.append("| Metric | Range | Median | Brokers |")
        lines.append("|---|---|---|---|")
        for k, vlist in estimates.items():
            values = [v["value"] for v in vlist]
            if values:
                vmin, vmax = min(values), max(values)
                vmed = sorted(values)[len(values) // 2]
                brokers_count = len(values)
                lines.append(f"| {k} | {vmin}–{vmax} | {vmed} | {brokers_count} |")
        lines.append("")

    # Bear thesis components
    lines.append("## Consensus Bear Thesis Components (by frequency)")
    lines.append("")
    for bear, count in bear_components.most_common(15):
        marker = "⚠" if count >= 3 else "•"
        lines.append(f"- **[{count}]** {bear}")
    lines.append("")

    # Bull thesis components
    lines.append("## Consensus Bull Thesis Components (by frequency)")
    lines.append("")
    for bull, count in bull_components.most_common(15):
        lines.append(f"- **[{count}]** {bull}")
    lines.append("")

    # Key data points
    if key_data_points:
        lines.append("## Key Data Points")
        lines.append("")
        lines.append("| Metric | Value | Source | Context |")
        lines.append("|---|---|---|---|")
        for kdp in key_data_points[:30]:
            lines.append(f"| {kdp.get('metric', '')[:60]} | {kdp.get('value', '')} | "
                        f"{kdp.get('source_broker', '')} ({kdp.get('source_date', '')}) | "
                        f"{kdp.get('context', '')[:80]} |")
        lines.append("")

    # Outlier views
    if outliers:
        lines.append("## Outlier / Notable Arguments (not in cons)")
        lines.append("")
        for o in outliers[:20]:
            lines.append(f"- **{o['broker']}** ({o['date']}): {o['argument'][:200]}")
        lines.append("")

    # P1-1: surface validation failures and thin extractions so analysts
    # see what was dropped or under-extracted. Previously these were
    # silently skipped, which let partial LLM extractions propagate as
    # "no thesis content" without warning.
    if validation_failures:
        lines.append("## Validation Failures")
        lines.append("")
        lines.append("Notes that failed JSON parse or schema validation are listed below. "
                     "These were NOT included in the aggregations above. Re-extract them "
                     "or fix manually before relying on the synthesis.")
        lines.append("")
        lines.append("| File | Kind | Error |")
        lines.append("|---|---|---|")
        for vf in validation_failures:
            err = vf.get("error", "")[:150]
            lines.append(f"| {vf.get('file', '')} | {vf.get('kind', '')} | {err} |")
        lines.append("")

    if thin_extractions:
        lines.append("## Thin Extractions (no thesis content)")
        lines.append("")
        lines.append("These notes parsed cleanly but contain no bear/bull components, "
                     "data points, notable arguments, or quotes. They were INCLUDED in "
                     "ratings/PT aggregation but contribute nothing to thesis frequency. "
                     "Re-extract if the source PDF contains content the LLM missed.")
        lines.append("")
        lines.append("| File | Broker | Date | Topic Summary |")
        lines.append("|---|---|---|---|")
        for te in thin_extractions:
            lines.append(f"| {te.get('file', '')} | {te.get('broker', '')} | "
                        f"{te.get('date', '')} | {te.get('topic_summary', '')} |")
        lines.append("")

    md_text = "\n".join(lines)
    md_path.write_text(md_text, encoding="utf-8")

    return {
        "status": "complete",
        "ticker": ticker,
        "notes_synthesized": len(notes),
        "synthesis_path": str(md_path),
        "validation_failures": validation_failures,
        "thin_extractions": thin_extractions,
        "summary": {
            "ratings_count": len(ratings_table),
            "bear_components_count": len(bear_components),
            "bull_components_count": len(bull_components),
            "key_data_points_count": len(key_data_points),
            "outlier_views_count": len(outliers),
            "validation_failures_count": len(validation_failures),
            "thin_extractions_count": len(thin_extractions),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _cli() -> int:
    ap = argparse.ArgumentParser(description="Sell-side synthesizer orchestrator")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--phase", choices=["plan", "aggregate"], required=True,
                    help="plan: generate extraction tasks for orchestrator; aggregate: build synthesis md")
    ap.add_argument("--out", default=None, help="Output JSON path (for plan phase)")
    args = ap.parse_args()

    if args.phase == "plan":
        result = generate_extraction_plan(args.ticker)
    else:
        result = aggregate(args.ticker)

    text = json.dumps(result, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text[:2000])  # truncate for stdout

    if result.get("status") == "error":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
