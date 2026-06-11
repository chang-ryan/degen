"""
Tests for render_verify — strict per-table row-count comparison.

The check replaces a heuristic (`abs(md - html) > 5`) with
table-by-table structured comparison. Tests cover:
  - Markdown table extraction (single, multiple, with/without separator)
  - HTML table extraction (clean pandoc output)
  - Comparison: count mismatch, row-count mismatch, exact match
  - The pandoc tex_math_dollars failure mode (rows swallowed)
"""
from __future__ import annotations

import pytest

from render_verify import (
    Table, ComparisonResult,
    extract_markdown_tables, extract_html_tables, compare_tables,
)


# ─── markdown extraction ────────────────────────────────────────────────

def test_extract_md_single_table():
    md = """
| Metric | Variant | Cons |
|---|---|---|
| Revenue | $1,000mm | $988mm |
| EPS | $1.50 | $1.45 |
"""
    tables = extract_markdown_tables(md)
    assert len(tables) == 1
    assert tables[0].row_count == 3   # header + 2 body rows
    assert "Metric" in tables[0].header_excerpt


def test_extract_md_separator_excluded_from_count():
    md = """
| A | B |
|---|---|
| 1 | 2 |
"""
    tables = extract_markdown_tables(md)
    assert tables[0].row_count == 2  # header + 1 body, NOT 3


def test_extract_md_multiple_tables():
    md = """
| A | B |
|---|---|
| 1 | 2 |

prose

| C | D | E |
|---|---|---|
| 3 | 4 | 5 |
| 6 | 7 | 8 |
"""
    tables = extract_markdown_tables(md)
    assert len(tables) == 2
    assert tables[0].row_count == 2
    assert tables[1].row_count == 3


def test_extract_md_pseudo_table_without_separator_ignored():
    """A `|...|` line not followed by a separator isn't a real table."""
    md = """
| not a table line |

# Header

prose with | pipes | not actually a table.
"""
    tables = extract_markdown_tables(md)
    assert tables == []


def test_extract_md_handles_alignment_separator():
    """Markdown supports `:---:`, `:---`, `---:` alignment syntax."""
    md = """
| A | B | C |
|:---|---:|:---:|
| 1 | 2 | 3 |
"""
    tables = extract_markdown_tables(md)
    assert len(tables) == 1
    assert tables[0].row_count == 2


def test_extract_md_separator_must_have_dashes():
    """A `|...|` with only spaces between pipes is NOT a separator."""
    md = """
| A | B |
|   |   |
| 1 | 2 |
"""
    tables = extract_markdown_tables(md)
    # No table — the second line isn't a real separator
    assert tables == []


# ─── html extraction ────────────────────────────────────────────────────

def test_extract_html_single_table():
    html = """
<p>Prose</p>
<table>
<thead><tr><th>A</th><th>B</th></tr></thead>
<tbody>
<tr><td>1</td><td>2</td></tr>
<tr><td>3</td><td>4</td></tr>
</tbody>
</table>
"""
    tables = extract_html_tables(html)
    assert len(tables) == 1
    assert tables[0].row_count == 3   # one header row + 2 body rows


def test_extract_html_two_tables():
    html = """
<table><tr><th>A</th></tr><tr><td>1</td></tr></table>
<table><tr><th>B</th></tr><tr><td>2</td></tr><tr><td>3</td></tr></table>
"""
    tables = extract_html_tables(html)
    assert len(tables) == 2
    assert tables[0].row_count == 2
    assert tables[1].row_count == 3


def test_extract_html_with_attributes_on_tr():
    html = """
<table>
<tr class="header"><th>A</th></tr>
<tr id="row1"><td>1</td></tr>
<tr style="background: #eee;"><td>2</td></tr>
</table>
"""
    tables = extract_html_tables(html)
    assert tables[0].row_count == 3


# ─── comparison ─────────────────────────────────────────────────────────

def test_compare_exact_match():
    md = "| A |\n|---|\n| 1 |\n"
    html = "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"
    md_tables = extract_markdown_tables(md)
    html_tables = extract_html_tables(html)
    result = compare_tables(md_tables, html_tables)
    assert result.ok is True
    assert result.reason is None
    assert result.md_count == 1
    assert result.html_count == 1
    assert result.per_table_diffs[0]["ok"] is True


def test_compare_table_count_mismatch():
    """If pandoc drops a table entirely, we must catch it."""
    md = """
| A |
|---|
| 1 |

| B |
|---|
| 2 |
"""
    # HTML only has one table — pandoc dropped the second
    html = "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"
    md_tables = extract_markdown_tables(md)
    html_tables = extract_html_tables(html)
    result = compare_tables(md_tables, html_tables)
    assert result.ok is False
    assert "count mismatch" in result.reason.lower()
    assert "2 tables" in result.reason and "1" in result.reason


def test_compare_row_count_mismatch_in_one_table():
    """The pandoc tex_math_dollars failure mode: one table loses rows."""
    md = """
| Metric | Value |
|---|---|
| Rev   | $1,000mm |
| EPS   | $1.50 |
| FCF   | $200mm |
"""
    # HTML missing 2 rows (simulating $ math swallowing)
    html = "<table><tr><th>Metric</th><th>Value</th></tr><tr><td>Rev</td><td>$1,000mm</td></tr></table>"
    md_tables = extract_markdown_tables(md)
    html_tables = extract_html_tables(html)
    result = compare_tables(md_tables, html_tables)
    assert result.ok is False
    assert "row-count mismatch" in result.reason.lower()
    assert "tex_math_dollars" in result.reason
    assert "md=4" in result.reason and "html=2" in result.reason


def test_compare_within_one_row_tolerance_now_strict():
    """Pre-fix code had 5-row tolerance; new code requires exact match.
    A 1-row mismatch must now fail."""
    md = "| A |\n|---|\n| 1 |\n| 2 |\n"  # 3 rows (header + 2)
    html = "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"  # 2 rows
    result = compare_tables(extract_markdown_tables(md), extract_html_tables(html))
    assert result.ok is False
    assert "1 of 1" in result.reason


def test_compare_empty_inputs_ok():
    """A document with no tables on either side is valid."""
    result = compare_tables([], [])
    assert result.ok is True
    assert result.md_count == 0
    assert result.html_count == 0


def test_compare_multi_table_one_bad():
    md = """
| A |
|---|
| 1 |

| B |
|---|
| 2 |
| 3 |
| 4 |
"""
    # Second table loses 1 row
    html = """
<table><tr><th>A</th></tr><tr><td>1</td></tr></table>
<table><tr><th>B</th></tr><tr><td>2</td></tr><tr><td>3</td></tr></table>
"""
    result = compare_tables(extract_markdown_tables(md), extract_html_tables(html))
    assert result.ok is False
    # First table is fine; second has md=4 vs html=3
    bad = [d for d in result.per_table_diffs if not d["ok"]]
    assert len(bad) == 1
    assert bad[0]["index"] == 1
    assert bad[0]["md_rows"] == 4
    assert bad[0]["html_rows"] == 3
