"""
standalone_config_gen.py — generate a draft config.yaml from sell-side notes
and SEC filings extracts, for tickers with no hand-authored config.

Scope: implements the derivation rules and the business-model classifier.
It reads on-disk inputs (free SEC EDGAR extracts + your own sell-side
synthesis) and synthesizes a draft config.

Expected input files (all optional, best-effort):

    workspace/{TICKER}/filings/
        latest_10K_business.txt         — 10-K Item 1 business description
                                          (pulled by edgar_fetch.py)

    workspace/{TICKER}/synthesis/
        sell_side_synthesis.md          — produced by sell_side_synthesizer

Missing inputs degrade specific derivations to defaults; the generator
records every degradation in the result so you can see coverage gaps.

Public API:
    classify_business_model(sector_code, business_text) -> dict
    derive_sector_etf(sector_code) -> str
    derive_comp_set(sector_peers, business_text, sell_side_synth_path) -> list[dict]
    derive_key_metrics(business_class, segments, sell_side_synth_path) -> list[str]
    derive_day_of_binary(key_metrics, sell_side_synth_path) -> str
    generate_config(ticker, analyst, **inputs) -> dict

CLI:
    python3 standalone_config_gen.py --ticker XYZ [--dry-run]
        Writes draft config.yaml to workspace/{TICKER}/config.yaml
        unless --dry-run is set.

The generated config has every auto-derived field commented inline with
the source that drove the value. Review and edit before using the
preview pipeline.

Note: the sector-ETF and business-model maps key off an optional industry
classification code. Without one (the common free-data case) the classifier
falls back to keyword matching on the 10-K business description.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from _paths import ticker_dir as _ws_ticker_dir


# ─────────────────────────────────────────────────────────────────────────────
# Business-model classifier
# ─────────────────────────────────────────────────────────────────────────────

# Map of (sector-classification sector code prefix, business-model class). sector-classification taxonomy
# uses 8-digit codes; first 4 digits ≈ sector. This is a coarse map —
# refined by the keyword classifier below.
_SECTOR_TO_CLASS: dict[str, str] = {
    "5010": "health_insurer_mco",     # Healthcare Equipment & Services / Insurers
    "5015": "health_insurer_mco",
    "5020": "lifesci_tools",          # Pharma / Biotech / Lifesci
    "5025": "lifesci_tools",
    "4010": "financial_services",     # Financials
    "4510": "software_saas",          # Software
    "4520": "manufactured_goods",     # Tech hardware
    "2510": "consumer_brands",        # Consumer durables / apparel
    "2530": "consumer_brands",        # Consumer services
    "3020": "consumer_brands",        # Consumer staples
    "2010": "industrials_capex_heavy", # Capital goods
    "1010": "energy_commodities",     # Energy
    "1510": "manufactured_goods",     # Materials
    "5520": "industrials_capex_heavy", # Utilities
    "6010": "consumer_brands",        # Real Estate / REIT (proxy until added)
}

# Per-class keyword signatures. Each business is scored against every
# class and the highest-confidence wins. Confidence = sum of matched
# keyword weights normalized by total possible. Keywords are lowercased.
_CLASS_KEYWORDS: dict[str, dict[str, float]] = {
    "subscription_dtc": {
        "subscriber": 3.0, "subscription": 3.0, "monthly active": 2.0,
        "average revenue per user": 2.5, "arpu": 2.5, "churn": 1.5,
        "direct-to-consumer": 2.0, "dtc": 2.0, "telehealth": 2.0,
    },
    "health_insurer_mco": {
        "medical loss ratio": 3.0, "mlr": 3.0, "premiums": 2.0,
        "medicare advantage": 2.5, "medicaid": 2.0, "marketplace": 1.5,
        "members": 1.5, "covered lives": 2.0, "managed care": 2.5,
        "risk adjustment": 2.0,
    },
    "lifesci_tools": {
        "sequencing": 2.5, "instrument": 2.0, "consumables": 2.0,
        "lab equipment": 2.0, "molecular diagnostics": 2.0,
        "research products": 1.5, "throughput": 1.0,
    },
    "software_saas": {
        "annual recurring revenue": 3.0, "arr": 2.5,
        "net retention": 2.5, "billings": 2.0, "saas": 2.5,
        "software platform": 2.0, "rpo": 1.5, "remaining performance": 2.0,
    },
    "manufactured_goods": {
        "units shipped": 2.0, "channel inventory": 2.0,
        "asp": 1.5, "average selling price": 2.0, "wholesale": 1.0,
        "manufacturing capacity": 2.0, "shipments": 1.5,
    },
    "industrials_capex_heavy": {
        "backlog": 2.5, "book-to-bill": 2.5, "capacity utilization": 2.0,
        "capital projects": 1.5, "engineering": 1.0, "infrastructure": 1.5,
        "capex": 1.5, "fixed assets": 1.5,
    },
    "consumer_brands": {
        "comparable sales": 2.5, "same-store sales": 2.5,
        "store count": 2.0, "brand": 1.0, "merchandise": 1.5,
        "private label": 1.5, "wholesale": 1.0,
    },
    "energy_commodities": {
        "barrel": 2.5, "btu": 2.0, "crude oil": 2.5, "natural gas": 2.0,
        "production volumes": 2.0, "reserves": 2.0, "wells": 1.5,
    },
    "financial_services": {
        "net interest margin": 2.5, "loan loss": 2.0, "deposits": 1.5,
        "assets under management": 2.5, "aum": 2.0,
        "regulatory capital": 2.0, "tier 1": 1.5,
    },
}


def classify_business_model(
    sector_code: str | None,
    business_text: str | None,
) -> dict:
    """Classify a company into one of the eight business-model categories.

    Returns:
        {
          "class": "subscription_dtc",  # picked
          "confidence": 0.62,           # 0..1, normalized
          "alternative": "consumer_brands",
          "alt_confidence": 0.18,
          "sector_seed_class": "manufactured_goods",  # what sector-classification alone said
          "sources": ["sector_code", "keywords"],
        }

    Resolution:
      1. If both sector-classification and keyword classifier agree → high confidence.
      2. If they disagree → keyword classifier wins (better at sub-segment
         distinctions like subscription_dtc within consumer/healthcare).
      3. If only sector-classification available → use sector-classification (lower confidence).
      4. If only keywords available → use keyword winner.
      5. If neither available → "other" with confidence 0.
    """
    sector_class: str | None = None
    if sector_code and isinstance(sector_code, str):
        prefix = sector_code[:4]
        sector_class = _SECTOR_TO_CLASS.get(prefix)

    # Keyword scoring
    keyword_scores: dict[str, float] = {}
    if business_text and isinstance(business_text, str):
        text_lower = business_text.lower()
        for cls, kws in _CLASS_KEYWORDS.items():
            score = 0.0
            max_possible = sum(kws.values())
            for kw, weight in kws.items():
                if kw in text_lower:
                    score += weight
            if max_possible > 0:
                keyword_scores[cls] = round(score / max_possible, 4)

    # Pick winner
    sources: list[str] = []
    chosen: str | None = None
    confidence = 0.0
    alternative: str | None = None
    alt_confidence = 0.0

    if keyword_scores:
        sources.append("keywords")
        # Sort descending by score
        ranked = sorted(keyword_scores.items(), key=lambda kv: kv[1], reverse=True)
        if ranked[0][1] > 0:
            chosen = ranked[0][0]
            confidence = ranked[0][1]
        if len(ranked) > 1 and ranked[1][1] > 0:
            alternative = ranked[1][0]
            alt_confidence = ranked[1][1]

    if sector_class:
        sources.append("sector_code")
        if chosen is None:
            chosen = sector_class
            confidence = 0.3  # sector-classification-only confidence is bounded
        elif chosen != sector_class:
            # Keyword winner disagrees with sector-classification — keep the keyword pick
            # but record sector-classification as the alternative if not already set.
            if alternative is None:
                alternative = sector_class
                alt_confidence = 0.3

    if chosen is None:
        chosen = "other"
        confidence = 0.0

    return {
        "class": chosen,
        "confidence": confidence,
        "alternative": alternative,
        "alt_confidence": alt_confidence,
        "sector_seed_class": sector_class,
        "sources": sources,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Sector ETF derivation
# ─────────────────────────────────────────────────────────────────────────────

# sector-classification sector → primary sector ETF mapping. Per the design memo §3.
# Sub-sector overrides (e.g., IBB for biotech) are out of scope for v1 —
# the analyst can edit the generated config to override.
_sector-classification_TO_ETF: dict[str, str] = {
    "5010": "XLV",   # Healthcare equipment & services
    "5015": "XLV",   # Healthcare insurers
    "5020": "XLV",   # Pharma / biotech (could be IBB; analyst overrides)
    "5025": "XLV",   # Lifesci tools
    "4010": "XLF",   # Banks / diversified financials
    "4510": "XLK",   # Software
    "4520": "XLK",   # Tech hardware
    "2010": "XLI",   # Capital goods
    "2510": "XLY",   # Consumer durables / apparel
    "2530": "XLY",   # Consumer services
    "3010": "XLP",   # Food retail
    "3020": "XLP",   # Consumer staples
    "1010": "XLE",   # Energy
    "1510": "XLB",   # Materials
    "5520": "XLU",   # Utilities
    "6010": "XLRE",  # Real estate
    "5040": "XLC",   # Communications
}


def derive_sector_etf(sector_code: str | None) -> tuple[str, str]:
    """Return (etf_ticker, source_note). Defaults to "XLV" with a clear
    source note when sector-classification is missing — analyst is expected to review."""
    if not sector_code or not isinstance(sector_code, str):
        return "XLV", "default (no sector-classification code provided; analyst should override)"
    prefix = sector_code[:4]
    etf = _sector-classification_TO_ETF.get(prefix)
    if etf:
        return etf, f"sector-classification prefix {prefix} → {etf}"
    return "XLV", f"sector-classification prefix {prefix} not in mapping; defaulted to XLV (analyst should override)"


# ─────────────────────────────────────────────────────────────────────────────
# Comp set derivation
# ─────────────────────────────────────────────────────────────────────────────

# Match standalone-mode peer ticker mentions in 10-K Item 1 "Competition"
# disclosures. Tickers are typically 1-5 uppercase letters in parens or
# after "such as" / "including" patterns.
_TICKER_IN_COMPETITION_RE = re.compile(
    r"\b(?:competitors?|competition|including|such as)[^.]*?\(([A-Z]{1,5})\)",
    re.IGNORECASE,
)
_PARENTHETICAL_TICKER_RE = re.compile(r"\(([A-Z]{2,5})\)")


def _extract_tickers_from_business_text(text: str | None, limit: int = 15) -> list[str]:
    """Extract candidate competitor tickers from 10-K Item 1 competition text.

    Heuristic: parenthetical tickers within sentences containing 'competitor',
    'competition', 'including', or 'such as'. Falls back to all
    parenthetical 2-5-char uppercase tokens (capped at `limit`).
    """
    if not text or not isinstance(text, str):
        return []
    found: list[str] = []
    # First pass: explicitly competitive context
    for m in _TICKER_IN_COMPETITION_RE.finditer(text):
        t = m.group(1).upper()
        if t not in found:
            found.append(t)
    # Second pass: any parenthetical 2-5-char uppercase token, capped
    if len(found) < limit:
        for m in _PARENTHETICAL_TICKER_RE.finditer(text):
            t = m.group(1).upper()
            if t in found:
                continue
            # Skip common non-ticker abbreviations that show up in 10-Ks
            if t in {"GAAP", "FDA", "FCC", "SEC", "CEO", "CFO", "COO", "USA", "USD",
                     "EU", "UK", "EBITDA", "USA", "GDP", "FY", "QA", "RD"}:
                continue
            found.append(t)
            if len(found) >= limit:
                break
    return found


def _extract_tickers_from_sell_side_synth(synth_path: Path | None, limit: int = 10) -> list[str]:
    """Pull tickers mentioned in the sell-side synthesis markdown — typically
    in Outlier Arguments and Key Data Points."""
    if not synth_path or not synth_path.exists():
        return []
    try:
        text = synth_path.read_text(encoding="utf-8")
    except OSError:
        return []
    found: list[str] = []
    for m in _PARENTHETICAL_TICKER_RE.finditer(text):
        t = m.group(1).upper()
        if t in found:
            continue
        if t in {"GAAP", "FDA", "EBITDA", "PT", "BBG", "USD", "EU", "UK"}:
            continue
        found.append(t)
        if len(found) >= limit:
            break
    return found


def derive_comp_set(
    sector_peers: list[str] | None,
    business_text: str | None,
    sell_side_synth_path: Path | None,
    *,
    target_count: int = 5,
    self_ticker: str | None = None,
) -> list[dict]:
    """Blend three sources: sector-classification sub-industry peers (seed), 10-K competition
    extraction, sell-side synthesis ticker mentions. Top `target_count` by
    overlap frequency. Each peer tagged role=auto_derived_peer.

    The list is intentionally small (5 by default — the canonical preview
    template doesn't accommodate >7 comps comfortably).
    """
    seen: Counter = Counter()
    if sector_peers and isinstance(sector_peers, list):
        for t in sector_peers:
            if isinstance(t, str) and t.strip():
                seen[t.upper().strip()] += 3  # sector-classification gets weight 3 (most reliable)
    for t in _extract_tickers_from_business_text(business_text):
        seen[t.upper()] += 2  # 10-K weight 2
    for t in _extract_tickers_from_sell_side_synth(sell_side_synth_path):
        seen[t.upper()] += 1  # sell-side weight 1
    # Drop self-ticker if present
    if self_ticker:
        seen.pop(self_ticker.upper(), None)
    # Top N by score, then alphabetic for stability
    ranked = sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))
    out: list[dict] = []
    for ticker, score in ranked[:target_count]:
        out.append({
            "ticker": ticker,
            "role": "auto_derived_peer",
            "_score": score,
            "_source": "auto",
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Key metrics derivation (per business-model class)
# ─────────────────────────────────────────────────────────────────────────────

# Default seed list per class. Always-included regardless of source signal.
# Per the design memo §5.
_KEY_METRICS_SEEDS: dict[str, list[str]] = {
    "subscription_dtc": [
        "subscribers_total", "arpu", "revenue_total",
        "gross_margin_pct", "operating_margin_pct", "eps_non_gaap",
        "marketing_pct_revenue", "free_cash_flow",
    ],
    "health_insurer_mco": [
        "premium_revenue", "members", "medical_loss_ratio",
        "sga_pct_revenue", "total_revenue", "operating_margin_pct",
        "eps_non_gaap",
    ],
    "lifesci_tools": [
        "instrument_placements", "consumables_revenue",
        "services_revenue", "total_revenue",
        "gross_margin_pct", "operating_margin_pct", "eps_non_gaap",
    ],
    "software_saas": [
        "arr", "net_retention", "billings", "total_revenue",
        "gross_margin_pct", "operating_margin_pct", "fcf_margin",
    ],
    "manufactured_goods": [
        "units_shipped", "asp", "total_revenue",
        "gross_margin_pct", "operating_margin_pct", "eps_non_gaap",
        "capex_fy_only",
    ],
    "industrials_capex_heavy": [
        "volumes", "asp", "backlog", "book_to_bill",
        "total_revenue", "gross_margin_pct", "operating_margin_pct",
        "eps_non_gaap", "capex",
    ],
    "consumer_brands": [
        "comparable_sales_growth", "store_count", "total_revenue",
        "gross_margin_pct", "operating_margin_pct", "eps_non_gaap",
    ],
    "energy_commodities": [
        "production_volumes", "realized_price", "total_revenue",
        "operating_margin_pct", "eps_non_gaap", "capex",
    ],
    "financial_services": [
        "net_interest_margin", "deposits", "loan_growth",
        "efficiency_ratio", "eps_non_gaap",
    ],
    "other": [
        "total_revenue", "gross_margin_pct", "operating_margin_pct",
        "eps_non_gaap",
    ],
}


def derive_key_metrics(
    business_class: str,
    segments: list[dict] | None,
    sell_side_synth_path: Path | None,
) -> tuple[list[str], list[str]]:
    """Return (key_metrics_list, source_notes).

    Order of operations:
      1. Seed with the per-class default list.
      2. Add up to 3 segment-revenue metrics if `segments` is structured.
      3. (Sell-side mining for most-cited metrics is deferred to v2 — too
         noisy without a strong tokenizer.)
    """
    notes: list[str] = []
    seed = list(_KEY_METRICS_SEEDS.get(business_class, _KEY_METRICS_SEEDS["other"]))
    notes.append(f"seeded {len(seed)} metrics from business class '{business_class}'")
    out = list(seed)

    if segments and isinstance(segments, list):
        added = 0
        for seg in segments[:3]:
            if not isinstance(seg, dict):
                continue
            name = seg.get("name") or seg.get("segment") or seg.get("label")
            if not isinstance(name, str):
                continue
            slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            if not slug:
                continue
            metric = f"{slug}_revenue"
            if metric not in out:
                out.append(metric)
                added += 1
        if added:
            notes.append(f"added {added} segment-revenue metrics from sec_segments.json")

    return out, notes


# ─────────────────────────────────────────────────────────────────────────────
# Day-of binary default
# ─────────────────────────────────────────────────────────────────────────────

def derive_day_of_binary(
    key_metrics: list[str],
    sell_side_synth_path: Path | None = None,
) -> tuple[str, str]:
    """Return (metric_name, source_note).

    Default: revenue (or close synonym from key_metrics if 'revenue' isn't
    literally listed). Standalone mode never produces a confident 'binary'
    judgment — that's analyst territory. The chosen metric is labeled in
    the generated config as "agent-suggested" with a clear note.
    """
    if not key_metrics:
        return "revenue", "no key_metrics; defaulted to revenue (analyst should override)"
    rev_candidates = [m for m in key_metrics
                      if "revenue" in m.lower() or m.lower() in ("rev", "sales")]
    if rev_candidates:
        chosen = rev_candidates[0]
        return chosen, f"agent-suggested: first revenue-like metric in key_metrics ({chosen})"
    # No revenue-like metric — fall back to first key_metric
    return key_metrics[0], (
        f"agent-suggested: no revenue metric in key_metrics, picked first listed "
        f"({key_metrics[0]}); analyst should override"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Top-level config generator
# ─────────────────────────────────────────────────────────────────────────────

def generate_config(
    ticker: str,
    analyst: str,
    *,
    fiscal_period_in_focus: str | None = None,
    sector_code: str | None = None,
    sector_peers: list[str] | None = None,
    business_text: str | None = None,
    segments: list[dict] | None = None,
    sell_side_synth_path: Path | None = None,
    company_name: str | None = None,
) -> dict:
    """Synthesize a draft config.yaml dict from the structured inputs."""
    cls_result = classify_business_model(sector_code, business_text)
    etf, etf_note = derive_sector_etf(sector_code)
    comp_set = derive_comp_set(
        sector_peers, business_text, sell_side_synth_path,
        self_ticker=ticker,
    )
    key_metrics, km_notes = derive_key_metrics(
        cls_result["class"], segments, sell_side_synth_path,
    )
    day_of_binary, dob_note = derive_day_of_binary(key_metrics, sell_side_synth_path)

    config = {
        "ticker": ticker.upper(),
        "_auto_generated": True,
        "_auto_generated_notes": (
            "This config was synthesized by standalone_config_gen.py from the "
            "10-K business description (free SEC EDGAR) and sell-side synthesis. "
            "Every field is auto-derived. Review and edit before relying on the "
            "preview pipeline. Set _analyst_reviewed: true once you've confirmed "
            "the values match your expectations."
        ),
        "_analyst_reviewed": False,
        "fiscal_period_in_focus": fiscal_period_in_focus,
        "business_model_class": cls_result["class"],
        "_business_model_classification": cls_result,
        "sector_etf": etf,
        "_sector_etf_note": etf_note,
        "comp_set": comp_set,
        "key_metrics": key_metrics,
        "_key_metrics_notes": km_notes,
        "day_of_binary_agent_suggested": day_of_binary,
        "_day_of_binary_note": dob_note,
        "company_name_aliases": [company_name] if company_name else [],
        "positioning_inputs": {
            "whisper_culture": False,
            "desk_emails_typical": False,
        },
        "analyst_signature_style": "auto",
    }
    return config


def _serialize_to_yaml(config: dict) -> str:
    """Serialize the config to YAML, preserving the key order in `config`."""
    try:
        import yaml
    except ImportError:
        return json.dumps(config, indent=2)

    class _OrderedDumper(yaml.SafeDumper):
        pass

    def _dict_representer(dumper, data):
        return dumper.represent_mapping(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, data.items()
        )

    _OrderedDumper.add_representer(dict, _dict_representer)
    return yaml.dump(config, Dumper=_OrderedDumper, default_flow_style=False, sort_keys=False)


def _read_optional_json(p: Path) -> Any:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_optional_text(p: Path) -> str | None:
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


def generate_config_from_disk(
    ticker: str,
    analyst: str = "user",
    *,
    ticker_dir_override: Path | None = None,
) -> tuple[dict, dict]:
    """Read the on-disk input files and call generate_config.

    Returns (config, source_summary).

    `ticker_dir_override` lets callers pass an explicit ticker-directory
    Path. When None (default), the directory is resolved via
    `ticker_dir(TICKER)` (workspace/{TICKER}). The override exists for the
    runner's stage method (which already has `self.ticker_dir` cached) and
    for tests with monkeypatched paths.
    """
    ticker = ticker.upper()
    if ticker_dir_override is not None:
        tdir = ticker_dir_override
    else:
        tdir = _ws_ticker_dir(ticker)
    filings_dir = tdir / "filings"
    data_dir = tdir / "data"
    synthesis_path = tdir / "synthesis" / "sell_side_synthesis.md"

    # No paid industry-classification feed in the free build. sector-classification code and
    # peer list are left unset; the classifier falls back to keyword matching
    # on the 10-K business text and competitor extraction.
    sector_code = None
    company_name = None
    sector_peers: list[str] = []

    # Fiscal period is left for you to fill into config.yaml (the print date
    # comes from the company IR site / latest 8-K, not a paid calendar feed).
    fiscal_period = None

    # 10-K Item 1 business description (pulled by edgar_fetch.py). Fall back to
    # the older data/ location if present.
    business_text = (
        _read_optional_text(filings_dir / "latest_10K_business.txt")
        or _read_optional_text(data_dir / "sec_business_section.txt")
    )

    segments: list[dict] = []

    config = generate_config(
        ticker=ticker, analyst=analyst,
        fiscal_period_in_focus=fiscal_period,
        sector_code=sector_code, sector_peers=sector_peers,
        business_text=business_text, segments=segments,
        sell_side_synth_path=synthesis_path if synthesis_path.exists() else None,
        company_name=company_name,
    )

    summary = {
        "ticker": ticker, "analyst": analyst,
        "inputs_present": {
            "sec_business_section": business_text is not None,
            "sell_side_synthesis": synthesis_path.exists(),
        },
        "fiscal_period_derived": fiscal_period,
        "business_class": config["business_model_class"],
        "comp_set_size": len(config["comp_set"]),
        "key_metrics_count": len(config["key_metrics"]),
    }
    return config, summary


def _cli() -> int:
    ap = argparse.ArgumentParser(description=(
        "Generate a draft config.yaml for a new ticker by synthesizing the "
        "10-K business description (free SEC EDGAR) and your sell-side synthesis."
    ))
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--analyst", default="user")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the generated config to stdout without writing.")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing config.yaml. Default is to refuse.")
    args = ap.parse_args()

    config, summary = generate_config_from_disk(args.ticker, args.analyst)
    yaml_text = _serialize_to_yaml(config)

    print("# Source summary:", file=sys.stderr)
    print(json.dumps(summary, indent=2), file=sys.stderr)

    if args.dry_run:
        print(yaml_text)
        return 0

    target = _ws_ticker_dir(args.ticker.upper()) / "config.yaml"
    if target.exists() and not args.force:
        print(f"[error] {target} already exists. Use --force to overwrite, "
              f"or --dry-run to preview.", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml_text, encoding="utf-8")
    print(f"[ok] wrote {target}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
