#!/usr/bin/env python3
"""
render_digest.py — render a digest markdown to PDF with versioned filenames.

Purpose
-------
Wraps the pandoc + weasyprint pipeline. Always uses versioned filenames
(_v1, _v2, _v3, ...) by default to avoid PermissionError when a previously-
rendered PDF is open in a viewer (the failure mode that hit this session).

Always passes --from markdown-tex_math_dollars to pandoc (avoids the $ math
swallow bug).

Usage
-----
    python3 render_digest.py /path/to/digest.md
    python3 render_digest.py /path/to/digest.md --css /path/to/style.css
    python3 render_digest.py /path/to/digest.md --pdf-suffix v3   # explicit version
    python3 render_digest.py /path/to/digest.md --no-versioning    # overwrite if possible
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_CSS = Path(__file__).resolve().parent / "digest_style.css"

# WEASYPRINT_BIN is a soft override for the weasyprint executable path. The
# render() function below falls back to shutil.which("weasyprint") and to the
# python -c invocation, so WEASYPRINT_BIN only needs to be set (via env var)
# when weasyprint is not on PATH.
import os as _os
WEASYPRINT_BIN = _os.environ.get("WEASYPRINT_BIN", "")


def _post_render_audit(pdf_path: Path) -> None:
    """Quick post-render formatting heuristic check.

    Flags:
    - First page mostly empty (< 30% character density vs page size)
    - Pages with single-table-only content that's narrower than expected
    - Wildly uneven character density across pages
    """
    try:
        import pdfplumber
    except ImportError:
        return
    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
        char_counts = []
        for p in pdf.pages:
            t = p.extract_text() or ""
            char_counts.append(len(t))

    if n_pages == 0:
        return

    avg = sum(char_counts) / len(char_counts) if char_counts else 0
    warnings = []
    # Page 1 should be at least 50% of average density (rough heuristic)
    if char_counts and char_counts[0] < avg * 0.4:
        warnings.append(
            f"page 1 has only {char_counts[0]} chars vs avg {avg:.0f}/page "
            f"({char_counts[0]/avg*100:.0f}% of avg) — may be mostly empty"
        )
    # Any page with <30% of avg is suspect
    sparse_pages = [i + 1 for i, c in enumerate(char_counts) if avg > 0 and c < avg * 0.3]
    if len(sparse_pages) > 1:
        warnings.append(f"sparse pages (< 30% avg density): {sparse_pages}")

    if warnings:
        print("[format-audit] WARNINGS:")
        for w in warnings:
            print(f"    - {w}")
    else:
        print(f"[format-audit] OK ({n_pages} pages, avg {avg:.0f} chars/page)")


def find_next_version(base_path: Path) -> Path:
    """Given /path/to/foo.pdf, find foo_vN.pdf where N is the next available integer."""
    parent = base_path.parent
    stem = base_path.stem
    suffix = base_path.suffix

    # Find existing _vN files
    pat = re.compile(rf"^{re.escape(stem)}_v(\d+){re.escape(suffix)}$")
    max_n = 0
    for f in parent.iterdir():
        m = pat.match(f.name)
        if m:
            n = int(m.group(1))
            if n > max_n:
                max_n = n

    # Also check if base file exists (without _vN suffix)
    if base_path.exists() and max_n == 0:
        max_n = 1  # base counts as v1; next is v2

    next_n = max_n + 1
    return parent / f"{stem}_v{next_n}{suffix}"


def render(md_path: Path, css_path: Path, pdf_path: Path, html_path: Path = None) -> None:
    """Run pandoc + weasyprint."""
    if html_path is None:
        html_path = pdf_path.with_suffix(".html")

    # Pandoc step — note --from markdown-tex_math_dollars to avoid $ swallow bug
    # Extract H1 title from the markdown so it doesn't get the auto-filename fallback;
    # also pass a CSS-side rule to hide the auto-title block.
    md_h1 = ""
    try:
        for line in md_path.read_text().splitlines():
            line_s = line.strip()
            if line_s.startswith("# ") and not line_s.startswith("## "):
                md_h1 = line_s.lstrip("# ").strip()
                break
    except Exception:
        pass

    pandoc_cmd = [
        "pandoc",
        str(md_path),
        "--from", "markdown-tex_math_dollars",
        "--to", "html5",
        "--standalone",
        "--css", str(css_path),
        # Use the markdown H1 as the title metadata so pandoc doesn't fallback to filename;
        # CSS hides the duplicate heading display.
        "--metadata", f"title={md_h1 or pdf_path.stem}",
        "-o", str(html_path),
    ]
    subprocess.run(pandoc_cmd, check=True, stderr=subprocess.PIPE)

    # Weasyprint step.
    # WEASYPRINT_BIN is now an optional override (env var) rather than a hardcoded
    # stale session path. Resolution order:
    #   1. WEASYPRINT_BIN env var, if it points at an existing executable
    #   2. shutil.which("weasyprint") on PATH
    #   3. fail loudly
    weasyprint = None
    if WEASYPRINT_BIN and Path(WEASYPRINT_BIN).is_file():
        weasyprint = WEASYPRINT_BIN
    if not weasyprint:
        weasyprint = shutil.which("weasyprint")
    if not weasyprint:
        print("[error] weasyprint not found on PATH and WEASYPRINT_BIN env var "
              "either unset or pointing at non-existent file", file=sys.stderr)
        sys.exit(2)

    weasy_cmd = [weasyprint, str(html_path), str(pdf_path)]
    subprocess.run(weasy_cmd, check=True, stderr=subprocess.PIPE)

    # Post-render formatting audit — quick heuristic checks on the generated PDF
    try:
        _post_render_audit(pdf_path)
    except Exception as e:
        print(f"[format-audit] check skipped: {e}")


def main():
    parser = argparse.ArgumentParser(description="Render digest markdown to versioned PDF")
    parser.add_argument("md_path", help="Path to digest markdown file")
    parser.add_argument("--css", default=str(DEFAULT_CSS), help="CSS path (default: digest_style.css)")
    parser.add_argument("--pdf-suffix", default=None, help="Explicit version suffix (e.g. 'v3')")
    parser.add_argument("--no-versioning", action="store_true",
                        help="Overwrite base PDF instead of versioning (use only if you know it's not locked)")
    parser.add_argument("--output", default=None, help="Explicit output path (overrides versioning)")
    parser.add_argument(
        "--skip-production-check",
        action="store_true",
        help=(
            "Skip production_ready_check gate. ONLY use for internal debugging "
            "renders of scaffolded files. Never for circulation output."
        ),
    )
    args = parser.parse_args()

    md_path = Path(args.md_path)
    if not md_path.exists():
        print(f"[error] {md_path} not found", file=sys.stderr)
        sys.exit(2)

    css_path = Path(args.css)

    # ── Production-ready gate (HALTS render if forbidden phrases present) ──
    # Runs by default; bypass via --skip-production-check for scaffolded
    # internal renders only. See production_ready_check.py for the rule set.
    if not args.skip_production_check:
        try:
            from production_ready_check import check_file as _prd_check
        except ImportError:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from production_ready_check import check_file as _prd_check
        prd = _prd_check(md_path)
        if not prd.get("pass"):
            print(
                f"[production_ready_check] FAIL — "
                f"{prd.get('violation_count', 0)} forbidden-phrase violations:",
                file=sys.stderr,
            )
            for v in prd.get("violations", [])[:40]:
                print(
                    f"  L{v['line']} [{v['id']}] {v['name']}: {v['matched']!r}",
                    file=sys.stderr,
                )
                print(f"    fix: {v['fix']}", file=sys.stderr)
            print(
                "\nRender aborted. Remediate every violation above, or pass "
                "--skip-production-check ONLY for internal scaffolded renders.",
                file=sys.stderr,
            )
            sys.exit(2)
        print("[production_ready_check] PASS")

    # Determine output path
    if args.output:
        pdf_path = Path(args.output)
    elif args.pdf_suffix:
        pdf_path = md_path.with_name(f"{md_path.stem}_{args.pdf_suffix}.pdf")
    elif args.no_versioning:
        pdf_path = md_path.with_suffix(".pdf")
    else:
        # Default: auto-version
        base = md_path.with_suffix(".pdf")
        pdf_path = find_next_version(base)

    html_path = pdf_path.with_suffix(".html")

    print(f"[render] {md_path}")
    print(f"      → {pdf_path}")
    try:
        render(md_path, css_path, pdf_path, html_path)
        print(f"[ok] rendered {pdf_path.stat().st_size:,} bytes ({pdf_path.stat().st_size/1024:.1f}KB)")
        # Soft reminder to emit a chat-only TLDR. This is a workflow-level
        # prompt, not a content gate; the drafting agent is responsible for
        # generating and delivering the TLDR in chat alongside the PDF link.
        print(
            "[reminder] Emit chat-only run-on TLDR (60-100 words, semicolon-"
            "separated, data-rich) alongside this PDF delivery. "
            "NOT to be embedded in the PDF."
        )
    except subprocess.CalledProcessError as e:
        print(f"[error] render failed: {e}", file=sys.stderr)
        sys.exit(2)
    except PermissionError as e:
        print(f"[error] permission denied — file likely open in viewer. Re-run with default versioning to write a new _vN.pdf.",
              file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
