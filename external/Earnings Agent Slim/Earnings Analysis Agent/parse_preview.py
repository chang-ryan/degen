#!/usr/bin/env python3
"""
parse_preview.py — extract structured metadata from a preview PDF/markdown.

Purpose
-------
The earnings preview ships as `notification.pdf` (or markdown). The digest
agent needs the salient KPIs, day-of binary trigger, composition test, and
listening list as STRUCTURED data — not free-text. Without structured input,
the digest agent has to ask the user what the day-of binary is (which
biases via multiple-choice), or it guesses (which can lead to an
OM-as-day-of-binary error).

This script parses a preview into `preview_metadata.yaml`. The digest agent
reads that YAML and binds template placeholders without further user input.

Usage
-----
    python3 parse_preview.py --ticker XYZ --analyst user --period C1Q26

    # Reads:  workspace/{TICKER}/print_materials/notification.pdf
    # Writes: workspace/{TICKER}/preview_metadata.yaml

What it extracts
----------------
1. Position context: current size $M, shares, % port, current price
2. Pre-earnings decision: HOLD / ADD / TRIM / EXIT + recommended size
3. Earnings preview score (1-5)
4. Salient KPIs: from "What metric(s) / line item(s) are most important" section
5. Day-of binary primary: the FIRST salient KPI named in the metrics list
6. Composition test: from "what would be enough for the stock to go up/down" section
7. Listening list: from "What we will be listening for this quarter" section
8. Implied move: from "What options market is pricing in" section
9. Historical reactions: from the EE SURP table in the preview

The output schema documents the salient_kpis structure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_BASE = REPO_ROOT / "workspace"


def ticker_root(analyst: str, ticker: str) -> Path:
    return WORKSPACE_BASE / ticker


def find_preview(analyst: str, ticker: str) -> Path | None:
    """Find the preview file. Prefer notification.pdf; fall back to PREVIEW_V*.md."""
    root = ticker_root(analyst, ticker)
    candidates = [
        root / "print_materials" / "notification.pdf",
        root / "notification.pdf",
    ]
    for c in candidates:
        if c.exists():
            return c
    # Fall back to most recent PREVIEW markdown
    out = root / "outputs"
    if out.exists():
        previews = sorted(out.glob("*PREVIEW*V*.md"))
        if previews:
            return previews[-1]
    return None


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract all text from a PDF using pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        print("[error] pdfplumber not installed; pip install pdfplumber", file=sys.stderr)
        sys.exit(2)
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            text_parts.append(t)
    return "\n".join(text_parts)


def extract_section(full_text: str, section_header: str, next_header_pattern: str = None) -> str:
    """Extract a named section from preview text.

    Args:
        full_text: full preview text
        section_header: literal header text to match (case-insensitive)
        next_header_pattern: optional regex pattern that marks the end of the section
    """
    # Find the header
    header_re = re.compile(re.escape(section_header), re.IGNORECASE)
    m = header_re.search(full_text)
    if not m:
        return ""
    start = m.end()

    # Find the end (next header or 1500 chars)
    if next_header_pattern:
        end_re = re.compile(next_header_pattern, re.IGNORECASE)
        em = end_re.search(full_text, pos=start)
        end = em.start() if em else min(start + 2000, len(full_text))
    else:
        end = min(start + 2000, len(full_text))

    return full_text[start:end].strip()


def parse_position_context(text: str) -> dict:
    """Extract position size, shares, % port, current price."""
    out = {}
    # "Current Share Price of stock $122.80"
    m = re.search(r"Current Share Price.*?\$([0-9,.]+)", text)
    if m:
        out["current_price"] = float(m.group(1).replace(",", ""))
    # "Current Position Size $, million 175.8M"
    m = re.search(r"Current Position Size.*?million\s+([0-9,.]+)", text)
    if m:
        out["position_size_usd_mm"] = float(m.group(1).replace(",", ""))
    # "Current Position Size # of Shares 1,431,214"
    m = re.search(r"Current Position Size # of Shares\s+([0-9,]+)", text)
    if m:
        out["position_shares"] = int(m.group(1).replace(",", ""))
    # "Current Position Size % of Port. 6.45%"
    m = re.search(r"Current Position Size % of Port\.\s+([0-9.]+)%?", text)
    if m:
        out["pct_port"] = float(m.group(1))
    return out


def parse_pre_earnings_decision(text: str) -> dict:
    """Extract pre-earnings decision + recommended size + preview score."""
    out = {}
    # Look for HOLD / ADD / TRIM / EXIT after "Pre Earnings decision"
    m = re.search(r"Pre Earnings decision[^\n]*\n+\s*(HOLD|ADD|TRIM|EXIT)", text, re.IGNORECASE)
    if m:
        out["decision"] = m.group(1).upper()
    # Recommended position size — number followed by M
    m = re.search(r"Recommended Position Size[^\n]*\n+\s*([0-9.]+)\s*M", text, re.IGNORECASE)
    if m:
        out["recommended_size_usd_mm"] = float(m.group(1))
    # Earnings Preview Score — single digit
    m = re.search(r"Earnings Preview Score[^\n]*\n+\s*(\d)", text)
    if m:
        out["preview_score"] = int(m.group(1))
    return out


def parse_salient_kpis(text: str) -> list[dict]:
    """Extract KPIs from 'What metric(s) / line item(s) are most important' section.

    The PDF text doesn't preserve bullet characters — bullets appear as plain
    lines. Strategy: extract the section, split on newlines, keep lines that
    look like KPI labels (3-100 chars, don't end with ? or :).
    """
    section = extract_section(
        text,
        "What metric(s) / line item(s) are most important",
        r"How does .{0,40}compare|Buy-side expectations|Data Monitoring|What we will be listening"
    )
    if not section:
        return []

    kpis = []
    # First strip the prompt suffix (everything before the first newline after the header is question text)
    # Then split into lines
    lines = section.split("\n")
    for line in lines:
        line = line.strip()
        # Strip leading bullet/dash characters if present
        line = re.sub(r"^[•\-\*]\s*", "", line).strip()
        if not line:
            continue
        # Skip the prompt-like lines
        if line.endswith("?") or line.endswith(":"):
            continue
        # Skip very long lines (paragraph text, not bullets)
        if len(line) > 120:
            continue
        # Skip very short lines (artifacts)
        if len(line) < 4:
            continue
        # Skip lines that include common preview prompt fragments
        if any(stop in line.lower() for stop in [
            "has this changed", "how does ", "metric(s)",
            "stock to go up", "buyside is expecting"
        ]):
            continue
        kpis.append({
            "label": line,
            "raw_text": line,
        })
    return kpis


def parse_listening_list(text: str) -> list[str]:
    """Extract items from 'What we will be listening for this quarter' section."""
    section = extract_section(
        text,
        "What we will be listening for",
        r"Milestones|Historical earnings|What options market"
    )
    if not section:
        return []
    items = []
    lines = section.split("\n")
    for line in lines:
        line = line.strip()
        line = re.sub(r"^[•\-\*]\s*", "", line).strip()
        if not line:
            continue
        if line.endswith(":") or line.endswith("?"):
            continue
        if "this quarter" in line.lower() and len(line) < 30:
            continue
        # Listening items can be longer (full sentences)
        if len(line) < 6 or len(line) > 250:
            continue
        items.append(line)
    return items


def parse_implied_move(text: str) -> dict:
    """Extract implied move % from 'What options market is pricing in' section."""
    out = {}
    section = extract_section(
        text,
        "What options market is pricing in",
        r"Historical earnings|About the company|^\s*$"
    )
    if section:
        m = re.search(r"\+/?\-\s*([0-9.]+)%", section)
        if m:
            out["implied_move_pct"] = float(m.group(1))
    return out


def parse_takeaways(text: str) -> str:
    """Extract Takeaways section — high-level commentary."""
    section = extract_section(
        text,
        "Takeaways",
        r"Overview|Why we are bullish|Pre Earnings Decision Comment|What metric"
    )
    return section.strip() if section else ""


def derive_day_of_binary(salient_kpis: list[dict], takeaways_text: str = "") -> dict:
    """The day-of binary is the FIRST SPECIFIC METRIC in the preview's metrics list.

    Heuristic: skip meta-instructions like "Any updates to guidance" and pick the
    first line that names a specific line item (revenue, margin, units, EPS, etc.).
    Do NOT default to rev/EPS unless the preview explicitly says so.
    """
    if not salient_kpis:
        return {
            "primary": "UNKNOWN — preview parsing failed",
            "primary_alternates": [],
            "composition_test": "",
            "_extraction_confidence": "none",
        }

    META_PREFIXES = ["any updates", "updates to", "general "]
    primary = None
    alternates = []
    for kpi in salient_kpis:
        lbl_lower = kpi["label"].lower().strip()
        if any(lbl_lower.startswith(p) for p in META_PREFIXES):
            alternates.append(kpi["label"])
            continue
        if primary is None:
            primary = kpi["label"]
        else:
            alternates.append(kpi["label"])

    # Extract composition test from takeaways
    composition_test = ""
    if takeaways_text:
        # Look for sentences with "needs to be" / "must be" / "driven by"
        for sentence in re.split(r"[.!?]\s+", takeaways_text):
            s = sentence.strip()
            if any(phrase in s.lower() for phrase in ["needs to be", "must be", "driven by", "needs to come from", "would lift", "would pressure"]):
                composition_test = s
                break

    return {
        "primary": primary or salient_kpis[0]["label"],
        "primary_alternates": alternates,
        "composition_test": composition_test,
        "_extraction_confidence": "medium" if primary else "low — first item was meta-instruction",
        "_analyst_review_required": True,
    }


def clean_pdf_text(text: str) -> str:
    """Strip PDF extraction artifacts: null bytes, control characters."""
    text = text.replace("\x00", "")
    text = "".join(ch for ch in text if ch in "\n\t\r" or ord(ch) >= 0x20)
    return text


def merge_continuation_lines(items: list[str]) -> list[str]:
    """Merge listening-list continuation lines.

    Heuristic: if an item ends without sentence-ending punctuation AND the next
    item starts with lowercase, they're a continuation pair.
    """
    merged = []
    skip_next = False
    for i, item in enumerate(items):
        if skip_next:
            skip_next = False
            continue
        # Look ahead
        if i + 1 < len(items):
            next_item = items[i + 1]
            # Continuation if current doesn't end with .!?: AND next starts with lowercase
            if (not item.rstrip().endswith((".", "!", "?", ":", ")"))
                and next_item and next_item[0].islower()):
                merged.append(f"{item} {next_item}")
                skip_next = True
                continue
        merged.append(item)
    return merged


def parse_preview(preview_path: Path) -> dict:
    """Parse a preview file into structured metadata."""
    if preview_path.suffix.lower() == ".pdf":
        full_text = extract_text_from_pdf(preview_path)
    else:
        full_text = preview_path.read_text()

    full_text = clean_pdf_text(full_text)

    metadata = {
        "schema_version": "preview_metadata_v0.2",
        "source_file": str(preview_path),
        "position_context": parse_position_context(full_text),
        "pre_earnings_decision": parse_pre_earnings_decision(full_text),
        "salient_kpis_extracted_raw": parse_salient_kpis(full_text),
        "listening_list": merge_continuation_lines(parse_listening_list(full_text)),
        "implied_move": parse_implied_move(full_text),
        "takeaways_text": parse_takeaways(full_text)[:2000],
        "day_of_binary": {},
    }
    metadata["day_of_binary"] = derive_day_of_binary(
        metadata["salient_kpis_extracted_raw"],
        metadata["takeaways_text"]
    )

    return metadata


def write_yaml(metadata: dict, out_path: Path) -> None:
    """Write metadata as YAML. Use simple json-style YAML (no external dep)."""
    try:
        import yaml
        out_path.write_text(yaml.safe_dump(metadata, sort_keys=False, default_flow_style=False, width=120))
    except ImportError:
        # Fallback: write JSON with .yaml extension
        out_path.write_text(json.dumps(metadata, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Parse preview into structured metadata YAML")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--analyst", required=True)
    parser.add_argument("--period", required=False, default="current",
                        help="Period label (informational; output filename uses ticker only)")
    parser.add_argument("--preview-path", required=False, default=None,
                        help="Override preview path discovery")
    parser.add_argument("--output-path", required=False, default=None,
                        help="Override output path")
    args = parser.parse_args()

    if args.preview_path:
        preview_path = Path(args.preview_path)
    else:
        preview_path = find_preview(args.analyst, args.ticker)

    if not preview_path or not preview_path.exists():
        print(f"[error] preview not found for {args.ticker} ({args.analyst})", file=sys.stderr)
        sys.exit(2)

    metadata = parse_preview(preview_path)
    metadata["ticker"] = args.ticker
    metadata["analyst"] = args.analyst
    metadata["period"] = args.period

    if args.output_path:
        out_path = Path(args.output_path)
    else:
        out_path = ticker_root(args.analyst, args.ticker) / "preview_metadata.yaml"

    write_yaml(metadata, out_path)
    print(f"[ok] preview parsed → {out_path}")
    print(f"  position: ${metadata['position_context'].get('position_size_usd_mm', 'n/a')}M / {metadata['position_context'].get('pct_port', 'n/a')}% port")
    print(f"  decision: {metadata['pre_earnings_decision'].get('decision', 'n/a')} (score {metadata['pre_earnings_decision'].get('preview_score', 'n/a')})")
    print(f"  salient KPIs extracted: {len(metadata['salient_kpis_extracted_raw'])}")
    print(f"  day-of binary: {metadata['day_of_binary']['primary'][:80]}")
    print(f"  listening list items: {len(metadata['listening_list'])}")
    print(f"  implied move: ±{metadata['implied_move'].get('implied_move_pct', 'n/a')}%")
    print(f"")
    print(f"[next] Review preview_metadata.yaml — verify salient_kpis_extracted_raw matches the preview's intent.")
    print(f"       Then merge with config.yaml's salient_kpis (preview wins on conflict).")


if __name__ == "__main__":
    main()
