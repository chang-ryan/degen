#!/usr/bin/env python3
"""
baseline_audit.py — deterministic pre-render audit gate.

Purpose
-------
Catches structural and source-tier errors BEFORE the digest is rendered.

Specifically catches common failure modes:
1. Source-tier confusion (numbers labeled with a paid data feed without a manifest entry)
2. Derived non-GAAP OM (do not derive non-GAAP operating margin)
3. Missing salient_kpi coverage (KPI in config but not in scorecard/synthesis/watch-list)
4. Day-of binary not anchored in synthesis para 1
5. Conditional sections present when their flag is false (or vice versa)
6. Performative jargon ("risk symmetry / asymmetric right vs left")

Usage
-----
    # Audit a digest before rendering
    python3 baseline_audit.py --digest-md path/to/digest.md --ticker XYZ --analyst user

    # Returns exit code 0 if all gates pass, 1 if WARNINGs only, 2 if any FAIL.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_BASE = REPO_ROOT / "workspace"


def ticker_root(analyst: str, ticker: str) -> Path:
    return WORKSPACE_BASE / ticker


# ──────────────────────────────────────────────────────────────────
# Audit gates
# ──────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────
# Arithmetic / derivation consistency gates
#
# In response to a class of derivation errors observed in narrative prose:
#   - A digest claimed "$52.2M, -1.4% YoY vs $47.8M" (actual +9.1%)
#   - A digest claimed "TTM Adj EBITDA $56M = 3.5x leverage" (TTM was
#     $45M, $56M was FY — label was wrong, even though arithmetic checked
#     against the wrong denominator)
# These belong to a class of errors the existing audit machinery does not
# catch: derivation errors in narrative prose. The fix is two-fold —
# (a) flag derived percentage / margin / ratio statements that fail to
# reconcile against inputs cited in the same sentence; (b) flag temporal
# denominators (TTM, NTM, FY, LTM) whose cited value doesn't match the
# manifest's record for that temporal scope.
# ──────────────────────────────────────────────────────────────────

# Pattern: "$X ... Y% YoY ... $Z" within one sentence — derive (X/Z - 1) and
# compare to Y. Anchored on the YoY token; '[^.]*?' keeps the match inside a
# single sentence and stays lazy so the smallest valid window wins.
_YOY_DERIVED_RE = re.compile(
    r"\$(?P<num>[0-9]+(?:\.[0-9]+)?)M[^.]*?"
    r"(?P<pct>[+\-]?[0-9]+(?:\.[0-9]+)?)%\s*YoY[^.]*?"
    r"\$(?P<den>[0-9]+(?:\.[0-9]+)?)M",
    re.IGNORECASE,
)

# Pattern: "gross margin of Y%" with GP and revenue stated nearby
_GM_DERIVED_RE = re.compile(
    r"gross\s+profit\s+(?:was\s+|of\s+)?\$?(?P<gp>[0-9]+(?:\.[0-9]+)?)\s*M?[^.]*?"
    r"revenue\s+of\s+\$?(?P<rev>[0-9]+(?:\.[0-9]+)?)\s*M?[^.]*?"
    r"(?:gross\s+margin\s+of\s+)?(?P<gm>[0-9]+(?:\.[0-9]+)?)%",
    re.IGNORECASE,
)

# Pattern: "$X / TTM Y $Z = Wx" — temporal denominator
_LEVERAGE_RE = re.compile(
    r"(?P<numerator>\$?[0-9]+(?:\.[0-9]+)?\s*M?)\s*/\s*"
    r"(?P<temporal>TTM|LTM|NTM|FY\d{2}|FY)\s+"
    r"(?P<metric>[A-Za-z][A-Za-z\s]*?)\s*~?\s*\$?(?P<denominator>[0-9]+(?:\.[0-9]+)?)\s*M?",
    re.IGNORECASE,
)


def gate_arithmetic_consistency(md_text: str, tolerance: float = 0.01) -> dict:
    """Flag derived percentage claims that don't reconcile against cited inputs.

    Currently checks:
      - "$X, Y% YoY vs $Z" patterns
      - "gross profit of $X on revenue of $Y, GM Z%" patterns

    Extensible to other derivation patterns (margin walk, growth rate, etc.).

    Returns FAIL if any cited derivation disagrees with the recomputed value
    by more than `tolerance` (default 1% relative).
    """
    findings = []

    # YoY derivations
    for m in _YOY_DERIVED_RE.finditer(md_text):
        num = float(m.group("num"))
        cited_pct = float(m.group("pct"))
        den = float(m.group("den"))
        if den == 0:
            continue
        recomputed_pct = (num / den - 1) * 100
        if abs(cited_pct - recomputed_pct) > max(abs(recomputed_pct) * tolerance, 0.5):
            line_start = md_text.rfind("\n", 0, m.start()) + 1
            line_end = md_text.find("\n", m.end())
            findings.append(
                f"YoY arithmetic mismatch: cited {cited_pct:+.1f}% but "
                f"${num}M / ${den}M - 1 = {recomputed_pct:+.1f}% | "
                f"near: {md_text[line_start:line_end].strip()[:140]}"
            )

    # GM derivations
    for m in _GM_DERIVED_RE.finditer(md_text):
        gp = float(m.group("gp"))
        rev = float(m.group("rev"))
        cited_gm = float(m.group("gm"))
        if rev == 0:
            continue
        recomputed_gm = (gp / rev) * 100
        if abs(cited_gm - recomputed_gm) > max(abs(recomputed_gm) * tolerance, 0.5):
            line_start = md_text.rfind("\n", 0, m.start()) + 1
            line_end = md_text.find("\n", m.end())
            findings.append(
                f"GM arithmetic mismatch: cited {cited_gm:.1f}% but "
                f"${gp}M / ${rev}M = {recomputed_gm:.1f}% | "
                f"near: {md_text[line_start:line_end].strip()[:140]}"
            )

    return {
        "gate": "arithmetic_consistency",
        "rule": "derivation_errors_2026_05_12",
        "status": "FAIL" if findings else "PASS",
        "findings": findings,
    }


def gate_temporal_denominator_match(md_text: str, manifest: dict) -> dict:
    """Flag leverage / multiple ratios that label the denominator with a
    temporal qualifier (TTM/LTM/NTM/FY) whose cited value doesn't match the
    manifest's record for that scope.

    Manifest schema (additions required):
      {
        "temporal_values": {
          "TTM_adj_ebitda": {"value": 45.3, "as_of": "Q1_2026"},
          "FY25_adj_ebitda": {"value": 56.0, "as_of": "FY2025"},
          "NTM_sales": {"value": 400.0, "as_of": "..."},
          ...
        }
      }

    Example failure: a digest cited "TTM Adj EBITDA $56M" but the manifest
    TTM was $45M. The gate compares the cited dollar value against the
    manifest TTM, not against the FY value.
    """
    findings = []
    temporal_values = manifest.get("temporal_values", {})
    if not temporal_values:
        # Without a manifest, gate cannot evaluate — emit WARN, not PASS
        return {
            "gate": "temporal_denominator_match",
            "rule": "derivation_errors_2026_05_12",
            "status": "WARN",
            "findings": ["manifest has no temporal_values block — gate skipped"],
        }

    for m in _LEVERAGE_RE.finditer(md_text):
        temporal = m.group("temporal").upper()
        metric_label = m.group("metric").lower().strip()
        cited_denom = float(m.group("denominator"))
        # Construct lookup key — e.g. "TTM_adj_ebitda"
        key = f"{temporal}_{metric_label.replace(' ', '_')}"
        manifest_entry = temporal_values.get(key)
        if manifest_entry is None:
            continue
        manifest_val = float(manifest_entry["value"])
        if abs(cited_denom - manifest_val) / max(abs(manifest_val), 1) > 0.05:
            line_start = md_text.rfind("\n", 0, m.start()) + 1
            line_end = md_text.find("\n", m.end())
            findings.append(
                f"{temporal} {metric_label}: cited ${cited_denom}M but "
                f"manifest has {temporal} value ${manifest_val}M | "
                f"near: {md_text[line_start:line_end].strip()[:140]}"
            )

    return {
        "gate": "temporal_denominator_match",
        "rule": "derivation_errors_2026_05_12",
        "status": "FAIL" if findings else "PASS",
        "findings": findings,
    }


# Pattern: any 99.X token that appears within ~80 chars after the word "Exhibit"
# (or its plural). Handles "Exhibit 99.3", "Exhibits 99.1, 99.2, 99.3", etc.
_EXHIBIT_TOKEN_RE = re.compile(r"\b99\.(\d+)\b")


def gate_source_citation_valid(md_text: str, manifest: dict) -> dict:
    """Flag exhibit citations that don't exist in the print_materials manifest.

    Example failure: a digest cited "Exhibit 99.3 Corporate Presentation" but
    only 99.1 and 99.2 were filed; the deck was website-only.

    Manifest schema:
      {
        "filed_exhibits": ["99.1", "99.2"]
      }
    """
    filed = set(manifest.get("filed_exhibits", []))
    if not filed:
        return {
            "gate": "source_citation_valid",
            "rule": "derivation_errors_2026_05_12",
            "status": "WARN",
            "findings": ["manifest has no filed_exhibits block — gate skipped"],
        }
    findings = []
    # Find every "Exhibit(s) ..." context; collect all 99.X tokens inside the
    # following ~120 char window.
    for ctx_m in re.finditer(r"\bExhibits?\b", md_text, re.IGNORECASE):
        window = md_text[ctx_m.start(): ctx_m.start() + 120]
        for m in _EXHIBIT_TOKEN_RE.finditer(window):
            suffix = m.group(1)
            full_label = f"99.{suffix}"
            if full_label not in filed:
                line_start = md_text.rfind("\n", 0, ctx_m.start()) + 1
                line_end = md_text.find("\n", ctx_m.start() + len(window))
                snippet = md_text[line_start:line_end].strip()[:140]
                msg = (
                    f"cited {full_label} but only filed exhibits are: "
                    f"{sorted(filed)} | near: {snippet}"
                )
                if msg not in findings:
                    findings.append(msg)
    return {
        "gate": "source_citation_valid",
        "rule": "derivation_errors_2026_05_12",
        "status": "FAIL" if findings else "PASS",
        "findings": findings,
    }


# Pattern: "first [time] since QnYY" or "first ... in N years" or "for the first time in"
_HISTORICAL_SPECIFICITY_RE = re.compile(
    r"\b(?:first|only|last)\s+[^.]{0,80}?"
    r"(?:since\s+(?:Q[1-4]\s*['’]?[0-9]{2,4}|[12][09][0-9]{2})"
    r"|in\s+(?:over\s+)?\d+\s+(?:year|quarter)s?"
    r"|in\s+(?:five|four|three|ten|twenty|several)\s+years)",
    re.IGNORECASE,
)


def gate_historical_specificity(md_text: str) -> dict:
    """Flag historical-period claims that don't have a citation or unverified tag.

    Example failure: "first meaningfully negative OCF quarter since Q3 2023"
    — no citation, labeled [INFERRED] but never verified against actual data.

    Acceptable resolutions:
      (a) Add a citation to a manifest entry that proves the claim
      (b) Tag with [INFERRED-UNVERIFIED] explicitly
      (c) Soften the claim ("first negative OCF in multiple quarters")
    """
    findings = []
    for m in _HISTORICAL_SPECIFICITY_RE.finditer(md_text):
        # Look ahead 80 chars for an unverified tag or citation
        window = md_text[m.start():m.end() + 80]
        if re.search(r"\[INFERRED-UNVERIFIED\]|\[SPECULATIVE\]|\[source:", window, re.IGNORECASE):
            continue
        line_start = md_text.rfind("\n", 0, m.start()) + 1
        line_end = md_text.find("\n", m.end())
        findings.append(
            f"historical-specificity claim without citation: "
            f"{md_text[line_start:line_end].strip()[:160]}"
        )
    return {
        "gate": "historical_specificity",
        "rule": "derivation_errors_2026_05_12",
        "status": "WARN" if findings else "PASS",
        "findings": findings,
    }


# ──────────────────────────────────────────────────────────────────
# Semantic / cross-source gates
#
# These cover the four error classes that escape the mechanical gates:
#   - Logical errors with correct math (TREND DIRECTION subset)
#   - Quote misattribution in transcripts (SPEAKER ROLE subset)
#   - Stale saved-note anchors (FRESHNESS)
#   - Cherry-picked time windows (MULTI-WINDOW DISCLOSURE)
# These are higher-noise than the L1 gates — emit WARN, not FAIL, by
# default. Operator reviews findings before render.
# ──────────────────────────────────────────────────────────────────


# ── Note freshness ────────────────────────────────────────────────

_MEMORY_CITATION_RE = re.compile(
    r"\[memory[:\s]+([A-Za-z0-9_\-./]+\.md)(?:[,;]\s*cached\s+(\d{4}-\d{2}-\d{2}))?\]",
    re.IGNORECASE,
)


def gate_memory_freshness(md_text: str, memory_dir: Path = None,
                          max_age_days: int = 14) -> dict:
    """Flag citations to saved-note files where the file's mtime is older
    than `max_age_days`.

    Forces the discipline of either re-verifying the underlying source
    before relying on a saved-note anchor, or explicitly accepting the
    staleness by tagging the citation with a recent `cached: YYYY-MM-DD`
    marker.

    Two citation styles supported:
      [memory: short_position.md, cached 2026-05-12]   ← preferred
      [memory: short_position.md]                       ← bare; gate checks mtime
    """
    import datetime as _dt
    if memory_dir is None:
        memory_dir = REPO_ROOT / "notes"

    findings = []
    now = _dt.datetime.now()
    for m in _MEMORY_CITATION_RE.finditer(md_text):
        fname = m.group(1)
        cached_date = m.group(2)
        if cached_date:
            try:
                cached_dt = _dt.datetime.fromisoformat(cached_date)
                age = (now - cached_dt).days
            except ValueError:
                age = None
        else:
            # Fall back to file mtime
            path = memory_dir / fname
            if not path.exists():
                findings.append(f"cited memory file not found: {fname}")
                continue
            age = (now - _dt.datetime.fromtimestamp(path.stat().st_mtime)).days
        if age is not None and age > max_age_days:
            line_start = md_text.rfind("\n", 0, m.start()) + 1
            line_end = md_text.find("\n", m.end())
            findings.append(
                f"stale memory citation ({age}d old, max {max_age_days}d): "
                f"{fname} | near: {md_text[line_start:line_end].strip()[:140]}"
            )
    return {
        "gate": "memory_freshness",
        "rule": "semantic_gates_2026_05_12",
        "status": "WARN" if findings else "PASS",
        "findings": findings,
    }


# ── Speaker role consistency ──────────────────────────────────────

# Default role mapping; can be overridden per-ticker via config.yaml
# `speaker_roles` block. Topic phrases are case-insensitive substrings.
DEFAULT_SPEAKER_ROLES = {
    "CEO": {
        "owns": [
            "strategic", "vision", "growth trajectory", "long-term",
            "I believe", "I'm proud", "we expect", "guidance",
        ],
    },
    "CFO": {
        "owns": [
            "gross-to-net", "GTN", "accruals", "business rules",
            "buy-down", "buydown", "claims data", "co-pay", "copay",
            "revenue recognition", "variable consideration", "DSO",
            "operating cash flow", "OCF", "balance sheet", "debt covenant",
            "depreciation", "amortization",
        ],
    },
    "CCO": {
        "owns": [
            "sales force", "rep productivity", "commercial team",
            "market share", "prescriber base", "NRx", "TRx", "ASP",
            "field execution", "territory",
        ],
    },
    "CSO": {
        "owns": [
            "clinical", "regulatory", "NDA", "FDA", "pre-NDA", "Phase 3",
            "pharmacokinetic", "PK", "tox study", "CMC", "submission timing",
            "trial design", "primary endpoint",
        ],
    },
}


def gate_speaker_role_consistency(transcript_text: str, config: dict = None) -> dict:
    """Flag transcript Q&A segments where the speaker label appears
    inconsistent with the topic of the statement.

    Recognizes lines starting with "A - <Name>" or "[<Role> <Name>]" — a
    common transcript speaker label format. For each speaker block, scans
    the content for topic phrases assigned to ANOTHER role.

    Example: a transcript attributed the Chief Scientific Officer (CSO) to a
    statement about payer gross-to-net dynamics — clearly a CFO or CEO
    statement, not CSO. Gate would flag.
    """
    roles = (config or {}).get("speaker_roles", DEFAULT_SPEAKER_ROLES)

    # Build inverse map: topic phrase → owning role
    topic_to_role = {}
    for role, cfg in roles.items():
        for phrase in cfg.get("owns", []):
            topic_to_role[phrase.lower()] = role

    # Parse "A - <Name>" speaker label blocks. Name = 1-4 capitalized tokens,
    # each optionally followed by a period (handles middle initials and
    # initials-with-periods like "Mark L. Baum").
    block_re = re.compile(
        r"^(?:A\s*-\s*|Q\s*-\s*)?(?P<name>(?:[A-Z](?:[a-z]+|\.)?\s*){1,4})\s*"
        r"(?:\[BIO\s+\d+\s*<GO>\]\([^)]+\)\s*)?$",
        re.MULTILINE,
    )

    findings = []
    # Split transcript into speaker blocks based on lines that match a speaker label
    # Naive parser: take each speaker-name line as a delimiter
    lines = transcript_text.splitlines()
    current_speaker = None
    current_role = None
    block_buffer = []

    name_to_role_map = (config or {}).get("name_to_role", {})

    def _normalize_name(name: str) -> str:
        """Strip middle initials (single-letter or letter+period tokens).
        'Amir H Shojaei' / 'Mark L. Baum' → 'amir shojaei' / 'mark baum'.
        """
        toks = [t for t in re.split(r"\s+", name)
                if not re.fullmatch(r"[A-Z]\.?", t)]
        return " ".join(toks).lower().strip()

    def role_of(name: str) -> str | None:
        # Direct lookup
        if name in name_to_role_map:
            return name_to_role_map[name]
        norm = _normalize_name(name)
        # First-and-last-name match, ignoring middle initials
        for k, v in name_to_role_map.items():
            if _normalize_name(k) == norm:
                return v
            # Looser fallback: first OR last name match (handles single-name labels)
            kn = _normalize_name(k).split()
            nn = norm.split()
            if kn and nn and kn[0] == nn[0] and kn[-1] == nn[-1]:
                return v
        return None

    def flush_block():
        if current_role is None or not block_buffer:
            return
        body = " ".join(block_buffer).lower()
        # Deferral-only blocks should be skipped — when a speaker's text is
        # primarily handing off to someone else ("Andrew, do you want to
        # comment on that?"), don't flag for the substantive topic that
        # follows the deferral. Heuristic: if the body contains a deferral
        # phrase AND is short (<300 chars), it's pure handoff.
        deferral_phrases = [
            "do you want to comment", "do you want to talk",
            "do you want to add", "i'll let", "ask andrew",
            "ask pat", "ask amir", "ask mark",
        ]
        is_short_deferral = (
            len(body) < 300
            and any(p in body for p in deferral_phrases)
        )
        if is_short_deferral:
            return
        for phrase, owning_role in topic_to_role.items():
            if owning_role == current_role:
                continue
            if phrase in body:
                findings.append(
                    f"speaker '{current_speaker}' ({current_role}) discussed "
                    f"'{phrase}' which is owned by {owning_role} — possible mislabel"
                )
                break  # one finding per block

    for line in lines:
        stripped = line.strip()
        m = block_re.match(stripped)
        # Heuristic: speaker label lines are short and end in BIO link or just a name
        if m and ("[BIO" in stripped or len(stripped.split()) <= 4):
            # flush previous block
            flush_block()
            current_speaker = m.group("name").strip()
            current_role = role_of(current_speaker)
            block_buffer = []
        else:
            block_buffer.append(stripped)
    flush_block()

    return {
        "gate": "speaker_role_consistency",
        "rule": "semantic_gates_2026_05_12",
        "status": "WARN" if findings else "PASS",
        "findings": findings,
    }


# ── Multi-window disclosure (anti cherry-picking) ─────────────────

# Words that imply directional growth assessment — require multi-window context
_TREND_CLAIM_RE = re.compile(
    r"\b(?:accelerating|decelerating|inflecting|reaccelerating|"
    r"strengthening|weakening|improving|deteriorating|growing|declining|"
    r"breaking out|momentum building|momentum slowing)\b",
    re.IGNORECASE,
)
_YOY_NEAR_RE = re.compile(r"\b(?:Yo[/]?Y|YoY|year[-\s]?over[-\s]?year)\b", re.IGNORECASE)
_QOQ_NEAR_RE = re.compile(r"\b(?:Qo[/]?Q|QoQ|quarter[-\s]?over[-\s]?quarter|sequential)\b", re.IGNORECASE)


def gate_multi_window_disclosure(md_text: str, window_chars: int = 400) -> dict:
    """For every trend-direction claim, require both YoY and QoQ context
    within `window_chars` of the claim. Flag if only one window is present
    — that's a cherry-picking signature.

    Rationale: a product line can be claimed "growing" by citing only the
    favorable comp (e.g., underlying +9% YoY) while ignoring the unfavorable
    one (e.g., reported -2.6% YoY, or sequential -19%). Forcing both windows
    surfaces the framing choice.

    Acceptable resolutions:
      (a) Add the missing window — show both YoY and QoQ
      (b) Tag the trend claim as one-sided: "[YoY-only], [QoQ-only]"
    """
    findings = []
    for m in _TREND_CLAIM_RE.finditer(md_text):
        ctx_start = max(0, m.start() - window_chars)
        ctx_end = min(len(md_text), m.end() + window_chars)
        ctx = md_text[ctx_start:ctx_end]
        has_yoy = bool(_YOY_NEAR_RE.search(ctx))
        has_qoq = bool(_QOQ_NEAR_RE.search(ctx))
        # Allow explicit tags to silence
        if "[YoY-only]" in ctx or "[QoQ-only]" in ctx or "[multi-window-exempt]" in ctx:
            continue
        if has_yoy and has_qoq:
            continue
        if not has_yoy and not has_qoq:
            # trend claim with NO numerical comp at all — bigger flag
            findings.append(
                f"trend claim '{m.group(0)}' has no comp window cited within "
                f"±{window_chars} chars — direction asserted without evidence"
            )
        else:
            missing = "QoQ" if has_yoy else "YoY"
            findings.append(
                f"trend claim '{m.group(0)}' shows {('YoY' if has_yoy else 'QoQ')} "
                f"only — {missing} window missing within ±{window_chars} chars "
                f"(possible cherry-pick)"
            )
    return {
        "gate": "multi_window_disclosure",
        "rule": "semantic_gates_2026_05_12",
        "status": "WARN" if findings else "PASS",
        "findings": findings,
    }


# ── Trend-direction consistency ───────────────────────────────────

_ACCEL_TOKEN_RE = re.compile(
    r"\b(accelerating|reaccelerating|inflecting up|gaining momentum)\b",
    re.IGNORECASE,
)
_DECEL_TOKEN_RE = re.compile(
    r"\b(decelerating|slowing|losing momentum|moderating)\b",
    re.IGNORECASE,
)
# Pattern to extract a sequence of growth rates: "Q1 +9%, Q2 +12%, Q3 +18%"
_GROWTH_SERIES_RE = re.compile(
    r"(?:Q[1-4]['']?[0-9]{2}|[12][09][0-9]{2})\s*[:=]?\s*"
    r"([+\-][0-9]+(?:\.[0-9]+)?)%",
    re.IGNORECASE,
)


def gate_trend_direction_consistency(md_text: str, window_chars: int = 300) -> dict:
    """For every "accelerating" or "decelerating" claim, look at nearby
    growth-rate sequences and check whether the direction matches the
    trajectory.

    Sequence detection requires at least 2 cited growth rates within
    `window_chars` of the claim. If the trajectory contradicts the claim,
    emit WARN.

    Real-world rationale: a digest could correctly cite "+9% YoY" and
    "+18% YoY (prior Q)" and conclude "growth accelerating" — but the
    sequence -18 → -9 is decelerating. The arithmetic gate doesn't catch
    this; it only verifies each individual number reconciles.
    """
    findings = []
    for direction_re, claimed_direction in [
        (_ACCEL_TOKEN_RE, "accelerating"),
        (_DECEL_TOKEN_RE, "decelerating"),
    ]:
        for m in direction_re.finditer(md_text):
            ctx_start = max(0, m.start() - window_chars)
            ctx_end = min(len(md_text), m.end() + window_chars)
            ctx = md_text[ctx_start:ctx_end]
            series = [float(g) for g in _GROWTH_SERIES_RE.findall(ctx)]
            if len(series) < 2:
                continue
            # Check trajectory direction (first → last)
            actual_direction = (
                "accelerating" if series[-1] > series[0] else
                "decelerating" if series[-1] < series[0] else
                "flat"
            )
            if actual_direction != claimed_direction and actual_direction != "flat":
                line_start = md_text.rfind("\n", 0, m.start()) + 1
                line_end = md_text.find("\n", m.end())
                findings.append(
                    f"claimed '{claimed_direction}' but cited series "
                    f"{series[0]:+.1f}% → {series[-1]:+.1f}% is "
                    f"{actual_direction} | near: "
                    f"{md_text[line_start:line_end].strip()[:140]}"
                )
    return {
        "gate": "trend_direction_consistency",
        "rule": "semantic_gates_2026_05_12",
        "status": "WARN" if findings else "PASS",
        "findings": findings,
    }


def gate_no_performative_jargon(md_text: str) -> dict:
    """FAIL if banned performative phrases appear."""
    banned = [
        "risk symmetry",
        "asymmetric right",
        "asymmetric left",
        "asymmetric to the right",
        "asymmetric to the left",
    ]
    findings = []
    for phrase in banned:
        for m in re.finditer(re.escape(phrase), md_text, re.IGNORECASE):
            line_start = md_text.rfind("\n", 0, m.start()) + 1
            line_end = md_text.find("\n", m.end())
            line = md_text[line_start:line_end].strip()
            findings.append(f"banned phrase '{phrase}' on line: {line[:120]}")
    return {
        "gate": "no_performative_jargon",
        "rule": "feedback_no_performative_synthesis",
        "status": "FAIL" if findings else "PASS",
        "findings": findings,
    }


def gate_no_derived_nongaap_om(md_text: str) -> dict:
    """WARN if non-GAAP OM appears to be derived from NI/rev rather than stated."""
    warnings = []
    # Look for patterns that suggest derivation: "non-GAAP OM = X% (derived)" or "implied non-GAAP OM" or
    # "non-GAAP NI / rev = Y%"
    derivation_markers = [
        r"non-?GAAP\s+(?:OM|operating margin)\s*[:=]\s*\d+\.?\d*%\s*\(?\s*(?:derived|implied|computed)",
        r"derived\s+non-?GAAP\s+(?:OM|operating margin)",
        r"non-?GAAP\s+NI\s*/\s*rev",
    ]
    for pat in derivation_markers:
        for m in re.finditer(pat, md_text, re.IGNORECASE):
            line_start = md_text.rfind("\n", 0, m.start()) + 1
            line_end = md_text.find("\n", m.end())
            warnings.append(f"possibly-derived OM near: {md_text[line_start:line_end].strip()[:120]}")
    # Look for explicit STATED tag near OM mentions — that's the protective pattern
    has_stated_tag_near_om = bool(re.search(r"non-?GAAP\s+(?:OM|operating margin)[^.\n]*\[STATED\]",
                                            md_text, re.IGNORECASE))
    return {
        "gate": "no_derived_nongaap_om",
        "rule": "feedback_no_derived_nongaap_om",
        "status": "WARN" if warnings else "PASS",
        "findings": warnings,
        "protective_pattern_found": has_stated_tag_near_om,
    }


def gate_salient_kpis_coverage(md_text: str, config: dict) -> dict:
    """FAIL if any salient_kpi from config doesn't appear in scorecard + synthesis."""
    findings = []
    salient = config.get("salient_kpis", [])
    if not salient:
        return {
            "gate": "salient_kpis_coverage",
            "rule": "feedback_digest_salient_kpis_pre_flight",
            "status": "WARN",
            "findings": ["no salient_kpis declared in config — can't verify coverage"],
        }

    # Parse digest into sections
    md_lower = md_text.lower()

    # Common abbreviations / alternate forms — KPIs often appear as "OM" not "Operating Margin"
    ABBREV_MAP = {
        "operating margin": ["om", "operating margin", "op margin", "non-gaap om", "nongaap om"],
        "gross margin": ["gm", "gross margin"],
        "earnings per share": ["eps", "earnings per share"],
        "free cash flow": ["fcf", "free cash flow", "free cashflow"],
        "ebitda margin": ["ebitda margin", "adj ebitda margin", "ebitda %"],
        "medical loss ratio": ["mlr", "medical loss ratio", "mcr"],
        "subscribers": ["subscribers", "subs"],
        "revenue": ["revenue", "rev", "sales"],
    }

    for kpi in salient[:4]:  # only check top 4 (synthesis paras only cover top 3-4)
        label = kpi.get("label", "")
        name = kpi.get("name", "")
        # Generate matching tokens — try the label, the name with underscores → spaces, abbreviations, distinctive words
        candidates = [
            label.lower(),
            name.replace("_", " ").lower(),
        ]
        # Add abbreviation expansions
        label_lower = label.lower()
        for full, alts in ABBREV_MAP.items():
            if full in label_lower or any(a in label_lower for a in alts):
                candidates.extend(alts)
        # Pull out 1-2 distinctive words from the label
        words = re.findall(r"\w+", label)
        if words:
            distinctive = [w.lower() for w in words if len(w) > 4][:2]
            if distinctive:
                candidates.append(" ".join(distinctive))
        # Dedupe
        candidates = list({c for c in candidates if c})

        # Check if ANY of the candidates appears in the digest text
        found_in_synthesis = False
        # Synthesis section: between "## Synthesis" and "## Guide Section"
        synth_match = re.search(r"##\s+Synthesis.*?(?=##\s+(?:Guide Section|Beat/Miss))", md_text, re.IGNORECASE | re.DOTALL)
        synthesis_text = synth_match.group(0).lower() if synth_match else ""

        # Scorecard section
        scorecard_match = re.search(r"##\s+Beat/Miss Scorecard.*?(?=##\s+)", md_text, re.IGNORECASE | re.DOTALL)
        scorecard_text = scorecard_match.group(0).lower() if scorecard_match else ""

        for cand in candidates:
            if cand and cand in synthesis_text:
                found_in_synthesis = True
                break
        found_in_scorecard = any(cand in scorecard_text for cand in candidates if cand)

        if not found_in_synthesis:
            findings.append(f"salient_kpi '{label}' NOT in Synthesis section")
        if not found_in_scorecard:
            findings.append(f"salient_kpi '{label}' NOT in Beat/Miss Scorecard")

    return {
        "gate": "salient_kpis_coverage",
        "rule": "feedback_digest_salient_kpis_pre_flight",
        "status": "FAIL" if findings else "PASS",
        "findings": findings,
    }


def gate_day_of_binary_anchored(md_text: str, config: dict) -> dict:
    """FAIL if day_of_binary.primary doesn't appear in Synthesis paragraph 1."""
    primary = config.get("day_of_binary", {}).get("primary", "")
    if not primary:
        return {
            "gate": "day_of_binary_anchored",
            "rule": "feedback_day_of_binary_lookup",
            "status": "WARN",
            "findings": ["day_of_binary.primary not declared in config"],
        }

    # Find the Synthesis section and isolate paragraph 1 (after **Story.**)
    synth_match = re.search(r"##\s+Synthesis.*?(?=##\s+(?:Guide|Beat))", md_text, re.IGNORECASE | re.DOTALL)
    if not synth_match:
        return {
            "gate": "day_of_binary_anchored",
            "rule": "feedback_day_of_binary_lookup",
            "status": "FAIL",
            "findings": ["no Synthesis section found in digest"],
        }
    synth_text = synth_match.group(0)
    # Story para = first **Story.** ... up to next ** or ##
    story_match = re.search(r"\*\*Story\.\*\*(.*?)(?=\*\*[A-Z]|##\s)", synth_text, re.DOTALL)
    story_para = story_match.group(1) if story_match else synth_text[:2000]

    # Look for distinctive tokens from primary in story_para
    primary_tokens = [w.lower() for w in re.findall(r"\w+", primary) if len(w) > 4][:3]
    if not primary_tokens:
        primary_tokens = [primary.lower()]
    found = any(tok in story_para.lower() for tok in primary_tokens)

    return {
        "gate": "day_of_binary_anchored",
        "rule": "feedback_day_of_binary_lookup",
        "status": "PASS" if found else "FAIL",
        "findings": [] if found else [f"day_of_binary.primary '{primary[:80]}' not found in Synthesis Story paragraph"],
    }


# Optional set of external data-feed labels to police. When populated (e.g.
# {"Feed A", "Feed B"}), the gate WARNs if the text references one of these
# feeds without a backing manifest entry. Empty by default — the generic build
# relies only on free sources (SEC EDGAR, Yahoo Finance, manual entry).
DATA_FEED_LABELS: set[str] = set()


def gate_source_tier_labels(md_text: str, manifest: dict) -> dict:
    """WARN if a named external data feed is referenced as a source without a
    corresponding manifest entry. Only feeds listed in DATA_FEED_LABELS are
    policed; by default that set is empty, so this gate PASSes."""
    sources = manifest.get("sources", []) if manifest else []
    findings = []
    for label in DATA_FEED_LABELS:
        labeled_in_manifest = any(label in s.get("tool_name", "") for s in sources)
        if not labeled_in_manifest and label in md_text:
            findings.append(
                f"Text references '{label}' but data_manifest.json has NO matching "
                f"entries — either add manifest entries or remove the labels"
            )
    return {
        "gate": "source_tier_labels",
        "rule": "feedback_verify_before_claim",
        "status": "WARN" if findings else "PASS",
        "findings": findings,
    }


def gate_required_sections_present(md_text: str) -> dict:
    """FAIL if any required section header is missing.

    Required sections:
      Synthesis, Guide Section, Beat/Miss Scorecard, Watch-List,
      Trade Construction (action box), Appendix A, Appendix B.
    Cash Quality / Cash Flow Walk is conditional.

    NOTE: 'Bias Pre-Commitment' is intentionally NOT required in the deliverable.
    It is an internal pre-flight artifact and lives in synthesis/ work files.
    The production_ready_check gate halts the render if the section appears
    in the rendered output.
    """
    required_patterns = [
        ("Synthesis", r"##\s+Synthesis"),
        ("Guide Section / Guide Delta", r"###?\s+Guide Delta"),
        ("Beat/Miss Scorecard", r"##\s+Beat/Miss Scorecard"),
        ("Watch-List Reconciliation", r"##\s+Watch-?List"),
        ("Trade Construction / Action box", r"##\s+(?:Trade Construction|Pod Tactical Lens)"),
        ("Appendix A — Historical Reactions", r"##\s+Appendix A"),
        ("Appendix B — Visibility Cues", r"##\s+Appendix B"),
    ]
    findings = []
    for label, pat in required_patterns:
        if not re.search(pat, md_text, re.IGNORECASE):
            findings.append(f"missing required section: {label}")
    return {
        "gate": "required_sections_present",
        "rule": "DIGEST_AGENT_SPEC §4",
        "status": "FAIL" if findings else "PASS",
        "findings": findings,
    }


def gate_conditional_sections_consistent(md_text: str, config: dict) -> dict:
    """FAIL if conditional sections present when flag is false (or absent when true)."""
    cond = config.get("conditional_sections", {})
    findings = []

    # Cash Flow Walk
    has_cfw = bool(re.search(r"##\s+Cash Flow Walk", md_text, re.IGNORECASE))
    expected_cfw = cond.get("include_cash_flow_walk", False)
    if has_cfw and not expected_cfw:
        findings.append("Cash Flow Walk section present but include_cash_flow_walk=false in config")
    elif not has_cfw and expected_cfw:
        findings.append("Cash Flow Walk section MISSING but include_cash_flow_walk=true in config")

    return {
        "gate": "conditional_sections_consistent",
        "rule": "DIGEST_AGENT_SPEC §4.0 conditional_sections",
        "status": "FAIL" if findings else "PASS",
        "findings": findings,
    }


# ──────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────

def load_config(analyst: str, ticker: str) -> dict:
    p = ticker_root(analyst, ticker) / "config.yaml"
    if not p.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(p.read_text()) or {}
    except ImportError:
        return {}


def load_manifest(analyst: str, ticker: str) -> dict:
    p = ticker_root(analyst, ticker) / "data_manifest.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def run_audit(md_path: Path, analyst: str, ticker: str) -> dict:
    md_text = md_path.read_text()
    config = load_config(analyst, ticker)
    manifest = load_manifest(analyst, ticker)

    gates = [
        gate_required_sections_present(md_text),
        gate_no_performative_jargon(md_text),
        gate_no_derived_nongaap_om(md_text),
        gate_salient_kpis_coverage(md_text, config),
        gate_day_of_binary_anchored(md_text, config),
        gate_source_tier_labels(md_text, manifest),
        gate_conditional_sections_consistent(md_text, config),
        # ── Derivation-error gates ──
        gate_arithmetic_consistency(md_text),
        gate_temporal_denominator_match(md_text, manifest),
        gate_source_citation_valid(md_text, manifest),
        gate_historical_specificity(md_text),
        # ── Semantic / cross-source gates ──
        gate_memory_freshness(md_text),
        gate_multi_window_disclosure(md_text),
        gate_trend_direction_consistency(md_text),
        # Speaker-role consistency runs on transcript files, not digest md.
        # Wire into the transcript stage separately.
    ]

    n_pass = sum(1 for g in gates if g["status"] == "PASS")
    n_warn = sum(1 for g in gates if g["status"] == "WARN")
    n_fail = sum(1 for g in gates if g["status"] == "FAIL")

    overall = "FAIL" if n_fail else ("WARN" if n_warn else "PASS")
    return {
        "audit_timestamp": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker,
        "analyst": analyst,
        "digest_path": str(md_path),
        "overall_status": overall,
        "summary": {"pass": n_pass, "warn": n_warn, "fail": n_fail, "total": len(gates)},
        "gates": gates,
    }


def print_report(report: dict) -> None:
    print("=" * 80)
    print(f"BASELINE AUDIT — {report['ticker']} ({report['analyst']})")
    print(f"Digest: {report['digest_path']}")
    print(f"Audit at: {report['audit_timestamp']}")
    print("=" * 80)
    for g in report["gates"]:
        symbol = {"PASS": "[+]", "WARN": "[?]", "FAIL": "[X]"}.get(g["status"], "[?]")
        print(f"  {symbol} {g['gate']:<40} {g['status']:<6} (rule: {g['rule']})")
        for finding in g.get("findings", []):
            print(f"        - {finding}")
    print()
    s = report["summary"]
    print(f"SUMMARY: {s['pass']}/{s['total']} pass, {s['warn']} warn, {s['fail']} fail")
    print(f"OVERALL: {report['overall_status']}")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Pre-render audit gate for digests")
    parser.add_argument("--digest-md", required=True, help="Path to digest markdown")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--analyst", required=True)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human report")
    parser.add_argument("--exit-nonzero-on-fail", action="store_true",
                        help="Exit code 2 if any gate FAILS, 1 if any WARN, 0 otherwise")
    args = parser.parse_args()

    md_path = Path(args.digest_md)
    if not md_path.exists():
        print(f"[error] {md_path} not found", file=sys.stderr)
        sys.exit(2)

    report = run_audit(md_path, args.analyst, args.ticker)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)

    if args.exit_nonzero_on_fail:
        if report["overall_status"] == "FAIL":
            sys.exit(2)
        elif report["overall_status"] == "WARN":
            sys.exit(1)


if __name__ == "__main__":
    main()
