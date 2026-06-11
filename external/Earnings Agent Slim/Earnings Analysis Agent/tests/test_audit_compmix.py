"""
Tests for the COMP_WATCH peer-mention flagging mechanism in audit_agent.

audit_agent exposes an optional `COMP_WATCH` set. When populated, any
whole-word mention of a watched symbol in the analysis text is flagged
(severity=warn) for business-mix review. It is EMPTY by default in the
generic build, so no comp flags fire unless a caller opts in.

These tests monkeypatch COMP_WATCH to a generic ticker and verify the
flagging mechanism via run_audit's comp_flags output.
"""
from __future__ import annotations

import pytest

import audit_agent  # resolved via conftest sys.path (Earnings Analysis Agent dir)


def _run(tmp_path, text):
    analysis = tmp_path / "preview.md"
    analysis.write_text(text)
    return audit_agent.run_audit(
        str(analysis),
        manifest_path=None,
        source_paths=[],
        ticker="XYZ",
        agent_id="test",
    )


def test_comp_watch_empty_by_default():
    """The generic build ships COMP_WATCH empty — no opt-in, no flags."""
    assert audit_agent.COMP_WATCH == set()


def test_no_comp_flags_when_watch_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_agent, "COMP_WATCH", set())
    rep = _run(tmp_path, "XYZ trades alongside ABCD in the same space.\n")
    assert rep["comp_flags"] == []
    assert rep["counts"]["comp_flags"] == 0


def test_comp_watch_flags_watched_symbol(tmp_path, monkeypatch):
    """When COMP_WATCH contains a symbol, a whole-word mention is flagged."""
    monkeypatch.setattr(audit_agent, "COMP_WATCH", {"XYZ"})
    rep = _run(tmp_path, "We think XYZ screens cheap into the print.\n")
    assert len(rep["comp_flags"]) == 1
    flag = rep["comp_flags"][0]
    assert "XYZ" in flag["reason"]
    assert flag["line"] == 1
    assert rep["counts"]["comp_flags"] == 1


def test_comp_watch_word_boundary_no_substring_match(tmp_path, monkeypatch):
    """A watched symbol must match on a word boundary, not as a substring."""
    monkeypatch.setattr(audit_agent, "COMP_WATCH", {"MA"})
    rep = _run(tmp_path, "MAJOR macro tailwinds support the setup.\n")
    assert rep["comp_flags"] == []


def test_comp_flags_are_warn_level_not_block(tmp_path, monkeypatch):
    """Comp flags contribute to warn, not fail — they must not BLOCK the gate
    on their own."""
    monkeypatch.setattr(audit_agent, "COMP_WATCH", {"XYZ"})
    rep = _run(tmp_path, "XYZ is the headline name this quarter.\n")
    assert rep["gate"] in ("WARN", "PASS")
    assert rep["gate"] != "BLOCK"
    assert rep["fail_severity_count"] == 0


def test_multiple_watched_symbols_each_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_agent, "COMP_WATCH", {"XYZ", "ABCD"})
    rep = _run(tmp_path, "XYZ leads on growth.\nABCD lags on margin.\n")
    reasons = " ".join(f["reason"] for f in rep["comp_flags"])
    assert "XYZ" in reasons
    assert "ABCD" in reasons
    assert rep["counts"]["comp_flags"] == 2
