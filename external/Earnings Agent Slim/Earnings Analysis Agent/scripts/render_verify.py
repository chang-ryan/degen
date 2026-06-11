"""
render_verify.py — strict per-table row-count comparison between source
markdown and rendered HTML.

Replaces the previous heuristic in `preview_runner.stage_render`:

    if abs(md_total_rows - html_total_rows) > 5:  # tolerance of 5
        BLOCK

The tolerance was arbitrary. Pandoc's `tex_math_dollars` bug can swallow
between zero and many rows depending on which dollar-sign pairs collide
with table boundaries. A tolerance of 5 could pass a draft missing 3
real rows. After this change, every row mismatch is detected.

Public API:
    extract_markdown_tables(text) -> list[Table]
    extract_html_tables(text)     -> list[Table]
    compare_tables(md_tables, html_tables) -> ComparisonResult

A Table is a dict with: index (0-based), header_excerpt (first row text,
truncated for readability), row_count (header + body rows excluding the
separator).

The comparison is intentionally strict: same number of tables AND same
row count per table. False-positives are unlikely because both parsers
operate on cleanly-delimited structures (markdown's `|...|` lines and
HTML's `<table>...</table>` blocks).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict


@dataclass
class Table:
    index: int
    row_count: int        # header + body rows (separator is NOT counted)
    header_excerpt: str   # first row's raw text, truncated to 80 chars

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ComparisonResult:
    ok: bool
    reason: str | None
    md_count: int
    html_count: int
    per_table_diffs: list[dict]  # for each pair: {index, md_rows, html_rows, header}


# ─────────────────────────────────────────────────────────────────────────────
# Markdown table extraction
# ─────────────────────────────────────────────────────────────────────────────

def _is_md_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and len(s) >= 2


def _is_md_separator_row(line: str) -> bool:
    """Recognize `|---|---|...|` separator rows.

    Permissive: any `|`-bracketed line whose interior is composed only of
    dashes, colons, pipes, and whitespace. This handles `:---:` alignment
    syntax and dash-runs of any length.
    """
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        return False
    inner = s[1:-1]
    return bool(inner) and all(c in "-:| \t" for c in inner) and "-" in inner


def extract_markdown_tables(text: str) -> list[Table]:
    """Return one Table per markdown table block in `text`.

    A table block is: a `|...|` header line, then a separator line, then
    zero or more `|...|` body lines, terminated by a non-table line.

    `row_count` excludes the separator (it's a structural marker, not a
    rendered row). It includes the header.
    """
    tables: list[Table] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if not _is_md_table_row(lines[i]):
            i += 1
            continue
        # Candidate header. Must be followed by a separator to count as a table.
        if i + 1 >= len(lines) or not _is_md_separator_row(lines[i + 1]):
            i += 1
            continue
        header_line = lines[i]
        # Walk body rows
        j = i + 2
        body_count = 0
        while j < len(lines) and _is_md_table_row(lines[j]) and not _is_md_separator_row(lines[j]):
            body_count += 1
            j += 1
        tables.append(Table(
            index=len(tables),
            row_count=1 + body_count,  # header + body (exclude separator)
            header_excerpt=header_line.strip()[:80],
        ))
        i = j  # skip past body
    return tables


# ─────────────────────────────────────────────────────────────────────────────
# HTML table extraction
# ─────────────────────────────────────────────────────────────────────────────

# Match a <table>...</table> block (non-greedy, multi-line). Pandoc emits
# well-formed HTML5 with closing tags, so a regex-based match is reliable
# for the structures pandoc produces.
_HTML_TABLE_BLOCK_RE = re.compile(r"<table\b[^>]*>(.*?)</table>", re.IGNORECASE | re.DOTALL)
# Within a table, count opening <tr ...> tags (handles `<tr>` and `<tr class="...">`).
_HTML_TR_OPEN_RE = re.compile(r"<tr\b[^>]*>", re.IGNORECASE)
# First-row excerpt: capture the contents of the first <tr>...</tr> for readability.
_HTML_FIRST_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)


def extract_html_tables(text: str) -> list[Table]:
    """Return one Table per <table>...</table> block in `text`.

    `row_count` is the number of `<tr>` open tags inside the block (which
    is what gets rendered). HTML doesn't have a separator-row construct,
    so this count maps directly to "rows the reader sees."
    """
    tables: list[Table] = []
    for m in _HTML_TABLE_BLOCK_RE.finditer(text):
        block = m.group(1)
        tr_count = len(_HTML_TR_OPEN_RE.findall(block))
        # Pull the first <tr>'s inner text for readability in error messages
        first_row = _HTML_FIRST_ROW_RE.search(block)
        header_excerpt = ""
        if first_row:
            inner = first_row.group(1)
            # Strip HTML tags, collapse whitespace
            stripped = re.sub(r"<[^>]+>", " ", inner)
            stripped = re.sub(r"\s+", " ", stripped).strip()
            header_excerpt = stripped[:80]
        tables.append(Table(
            index=len(tables),
            row_count=tr_count,
            header_excerpt=header_excerpt,
        ))
    return tables


# ─────────────────────────────────────────────────────────────────────────────
# Comparison
# ─────────────────────────────────────────────────────────────────────────────

def compare_tables(md_tables: list[Table], html_tables: list[Table]) -> ComparisonResult:
    """Strict per-table comparison.

    First: counts of tables must match. If not, the entire comparison
    fails — either pandoc dropped a table or merged two, both of which
    are loud failure modes that need human review.

    Then: for each table pair (by index), row_count must match exactly.
    Any mismatch is reported with the offending table identified by
    its header excerpt for diagnosis.
    """
    if len(md_tables) != len(html_tables):
        return ComparisonResult(
            ok=False,
            reason=(
                f"Table count mismatch: markdown has {len(md_tables)} tables, "
                f"HTML has {len(html_tables)}. Pandoc dropped or merged a table."
            ),
            md_count=len(md_tables),
            html_count=len(html_tables),
            per_table_diffs=[],
        )

    diffs: list[dict] = []
    any_mismatch = False
    for md_t, html_t in zip(md_tables, html_tables):
        diff = {
            "index": md_t.index,
            "md_rows": md_t.row_count,
            "html_rows": html_t.row_count,
            "md_header_excerpt": md_t.header_excerpt,
            "html_header_excerpt": html_t.header_excerpt,
            "ok": md_t.row_count == html_t.row_count,
        }
        if not diff["ok"]:
            any_mismatch = True
        diffs.append(diff)

    if any_mismatch:
        bad = [d for d in diffs if not d["ok"]]
        descs = "; ".join(
            f"table[{d['index']}] '{d['md_header_excerpt'][:40]}': "
            f"md={d['md_rows']} vs html={d['html_rows']}"
            for d in bad
        )
        return ComparisonResult(
            ok=False,
            reason=(
                f"{len(bad)} of {len(diffs)} tables have row-count mismatches. "
                f"Likely the pandoc tex_math_dollars bug — unescaped $ in a cell "
                f"swallowed surrounding rows. Details: {descs}"
            ),
            md_count=len(md_tables),
            html_count=len(html_tables),
            per_table_diffs=diffs,
        )

    return ComparisonResult(
        ok=True, reason=None,
        md_count=len(md_tables), html_count=len(html_tables),
        per_table_diffs=diffs,
    )
