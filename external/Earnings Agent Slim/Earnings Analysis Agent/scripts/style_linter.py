"""
style_linter.py — preview markdown style linter v0.1

Catches forbidden phrases, structural violations, and formatting issues that
otherwise require user correction. Built to reduce preview iteration churn.

Checks (each emits a violation with line number + rule_id + suggested fix):

  Lexical (forbidden phrases):
    L-01  Document version references ("V2", "V3", "vs V2", "from V1", etc.)
    L-02  "Print binary" / "primary binary" labeling
    L-03  Performative analytical phrases ("is the trap", "is the smoking gun",
          "is the call", "playing the under" without attribution context)
    L-04  Risk-symmetry / asymmetric jargon ("asymmetric right vs left",
          "risk symmetry")
    L-05  Prior-version self-references
    L-06  Banned internal codename terminology

  Structural:
    S-01  Takeaways section >9 bullets (max 9)
    S-02  KPI table missing y/y growth column
    S-03  KPI table contains z-score column (banned)
    S-04  Decision table missing required rows (Pre Earnings Decision /
          Recommended Position Size / Earnings Preview Score)

  Formatting:
    F-01  Unescaped `$` characters that could trigger pandoc TeX-math bug
          (paired `$...$` outside code spans / table cells with `\$` escape)
    F-02  Decimal precision: $-values to whole or 1dp; %-values to 1dp; bps whole
    F-03  Scare quotes: short quoted phrases (≤4 words) without attribution verb
          in same sentence

Usage:
    python style_linter.py --markdown path/to/preview.md
    python style_linter.py --markdown preview.md --analyst user  # loads style preferences
    python style_linter.py --markdown preview.md --json out.json

Exit codes:
    0 — clean (no violations)
    1 — violations present (block pipeline)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Forbidden-phrase regex library
# ─────────────────────────────────────────────────────────────────────────────

FORBIDDEN_PHRASES = [
    {
        "rule_id": "L-01",
        "name": "version_reference",
        "pattern": re.compile(
            r"\b(?:vs?\s+|from\s+|since\s+|than\s+)V\d+\b|"
            r"\bV\d+\s+(?:was|had|missed|caught)\b|"
            r"\bprior\s+(?:version|draft)\b|"
            r"\b(?:previous|earlier)\s+(?:version|iteration|draft)\s+of\s+(?:this|the)\b",
            re.IGNORECASE,
        ),
        "fix": "Drop document version comparisons; circulation copies should be self-contained.",
    },
    {
        "rule_id": "L-02",
        "name": "binary_labeling",
        "pattern": re.compile(
            r"\b(?:print|day-of)\s+binary\b|\bTHE\s+(?:print\s+)?BINARY\b|"
            r"\bprimary\s+binary\b|\bday-of\s+primary\s+binary\b",
            re.IGNORECASE,
        ),
        "fix": "Drop 'binary' labeling. Multiple things can be important on the print; just list them.",
    },
    {
        "rule_id": "L-03",
        "name": "performative_phrases",
        "pattern": re.compile(
            r"\bis\s+the\s+(?:trap|smoking\s+gun|call|tell|trigger)\b|"
            r"\bplaying\s+the\s+under\b(?!\s+(?:per|according))|"
            r"\bbuy\s+the\s+rumor\s+/?\s+hedge\b",
            re.IGNORECASE,
        ),
        "fix": "Replace with flat factual statement. Cute framing reads as sell-side commentary.",
    },
    {
        "rule_id": "L-04",
        "name": "risk_symmetry_jargon",
        "pattern": re.compile(
            r"\b(?:risk\s+symmetry|asymmetric\s+right\s+vs\s+left|"
            r"asymmetric\s+left\s+vs\s+right)\b",
            re.IGNORECASE,
        ),
        "fix": "Lead synthesis with narrative on volumes/ASP/recovery/OM bridge instead of jargon.",
    },
    {
        "rule_id": "L-05",
        "name": "prior_draft_self_reference",
        "pattern": re.compile(
            r"\b(?:Yodlee[-\s]only\s+narrative|the\s+prior\s+(?:framing|interpretation)|"
            r"my\s+(?:earlier|prior)\s+(?:framing|read|take))\b",
            re.IGNORECASE,
        ),
        "fix": "Drop self-references to prior drafts; deliverable should stand alone.",
    },
    {
        "rule_id": "L-07",
        "name": "bias_pre_commitment_in_deliverable",
        "pattern": re.compile(
            r"^#{1,4}\s+Bias Pre-?Commitment\b|"
            r"\b(?:Going in I['’]m leaning|I['’]m at risk of "
            r"(?:confirmation|anchoring|recency) bias|"
            r"Pre-commit horizon|post-hoc rewrites? (?:of this section )?are? forbidden)\b",
            re.IGNORECASE | re.MULTILINE,
        ),
        "fix": (
            "Remove Bias Pre-Commitment block and first-person pre-commitment "
            "language. Pre-commitment is an internal pre-flight artifact; it "
            "lives in synthesis/ work files, not the circulation deliverable."
        ),
    },
    {
        "rule_id": "L-08",
        "name": "analyst_named_action_label",
        # Flag any person-named action label ("<Name>'s AI Bot Call").
        "pattern": re.compile(
            r"[A-Z][a-z]+['’]s AI Bot Call|AI Bot Call",
            re.IGNORECASE,
        ),
        "fix": (
            "Replace any analyst-named action label with 'Recommended Action'. "
            "Circulation deliverables use neutral institutional labels."
        ),
    },
    {
        "rule_id": "L-09",
        "name": "analyst_name_placeholder",
        # Catch residual fill-me placeholders awaiting human input.
        "pattern": re.compile(
            r"\[user\s*—|\[user\s+pending\]|\[user\s+will\b|\[user\s+to\b|"
            r"\buser\s+pending\b|\bper\s+user\b",
            re.IGNORECASE,
        ),
        "fix": (
            "Remove analyst-name placeholders awaiting human fill. "
            "Either fill the value or omit the line."
        ),
    },
    {
        "rule_id": "L-10",
        "name": "scaffolding_placeholder",
        "pattern": re.compile(
            r"\[PENDING\b|PENDING\s*—\s*Sub-agent|<!--\s*LLM_FILL\b|"
            r"<!--\s*PENDING\b|TBD by Sub-agent",
            re.IGNORECASE,
        ),
        "fix": (
            "Replace all [PENDING] / LLM_FILL / Sub-agent placeholders with "
            "actual content. Do not deliver scaffolding."
        ),
    },
    {
        "rule_id": "L-11",
        "name": "stage_footer_commentary",
        "pattern": re.compile(
            r"\*?End of Stage [12]\b|"
            r"^#{1,4}\s+Audit metadata\b|"
            r"^#{1,4}\s+Template Usage Notes\b|"
            r"REMOVE BEFORE RENDERING",
            re.IGNORECASE | re.MULTILINE,
        ),
        "fix": (
            "Remove stage / process commentary footers. These are internal "
            "build artifacts and do not belong in circulation deliverables."
        ),
    },
    {
        "rule_id": "L-12",
        "name": "prestaged_reference",
        "pattern": re.compile(
            r"PRESTAGED|pre-?staged\s+(?:skeleton|digest|preview|file|template)",
            re.IGNORECASE,
        ),
        "fix": (
            "Remove references to 'PRESTAGED' or 'pre-staged' files. "
            "These are internal scaffolding artifacts."
        ),
    },
    {
        "rule_id": "L-13",
        "name": "drafting_self_reference",
        "pattern": re.compile(
            r"\b(?:my\s+(?:earlier|prior)\s+(?:framing|read|take|analysis)|"
            r"as\s+(?:I|the\s+agent)\s+(?:wrote|noted|said)\s+(?:above|earlier|before)|"
            r"in\s+my\s+(?:initial|first|previous)\s+draft)\b",
            re.IGNORECASE,
        ),
        "fix": (
            "Remove self-referential commentary about drafting process. "
            "Deliverable should read like a finished research note."
        ),
    },
    {
        "rule_id": "L-14",
        "name": "internal_process_reference",
        # Pattern retains the legacy internal data-feed token as a detection string.
        "pattern": re.compile(
            r"price target is (?:now )?stale|"
            r"\bEDS (?:weighted )?(?:price )?target\b|"
            r"(?:internal target|target/IRR|\bIRR\b) (?:should be|needs? to be|to be) revised|"
            r"should be (?:revised down|marked (?:down|toward))|"
            r"unsupported by the (?:aligned )?model|"
            r"stale relative to the",
            re.IGNORECASE,
        ),
        "fix": (
            "Remove internal-target / model-housekeeping language. Frame valuation "
            "as a market observation (street PT vs the quote, multiples on consensus EPS)."
        ),
    },
    {
        "rule_id": "L-15",
        "name": "filler_repetition",
        "pattern": re.compile(
            r"fairly[-\s]to[-\s](?:slightly[-\s])?richly valued|"
            r"no longer (?:a |an )?fundamental edge|"
            r"the variant is no longer expressed|"
            r"high[-\s]variance,?\s*high[-\s]beta print",
            re.IGNORECASE,
        ),
        "fix": (
            "Cut filler / word-salad and repeated framing. State the consensus-view "
            "point once and weave the quant into the thesis."
        ),
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Markdown structural parser (lightweight)
# ─────────────────────────────────────────────────────────────────────────────

def _find_section(lines: list[str], heading_pattern: re.Pattern) -> tuple[int, int] | None:
    """Return (start_line, end_line) for a section identified by heading regex.

    end_line is exclusive (next heading at same or higher level, or EOF).
    Returns None if section not found.
    """
    start = None
    start_level = 0
    for idx, line in enumerate(lines):
        if start is None:
            m = heading_pattern.match(line)
            if m:
                start = idx
                # Count #s to determine level
                lead = re.match(r"^(#+)", line.strip())
                start_level = len(lead.group(1)) if lead else 3
        else:
            # Find next heading at same or higher level (= shorter or equal #)
            lead = re.match(r"^(#+)\s", line)
            if lead and len(lead.group(1)) <= start_level:
                return (start, idx)
    if start is not None:
        return (start, len(lines))
    return None


def _bullets_in_range(lines: list[str], start: int, end: int) -> list[tuple[int, str]]:
    """Return [(line_no, bullet_text)] for top-level bullets in the line range."""
    out = []
    for idx in range(start, end):
        line = lines[idx]
        # Top-level bullet = starts with - or * with no leading whitespace > 2 spaces
        m = re.match(r"^(?:-|\*)\s+(.*)$", line)
        if m:
            out.append((idx + 1, m.group(1)))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Lexical checks
# ─────────────────────────────────────────────────────────────────────────────

# Rules that BLOCK the pipeline (severity = fail). Others are warn.
FAIL_RULE_IDS = {"L-06", "L-07", "L-08", "L-09", "L-10", "L-11", "L-12", "L-13", "L-14", "L-15"}


def check_forbidden_phrases(text: str) -> list[dict]:
    """Scan for forbidden phrases. Production-ready rules (L-06+) are FAIL severity
    and block the pipeline; older lexical rules (L-01..L-05) remain warn-only.
    """
    violations = []
    lines = text.splitlines()

    # Multi-line / MULTILINE-flagged rules: scan whole text
    for rule in FORBIDDEN_PHRASES:
        pat = rule["pattern"]
        if pat.flags & re.MULTILINE:
            for m in pat.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                excerpt = lines[line_no - 1].strip() if line_no - 1 < len(lines) else ""
                violations.append({
                    "rule_id": rule["rule_id"],
                    "rule_name": rule["name"],
                    "severity": "fail" if rule["rule_id"] in FAIL_RULE_IDS else "warn",
                    "line": line_no,
                    "matched": m.group(0),
                    "excerpt": excerpt[:160],
                    "fix": rule["fix"],
                })

    # Single-line rules: scan line by line for context
    for idx, line in enumerate(lines, start=1):
        for rule in FORBIDDEN_PHRASES:
            pat = rule["pattern"]
            if pat.flags & re.MULTILINE:
                continue
            for m in pat.finditer(line):
                violations.append({
                    "rule_id": rule["rule_id"],
                    "rule_name": rule["name"],
                    "severity": "fail" if rule["rule_id"] in FAIL_RULE_IDS else "warn",
                    "line": idx,
                    "matched": m.group(0),
                    "excerpt": line.strip()[:160],
                    "fix": rule["fix"],
                })

    # De-dup (same rule + same line + same matched string)
    seen = set()
    unique = []
    for v in violations:
        key = (v["rule_id"], v["line"], v["matched"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(v)
    return unique


# ─────────────────────────────────────────────────────────────────────────────
# Structural checks
# ─────────────────────────────────────────────────────────────────────────────

def check_takeaways_density(text: str) -> list[dict]:
    """S-01: Takeaways section should have ≤9 bullets."""
    violations = []
    lines = text.splitlines()
    sec = _find_section(lines, re.compile(r"^#{2,4}\s*Takeaways\b", re.IGNORECASE))
    if not sec:
        return []  # Section absent — no density check; warn elsewhere if required
    start, end = sec
    bullets = _bullets_in_range(lines, start, end)
    if len(bullets) > 9:
        violations.append({
            "rule_id": "S-01",
            "rule_name": "takeaways_density",
            "severity": "warn",
            "line": start + 1,
            "matched": f"{len(bullets)} bullets in Takeaways",
            "excerpt": f"Takeaways section has {len(bullets)} top-level bullets",
            "fix": "Consolidate to ≤9 bullets. PM scan target = 30s-1min.",
        })
    return violations


def check_kpi_table_format(text: str) -> list[dict]:
    """S-02 / S-03: KPI tables should have y/y growth columns; no z-score column."""
    violations = []
    lines = text.splitlines()
    # Find KPI tables — header row containing | Metric | ... | Cons | ... or similar
    # Exclude dispersion / positioning tables (those have "LOW"/"HIGH"/"Q1 (norm)"/"std"/"CV" cols).
    DISPERSION_INDICATORS = re.compile(
        r"\bLOW\b|\bHIGH\b|\bQ1\s*\(norm\)|\bstd\b|\bCV\b|\bdispersion\b|\bbottom[-\s]quartile\b",
        re.IGNORECASE,
    )
    for idx, line in enumerate(lines):
        is_table_header = (
            line.strip().startswith("|")
            and ("metric" in line.lower() or "your est" in line.lower())
            and "cons" in line.lower()
        )
        if not is_table_header:
            continue
        # Skip dispersion / positioning tables — y/y is N/A there
        if DISPERSION_INDICATORS.search(line):
            # Still check z-score on dispersion tables (banned)
            if re.search(r"z[-\s]?score|σ", line, re.IGNORECASE):
                violations.append({
                    "rule_id": "S-03",
                    "rule_name": "kpi_zscore_column",
                    "severity": "warn",
                    "line": idx + 1,
                    "matched": "z-score column",
                    "excerpt": line.strip()[:200],
                    "fix": "Drop z-score column from KPI / dispersion tables.",
                })
            continue
        # S-03: z-score column
        if re.search(r"z[-\s]?score|σ", line, re.IGNORECASE):
            violations.append({
                "rule_id": "S-03",
                "rule_name": "kpi_zscore_column",
                "severity": "warn",
                "line": idx + 1,
                "matched": "z-score column",
                "excerpt": line.strip()[:200],
                "fix": "Drop z-score column from KPI / dispersion tables.",
            })
        # S-02: y/y column required (look for "y/y" in header)
        if "y/y" not in line.lower() and "yoy" not in line.lower():
            violations.append({
                "rule_id": "S-02",
                "rule_name": "kpi_missing_yy",
                "severity": "warn",
                "line": idx + 1,
                "matched": "no y/y column",
                "excerpt": line.strip()[:200],
                "fix": "Add y/y growth column for revenue/volume rows (KPI gut checks).",
            })
    return violations


def check_decision_table(text: str) -> list[dict]:
    """S-04: Decision table at top should have all 3 rows."""
    violations = []
    required = ["Pre Earnings Decision", "Recommended Position Size", "Earnings Preview Score"]
    found = {r: False for r in required}
    for line in text.splitlines()[:80]:  # only check top of doc
        for r in required:
            if r.lower() in line.lower():
                found[r] = True
    missing = [r for r, v in found.items() if not v]
    if missing:
        violations.append({
            "rule_id": "S-04",
            "rule_name": "decision_table_incomplete",
            "severity": "warn",
            "line": 1,
            "matched": f"missing rows: {', '.join(missing)}",
            "excerpt": "Decision table missing required rows",
            "fix": f"Add rows: {', '.join(missing)} to the decision table at the top.",
        })
    return violations


# ─────────────────────────────────────────────────────────────────────────────
# Formatting checks
# ─────────────────────────────────────────────────────────────────────────────

UNESCAPED_DOLLAR_PAIR_RE = re.compile(
    r"(?<!\\)\$(?!\\)([^\$\n]{1,80}?)(?<!\\)\$(?!\\)"
)

def check_pandoc_dollar_safety(text: str) -> list[dict]:
    """F-01: paired unescaped $...$ outside code spans/table cells trigger pandoc math bug."""
    violations = []
    lines = text.splitlines()
    in_code = False
    for idx, line in enumerate(lines, start=1):
        # Skip code blocks
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        # Find paired $...$ that are not preceded by backslash
        for m in UNESCAPED_DOLLAR_PAIR_RE.finditer(line):
            inner = m.group(1)
            # Heuristic: if inner content looks like a number with thousands separator,
            # it's likely a value — flag as risk
            if re.search(r"\d", inner):
                violations.append({
                    "rule_id": "F-01",
                    "rule_name": "pandoc_dollar_pair",
                    "severity": "fail",
                    "line": idx,
                    "matched": m.group(0),
                    "excerpt": line.strip()[:200],
                    "fix": "Escape dollar signs as \\$ to avoid pandoc TeX-math swallowing rows. Render with --from markdown-tex_math_dollars.",
                })
    return violations


def check_decimal_precision(text: str) -> list[dict]:
    """F-02: $-values to whole or 1dp; %-values to 1dp; bps whole.

    Lightweight check: flag obvious over-precision (e.g., $616.878mm → should be $616.9 or $617).
    """
    violations = []
    lines = text.splitlines()
    # $-values with >=3 decimal places (e.g., $616.878)
    dollar_overpre = re.compile(r"\$\d{1,3}(?:,\d{3})*\.\d{3,}")
    # %-values with >=3 decimal places (e.g., 7.532%)
    pct_overpre = re.compile(r"\b\d+\.\d{3,}\s*%")
    # bps with decimal (e.g., -800.5 bps)
    bps_decimal = re.compile(r"-?\d+\.\d+\s*bps", re.IGNORECASE)
    for idx, line in enumerate(lines, start=1):
        for m in dollar_overpre.finditer(line):
            violations.append({
                "rule_id": "F-02a",
                "rule_name": "dollar_overprecision",
                "severity": "info",
                "line": idx,
                "matched": m.group(0),
                "excerpt": line.strip()[:160],
                "fix": "Round $-values to whole or 1 decimal. Excessive precision reads as false precision.",
            })
        for m in pct_overpre.finditer(line):
            violations.append({
                "rule_id": "F-02b",
                "rule_name": "pct_overprecision",
                "severity": "info",
                "line": idx,
                "matched": m.group(0),
                "excerpt": line.strip()[:160],
                "fix": "Round %-values to 1 decimal place.",
            })
        for m in bps_decimal.finditer(line):
            violations.append({
                "rule_id": "F-02c",
                "rule_name": "bps_decimal",
                "severity": "info",
                "line": idx,
                "matched": m.group(0),
                "excerpt": line.strip()[:160],
                "fix": "Round bps to whole numbers.",
            })
    return violations


SCARE_QUOTE_RE = re.compile(r'["“”]([^"“”]{4,})["“”]')
ATTRIBUTION_VERB_RE = re.compile(
    r"\b(said|stated|disclosed|reported|announced|confirmed|acknowledged|"
    r"per\s+\w+|according\s+to|noted|wrote|told|quoted|writes|highlighted)\b",
    re.IGNORECASE,
)

def check_scare_quotes(text: str) -> list[dict]:
    """F-03: short quoted phrases without attribution = scare quotes (analytical framing).

    Soft warn — analyst may intentionally use scare quotes for emphasis. Only flag short ones
    (≤4 words) without nearby attribution verb.
    """
    violations = []
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        for m in SCARE_QUOTE_RE.finditer(line):
            quoted = m.group(1)
            word_count = len(quoted.split())
            if word_count > 4:
                continue
            # Check 60-char window around for attribution verb
            ctx_start = max(0, m.start() - 60)
            ctx_end = min(len(line), m.end() + 60)
            context = line[ctx_start:ctx_end]
            if ATTRIBUTION_VERB_RE.search(context):
                continue
            violations.append({
                "rule_id": "F-03",
                "rule_name": "scare_quote",
                "severity": "info",
                "line": idx,
                "matched": m.group(0),
                "excerpt": line.strip()[:160],
                "fix": "Drop scare quotes around short colloquial phrases. State the point plainly.",
            })
    return violations


# ─────────────────────────────────────────────────────────────────────────────
# Aggregator
# ─────────────────────────────────────────────────────────────────────────────

def check_takeaways_vs_overview(text: str) -> list[dict]:
    """S-04: Takeaways are the distilled piece and must be SHORTER than the
    Overview (the Overview carries the substance). FAIL if Takeaways body length
    >= Overview body length."""
    violations = []
    lines = text.splitlines()
    tk = _find_section(lines, re.compile(r"^#{2,4}\s*Takeaways\b", re.IGNORECASE))
    ov = _find_section(lines, re.compile(r"^#{2,4}\s*Overview\b", re.IGNORECASE))
    if not tk or not ov:
        return []
    def _body_len(sec):
        s, e = sec
        return sum(len(lines[i]) for i in range(s + 1, e))
    tk_len, ov_len = _body_len(tk), _body_len(ov)
    if ov_len > 0 and tk_len >= ov_len:
        violations.append({
            "rule_id": "S-04",
            "rule_name": "takeaways_longer_than_overview",
            "severity": "fail",
            "line": tk[0] + 1,
            "matched": f"Takeaways {tk_len} chars >= Overview {ov_len} chars",
            "excerpt": "Takeaways section is not shorter than the Overview",
            "fix": "Takeaways are the distilled thesis; the Overview is the meat. Tighten Takeaways and/or deepen the Overview so Takeaways < Overview.",
        })
    return violations


CHECKS = [
    ("forbidden_phrases", check_forbidden_phrases),
    ("takeaways_density", check_takeaways_density),
    ("takeaways_vs_overview", check_takeaways_vs_overview),
    ("kpi_table_format", check_kpi_table_format),
    ("decision_table", check_decision_table),
    ("pandoc_dollar_safety", check_pandoc_dollar_safety),
    ("decimal_precision", check_decimal_precision),
    ("scare_quotes", check_scare_quotes),
]


def lint(markdown_path: str | Path) -> dict:
    p = Path(markdown_path)
    if not p.exists():
        return {
            "status": "error",
            "error": f"file not found: {markdown_path}",
            "violations": [],
            "summary": {},
        }
    text = p.read_text(encoding="utf-8", errors="replace")

    all_violations = []
    by_check = {}
    for name, fn in CHECKS:
        v = fn(text)
        by_check[name] = len(v)
        all_violations.extend(v)

    severity_counts = {"fail": 0, "warn": 0, "info": 0}
    for v in all_violations:
        sev = v.get("severity", "warn")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    total = len(all_violations)
    blocks = severity_counts["fail"] > 0
    status = "blocked" if blocks else ("warn" if severity_counts["warn"] > 0 else "clean")

    return {
        "status": status,
        "blocks_pipeline": blocks,
        "summary": {
            "total_violations": total,
            "by_severity": severity_counts,
            "by_check": by_check,
        },
        "violations": all_violations,
        "input_path": str(p),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _cli() -> int:
    ap = argparse.ArgumentParser(description="Style linter for preview markdown")
    ap.add_argument("--markdown", required=True, help="Path to preview markdown file")
    ap.add_argument("--analyst", default=None, help="Optional analyst id (loads style preferences)")
    ap.add_argument("--json", default=None, help="Optional path to write JSON result")
    ap.add_argument("--quiet", action="store_true", help="Suppress text output; exit code only")
    args = ap.parse_args()

    result = lint(args.markdown)

    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2), encoding="utf-8")

    if not args.quiet:
        print(f"=== style_linter v0.1 ===")
        print(f"Input: {result['input_path']}")
        print(f"Status: {result['status']}  |  Blocks pipeline: {result['blocks_pipeline']}")
        print(f"Total violations: {result['summary']['total_violations']}")
        print(f"By severity: {result['summary']['by_severity']}")
        print(f"By check: {result['summary']['by_check']}")
        if result['violations']:
            print()
            print("--- Violations (first 20) ---")
            for v in result['violations'][:20]:
                print(f"  L{v['line']} [{v['rule_id']}] {v['severity']}: {v['matched']}")
                print(f"    fix: {v['fix']}")

    if result['status'] == 'error':
        return 2
    return 1 if result['blocks_pipeline'] else 0


if __name__ == "__main__":
    sys.exit(_cli())
