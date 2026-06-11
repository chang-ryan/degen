"""
fiscal_period.py — canonical fiscal-period notation + normalizer.

By convention, the canonical fiscal-period form is:

    C{calendar_quarter}Q{yy}    e.g., C1Q26, C2Q26, C3Q25

This module is the single source of truth for parsing and normalizing
fiscal-period strings. It is shared between:

  - the preview runner (initializing the manifest from config.yaml)
  - `audit_agent.py` (D-03-FISCAL: cross-checking the period in the preview
    header against config and manifest)

Why a shared module: avoids logic drift if a third caller adds a normalization
case. The preview-runner method delegates here; the audit-agent check imports
from here. One canonical normalizer, one canonical regex set.

Forms recognized:
    C1Q26      -> C1Q26   (canonical pass-through)
    1Q26       -> C1Q26   (legacy config form)
    1Q2026     -> C1Q26   (4-digit-year variant)
    2026/1F    -> C1Q26   (year-first config form: year first, fiscal-quarter suffix)

Inputs that don't match any of those return (None, reason_string) so callers
can surface a clear error rather than silently dropping the period.
"""
from __future__ import annotations

import re

# Canonical form: C{calendar_q}Q{yy}, e.g., C1Q26.
CANONICAL_PERIOD_RE = re.compile(r"^C[1-4]Q[0-9]{2}$")

# Alternative forms encountered in real ticker configs.
_FORM_1Q26 = re.compile(r"^([1-4])Q([0-9]{2})$")          # 1Q26
_FORM_1Q2026 = re.compile(r"^([1-4])Q20([0-9]{2})$")      # 1Q2026
_FORM_2026_1F = re.compile(r"^20([0-9]{2})/([1-4])F$")    # 2026/1F (year first)


def normalize_fiscal_period(raw: str | None) -> tuple[str | None, str | None]:
    """Return (canonical_period, warning).

    - If raw is already canonical: returns (canonical, None).
    - If we successfully normalized a non-canonical form: returns
      (canonical, "normalized X -> Y (form-name)").
    - If we cannot normalize: returns (None, reason).

    The function is case-insensitive on input but always returns
    canonical (uppercase) form. Whitespace is stripped.
    """
    if not raw or not isinstance(raw, str):
        return None, "fiscal period missing or non-string"
    s = raw.strip().upper()
    if CANONICAL_PERIOD_RE.match(s):
        return s, None
    m = _FORM_1Q26.match(s)
    if m:
        return f"C{m.group(1)}Q{m.group(2)}", (
            f"normalized '{raw}' → 'C{m.group(1)}Q{m.group(2)}' (1Q26 form)"
        )
    m = _FORM_1Q2026.match(s)
    if m:
        return f"C{m.group(1)}Q{m.group(2)}", (
            f"normalized '{raw}' → 'C{m.group(1)}Q{m.group(2)}' (1Q2026 form)"
        )
    m = _FORM_2026_1F.match(s)
    if m:
        return f"C{m.group(2)}Q{m.group(1)}", (
            f"normalized '{raw}' → 'C{m.group(2)}Q{m.group(1)}' (2026/1F form)"
        )
    return None, f"could not normalize '{raw}' to canonical C{{q}}Q{{yy}} form"
