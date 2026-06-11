"""
conftest.py — pytest config for Earnings Analysis Agent tests.

Adds the Earnings Analysis Agent directory and its scripts/ subdirectory
to sys.path so test modules can import the modules under test by name
(e.g., `import _paths`, `import runner_preconditions`, `import preview_runner`)
without dealing with the space in the parent directory's name.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_EARNINGS_DIR = _HERE.parent
_SCRIPTS_DIR = _EARNINGS_DIR / "scripts"

# Prepend so test imports beat any conflicting installed package
for p in (str(_SCRIPTS_DIR), str(_EARNINGS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)
