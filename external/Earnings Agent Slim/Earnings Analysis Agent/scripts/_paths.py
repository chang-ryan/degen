"""
_paths.py — project-anchored path resolution for the Earnings Analysis Agent.

Every script derives its paths from here instead of hardcoding absolute paths.
The module finds the project root from `__file__` and asserts that the resolved
root contains a known anchor file (PREVIEW_AGENT_SPEC.md). If the anchor isn't
found, `repo_root()` raises loudly rather than returning a wrong directory — a
wrong directory could otherwise cause the runner to write artifacts into the
wrong place silently.

This file lives at: <PROJECT_ROOT>/Earnings Analysis Agent/scripts/_paths.py
So `_THIS.parents[2]` is the project root.

Public helpers:
    repo_root()             — the project root (parent of "Earnings Analysis Agent")
    earnings_agent_dir()    — Path to "Earnings Analysis Agent"
    scripts_dir()           — Path to "Earnings Analysis Agent/scripts"
    audit_agent_script()    — Path to "Earnings Analysis Agent/audit_agent.py"
    reference_base()        — Path to "Earnings Analysis Agent/Reference Files"
    workspace_base()        — Path to "workspace" (single-user, one folder per ticker)
    ticker_dir(ticker)      — Path to "workspace/{TICKER}"

All return absolute, resolved Path objects. Nothing here uses time, random, or
external state — repeated calls return equivalent paths.
"""
from __future__ import annotations

from pathlib import Path

_THIS = Path(__file__).resolve()
_ANCHOR_RELATIVE = Path("Earnings Analysis Agent") / "PREVIEW_AGENT_SPEC.md"


class RepoRootResolutionError(RuntimeError):
    """Raised when the resolved project root does not contain the spec anchor.

    A wrong root would let the runner read/write artifacts in the wrong place
    silently. We fail loudly instead.
    """


def repo_root() -> Path:
    """Return the absolute path to the project root.

    Raises RepoRootResolutionError if the anchor file is not found at the
    derived root. This guards against scenarios where _paths.py has been
    moved or symlinked into a different layout.
    """
    candidate = _THIS.parents[2]
    anchor = candidate / _ANCHOR_RELATIVE
    if not anchor.exists():
        raise RepoRootResolutionError(
            f"Project root resolution failed.\n"
            f"  _paths.py: {_THIS}\n"
            f"  derived project root: {candidate}\n"
            f"  expected anchor: {anchor}\n"
            f"  anchor exists: False\n"
            f"Refusing to return a possibly-wrong root. If the layout has changed, "
            f"update _paths.py to match."
        )
    return candidate


def earnings_agent_dir() -> Path:
    return repo_root() / "Earnings Analysis Agent"


def scripts_dir() -> Path:
    return earnings_agent_dir() / "scripts"


def audit_agent_script() -> Path:
    return earnings_agent_dir() / "audit_agent.py"


def reference_base() -> Path:
    return earnings_agent_dir() / "Reference Files"


def workspace_base() -> Path:
    """Single-user workspace root. One folder per ticker lives directly under it."""
    return repo_root() / "workspace"


def ticker_dir(ticker: str) -> Path:
    """Workspace folder for a given ticker: workspace/{TICKER}."""
    return workspace_base() / ticker.upper()
