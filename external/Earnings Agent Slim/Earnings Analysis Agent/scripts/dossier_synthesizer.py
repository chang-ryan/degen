"""
dossier_synthesizer.py — Story Dossier auto-aggregator

Per PREVIEW_AGENT_SPEC.md §1.5. The Story Dossier gates drafting; without it,
the preview is missing the company-specific primary-source synthesis.

This script is a HYBRID:

  Phase 1 (auto-aggregation, pure Python):
    Consumes whatever structured inputs are present and produces
    synthesis_inputs.json with:
      - Optional position snapshot from position.json (if you track one)
      - Your own research notes index from research_notes/
      - Sell-side ratings + bear/bull components from sell_side_synthesis.md
      - Quantitative anchors from config.yaml (acquisitions, salient KPIs, day_of_binary)
      - Reference inventory (what was read) + SEC filings pulled

  Phase 2 (agent-fill, runbook):
    Emits STORY_DOSSIER_TEMPLATE.md with the required sections + auto-populated
    tables + structured prompts for the calling agent to fill the prose sections.

The CALLING AGENT consumes both outputs:
  1. Reads synthesis_inputs.json for structured data
  2. Fills the template sections (story / bear / bull / rally / accounting / questions)
     by reading the actual notes + sell-side PDFs + filings end-to-end
  3. Writes STORY_DOSSIER.md to disk

Everything is optional — the dossier degrades gracefully when an input is absent.

Usage:
  python dossier_synthesizer.py --ticker XYZ --phase aggregate
  python dossier_synthesizer.py --ticker XYZ --phase template
  python dossier_synthesizer.py --ticker XYZ --phase both
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from _paths import ticker_dir, reference_base

REFERENCE_BASE = reference_base()


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — Aggregate
# ─────────────────────────────────────────────────────────────────────────────

def aggregate(ticker: str) -> dict:
    tdir = ticker_dir(ticker)
    notes_dir = tdir / "research_notes"
    config_path = tdir / "config.yaml"
    sell_side_synth = tdir / "sell_side_synthesis.md"
    reference_dir = REFERENCE_BASE / ticker

    out = {
        "ticker": ticker,
        "synthesized_at": datetime.utcnow().isoformat() + "Z",
        "inputs": {},
        "structured_data": {},
        "warnings": [],
    }

    # 1. Optional position snapshot (your own — not from any data feed)
    mp_path = tdir / "position.json"
    if mp_path.exists():
        with open(mp_path) as f:
            mp = json.load(f)
        out["structured_data"]["position"] = {
            "direction": mp.get("direction"),
            "quantity": mp.get("quantity"),
            "invested_amount": mp.get("invested_amount"),
            "pct_portfolio": mp.get("pct_portfolio"),
            "as_of_date": mp.get("as_of_date"),
        }
        out["inputs"]["position"] = str(mp_path)
    else:
        out["warnings"].append("No position.json — position section will be left blank")

    # 2. Your own research notes — load index if present, else scan research_notes/
    notes = []
    if (notes_dir / "INDEX.json").exists():
        with open(notes_dir / "INDEX.json") as f:
            idx = json.load(f)
        notes = idx.get("notes", [])
        out["inputs"]["research_notes_index"] = str(notes_dir / "INDEX.json")
    elif notes_dir.exists():
        for jf in sorted(notes_dir.glob("*.json")):
            try:
                with open(jf) as f:
                    n = json.load(f)
                notes.append({
                    "date": n.get("date", n.get("createdDate", ""))[:10],
                    "title": n.get("title", ""),
                    "author": n.get("author", n.get("createdBy", "")),
                    "key_takeaways": (n.get("key_takeaways") or n.get("searchDescription", ""))[:500],
                })
            except (json.JSONDecodeError, OSError):
                continue
        out["inputs"]["research_notes_dir"] = str(notes_dir)
    out["structured_data"]["research_notes"] = notes
    out["structured_data"]["research_notes_count"] = len(notes)

    # 3. Config (acquisitions, salient KPIs, day-of binary)
    if config_path.exists():
        try:
            import yaml
            with open(config_path) as f:
                cfg = yaml.safe_load(f)
            out["structured_data"]["config"] = {
                "ticker": cfg.get("ticker"),
                "comp_set": cfg.get("comp_set"),
                "salient_kpis": cfg.get("salient_kpis", []),
                "day_of_binary": cfg.get("day_of_binary"),
                "conditional_sections": cfg.get("conditional_sections"),
                "acquisitions_in_play": cfg.get("acquisitions_in_play", []),
            }
            out["inputs"]["config"] = str(config_path)
        except ImportError:
            out["warnings"].append("PyYAML not installed; config.yaml not parsed")

    # 4. Sell-side synthesis
    if sell_side_synth.exists():
        out["inputs"]["sell_side_synthesis"] = str(sell_side_synth)
        text = sell_side_synth.read_text(encoding="utf-8")
        rating_lines = [l for l in text.splitlines()
                        if l.startswith("|") and any(r in l for r in
                        ["Buy", "Hold", "Overweight", "Neutral", "Underweight", "Sell", "Outperform"])]
        out["structured_data"]["sell_side_ratings_count"] = len(rating_lines)

    # 5. Reference Files inventory
    ref_inv = {}
    if reference_dir.exists():
        for sub in ["sell_side_notes", "press_releases", "ir_decks", "models", "transcripts"]:
            sub_path = reference_dir / sub
            ref_inv[sub] = len(list(sub_path.iterdir())) if sub_path.exists() else 0
        notes_files = [f.name for f in reference_dir.iterdir()
                       if f.is_file() and f.name.startswith("notes.")]
        ref_inv["notes_root"] = notes_files
    out["structured_data"]["reference_inventory"] = ref_inv

    # 6. SEC filings (extracts pulled by edgar_fetch.py)
    filings_dir = tdir / "filings"
    if filings_dir.exists():
        filing_files = [f.name for f in filings_dir.iterdir() if f.is_file()]
        out["structured_data"]["filings"] = filing_files
        out["inputs"]["filings_dir"] = str(filings_dir)

    # 7. Existing dossier check
    dossier_path = tdir / "STORY_DOSSIER.md"
    out["structured_data"]["dossier_exists"] = dossier_path.exists()
    if dossier_path.exists():
        out["structured_data"]["dossier_size"] = dossier_path.stat().st_size

    return out


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — Template
# ─────────────────────────────────────────────────────────────────────────────

def generate_template(synthesis_inputs: dict) -> str:
    """Produce a STORY_DOSSIER.md template with auto-populated tables + agent-fill prompts."""
    ticker = synthesis_inputs["ticker"]
    sd = synthesis_inputs["structured_data"]
    pos = sd.get("position", {})
    notes = sd.get("research_notes", [])
    cfg = sd.get("config", {})
    ref_inv = sd.get("reference_inventory", {})
    filings = sd.get("filings", [])

    lines = [f"# {ticker} — Story Dossier", ""]
    lines.append(f"**Built:** {synthesis_inputs.get('synthesized_at', 'TBD')[:10]}")
    lines.append("**Auto-aggregated by:** dossier_synthesizer.py — agent fills prose sections.")
    lines.append("")
    lines.append("---")
    lines.append("")

    # AUTO-POPULATED: Position (optional)
    lines.append("## Position (optional, from position.json)")
    lines.append("")
    if pos:
        lines.append(f"- **Direction:** {pos.get('direction')}")
        if pos.get("quantity") is not None:
            lines.append(f"- **Quantity:** {pos.get('quantity')}")
        if pos.get("invested_amount") is not None:
            lines.append(f"- **Invested:** {pos.get('invested_amount')}")
        if pos.get("pct_portfolio") is not None:
            lines.append(f"- **% portfolio:** {pos.get('pct_portfolio')}")
        lines.append(f"- **As of:** {pos.get('as_of_date')}")
    else:
        lines.append("- No position tracked (drop a position.json if you want this populated).")
    lines.append("")

    # AGENT-FILL: Section 1 — The story
    lines.append("## 1. The Story in One Paragraph")
    lines.append("")
    lines.append("[AGENT-FILL: synthesize from research notes + Reference Files notes + sell-side notes + 10-K business description. Cover: what the company does, current narrative, recent rally/sell-off context, structural debate. ~100-150 words.]")
    lines.append("")

    # AGENT-FILL: Section 2 — Bear thesis components
    lines.append("## 2. Bear Thesis Components")
    lines.append("")
    lines.append("[AGENT-FILL: numbered list of distinct bear mechanisms. Synthesize from:")
    lines.append("  - Sell-side bear thesis components (consensus by frequency)")
    lines.append("  - Your own research notes")
    lines.append("Each item should be a distinct mechanism, not a restated symptom. Aim for 5-8 components.]")
    lines.append("")

    # AGENT-FILL: Section 3 — Bull thesis components
    lines.append("## 3. Bull Thesis Components")
    lines.append("")
    lines.append("[AGENT-FILL: numbered list of distinct bull drivers. Synthesize from:")
    lines.append("  - Sell-side bull thesis components")
    lines.append("  - Mgmt commentary (transcripts, IR decks)")
    lines.append("  - Recent positive news / catalysts")
    lines.append("Aim for 5-8 components, parallel structure to bear.]")
    lines.append("")

    # AGENT-FILL: Section 4 — Rally / sell-off drivers
    lines.append("## 4. Recent Rally / Sell-Off Drivers")
    lines.append("")
    lines.append("[AGENT-FILL: dated event table (Date | Event | Stock impact). Pull from press releases, 8-Ks, sell-side note dates, regulatory events. Include the recent move since last earnings print.]")
    lines.append("")

    # AGENT-FILL: Section 5 — Accounting / partnership nuances
    lines.append("## 5. Specific Accounting / Partnership Nuances")
    lines.append("")
    lines.append("[AGENT-FILL: rev recognition treatment per partnership; gross vs net; pass-through dynamics; TIMING of when each kicks in. Pull from the 10-Q rev recognition footnote (filings/) + sell-side analyst commentary. This is the LOAD-BEARING section — get the mechanics right.]")
    lines.append("")

    # AGENT-FILL: Section 6 — Open questions
    lines.append("## 6. Open Questions / Things to Verify")
    lines.append("")
    lines.append("[AGENT-FILL: numbered list of questions that primary sources can't yet answer. Pull from sell-side outlier views + your own gaps in understanding. These become the listening list for the call.]")
    lines.append("")

    # AUTO-POPULATED: Acquisitions in play
    if cfg.get("acquisitions_in_play"):
        lines.append("## 7. Acquisitions in Play (from config)")
        lines.append("")
        lines.append("| Name | Announce | Close | Value | Status |")
        lines.append("|---|---|---|---|---|")
        for acq in cfg.get("acquisitions_in_play", []):
            value_str = f"\\${acq.get('value_usd_mm', 'undisclosed')}mm" if acq.get('value_usd_mm') != 'undisclosed' else 'undisclosed'
            lines.append(f"| {acq.get('name')} | {acq.get('announce')} | {acq.get('close')} | {value_str} | {acq.get('integration_status')} |")
        lines.append("")

    # AUTO-POPULATED: Salient KPIs
    if cfg.get("salient_kpis"):
        lines.append("## 8. Salient KPIs (from config)")
        lines.append("")
        for k in cfg.get("salient_kpis", []):
            lines.append(f"- **{k.get('label')}** — {k.get('why', '')[:140]}")
        lines.append("")

    # AUTO-POPULATED: Day-of binary
    if cfg.get("day_of_binary"):
        dob = cfg["day_of_binary"]
        lines.append("## 9. Day-of Binary (from config)")
        lines.append("")
        lines.append(f"- **Primary:** {dob.get('primary')}")
        lines.append(f"- **Composition test:** {dob.get('composition_test')}")
        lines.append("")

    # AUTO-POPULATED: Research notes inventory
    lines.append(f"## 10. Research Notes Read ({len(notes)})")
    lines.append("")
    if notes:
        lines.append("| Date | Title | Author | Key Takeaway (truncated) |")
        lines.append("|---|---|---|---|")
        for n in notes:
            takeaway = n.get('key_takeaways', '')[:180].replace('|', '/').replace('\n', ' ')
            lines.append(f"| {n.get('date')} | {n.get('title', '')[:60]} | {n.get('author', '')} | {takeaway} |")
    else:
        lines.append("- No research notes found.")
    lines.append("")

    # AUTO-POPULATED: Reference inventory
    lines.append("## 11. Reference Files Inventory")
    lines.append("")
    for sub, count in ref_inv.items():
        if isinstance(count, int):
            lines.append(f"- **{sub}/** — {count} files")
        else:
            lines.append(f"- **{sub}** — {count}")
    lines.append("")

    if filings:
        lines.append("## 12. SEC Filings (EDGAR extracts)")
        lines.append("")
        for ps in filings:
            lines.append(f"- {ps}")
        lines.append("")

    # AGENT-FILL: Surprises / corrections
    lines.append("## 13. Surprises / Things to Self-Correct")
    lines.append("")
    lines.append("[AGENT-FILL: capture any framings the data forces you to revise. Use the format: | Initial framing | Correct framing | Source that corrects it |. Useful for downstream lessons + spec updates.]")
    lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _cli() -> int:
    ap = argparse.ArgumentParser(description="Story Dossier auto-aggregator")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--phase", choices=["aggregate", "template", "both"], default="both")
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--out-template", default=None)
    args = ap.parse_args()

    tdir = ticker_dir(args.ticker)
    tdir.mkdir(parents=True, exist_ok=True)

    inputs_path = Path(args.out_json) if args.out_json else tdir / "_dossier_inputs.json"
    template_path = Path(args.out_template) if args.out_template else tdir / "STORY_DOSSIER_TEMPLATE.md"

    synth = None
    if args.phase in ("aggregate", "both"):
        synth = aggregate(args.ticker)
        inputs_path.write_text(json.dumps(synth, indent=2, default=str), encoding="utf-8")
        print(f"Wrote synthesis inputs: {inputs_path}")
        print(f"  Research notes: {synth['structured_data'].get('research_notes_count', 0)}")
        print(f"  Position: {synth['structured_data'].get('position', {}).get('direction', 'n/a')}")
        print(f"  Reference inv: {sum(v for v in synth['structured_data'].get('reference_inventory', {}).values() if isinstance(v, int))} files")
        print(f"  Existing dossier: {synth['structured_data'].get('dossier_exists')}")
        if synth.get("warnings"):
            print(f"  Warnings: {synth['warnings']}")

    if args.phase in ("template", "both"):
        if synth is None:
            with open(inputs_path) as f:
                synth = json.load(f)
        template = generate_template(synth)
        template_path.write_text(template, encoding="utf-8")
        print(f"Wrote dossier template: {template_path}")
        print(f"  Lines: {len(template.splitlines())}")

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
