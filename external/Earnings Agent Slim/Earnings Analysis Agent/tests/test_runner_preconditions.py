"""
Tests for runner_preconditions.py.

Focus areas:
  1. Trojan removal: no hardcoded company-name cross-ticker contamination.
  2. _company_name_aliases reads config.yaml correctly when present, returns
     empty list when absent or malformed.
  3. _check_uploads_for_pr requires both a PR-keyword AND a ticker/alias match.

These tests use isolated tmp_path fixtures so they don't touch the live
workspace directories.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import runner_preconditions as rp


@pytest.fixture
def isolated_repo(tmp_path, monkeypatch):
    """Build a fake repo layout under tmp_path and rebind module-level paths.

    Layout (single-user workspace):
        tmp_path/
            mnt/                  <- session mnt level
                repo/             <- REPO_ROOT
                    workspace/
                        {TICKER}/
                            config.yaml  (optional, written per-test)
                uploads/          <- REPO_ROOT.parent / "uploads" (live path)

    The function _check_uploads_for_pr also checks the legacy path
    `REPO_ROOT.parent.parent.parent / "uploads"` for back-compat; that
    path doesn't exist in this fixture, so only the corrected path is
    exercised — which is what we want to validate post-fix.
    """
    mnt = tmp_path / "mnt"
    mnt.mkdir()
    repo = mnt / "repo"
    repo.mkdir()
    workspace = repo / "workspace"
    workspace.mkdir()
    uploads = mnt / "uploads"
    uploads.mkdir()

    monkeypatch.setattr(rp, "REPO_ROOT", repo)
    monkeypatch.setattr(rp, "WORKSPACE_BASE", workspace)
    return {"repo": repo, "workspace": workspace, "uploads": uploads}


def _write_config(workspace_root: Path, ticker: str, body: str) -> None:
    # Single-user workspace: config lives at workspace/{TICKER}/config.yaml.
    d = workspace_root / ticker.upper()
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.yaml").write_text(body)


def test_aliases_empty_when_config_missing(isolated_repo):
    aliases = rp._company_name_aliases("user", "ZZZZ")
    assert aliases == []


def test_aliases_empty_when_field_absent(isolated_repo):
    _write_config(isolated_repo["workspace"], "ZZZZ", "ticker: ZZZZ\n")
    assert rp._company_name_aliases("user", "ZZZZ") == []


def test_aliases_lowercased_and_stripped(isolated_repo):
    _write_config(
        isolated_repo["workspace"], "ZZZZ",
        "company_name_aliases:\n  - Acme Corporation\n  - '  acme  '\n  - ACME Inc\n",
    )
    aliases = rp._company_name_aliases("user", "ZZZZ")
    assert aliases == ["acme corporation", "acme", "acme inc"]


def test_aliases_handles_malformed_yaml(isolated_repo):
    _write_config(isolated_repo["workspace"], "ZZZZ", "company_name_aliases: : :\n")
    assert rp._company_name_aliases("user", "ZZZZ") == []


def test_aliases_handles_non_list_field(isolated_repo):
    _write_config(isolated_repo["workspace"], "ZZZZ", "company_name_aliases: not_a_list\n")
    assert rp._company_name_aliases("user", "ZZZZ") == []


# --- Trojan-specific behavior ---

def test_check_uploads_no_company_trojan_for_other_tickers(isolated_repo):
    """Regression: previously, an upload with a hardcoded company name in
    the filename would be accepted as a PR for ANY ticker. After the fix,
    that file must NOT be accepted unless the active ticker's config
    explicitly aliases that company name."""
    upload = isolated_repo["uploads"] / "Acme_press_release_2026Q1.pdf"
    upload.write_text("dummy")
    # No config for XYZ that includes 'acme' as alias → must be False
    result = rp._check_uploads_for_pr("user", "XYZ")
    assert result is False, "Acme-named upload should not match XYZ check"


def test_check_uploads_accepts_alias_match(isolated_repo):
    """When ABCD's config declares 'acme' as an alias, the same upload is
    accepted — because the analyst opted in, not because of a code-level
    Trojan."""
    _write_config(
        isolated_repo["workspace"], "ABCD",
        "company_name_aliases:\n  - Acme\n",
    )
    upload = isolated_repo["uploads"] / "Acme_press_release_2026Q1.pdf"
    upload.write_text("dummy")
    assert rp._check_uploads_for_pr("user", "ABCD") is True


def test_check_uploads_requires_pr_keyword(isolated_repo):
    """Filename must contain a PR-like keyword OR it doesn't match
    regardless of ticker hits."""
    _write_config(isolated_repo["workspace"], "ABCD", "company_name_aliases:\n  - Acme\n")
    upload = isolated_repo["uploads"] / "Acme_random_doc.pdf"
    upload.write_text("dummy")
    # No PR keyword → False
    assert rp._check_uploads_for_pr("user", "ABCD") is False


def test_check_uploads_matches_ticker_directly(isolated_repo):
    """No alias needed when the filename contains the ticker symbol."""
    upload = isolated_repo["uploads"] / "XYZ_earnings_release_2026Q1.pdf"
    upload.write_text("dummy")
    assert rp._check_uploads_for_pr("user", "XYZ") is True


def test_check_uploads_returns_false_when_no_uploads_dir(isolated_repo, monkeypatch):
    # Remove the uploads directory entirely
    import shutil
    shutil.rmtree(isolated_repo["uploads"])
    assert rp._check_uploads_for_pr("user", "XYZ") is False


def test_check_uploads_returns_false_when_no_alias_and_unrelated_ticker(isolated_repo):
    """Coverage of the headline regression: a PR file labeled with a
    company name not declared as an alias for the active ticker must not
    match."""
    upload = isolated_repo["uploads"] / "Acme_press_release_2026.pdf"
    upload.write_text("dummy")
    # ZZZZ has no config and no aliases → should not match a non-ticker name
    assert rp._check_uploads_for_pr("user", "ZZZZ") is False
