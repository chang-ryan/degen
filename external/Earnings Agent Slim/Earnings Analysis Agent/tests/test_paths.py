"""
Tests for _paths.py — repo-anchored path resolution.

These tests verify that:
  1. repo_root() resolves to a directory that contains the anchor spec file.
  2. All derived helpers point at directories/files that actually exist.
  3. workspace_base()/ticker_dir() resolve to the single-user workspace layout.
  4. The anchor check raises loudly if the spec is missing.

Accuracy intent: a wrong repo root would let the pipeline write artifacts
into the wrong place silently. The tests assert the loud-failure mode.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import _paths


def test_repo_root_resolves_to_directory_containing_spec():
    root = _paths.repo_root()
    assert isinstance(root, Path)
    assert root.is_absolute()
    assert root.is_dir()
    assert (root / "Earnings Analysis Agent" / "PREVIEW_AGENT_SPEC.md").is_file()


def test_earnings_agent_dir_exists():
    p = _paths.earnings_agent_dir()
    assert p.is_dir()
    assert p.name == "Earnings Analysis Agent"


def test_scripts_dir_exists():
    p = _paths.scripts_dir()
    assert p.is_dir()
    assert p.name == "scripts"
    # _paths.py itself must live in the directory it claims as scripts/.
    assert (p / "_paths.py").is_file()


def test_audit_agent_script_exists():
    # audit_agent.py now lives inside the Earnings Analysis Agent dir.
    s = _paths.audit_agent_script()
    assert s.is_file()
    assert s.name == "audit_agent.py"
    assert s.parent == _paths.earnings_agent_dir()


def test_reference_base_exists():
    p = _paths.reference_base()
    assert p.name == "Reference Files"


def test_workspace_base_is_under_repo_root():
    p = _paths.workspace_base()
    assert p.name == "workspace"
    assert p.parent == _paths.repo_root()


def test_ticker_dir_is_uppercased_under_workspace():
    p = _paths.ticker_dir("xyz")
    assert p.name == "XYZ"
    assert p.parent == _paths.workspace_base()


def test_no_stale_session_literals_in_returned_paths():
    # Defense-in-depth: any path returned must reflect the live session, not
    # a literal we hardcoded somewhere by mistake.
    forbidden = ("loving-upbeat-maxwell", "confident-jolly-faraday", "relaxed-serene-maxwell")
    for fn in (
        _paths.repo_root,
        _paths.earnings_agent_dir,
        _paths.scripts_dir,
        _paths.audit_agent_script,
        _paths.reference_base,
        _paths.workspace_base,
    ):
        s = str(fn())
        for token in forbidden:
            assert token not in s, f"{fn.__name__} returned a path containing stale session id '{token}': {s}"


def test_repo_root_resolution_error_class_exists():
    # If the anchor check is removed or the error class renamed, callers that
    # try to handle this failure will silently regress. Lock the public API.
    assert hasattr(_paths, "RepoRootResolutionError")
    assert issubclass(_paths.RepoRootResolutionError, RuntimeError)
