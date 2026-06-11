"""
Tests for PreviewRunner._run_subprocess (P1-2).

Covers:
  - Success path: returncode 0, no log written
  - Non-zero return: log file written, contains command + stdout + stderr
  - Timeout: outcome.timed_out=True, returncode=-1, log file written
  - Timeout differentiation in short_error
  - Per-stage log filenames preserve run_id collision-safety
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

import preview_runner as pr


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "ticker_dir", lambda t: tmp_path / "workspace" / t.upper())
    monkeypatch.setattr(pr, "REFERENCE_BASE", tmp_path / "Reference Files")
    r = pr.PreviewRunner(ticker="XYZ", analyst="user", mode="symbiotic")
    r.outputs_dir.mkdir(parents=True, exist_ok=True)
    return r


def test_run_subprocess_success_no_log(runner):
    # Echoes "ok" to stdout; returncode 0 → no log file.
    outcome = runner._run_subprocess(
        ["python3", "-c", "print('ok')"],
        stage="test_success", timeout=10.0,
    )
    assert outcome.returncode == 0
    assert outcome.stdout.strip() == "ok"
    assert outcome.stderr == ""
    assert outcome.timed_out is False
    assert outcome.log_path is None


def test_run_subprocess_nonzero_writes_log(runner):
    outcome = runner._run_subprocess(
        ["python3", "-c", "import sys; sys.stderr.write('boom\\n'); sys.exit(3)"],
        stage="test_nonzero", timeout=10.0,
    )
    assert outcome.returncode == 3
    assert outcome.timed_out is False
    assert outcome.log_path is not None
    log_text = Path(outcome.log_path).read_text()
    assert "stage: test_nonzero" in log_text
    assert "returncode: 3" in log_text
    assert "boom" in log_text


def test_run_subprocess_timeout(runner):
    """Process sleeps longer than timeout — must be marked timed_out and logged."""
    outcome = runner._run_subprocess(
        ["python3", "-c", "import time; time.sleep(5)"],
        stage="test_timeout", timeout=0.5,
    )
    assert outcome.timed_out is True
    assert outcome.returncode == -1
    assert outcome.log_path is not None
    log_text = Path(outcome.log_path).read_text()
    assert "timed_out: True" in log_text


def test_short_error_distinguishes_timeout_from_nonzero(runner):
    """The text differentiates between timeout and non-zero exit so
    block_reason can be specific about the failure mode."""
    timeout_outcome = pr.SubprocessOutcome(
        returncode=-1, stdout="", stderr="some output",
        timed_out=True, log_path=None,
    )
    nonzero_outcome = pr.SubprocessOutcome(
        returncode=2, stdout="", stderr="some output",
        timed_out=False, log_path=None,
    )
    assert "timed out" in timeout_outcome.short_error()
    assert "returncode=2" in nonzero_outcome.short_error()


def test_log_path_is_under_outputs_subprocess_failures(runner):
    outcome = runner._run_subprocess(
        ["python3", "-c", "import sys; sys.exit(1)"],
        stage="test_loc", timeout=10.0,
    )
    assert outcome.log_path is not None
    log_path = Path(outcome.log_path)
    assert log_path.parent == runner.outputs_dir / "_subprocess_failures"
    assert log_path.name.startswith("test_loc_")
    assert log_path.name.endswith(".log")
    # run_id should be embedded in the log filename for collision safety
    assert runner.run_id in log_path.name


def test_log_includes_full_command(runner):
    outcome = runner._run_subprocess(
        ["python3", "-c", "import sys; sys.exit(7)"],
        stage="test_cmd_log", timeout=10.0,
    )
    log_text = Path(outcome.log_path).read_text()
    assert "command:" in log_text
    assert "import sys; sys.exit(7)" in log_text


def test_success_does_not_create_failures_dir(runner):
    """Lazy directory creation: only on failure should the failures dir
    appear. Successful runs leave outputs/ clean."""
    failures_dir = runner.outputs_dir / "_subprocess_failures"
    assert not failures_dir.exists()
    runner._run_subprocess(
        ["python3", "-c", "print('hello')"],
        stage="test_clean", timeout=10.0,
    )
    assert not failures_dir.exists()
