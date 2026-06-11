"""
preview_runner.py — Earnings Preview orchestrator

Single entry point for the preview workflow. Takes a ticker + mode and walks
through every stage with hard-gate halts at each transition. This is glue
code — the heavy lifting happens in the existing components:

  - AUTO-DISCOVER         → file system inventory
  - DEEP READ             → Reference Files + sell-side synth + SEC filings (EDGAR)
  - BUILD STORY_DOSSIER   → synthesizer that gates drafting
  - PRE-DRAFT GATE        → optional pre-draft questions (interactive)
  - PULL INPUTS           → your decision/score/variant (optional)
  - DRAFT PREVIEW         → from dossier + your inputs
  - SELF-LINT             → style_linter.py
  - AUDIT                 → audit_agent.py (block_on_fail_severity=True)
  - CONS-CONTEXT CHECK    → cons_context_check.py (your variant z-score / staleness)
  - RENDER                → pandoc + weasyprint, with row-count verification
  - DELIVER               → final PDF path

Architecture note: this is a HYBRID — pure Python where possible (file system
checks, lints, audits, render), and agent-dispatch where LLM extraction is
needed (sell-side synth, draft generation).

Usage:

  python preview_runner.py --ticker XYZ --mode symbiotic --stage AUTO_DISCOVER

Or programmatic:

  from preview_runner import PreviewRunner
  runner = PreviewRunner(ticker='XYZ', mode='symbiotic')
  status = runner.run_stage('AUTO_DISCOVER')
  if status.status == 'PASS':
      runner.run_stage('DEEP_READ')
  ...

Each stage returns a `StageResult` with:
  - status: PASS / BLOCK / NEEDS_INPUT
  - artifacts: list of files produced
  - next_stage: what to run next
  - block_reason: if BLOCK, why
  - dispatch_instructions: if needs agent dispatch, the prompts to send

The CALLING AGENT is responsible for dispatching agents when
`dispatch_instructions` is non-empty, and asking you when
`status == NEEDS_INPUT`.
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

# P1-5: structured logging. Module logger is silent by default (library use).
# The CLI entry point installs a basicConfig so direct invocations show logs.
_log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Path configuration
# ─────────────────────────────────────────────────────────────────────────────
#
# Paths are derived from _paths.py (project-anchored) instead of being
# hardcoded. _paths.repo_root() asserts the resolved root contains
# PREVIEW_AGENT_SPEC.md and raises loudly if not, so a misconfigured layout
# fails fast instead of writing artifacts to the wrong place.

import re

from _paths import (
    repo_root,
    scripts_dir,
    reference_base,
    ticker_dir,
    audit_agent_script,
)
from data_manifest import init_manifest
from fiscal_period import normalize_fiscal_period
import provenance as _prov

PROJECT_ROOT = repo_root()
SCRIPTS_DIR = scripts_dir()
REFERENCE_BASE = reference_base()
AUDIT_AGENT = audit_agent_script()


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StageResult:
    stage: str
    status: str  # PASS | BLOCK | NEEDS_INPUT
    artifacts: list[str] = field(default_factory=list)
    next_stage: str | None = None
    block_reason: str | None = None
    dispatch_instructions: list[dict] = field(default_factory=list)
    questions_for_analyst: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class SubprocessOutcome:
    """Structured result from `_run_subprocess`. Captures both happy-path
    (returncode + stdout/stderr) and failure modes (timeout flag + on-disk
    log path). Lets callers distinguish timeout from non-zero return when
    constructing block_reason — the original code conflated both into a
    generic error message that was hard to diagnose."""
    returncode: int          # -1 if timed_out
    stdout: str
    stderr: str
    timed_out: bool
    log_path: str | None     # set if outcome was logged to disk

    def short_error(self, max_chars: int = 300) -> str:
        if self.timed_out:
            return f"timed out after subprocess timeout (no return). stderr tail: {self.stderr[-max_chars:]}"
        return f"returncode={self.returncode}. stderr tail: {self.stderr[-max_chars:]}"


STAGES = [
    "AUTO_DISCOVER",
    "AUTO_GENERATE_CONFIG",  # synthesize a draft config.yaml for new tickers
    "DEEP_READ",
    "BUILD_DOSSIER",
    "ANALYST_GATE",
    "PULL_ANALYST_INPUTS",
    "PULL_DATA",
    "DRAFT",
    "SELF_LINT",
    "AUDIT",
    "CONS_CONTEXT_CHECK",
    "RENDER",
    "DELIVER",
]


# ─────────────────────────────────────────────────────────────────────────────
# PreviewRunner — main orchestrator class
# ─────────────────────────────────────────────────────────────────────────────

class PreviewRunner:
    def __init__(self, ticker: str, analyst: str = "user", mode: str = "symbiotic"):
        self.ticker = ticker.upper()
        self.analyst = analyst
        self.mode = mode  # symbiotic | standalone

        # Path scaffolding — single-user workspace, one folder per ticker.
        self.ticker_dir = ticker_dir(self.ticker)
        self.outputs_dir = self.ticker_dir / "outputs"
        self.synthesis_dir = self.ticker_dir / "synthesis"
        self.filings_dir = self.ticker_dir / "filings"
        self.alt_data_dir = self.ticker_dir / "alt_data"
        self.positioning_dir = self.ticker_dir / "positioning"
        self.data_dir = self.ticker_dir / "data"
        self.dossier_path = self.ticker_dir / "STORY_DOSSIER.md"
        self.config_path = self.ticker_dir / "config.yaml"
        self.manifest_path = self.data_dir / "data_manifest.json"

        # Derive the canonical fiscal period from config.yaml. The derived
        # period drives the output filename; if config doesn't provide a
        # parseable period, filenames degrade to UNKNOWN_PREVIEW.md and
        # downstream audit/render gates BLOCK — by design, since a preview
        # without a verified period is unsafe.
        self._fiscal_period_resolution = self._resolve_fiscal_period()
        period_label = self._fiscal_period_resolution["canonical"] or "UNKNOWN"
        self.preview_path = self.outputs_dir / f"{period_label}_PREVIEW.md"
        self.preview_pdf = self.outputs_dir / f"{period_label}_PREVIEW.pdf"

        # Source material for the ticker lives under Reference Files/<TICKER>.
        self.reference_dir = REFERENCE_BASE / self.ticker
        self.reference_subdirs = [
            "sell_side_notes", "press_releases", "ir_decks", "models", "transcripts",
        ]

        # Run metadata
        self.run_id = f"{self.ticker}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        # P1-6: per-run provenance accumulator. Each run_stage call appends
        # its outcome and artifacts. write_provenance() flushes to disk.
        # Provenance is best-effort — failures inside provenance helpers
        # never propagate, they accumulate in record["_record_errors"].
        self._provenance = _prov.make_record(
            ticker=self.ticker, analyst=self.analyst, mode=self.mode,
            run_id=self.run_id,
        )

    # ─────────────────────────────────────────────────────────────────────
    # Helpers — provenance accumulator (P1-6)
    # ─────────────────────────────────────────────────────────────────────

    def _record_stage_in_provenance(self, result: "StageResult") -> None:
        """Append a stage's outcome + its artifacts to the provenance record."""
        try:
            _prov.add_stage_outcome(self._provenance, asdict(result))
            for a in result.artifacts or []:
                _prov.add_artifact(self._provenance, a)
        except Exception:
            # Defensive — provenance must never break the pipeline.
            # We log at WARNING so the operator knows provenance is degraded
            # without failing the pipeline.
            _log.warning("provenance recording failed for stage %s", result.stage, exc_info=True)

    def write_provenance(self, output_path: str | Path | None = None) -> Path:
        """Flush the provenance record to disk and finalize metadata.

        If `output_path` is None, default is
        `outputs/_provenance_{run_id}.json`. The record's audit_score /
        gate / manifest_sha256 fields are populated from the most recent
        AUDIT stage and the manifest at self.manifest_path, when available.
        """
        if output_path is None:
            self.outputs_dir.mkdir(parents=True, exist_ok=True)
            output_path = self.outputs_dir / f"_provenance_{self.run_id}.json"
        # Pull audit metadata from the last AUDIT stage if present
        audit_score = None
        gate = None
        fail_count = None
        for s in reversed(self._provenance.get("stages", [])):
            if s.get("stage") == "AUDIT":
                # Score isn't in the stage outcome by default; we read it
                # from the audit JSON file if it exists
                audit_json = self.outputs_dir / "_audit.json"
                if audit_json.is_file():
                    try:
                        with open(audit_json) as f:
                            data = json.load(f)
                        audit_score = data.get("score")
                        gate = data.get("gate")
                        fail_count = data.get("fail_severity_count")
                    except (OSError, json.JSONDecodeError):
                        pass
                break
        _prov.finalize(
            self._provenance,
            audit_score=audit_score, gate=gate,
            fail_severity_count=fail_count,
            manifest_path=self.manifest_path if self.manifest_path.exists() else None,
        )
        return _prov.write(self._provenance, output_path)

    # ─────────────────────────────────────────────────────────────────────
    # Helpers — subprocess wrapper (P1-2)
    # ─────────────────────────────────────────────────────────────────────

    def _run_subprocess(self, cmd: list[str], *, stage: str, timeout: float) -> SubprocessOutcome:
        """Run a subprocess and capture stdout/stderr.

        On timeout or non-zero return code, writes the full command,
        stdout, and stderr to:

            outputs/_subprocess_failures/{stage}_{run_id}.log

        and sets `outcome.log_path` to that file. Distinguishes timeout
        (`outcome.timed_out=True`, returncode=-1) from non-zero return
        (returncode != 0, timed_out=False).

        Why this exists: the previous code used `timeout=60` uniformly and
        on failure surfaced only `stderr[:500]` in `block_reason`. The
        operator had no record of the full output, no distinction between
        timeout and exit-with-error, and no per-stage timeout tuning. The
        wrapper preserves all output to disk for diagnosis and lets each
        call site set its own appropriate timeout.
        """
        try:
            cp = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
            )
            outcome = SubprocessOutcome(
                returncode=cp.returncode,
                stdout=cp.stdout or "",
                stderr=cp.stderr or "",
                timed_out=False,
                log_path=None,
            )
        except subprocess.TimeoutExpired as e:
            stdout_data = e.stdout if isinstance(e.stdout, (bytes, bytearray)) else (e.stdout or b"")
            stderr_data = e.stderr if isinstance(e.stderr, (bytes, bytearray)) else (e.stderr or b"")
            if isinstance(stdout_data, (bytes, bytearray)):
                stdout_str = stdout_data.decode("utf-8", errors="replace")
            else:
                stdout_str = str(stdout_data)
            if isinstance(stderr_data, (bytes, bytearray)):
                stderr_str = stderr_data.decode("utf-8", errors="replace")
            else:
                stderr_str = str(stderr_data)
            outcome = SubprocessOutcome(
                returncode=-1,
                stdout=stdout_str,
                stderr=stderr_str,
                timed_out=True,
                log_path=None,
            )

        if outcome.returncode != 0 or outcome.timed_out:
            log_dir = self.outputs_dir / "_subprocess_failures"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / f"{stage}_{self.run_id}.log"
            log_path.write_text(
                f"command: {' '.join(cmd)}\n"
                f"stage: {stage}\n"
                f"timeout_sec: {timeout}\n"
                f"timed_out: {outcome.timed_out}\n"
                f"returncode: {outcome.returncode}\n"
                f"\n=== STDOUT ===\n{outcome.stdout}\n"
                f"\n=== STDERR ===\n{outcome.stderr}\n",
                encoding="utf-8",
            )
            outcome.log_path = str(log_path)

        return outcome

    # ─────────────────────────────────────────────────────────────────────
    # Helpers — fiscal-period extraction
    # ─────────────────────────────────────────────────────────────────────

    def _normalize_fiscal_period(self, raw: str | None) -> tuple[str | None, str | None]:
        """Delegate to scripts/fiscal_period.normalize_fiscal_period.

        The shared module is the single source of truth for fiscal-period
        normalization, used here AND by audit_agent.py's D-03-FISCAL check.
        Logic drift would let preview header and audit gate disagree on
        what counts as canonical — exactly the failure mode D-03 exists
        to catch.
        """
        return normalize_fiscal_period(raw)

    def _read_fiscal_period_from_config(self) -> tuple[str | None, str | None]:
        """Probe config.yaml for any of several fiscal-period field names.

        Returns (canonical_period, warning_or_error). Returns (None, reason)
        when config is absent, malformed, or doesn't declare a period.
        """
        if not self.config_path.exists():
            return None, f"config.yaml not found at {self.config_path}"
        try:
            import yaml  # type: ignore
        except ImportError:
            return None, "PyYAML not installed; cannot read config.yaml"
        try:
            cfg = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            return None, f"config.yaml parse error: {e}"
        candidates = ("fiscal_period_in_focus", "fiscal_period", "quarter")
        for key in candidates:
            if key in cfg and cfg[key]:
                canonical, warn = self._normalize_fiscal_period(str(cfg[key]))
                if canonical:
                    return canonical, warn  # may be None or a normalization note
                return None, f"config.{key} = {cfg[key]!r}: {warn}"
        return None, f"no fiscal period declared in config (looked for: {candidates})"

    def _resolve_fiscal_period(self) -> dict:
        """Derive the canonical fiscal period for this run from config.yaml.

        Returns a dict capturing the source, the chosen canonical period, and
        any warning — exposed in stage_auto_discover.metadata so you can
        inspect what the runner derived without reading the audit JSON.

        If config doesn't declare a parseable period, canonical=None and
        downstream audit/render gates BLOCK — by design, since a preview
        without a verified period is unsafe.
        """
        config_period, config_warn = self._read_fiscal_period_from_config()
        return {
            "canonical": config_period,
            "config_period": config_period,
            "config_warning": config_warn,
            "source_of_truth": "config" if config_period else "none",
            "discrepancy": False,
        }

    # ─────────────────────────────────────────────────────────────────────
    # STAGE 1: AUTO_DISCOVER
    # ─────────────────────────────────────────────────────────────────────

    def stage_auto_discover(self) -> StageResult:
        """Inventory the workspace + surface the derived fiscal period."""
        result = StageResult(stage="AUTO_DISCOVER", status="PASS", next_stage="AUTO_GENERATE_CONFIG")

        # Create workspace dirs if missing (data_dir holds the manifest)
        for d in [self.ticker_dir, self.outputs_dir, self.synthesis_dir,
                  self.filings_dir, self.alt_data_dir, self.positioning_dir,
                  self.data_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Surface the fiscal-period resolution so you can see what the runner
        # derived from config.yaml.
        self._fiscal_period_resolution = self._resolve_fiscal_period()
        result.metadata["fiscal_period_resolution"] = self._fiscal_period_resolution
        # If the resolution changed since __init__ (i.e., config.yaml was
        # written in between), update the preview filename targets so
        # downstream stages target the right files.
        new_label = self._fiscal_period_resolution["canonical"] or "UNKNOWN"
        new_md = self.outputs_dir / f"{new_label}_PREVIEW.md"
        if new_md != self.preview_path:
            _log.info("preview filename target updated to %s after fiscal-period resolution refresh", new_md)
            self.preview_path = new_md
            self.preview_pdf = self.outputs_dir / f"{new_label}_PREVIEW.pdf"

        # Inventory Reference Files
        ref_inventory = {}
        if self.reference_dir.exists():
            for sub in self.reference_subdirs:
                sub_path = self.reference_dir / sub
                if sub_path.exists():
                    ref_inventory[sub] = sorted([f.name for f in sub_path.iterdir() if f.is_file()])
                else:
                    ref_inventory[sub] = []
            # notes.* at root
            ref_inventory["notes"] = sorted([f.name for f in self.reference_dir.iterdir()
                                             if f.is_file() and f.name.startswith("notes.")])
        result.metadata["reference_inventory"] = ref_inventory
        return result

    # ─────────────────────────────────────────────────────────────────────
    # STAGE 1.5: AUTO_GENERATE_CONFIG (P0-2b round 2)
    # ─────────────────────────────────────────────────────────────────────

    def stage_auto_generate_config(self) -> StageResult:
        """Synthesize a draft config.yaml for tickers without one.

        Three branches:
          1. Config already exists → PASS, skip.
          2. Config missing AND a SEC business description is on disk (pulled
             by edgar_fetch.py into filings/latest_10K_business.txt) →
             generate via standalone_config_gen.generate_config_from_disk,
             write to ticker_dir/config.yaml, PASS.
          3. Config missing AND no business text → NEEDS_INPUT, instructing
             you to run edgar_fetch.py (or author config.yaml manually).

        The generated config carries `_auto_generated: true` and
        `_reviewed: false`. Audit gate D-06-CONFIG-REVIEWED emits
        severity=warn until you review.

        IMPORTANT: this stage NEVER overwrites an existing config.
        """
        result = StageResult(
            stage="AUTO_GENERATE_CONFIG", status="PASS", next_stage="DEEP_READ",
        )

        if self.config_path.exists():
            result.metadata["skipped"] = (
                f"config.yaml already exists at {self.config_path}; "
                f"AUTO_GENERATE_CONFIG never overwrites — you own the file once created."
            )
            return result

        # The generator needs the SEC 10-K business description as its seed.
        # edgar_fetch.py writes it to filings/latest_10K_business.txt.
        business_text_path = self.filings_dir / "latest_10K_business.txt"
        have_business = business_text_path.exists() and business_text_path.stat().st_size > 200

        if not have_business:
            result.status = "NEEDS_INPUT"
            result.next_stage = None
            result.dispatch_instructions = [{
                "type": "auto_generate_config_inputs",
                "ticker": self.ticker,
                "output_dir": str(self.filings_dir),
                "missing": [str(business_text_path)],
                "instruction": (
                    f"Run `python scripts/edgar_fetch.py --ticker {self.ticker}` to pull "
                    f"the latest 10-K business description (free SEC EDGAR), then re-run "
                    f"AUTO_GENERATE_CONFIG. Alternatively, author config.yaml manually."
                ),
            }]
            return result

        # Inputs present — synthesize. Defensive import (not at module top
        # because standalone_config_gen depends on _paths and yaml; failures
        # should be caught here rather than crashing the orchestrator at
        # import time).
        try:
            from standalone_config_gen import generate_config_from_disk, _serialize_to_yaml
            config, summary = generate_config_from_disk(
                self.ticker, ticker_dir_override=self.ticker_dir,
            )
            yaml_text = _serialize_to_yaml(config)
        except Exception as e:
            result.status = "BLOCK"
            result.next_stage = None
            result.block_reason = (
                f"standalone_config_gen.generate_config_from_disk failed: {e}. "
                f"Fall back to manually authoring config.yaml."
            )
            return result

        # Write the config. Refuses if the file appeared between the existence
        # check above and now (race-free; we'd rather BLOCK than overwrite).
        if self.config_path.exists():
            result.status = "BLOCK"
            result.next_stage = None
            result.block_reason = (
                f"config.yaml appeared at {self.config_path} during AUTO_GENERATE_CONFIG. "
                f"Refusing to overwrite. Re-run the stage (it will detect the existing config and PASS-skip)."
            )
            return result
        self.config_path.write_text(yaml_text, encoding="utf-8")

        # Re-resolve fiscal period now that config exists
        self._fiscal_period_resolution = self._resolve_fiscal_period()
        new_label = self._fiscal_period_resolution["canonical"] or "UNKNOWN"
        new_md = self.outputs_dir / f"{new_label}_PREVIEW.md"
        if new_md != self.preview_path:
            self.preview_path = new_md
            self.preview_pdf = self.outputs_dir / f"{new_label}_PREVIEW.pdf"

        result.metadata["generated_config_path"] = str(self.config_path)
        result.metadata["generation_summary"] = summary
        result.metadata["review_required"] = (
            f"config.yaml at {self.config_path} is auto-generated. Review and set "
            f"`_analyst_reviewed: true` once the values match expectations. "
            f"Audit gate D-06-CONFIG-REVIEWED will emit severity=warn until then."
        )
        result.artifacts.append(str(self.config_path))
        return result

    # ─────────────────────────────────────────────────────────────────────
    # STAGE 2: DEEP_READ
    # ─────────────────────────────────────────────────────────────────────

    def stage_deep_read(self) -> StageResult:
        """Force-read Reference Files + dispatch sell-side synth + pull primary sources + load memory.

        Auto-PASS if dossier exists with content AND (sell-side synth produced OR no sell-side
        notes to synthesize). The agent has already done the work in a prior session.
        """
        result = StageResult(stage="DEEP_READ", status="NEEDS_INPUT", next_stage="BUILD_DOSSIER")

        # Auto-PASS check: substantive dossier exists. The dossier is canonical proof of
        # deep-read completion — if it's >2000 chars and built from primary sources, the
        # agent has already absorbed the reference materials.
        if self.dossier_path.exists() and self.dossier_path.stat().st_size > 2000:
            result.status = "PASS"
            result.metadata["auto_pass"] = (
                f"Dossier exists ({self.dossier_path.stat().st_size} bytes) — "
                f"canonical proof of deep-read completion"
            )
            result.artifacts.append(str(self.dossier_path))
            sell_side_synth = self.ticker_dir / "sell_side_synthesis.md"
            if sell_side_synth.exists():
                result.artifacts.append(str(sell_side_synth))
                result.metadata["sell_side_synth_present"] = True
            else:
                result.metadata["sell_side_synth_present"] = False
                result.metadata["note"] = "Sell-side synth not produced; dossier built from manual reads of PDFs"
            return result

        # 1. Reference Files — calling agent must read each end-to-end
        ref_files_to_read = []
        if self.reference_dir.exists():
            for sub in self.reference_subdirs:
                sub_path = self.reference_dir / sub
                if sub_path.exists():
                    for f in sorted(sub_path.iterdir()):
                        if f.is_file():
                            ref_files_to_read.append(str(f))
            for f in sorted(self.reference_dir.iterdir()):
                if f.is_file() and f.name.startswith("notes."):
                    ref_files_to_read.append(str(f))

        # 2. Sell-side synthesizer plan (optional — only if you have broker PDFs)
        sell_side_plan_path = self.synthesis_dir / "_dispatch_plan.json"
        ss_outcome = self._run_subprocess(
            [sys.executable, str(SCRIPTS_DIR / "sell_side_synthesizer.py"),
             "--ticker", self.ticker, "--phase", "plan",
             "--out", str(sell_side_plan_path)],
            stage="deep_read_sell_side_plan", timeout=60.0,
        )
        if ss_outcome.returncode != 0 or ss_outcome.timed_out:
            result.metadata["sell_side_plan_error"] = ss_outcome.short_error()
            if ss_outcome.log_path:
                result.metadata["sell_side_plan_log"] = ss_outcome.log_path
        else:
            result.metadata["sell_side_plan_path"] = str(sell_side_plan_path)

        # 3. Pull SEC filings from EDGAR (free) into filings/
        ps_outcome = self._run_subprocess(
            [sys.executable, str(SCRIPTS_DIR / "primary_source_puller.py"),
             "--ticker", self.ticker, "--mode", "pull"],
            stage="deep_read_edgar_pull", timeout=180.0,
        )
        if ps_outcome.returncode != 0 or ps_outcome.timed_out:
            result.metadata["edgar_pull_error"] = ps_outcome.short_error()
            if ps_outcome.log_path:
                result.metadata["edgar_pull_log"] = ps_outcome.log_path
        else:
            result.metadata["filings_dir"] = str(self.filings_dir)

        # Dispatch instructions for the calling agent
        result.dispatch_instructions = [
            {
                "type": "read_reference_files",
                "files": ref_files_to_read,
                "instruction": "Read every file end-to-end. Extract bear/bull components, mgmt commentary, partnership timing, accounting nuances.",
            },
            {
                "type": "dispatch_sell_side_synthesis",
                "plan_path": str(sell_side_plan_path),
                "instruction": "If you have broker PDFs: for each task in the plan, dispatch a general-purpose agent in parallel to extract structured JSON. Then run sell_side_synthesizer.py --phase aggregate.",
            },
            {
                "type": "read_filings",
                "filings_dir": str(self.filings_dir),
                "instruction": "Read the 10-K/10-Q/8-K extracts pulled by edgar_fetch.py (revenue recognition, critical accounting, business description, latest earnings 8-K).",
            },
        ]
        result.artifacts = [str(p) for p in [sell_side_plan_path] if p.exists()]
        if self.filings_dir.exists():
            result.artifacts.append(str(self.filings_dir))
        return result

    # ─────────────────────────────────────────────────────────────────────
    # STAGE 3: BUILD_DOSSIER
    # ─────────────────────────────────────────────────────────────────────

    def stage_build_dossier(self) -> StageResult:
        """STORY_DOSSIER.md must exist before drafting can begin."""
        result = StageResult(stage="BUILD_DOSSIER", status="PASS", next_stage="ANALYST_GATE")

        if not self.dossier_path.exists() or self.dossier_path.stat().st_size < 1000:
            result.status = "BLOCK"
            result.next_stage = None
            result.block_reason = (
                f"STORY_DOSSIER.md missing or too small at {self.dossier_path}. "
                f"Per spec §1.5, the dossier must be built (story / bear components / bull "
                f"components / rally drivers / accounting nuances / open questions) BEFORE drafting. "
                f"Calling agent must synthesize the dossier from your research notes + Reference Files + "
                f"sell-side synthesis + SEC filings."
            )
            result.dispatch_instructions = [{
                "type": "synthesize_dossier",
                "output_path": str(self.dossier_path),
                "inputs": [str(self.reference_dir), str(self.synthesis_dir),
                          str(self.filings_dir)],
                "template_sections": [
                    "1. The story in one paragraph",
                    "2. Bear thesis components (numbered)",
                    "3. Bull thesis components (numbered)",
                    "4. Recent rally / sell-off drivers",
                    "5. Specific accounting / partnership nuances",
                    "6. Open questions to resolve before drafting",
                ],
            }]
            return result
        result.artifacts = [str(self.dossier_path)]
        return result

    # ─────────────────────────────────────────────────────────────────────
    # STAGE 4: ANALYST_GATE — 5 pre-draft questions
    # ─────────────────────────────────────────────────────────────────────

    def stage_analyst_gate(self) -> StageResult:
        """Symbiotic mode only. Optional pre-draft questions."""
        if self.mode == "standalone":
            return StageResult(stage="ANALYST_GATE", status="PASS",
                              next_stage="PULL_ANALYST_INPUTS",
                              metadata={"skipped": "standalone mode"})
        result = StageResult(stage="ANALYST_GATE", status="NEEDS_INPUT",
                            next_stage="PULL_ANALYST_INPUTS")
        result.questions_for_analyst = [
            {"id": "rally_narrative", "question": "What's the rally / sell-off narrative driving recent stock action?"},
            {"id": "bear_components", "question": "What are the bear thesis components (3-5)?"},
            {"id": "bull_components", "question": "What are the bull thesis components (3-5)?"},
            {"id": "accounting_nuances", "question": "Any partnership / accounting nuances (gross vs net, pass-through, timing)?"},
            {"id": "recent_filings_prs", "question": "Any recent press releases or filings the agent should know about?"},
        ]
        return result

    # ─────────────────────────────────────────────────────────────────────
    # STAGE 5: PULL_ANALYST_INPUTS
    # ─────────────────────────────────────────────────────────────────────

    def stage_pull_analyst_inputs(self) -> StageResult:
        """Symbiotic mode only. Your decision, score, variant, positioning data."""
        if self.mode == "standalone":
            return StageResult(stage="PULL_ANALYST_INPUTS", status="PASS",
                              next_stage="PULL_DATA")
        result = StageResult(stage="PULL_ANALYST_INPUTS", status="NEEDS_INPUT",
                            next_stage="PULL_DATA")
        result.questions_for_analyst = [
            {"id": "decision", "question": "Pre-earnings decision (BUY/SELL/HOLD/TRIM/SHORT) + price triggers?"},
            {"id": "score", "question": "Earnings preview score (1=high-conviction bullish, 3=neutral, 5=high-conviction bearish)?"},
            {"id": "your_model", "question": "Your own model file (drop the .xlsx into workspace/{TICKER}/)?"},
            {"id": "positioning", "question": "Any positioning data you have (short interest, implied move, vol)? Optional."},
            {"id": "alt_data", "question": "Any alternative-data drops (CSV into workspace/{TICKER}/alt_data/)? Optional."},
        ]
        return result

    # ─────────────────────────────────────────────────────────────────────
    # STAGE 6: PULL_DATA
    # ─────────────────────────────────────────────────────────────────────

    def stage_pull_data(self) -> StageResult:
        """Initialize the data manifest from the config-derived fiscal period.

        Auto-PASS if key_metrics.yaml exists with content.

        Also initializes data_manifest.json (provenance + freshness/coverage
        gates). Manifest is created best-effort: if the fiscal period can't be
        determined from config, manifest creation is skipped with a warning,
        and the audit's D-00-MANIFEST-PRESENT check will hard-block downstream
        — surfacing the config gap explicitly rather than silently proceeding
        without provenance.
        """
        result = StageResult(stage="PULL_DATA", status="NEEDS_INPUT", next_stage="DRAFT")

        self._fiscal_period_resolution = self._resolve_fiscal_period()
        canonical_period = self._fiscal_period_resolution["canonical"]
        result.metadata["fiscal_period_resolution"] = self._fiscal_period_resolution

        # Initialize the data manifest (best-effort). Manifest creation requires
        # a canonical period. If we don't have one, config failed to declare it;
        # the audit's D-00-MANIFEST-PRESENT will hard-block downstream.
        if canonical_period:
            try:
                init_manifest(self.ticker, self.analyst, canonical_period, self.manifest_path)
                result.metadata["manifest_initialized"] = str(self.manifest_path)
                result.metadata["manifest_init_source"] = self._fiscal_period_resolution.get("source_of_truth")
            except Exception as e:
                result.metadata["manifest_init_error"] = (
                    f"Manifest init failed for canonical period '{canonical_period}': {e}. "
                    f"Audit's D-00-MANIFEST-PRESENT will hard-block delivery."
                )
        else:
            result.metadata["manifest_init_skipped"] = (
                f"Could not derive a canonical fiscal period from config. "
                f"Config: {self._fiscal_period_resolution['config_warning']}. "
                f"Manifest not created. Audit's D-00-MANIFEST-PRESENT will hard-block delivery."
            )

        # Auto-PASS check: key_metrics.yaml exists with content
        km = self.ticker_dir / "key_metrics.yaml"
        if km.exists() and km.stat().st_size > 500:
            result.status = "PASS"
            result.metadata["auto_pass"] = f"key_metrics.yaml exists ({km.stat().st_size} bytes) — data already gathered"
            result.artifacts.append(str(km))
            if self.manifest_path.exists():
                result.artifacts.append(str(self.manifest_path))
            return result
        result.dispatch_instructions = [{
            "type": "gather_data",
            "ticker": self.ticker,
            "output_dir": str(self.ticker_dir),
            "manifest_path": str(self.manifest_path),
            "manifest_contract": (
                "For every metric used, append a manifest entry via "
                "data_manifest.append_entry(manifest_path, entry_dict). Entry must include: "
                "source_id (unique), tool_name (e.g. sec_filing_10Q, manual_consensus, "
                "yahoo_finance_prices), ticker, period (C{q}Q{yy} or null for period-agnostic), "
                "metric (snake_case), value (numeric preferred), unit ($mm, %, bps, etc.), "
                "pulled_at (ISO-8601 UTC). Audit gate D-01-FRESH blocks delivery if any entry "
                "is >24h old; D-02-MANIFEST-COVERAGE blocks if any config.yaml.key_metrics is uncovered."
            ),
            "sources": [
                "SEC filings (free, via scripts/edgar_fetch.py): 10-K / 10-Q / 8-K + earnings release",
                "Consensus estimates: enter manually into workspace/{TICKER}/consensus.csv (see input-formats.md)",
                "Stock prices / reaction: scripts/stock_reaction_helper.py (free Yahoo Finance)",
                "Print date + KPIs: company IR site / latest 8-K",
            ],
        }]
        return result

    # ─────────────────────────────────────────────────────────────────────
    # STAGE 7: DRAFT
    # ─────────────────────────────────────────────────────────────────────

    def stage_draft(self) -> StageResult:
        """Calling agent drafts the preview from dossier + your inputs.

        Auto-PASS if preview markdown already exists with content.
        """
        result = StageResult(stage="DRAFT", status="NEEDS_INPUT", next_stage="SELF_LINT")

        # Auto-PASS check: preview markdown exists with content
        if self.preview_path.exists() and self.preview_path.stat().st_size > 5000:
            result.status = "PASS"
            result.metadata["auto_pass"] = f"Preview markdown exists ({self.preview_path.stat().st_size} bytes)"
            result.artifacts.append(str(self.preview_path))
            return result
        result.dispatch_instructions = [{
            "type": "draft_preview",
            "output_path": str(self.preview_path),
            "inputs_required": [
                str(self.dossier_path),
                str(self.config_path),
                "Any inputs you provided (decision, score, your variant, positioning, alt data)",
                "SEC filings extracts + consensus + price data",
            ],
            "template_reference": "PREVIEW_AGENT_SPEC.md §4 Canonical Output Template",
            "style_constraints": "Flat Takeaways ≤9 bullets, no binary labeling, no scare quotes, no version refs",
        }]
        return result

    # ─────────────────────────────────────────────────────────────────────
    # STAGE 8: SELF_LINT
    # ─────────────────────────────────────────────────────────────────────

    def stage_self_lint(self) -> StageResult:
        """Run style_linter.py against the preview markdown."""
        result = StageResult(stage="SELF_LINT", status="PASS", next_stage="AUDIT")
        if not self.preview_path.exists():
            result.status = "BLOCK"
            result.block_reason = f"Preview markdown not found at {self.preview_path}"
            return result
        # Style linter exit codes (style_linter.py contract):
        #   0 = clean (no violations)
        #   1 = violations present (NOT a runtime failure — JSON details follow)
        #   2 = runtime error (e.g., file not found)
        # `1` is therefore expected and handled in the body. We treat
        # returncodes 2+, timeouts, and any other unexpected non-zero as
        # subprocess failures that must hard-block.
        outcome = self._run_subprocess(
            [sys.executable, str(SCRIPTS_DIR / "style_linter.py"),
             "--markdown", str(self.preview_path), "--quiet"],
            stage="self_lint_check", timeout=30.0,
        )
        if outcome.timed_out or outcome.returncode not in (0, 1):
            result.status = "BLOCK"
            result.block_reason = (
                f"Style linter subprocess failure ({outcome.short_error()}). "
                f"Diagnostic log: {outcome.log_path}"
            )
            return result
        if outcome.returncode == 1:
            # Violations present — re-run to capture JSON details
            lint_json_path = self.outputs_dir / "_lint.json"
            json_outcome = self._run_subprocess(
                [sys.executable, str(SCRIPTS_DIR / "style_linter.py"),
                 "--markdown", str(self.preview_path), "--json", str(lint_json_path)],
                stage="self_lint_json", timeout=30.0,
            )
            if json_outcome.timed_out or json_outcome.returncode not in (0, 1):
                result.status = "BLOCK"
                result.block_reason = (
                    f"Style linter JSON capture failed ({json_outcome.short_error()}). "
                    f"Diagnostic log: {json_outcome.log_path}"
                )
                return result
            try:
                with open(lint_json_path) as f:
                    lint_data = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                result.status = "BLOCK"
                result.block_reason = f"Style linter JSON unreadable at {lint_json_path}: {e}"
                return result
            if lint_data.get("blocks_pipeline"):
                result.status = "BLOCK"
                result.block_reason = (
                    f"Style linter blocks pipeline. "
                    f"Fail-severity: {lint_data['summary']['by_severity'].get('fail', 0)}."
                )
                result.metadata["lint_violations"] = lint_data["violations"]
            else:
                result.metadata["lint_warns"] = lint_data['summary']['by_severity'].get('warn', 0)
                result.metadata["lint_infos"] = lint_data['summary']['by_severity'].get('info', 0)
            result.artifacts.append(str(lint_json_path))
        return result

    # ─────────────────────────────────────────────────────────────────────
    # STAGE 9: AUDIT
    # ─────────────────────────────────────────────────────────────────────

    def stage_audit(self) -> StageResult:
        """Run audit_agent v0.2 with block_on_fail_severity=True."""
        result = StageResult(stage="AUDIT", status="PASS", next_stage="CONS_CONTEXT_CHECK")
        if not self.preview_path.exists():
            result.status = "BLOCK"
            result.block_reason = f"Preview markdown not found at {self.preview_path}"
            return result
        audit_json = self.outputs_dir / "_audit.json"
        # Build source_docs and loaded_data lists
        sources = []
        if self.dossier_path.exists():
            sources.append(str(self.dossier_path))
        for f in (self.alt_data_dir.glob("*.md") if self.alt_data_dir.exists() else []):
            sources.append(str(f))
        for f in (self.positioning_dir.glob("*.md") if self.positioning_dir.exists() else []):
            sources.append(str(f))
        # Add readable extracted sources from Reference Files/<TICKER> and the
        # workspace filings/ dir (markdown/text/json/csv; raw PDFs are
        # represented via their extracted synthesis files).
        _seen_src = set(sources)
        for _d in (self.reference_dir, self.filings_dir):
            if not _d.exists():
                continue
            for _f in sorted(_d.rglob("*")):
                if (_f.is_file() and _f.suffix.lower() in (".md", ".txt", ".json", ".csv")
                        and str(_f) not in _seen_src):
                    sources.append(str(_f))
                    _seen_src.add(str(_f))
        data_files = [str(self.config_path)] if self.config_path.exists() else []
        km = self.ticker_dir / "key_metrics.yaml"
        if km.exists():
            data_files.append(str(km))

        cmd = [sys.executable, str(SCRIPTS_DIR.parent / "audit_agent.py"),
               "--analysis", str(self.preview_path),
               "--out", str(audit_json),
               "--ticker", self.ticker,
               "--agent-id", "earnings-preview-agent"]
        for s in sources:
            cmd += ["--source", s]
        for d in data_files:
            cmd += ["--data", d]
        # P0-3: feed manifest + config to audit so D-01-FRESH and
        # D-02-MANIFEST-COVERAGE checks can run. Both args are passed
        # whenever the underlying file exists; if the manifest is
        # absent the audit agent emits D-00-MANIFEST-PRESENT (severity=fail)
        # which hard-blocks via block_on_fail_severity.
        cmd += ["--manifest", str(self.manifest_path)]
        if self.config_path.exists():
            cmd += ["--config", str(self.config_path)]
        # Audit runs all 5 base scoring categories + 4 D-* checks (manifest
        # freshness/coverage, fiscal period, compmix, y/y arithmetic) plus
        # the optional LLM overlay. The 120s timeout accounts for the new
        # check workload; the previous 60s was tight on long previews.
        outcome = self._run_subprocess(cmd, stage="audit_agent", timeout=120.0)
        if outcome.timed_out:
            result.status = "BLOCK"
            result.block_reason = (
                f"Audit subprocess timed out ({outcome.short_error()}). "
                f"Diagnostic log: {outcome.log_path}"
            )
            return result
        # audit_agent.py exits 0 for any audit completion (gate decision is
        # in the JSON, not the exit code). A non-zero return means the
        # audit subprocess itself failed (e.g., import error, crash).
        if outcome.returncode != 0:
            result.status = "BLOCK"
            result.block_reason = (
                f"Audit subprocess failed with returncode={outcome.returncode}. "
                f"Diagnostic log: {outcome.log_path}. stderr tail: {outcome.stderr[-300:]}"
            )
            return result
        if not audit_json.exists():
            result.status = "BLOCK"
            result.block_reason = (
                f"Audit completed but no audit JSON written at {audit_json}. "
                f"Likely a serialization failure in audit_agent.py."
            )
            return result
        try:
            with open(audit_json) as f:
                audit_data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            result.status = "BLOCK"
            result.block_reason = f"Audit JSON unreadable at {audit_json}: {e}"
            return result
        gate = audit_data.get("gate", "RED")
        score = audit_data.get("score", 0)
        fails = audit_data.get("fail_severity_count", 0)
        result.metadata["audit_score"] = score
        result.metadata["audit_gate"] = gate
        result.metadata["fail_severity_count"] = fails
        if gate == "BLOCK":
            result.status = "BLOCK"
            result.block_reason = f"Audit BLOCK gate. Score {score}/100. Fail-severity items: {fails}."
        result.artifacts.append(str(audit_json))
        return result

    # ─────────────────────────────────────────────────────────────────────
    # STAGE 10: CONS_CONTEXT_CHECK
    # ─────────────────────────────────────────────────────────────────────

    def stage_cons_context_check(self) -> StageResult:
        """Verify your variant against the consensus distribution."""
        result = StageResult(stage="CONS_CONTEXT_CHECK", status="PASS", next_stage="RENDER")
        variant_json = self.ticker_dir / "_variant.json"
        cons_json = self.ticker_dir / "_cons_dispersion.json"
        if not variant_json.exists() or not cons_json.exists():
            result.metadata["skipped"] = (
                f"Cons-context check skipped — requires {variant_json.name} + {cons_json.name}. "
                f"Produce these from your consensus inputs + your own model, if you have a variant."
            )
            return result
        # cons_context_check exit-code contract:
        #   0 = pass; 1 = fail (stale or outlier); other = subprocess failure.
        outcome = self._run_subprocess(
            [sys.executable, str(SCRIPTS_DIR / "cons_context_check.py"),
             "--variant-json", str(variant_json),
             "--cons-json", str(cons_json),
             "--out", str(self.outputs_dir / "_cons_check.json")],
            stage="cons_context_check", timeout=30.0,
        )
        if outcome.timed_out:
            result.status = "BLOCK"
            result.block_reason = (
                f"Cons-context check timed out ({outcome.short_error()}). "
                f"Diagnostic log: {outcome.log_path}"
            )
            return result
        if outcome.returncode == 1:
            result.status = "BLOCK"
            result.block_reason = "Cons-context check failed (stale model or outlier variant)."
        elif outcome.returncode != 0:
            result.status = "BLOCK"
            result.block_reason = (
                f"Cons-context check subprocess failure ({outcome.short_error()}). "
                f"Diagnostic log: {outcome.log_path}"
            )
        return result

    # ─────────────────────────────────────────────────────────────────────
    # STAGE 11: RENDER
    # ─────────────────────────────────────────────────────────────────────

    def stage_render(self) -> StageResult:
        """Pandoc + weasyprint with row-count verification."""
        result = StageResult(stage="RENDER", status="PASS", next_stage="DELIVER")
        if not self.preview_path.exists():
            result.status = "BLOCK"
            result.block_reason = f"Preview markdown not found at {self.preview_path}"
            return result
        css = self.outputs_dir / "_style.css"
        html = self.outputs_dir / "_temp.html"

        # Pandoc — typically fast but PDF-builder corner cases push to 60-90s.
        # 120s is comfortable headroom; the wrapper preserves stderr to disk
        # on failure for diagnosis.
        pandoc_outcome = self._run_subprocess(
            ["pandoc", str(self.preview_path), "-o", str(html),
             "--standalone", "--css", str(css),
             "--from", "markdown-tex_math_dollars",
             "--metadata", f"title={self.ticker} {self._fiscal_period_resolution.get('canonical') or ''} Preview"],
            stage="render_pandoc", timeout=120.0,
        )
        if pandoc_outcome.timed_out or pandoc_outcome.returncode != 0:
            result.status = "BLOCK"
            result.block_reason = (
                f"Pandoc subprocess failure ({pandoc_outcome.short_error()}). "
                f"Diagnostic log: {pandoc_outcome.log_path}"
            )
            return result

        # Weasyprint — the PDF rendering step. Long previews with many
        # tables / images / styled cells can run >2 minutes. 300s budget.
        weasy_outcome = self._run_subprocess(
            [sys.executable, "-c",
             f"from weasyprint import HTML, CSS; "
             f"HTML('{html}').write_pdf('{self.preview_pdf}', stylesheets=[CSS('{css}')])"],
            stage="render_weasyprint", timeout=300.0,
        )
        if weasy_outcome.timed_out or weasy_outcome.returncode != 0:
            result.status = "BLOCK"
            result.block_reason = (
                f"Weasyprint subprocess failure ({weasy_outcome.short_error()}). "
                f"Diagnostic log: {weasy_outcome.log_path}"
            )
            return result

        # P1-3: strict per-table row-count comparison via render_verify.
        # Replaces the previous global heuristic (`abs(md - html) > 5`),
        # which could pass a draft missing 3 rows when the pandoc
        # tex_math_dollars bug only swallowed a few cells. Now every
        # mismatch is caught and the offending table is identified
        # by its header text for diagnosis.
        from render_verify import (
            extract_markdown_tables, extract_html_tables, compare_tables,
        )
        try:
            md_tables = extract_markdown_tables(self.preview_path.read_text())
            html_tables = extract_html_tables(html.read_text())
        except OSError as e:
            result.status = "BLOCK"
            result.block_reason = f"Render verification could not read preview/HTML: {e}"
            return result
        comp = compare_tables(md_tables, html_tables)
        result.metadata["md_table_count"] = comp.md_count
        result.metadata["html_table_count"] = comp.html_count
        result.metadata["per_table_diffs"] = comp.per_table_diffs
        if not comp.ok:
            result.status = "BLOCK"
            result.block_reason = comp.reason
        result.artifacts = [str(self.preview_pdf), str(html)]
        return result

    # ─────────────────────────────────────────────────────────────────────
    # STAGE 12: DELIVER
    # ─────────────────────────────────────────────────────────────────────

    def stage_deliver(self) -> StageResult:
        """Final delivery — report the PDF path."""
        result = StageResult(stage="DELIVER", status="PASS", next_stage=None)
        if not self.preview_pdf.exists():
            result.status = "BLOCK"
            result.block_reason = f"PDF not found at {self.preview_pdf}"
            return result
        result.metadata["output_pdf"] = str(self.preview_pdf)
        result.metadata["pdf_size_bytes"] = self.preview_pdf.stat().st_size
        result.artifacts = [str(self.preview_pdf)]
        return result

    # ─────────────────────────────────────────────────────────────────────
    # Stage dispatcher
    # ─────────────────────────────────────────────────────────────────────

    def run_stage(self, stage: str) -> StageResult:
        method_name = f"stage_{stage.lower()}"
        method = getattr(self, method_name, None)
        if method is None:
            r = StageResult(stage=stage, status="BLOCK",
                           block_reason=f"Unknown stage: {stage}")
            self._record_stage_in_provenance(r)
            return r
        result = method()
        # P1-6: every stage outcome + its artifacts get appended to the
        # provenance record. write_provenance() is the explicit flush.
        self._record_stage_in_provenance(result)
        return result

    def run_all(self, halt_on_block: bool = True, skip_interactive: bool = False) -> list[StageResult]:
        results = []
        for stage in STAGES:
            r = self.run_stage(stage)
            results.append(r)
            if r.status == "BLOCK" and halt_on_block:
                break
            if r.status == "NEEDS_INPUT" and not skip_interactive:
                # Calling agent must handle the dispatch_instructions / questions before continuing
                break
        return results


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _cli() -> int:
    ap = argparse.ArgumentParser(description="Earnings Preview Agent orchestrator")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--analyst", default="user")
    ap.add_argument("--mode", choices=["symbiotic", "standalone"], default="symbiotic")
    ap.add_argument("--stage", default=None, help=f"Single stage to run. Options: {', '.join(STAGES)}")
    ap.add_argument("--all", action="store_true", help="Run all stages until first NEEDS_INPUT or BLOCK")
    ap.add_argument("--log-level", default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                    help="Logging verbosity for direct CLI invocations.")
    ap.add_argument("--out", default=None, help="Optional path to write result JSON")
    ap.add_argument("--provenance", default=None,
                    help="Optional explicit path for the provenance JSON. "
                         "Default: outputs/_provenance_{run_id}.json. "
                         "Set to 'off' to skip provenance write.")
    args = ap.parse_args()

    # Configure logging at the CLI entry point only — never at import time.
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="[%(levelname)s %(name)s] %(message)s",
        stream=sys.stderr,
    )

    runner = PreviewRunner(ticker=args.ticker, analyst=args.analyst, mode=args.mode)

    if args.stage:
        result = runner.run_stage(args.stage)
        out = asdict(result)
    elif args.all:
        results = runner.run_all()
        out = [asdict(r) for r in results]
    else:
        # Default: run AUTO_DISCOVER as a smoke test
        result = runner.run_stage("AUTO_DISCOVER")
        out = asdict(result)

    # P1-6: write provenance unless explicitly disabled. Captures what
    # stages ran, their outcomes, all artifacts (with sha256), the
    # environment versions, and the final audit gate decision.
    if args.provenance != "off":
        prov_path = None if args.provenance is None else Path(args.provenance)
        try:
            written = runner.write_provenance(prov_path)
            print(f"[provenance] wrote {written}", file=sys.stderr)
        except Exception as e:
            # Provenance is best-effort — don't fail the run if it can't write
            print(f"[provenance] write failed: {e}", file=sys.stderr)

    text = json.dumps(out, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)

    # Exit 1 on BLOCK status (CI-friendly)
    if isinstance(out, dict) and out.get("status") == "BLOCK":
        return 1
    if isinstance(out, list) and any(r.get("status") == "BLOCK" for r in out):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
