# Stage 1 Prep — Output Specification

**Purpose:** authoritative spec for what `earnings_stage1_runner.py` generates. Runner code must produce outputs that conform to this spec. See also `pre-earnings-output.md`.

---

## Output artifacts (per run)

| Artifact | Path | Consumers |
|---|---|---|
| PDF | `workspace/{TICKER}/outputs/stage1_prep_{TICKER}_{YYYYMMDD}.pdf` | Human reader |
| Markdown | `workspace/{TICKER}/outputs/stage1_prep_{TICKER}_{YYYYMMDD}.md` | Audit Agent, downstream runners |
| Audit result | written alongside as `stage1_prep_{TICKER}_{YYYYMMDD}_audit.json` per `/Audit Agent/output-format.md` |
| Run log entry | appended to `workspace/{TICKER}/run_log.json` |

Filenames use `{YYYYMMDD}` = run date, not earnings date. If two runs happen same day, append `_2`, `_3`, etc.

---

## Required inputs (per `input-formats.md`)

| Input | Path | Required | Missing-behavior |
|---|---|---|---|
| `key_metrics.yaml` | `workspace/{TICKER}/key_metrics.yaml` | **Yes** | Hard-fail with clear error |
| `consensus.csv` | same dir | **Yes** | Hard-fail |
| `thesis_current.md` | `workspace/{TICKER}/thesis_current.md` | No | Section 7 omitted; flag on cover |
| Transcripts (last 8 Q) | `workspace/{TICKER}/transcripts/*.txt` | No | Sections 4 (language), 8 (transcript appendix) omitted; flag on cover |
| Guidance history | `workspace/{TICKER}/guidance/*.{json,csv,md}` | No | Section 5 guidance-track-record omitted; flag on cover |
| Options implied move | `--implied-move X.X` CLI flag or `workspace/{TICKER}/options.json` | No | Section 6 implied-move row shows "not provided" |
| Positioning data (short interest, whisper) | `workspace/{TICKER}/positioning.json` | No | Section 6 corresponding rows show "not provided" |
| Buy-side bogey | `workspace/{TICKER}/bogey.yaml` | No | Section 6 buy-side row shows "not provided — input recommended"; rest of bogey card still renders |

**Graceful degradation rule:** when optional inputs are missing, runner continues, emits sections it can, inserts a `.warning` block at the top of the PDF enumerating missing inputs, and tags missing sections with a grey "data not provided" placeholder. Runner must never fail silently — every omission is visible in the output.

---

## PDF structure

| # | Section | Content | Degrades when |
|---|---------|---------|--------------|
| Cover | — | Ticker, company, earnings date, report time (BMO/AMC), run date, consensus as-of date, missing-input warning block | — |
| 1 | Executive Summary | 1 page. 5–7 line expectations narrative, top 3 consensus surprises (metric with widest range / highest dispersion), thesis status one-liner, top 3 watch items | thesis one-liner omitted if no thesis file |
| 2 | Expectations Stack | Table — one row per metric in `key_metrics.core_metrics` + `key_metrics.specific_metrics`. Columns: metric, unit, consensus mean (FY current), consensus range low-high, last guidance, implied bar (beat/in-line/miss-to-meet), staleness flag, N_estimates | If CSV has no range (single-point estimates), range column shows "single-point"; if guidance file missing, last-guidance column shows "—" |
| 3 | Variant vs Consensus | Table — for every metric in key_metrics that has a `variant_base_target` / `variant_bull_target` / `variant_bear_target`, show: variant value, consensus FY mean, delta (variant − consensus), delta as % of consensus. If `reporting_basis` missing on metric, emit BOTH `_gaap` and `_adj` consensus rows and flag ambiguity | metric rows without variant targets omitted |
| 4 | What Management Will Be Asked | Language triggers by topic. Derived from prior 8 transcripts' analyst-Q&A sections. Each trigger: topic, last-period language, watch-for language | **omitted entirely** if transcripts/ empty; replaced with placeholder card "Language triggers require 8 prior transcripts — none found. Populate /transcripts/ to enable." |
| 5 | Guidance Track Record | Table — last 6 quarters. Columns: quarter, metric, guidance issued, actual, beat/in-line/miss | **omitted entirely** if guidance/ empty |
| 6 | Bogey Card | Synthesized pre-print bogey synthesis. Buy-side bogey vs. sell-side consensus; whisper Δ; options-implied move; crowding score; positioning narrative (2–3 sentences). Replaces the prior raw "Positioning & Implied Move" table — that data feeds this section but is no longer the output. See Section 6 derivation below. | Each input row degrades individually with explicit "not provided" tag; if all positioning inputs missing, full section degrades to consensus-only with flag |
| 7 | Thesis Tie-In | For each open thesis claim (TC-01..TC-0N) from `thesis_current.md`: claim text, confirming signal to look for in this print, falsifying signal to look for. If thesis carries a `variant_view_headline:` field, that single-sentence summary appears at section top. | **omitted** if thesis_current.md missing |
| 8 | KPI Sensitivity | For each metric with `sensitivity:` field in key_metrics.yaml: bear / base / bull scenario values (from consensus range or fallback ±3%), EPS implication per sensitivity note, stock reaction estimate (if stock_reaction.json present) | stock-reaction column shows "—" if file missing |
| A | Appendix: Consensus data dump | Full `consensus.csv` rendered as table with source_field codes | — |
| B | Appendix: Pipeline audit | Data reconciliation checks runner performed, list of missing inputs, list of schema flags, **anti-pattern lint results** (informational only — see Audit Agent category 6) | — |

---

## Section-by-section data derivation rules

### Section 2 — Expectations Stack derivation
- Iterate every metric in `key_metrics.core_metrics` + `key_metrics.specific_metrics`, in that order.
- For each metric, look up corresponding row in `consensus.csv` by name match (case-insensitive, underscore normalization).
- If key_metrics metric name does not map to a consensus row, render the row with consensus columns = "—" and add a flag "no consensus mapping" in the Flags column. Do **not** skip.
- Implied bar logic: compare consensus mean to last-guidance value. If consensus > guidance high: "beat-to-meet"; if consensus < guidance low: "miss-to-meet"; else: "in-line".
- Staleness flag: if consensus CSV has an `as_of_date` field more than 7 days older than earnings date, tag every row with `🟡 stale`.
- N_estimates column: pull from consensus CSV if present; else show "—".

### Section 3 — Variant vs Consensus derivation
- Read every metric in key_metrics that has any `variant_*_target` field.
- If the metric has a `reporting_basis: gaap` or `reporting_basis: adjusted` hint, use that CSV column (`{metric}_gaap` or `{metric}_adj`).
- If no hint, and CSV has BOTH `_gaap` and `_adj` variants of the metric: emit two rows, one per basis, and append a schema flag "⚠ reporting_basis unspecified — compared against both".
- If CSV has only one variant: use it, no flag.
- Delta column: `variant_value − consensus_mean`. Percent delta: `delta / consensus_mean × 100`.

### Section 4 — Language triggers derivation
- For each transcript in `/transcripts/` (target: last 8 quarters):
  - Split into management-prepared-remarks and Q&A.
  - Extract analyst questions (speaker label = "Analyst" or matches pattern `{Firstname} {Lastname} — {Firm}`).
  - Cluster questions into topics (use simple keyword buckets configured per ticker in `key_metrics.yaml` under `language_topics:` — OPTIONAL field; if missing, bucket by "guidance / margin / demand / competition / capital-allocation / other").
- For each topic, surface: the last time this topic came up, the specific language management used, what changed vs two quarters prior.
- **Degradation:** if fewer than 3 transcripts available, emit the triggers table with a note "coverage limited to N transcripts — full 8-quarter analysis unavailable". If zero transcripts, omit section entirely and insert placeholder card.

### Section 5 — Guidance track record derivation
- Read every file in `/guidance/`. Accepted formats: YAML/JSON with schema `{quarter: "YYYY-QN", metrics: {metric: {guidance: value, actual: value}}}`, or a parseable `guidance_history.csv`.
- Produce table sorted newest→oldest, up to last 6 quarters.
- Beat/in-line/miss determined per metric's `direction` field in key_metrics.yaml (higher_better: actual > guidance high → beat; counter_cyclical: inverted).

### Section 6 — Bogey Card
**Purpose:** synthesized pre-print bogey assessment. Augments — does not replace — the medium/long-term thesis view in Section 7.

**Output rows:**
1. **Sell-side consensus** — auto-derived from Section 2's expectations stack. Pull the 1-2 most-watched metrics for this ticker (per `key_metrics.bogey_metrics` — defaults to revenue + EPS).
2. **Buy-side bogey** — supplied via `workspace/{TICKER}/bogey.yaml` if present, else "not provided — input recommended". Format: per-metric, "buy-side wants X to rally; needs Y to avoid sell-off". Free-text with each metric.
3. **Whisper Δ** — from `positioning.json:whisper_delta` if present. For names with no whisper feed, this row will display "no whisper feed for this ticker".
4. **Options-implied move** — from CLI flag or `options.json`. Format ±X.X%. If absent: "not provided".
5. **Crowding score** — derived: combines short-interest % (positioning.json), 13F top-holder concentration if available, and recent options open-interest skew. Bucket: `crowded_long` / `consensus_long` / `neutral` / `consensus_short` / `crowded_short`. Methodology in derivation logic below; degrades to "insufficient data" if fewer than 2 inputs present.
6. **Setup score** (informational, not numeric) — qualitative one-paragraph synthesis: sentiment + positioning + catalyst + R/R. Generated only if Sections 2, 3, 6.5, and 7 have populated rows. Otherwise display "Setup synthesis requires consensus + variant + crowding + thesis inputs".

**Crowding score derivation (deterministic):**
- Short interest % of float: <2% = positioning_neutral; 2-5% = neutral; 5-10% = consensus_short_signal; >10% = crowded_short_signal
- HF concentration: top 5 13F holders > 25% float = crowded_long; top 5 > 15% = consensus_long; <15% = neutral. (Pulled from `positioning.json:hf_concentration` if available; otherwise omit this input.)
- Options skew: 30-day put-call open-interest ratio > 1.5 = bearish skew; < 0.6 = bullish skew. (Pulled from `positioning.json:options_skew` if available.)
- Combined: weight SI 50%, HF 30%, options 20%. If any input absent, redistribute weights and flag.

**Setup score formula (qualitative):**
Synthesizer combines these literal inputs:
- Sentiment proxy: from Section 4 (language triggers) if available, else from Section 7 thesis status
- Positioning: from crowding score row above
- Catalyst: the upcoming print itself; tag as `binary` if guidance change is on the table
- R/R: from Section 8 (KPI sensitivity) — implied beat-case stock move vs miss-case stock move

**Buy-side bogey input file (`bogey.yaml`):**
```yaml
ticker: XYZ
as_of: 2026-04-25
metrics:
  revenue:
    sell_side_consensus: 1020
    buy_side_bogey: 1030
    rationale: "Buy-side wants 1030 to rally; 1010 = consensus sell-off"
  eps_adj:
    sell_side_consensus: 2.45
    buy_side_bogey: 2.55
    rationale: "Beat threshold for crowded longs"
notes: "no formal whisper feed; bogey here is desk-read inference, not whisper data"
```
This file is OPTIONAL. When absent, Section 6 degrades to "buy-side bogey not provided" but the rest of the bogey card renders (crowding, implied move, etc.).

### Section 7 — Thesis tie-in
- Parse `thesis_current.md`. Expected structure: claims listed as `TC-NN: <claim text>` headers or in a YAML front-matter block.
- For each open claim (status != "resolved"), generate:
  - Confirming-signal line: extracted from claim's `confirming_evidence:` subsection if present, else "not specified in thesis doc".
  - Falsifying-signal line: extracted from `falsifying_evidence:` subsection, same fallback.

### Section 8 — KPI sensitivity
- Iterate key_metrics with `sensitivity:` field.
- Base = consensus mean; Bull = consensus high (or mean × 1.03 fallback); Bear = consensus low (or mean × 0.97 fallback).
- EPS implication: apply the sensitivity string formula per scenario.
- Stock reaction: if stock_reaction.json has ≥4 priors, use median one-day reaction for comparable-magnitude beats/misses. Else: "insufficient history (N={count})".

---

## JSON output schema

The runner maintains a structured representation of the analysis (internal scaffolding; the delivered artifacts are PDF + markdown). Schema:

```json
{
  "run_metadata": {
    "agent_id": "earnings-analysis-stage-1",
    "ticker": "XYZ",
    "run_date": "2026-04-17",
    "earnings_date": "2026-04-29",
    "input_files_used": ["key_metrics.yaml", "consensus.csv", ...],
    "input_files_missing": ["transcripts/*", "guidance/*"],
    "runner_version": "0.1.0"
  },
  "sections": {
    "executive_summary": { "narrative": "...", "top_watch_items": [...] },
    "expectations_stack": [ { "metric": "...", "consensus_mean": ..., ... }, ... ],
    "variant_vs_consensus": [ ... ],
    "language_triggers": null,  // null when degraded
    "guidance_track_record": null,
    "bogey_card": {
        "sell_side_consensus": [...],
        "buy_side_bogey": [...] | null,
        "whisper_delta": "..." | null,
        "implied_move_pct": 0.085 | null,
        "crowding": { "score": "neutral", "inputs_used": ["short_interest"], "inputs_missing": ["hf_concentration","options_skew"] },
        "setup_synthesis": "..." | null
    },
    "thesis_tie_in": [ ... ],
    "kpi_sensitivity": [ ... ],
    "anti_pattern_lint": { "checks_run": 12, "warnings": [...], "passed": [...] }
  },
  "degradation_flags": [
    { "section": "language_triggers", "reason": "no transcripts in transcripts/" },
    ...
  ],
  "audit": { ... }  // populated by Audit Agent, per output-format.md
}
```

---

## Audit hook points

Runner calls `audit_agent.audit()` AFTER generating the structured representation, BEFORE rendering the PDF. Audit input: the structured representation and all loaded source files. Audit result written as standalone `stage1_prep_{TICKER}_{YYYYMMDD}_audit.json`. Gate behavior: audit RED does **not** block delivery for Stage 1 (comprehensive prep, errors surface for review), but RED triggers a visible banner at the top of the output.

---

## HTML template
Same weasyprint/HTML approach as `pre-earnings-output.md`. Style block reused verbatim for visual consistency across stages. New CSS classes:
- `.degraded-section` — grey background, italic "data not provided" text for missing sections
- `.schema-flag` — yellow inline badge for schema ambiguities (e.g., reporting_basis unspecified)

---

## Runner CLI signature

```
python earnings_stage1_runner.py \
    --ticker XYZ \
    --earnings-date 2026-04-29 \
    --report-time AMC \
    [--implied-move 0.08] \
    [--consensus-as-of 2026-04-17] \
    [--skip-audit]  # dev only
```

Default `--run-date` = today. The runner takes `--ticker` and writes to `workspace/{TICKER}/`.

---

## Acceptance criteria for runner
1. Runs end-to-end against a workspace in its current state (no transcripts, no guidance, annual-only consensus) without error.
2. Produces both artifacts (PDF, markdown).
3. Missing-input warning block is visible on the cover page.
4. Sections 4, 5 show as degraded cards, not blanks.
5. Section 3 emits both `_gaap` and `_adj` rows for EPS (reporting_basis unspecified in current key_metrics.yaml).
6. Audit runs and returns a score; result visible at the top of the output.
7. Audit result written alongside the output.
8. Section 6 (Bogey Card) renders even when `bogey.yaml` is absent — degraded buy-side row, but crowding score and implied move still computed where inputs allow.
9. Anti-pattern lint runs against the analysis text and emits results into Appendix B as informational warnings (does NOT affect Audit Agent score in v0.1; gating disabled by default).

---

## Design notes

The Bogey Card / Crowding / Setup sections follow common pre-print process patterns:

1. **Section 6 — Bogey Card synthesis.** Synthesizes the pre-print bogey (buy-side vs sell-side, whisper, implied move) rather than a raw positioning table. The bogey is one of the most useful pre-print artifacts.

2. **Section 6.5 — Crowding score derivation.** Crowding is a major factor in muted-beat / muted-miss reactions.

3. **Section 6.6 — Setup score (qualitative).** "Setup" = sentiment + positioning + catalyst + R/R. Stage 1 produces all four inputs separately; this section synthesizes them.

4. **Anti-pattern lint integration (Appendix B).** Detects a set of mechanically-detectable analyst mistakes. Detection logic lives in Audit Agent category 6 (informational, non-blocking).

**Deliberately out of scope** (not relevant to medium-to-long-term fundamental work):
- Idiosyncratic-variance threshold monitoring
- Alpha curve / decay tracking (short-horizon)
- Per-strategy capital allocation / shadow netting (multi-strategy structure)
