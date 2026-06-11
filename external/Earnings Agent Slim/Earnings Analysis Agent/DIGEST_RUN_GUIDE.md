# Digest Agent — Operator Run Guide

**Use this as the reference for digest runs.**

The runner has several phases. Some are deterministic (Bash/Python); some
require Claude-in-chat to do unstructured-text → structured-data work
(read press release, write actuals.json, fill narrative sections).

---

## Pre-flight — Confirm prerequisites

Before a print:

1. Confirm the ticker has a current preview output (the digest needs it as the spine).
2. Confirm `weasyprint` is installed: `pip install weasyprint --break-system-packages`
3. Confirm `pandoc` is on PATH: `pandoc --version`
4. Confirm the EDGAR fetcher works: `python scripts/edgar_fetch.py --ticker {TICKER}`

---

## Stage 1 — Post-Print, Pre-Call

### Phase 1 — Assemble baseline (deterministic)

```bash
python3 "Earnings Analysis Agent/earnings_digest_runner.py" \
  --ticker {TICKER} --period {PERIOD} \
  --mode print --phase fetch_baseline
```

Output: `digest_work/{PERIOD}/digest_baseline.json`
Contains: parsed KPI tables (current Q, next Q, FY), positioning data (if provided),
guidance history, key_metrics config.

### Phase 2 — Fetch the print materials (Claude-in-chat)

```bash
python3 "Earnings Analysis Agent/earnings_digest_runner.py" \
  --ticker {TICKER} --period {PERIOD} \
  --mode print --phase fetch_print_materials
```

This emits `digest_work/{PERIOD}/fetch_request.json` with EDGAR fetch
instructions. **Claude then:**

1. Runs `python scripts/edgar_fetch.py --ticker {TICKER}` to pull the latest 8-K into `workspace/{TICKER}/filings/`
2. Identifies the earnings 8-K (Item 2.02 — Results of Operations and Financial Condition)
3. Saves the Exhibit 99.1 body as `digest_work/{PERIOD}/press_release.txt`
4. Saves any 99.2 / 99.3 exhibits if present
5. Writes `digest_work/{PERIOD}/manifest.json` with accession number, filing date, exhibit list

If the company files only Exhibit 99.1, the deck may be on the IR site — fetch via
WebFetch (the `ir_deck_url` in config.yaml) as a fallback if you want deck commentary.

### Phase 3 — Extract numerical actuals (Claude-in-chat)

```bash
python3 "Earnings Analysis Agent/earnings_digest_runner.py" \
  --ticker {TICKER} --period {PERIOD} \
  --mode print --phase request_extraction
```

This emits `digest_work/{PERIOD}/extraction_request.json`. **Claude then:**

1. Reads `press_release.txt` verbatim
2. For the current quarter, extracts every metric
   on the expectations stack with: value, unit, GAAP-or-non-GAAP, raw quote,
   character offset within press_release.txt
3. Extracts new guidance (Q+1 + FY)
4. Writes `digest_work/{PERIOD}/actuals.json` per the schema in
   `extraction_request.json`

Schema for actuals.json:
```json
{
  "period_reported": "C1Q26",
  "metrics": [
    {"metric": "Total Revenue ($mm)", "period": "C1Q26",
     "value": 1031.5, "unit": "usd_mm", "gaap_flag": "GAAP",
     "raw_quote": "Q1'26 total revenues of $1,031.5 million",
     "offset_start": 4823}
  ],
  "guidance_new": [
    {"period": "C2Q26", "metric": "Total Revenue ($mm)",
     "low": 1060.0, "high": 1080.0, "point": null,
     "raw_quote": "expects Q2 2026 worldwide revenues of $1,060–$1,080 million",
     "offset_start": 12450}
  ]
}
```

### Phase 4 — Compute scorecard (deterministic)

```bash
python3 "Earnings Analysis Agent/earnings_digest_runner.py" \
  --ticker {TICKER} --period {PERIOD} \
  --mode print --phase compute_scorecard
```

Output: `digest_work/{PERIOD}/scorecard.json` with beat/miss per metric vs
cons + variant, classifications (beat/in_line/miss), guide changes, and
warnings for unmatched metrics.

**Inspect warnings.** If any metric in actuals didn't match a baseline row,
fix the metric name in actuals.json (must match the preview's KPI table
metric name) and re-run.

### Phase 5 — Draft skeleton (deterministic)

```bash
python3 "Earnings Analysis Agent/earnings_digest_runner.py" \
  --ticker {TICKER} --period {PERIOD} \
  --mode print --phase draft_skeleton
```

Output: `outputs/digest_v1_print_{PERIOD}_{YYYYMMDD}.md`

Skeleton has filled scorecard table + filled guide delta table +
LLM_FILL placeholders for all narrative sections.

### Phase 6 — Fill narrative sections (Claude-in-chat)

Each LLM_FILL marker is a section Claude must write. Sections:
- TL;DR (5-7 bullets)
- Beat/Miss gut-check paragraph
- Narrative Read (improving / deteriorating / mixed)
- Guide Delta read (raised / reaffirmed / lowered + magnitude commentary)
- Implied Estimate Moves (direction + magnitude only — no draft numbers)
- Watch-List Reconciliation (per-item from preview)
- Questions to Pay Attention To On the Call
- Tactical Lens (action + sizing + pair view)
- Historical Earnings Reaction Calibration
- Appendix A.1 (options surface), A.2 (pair re-rate), A.3 (cons revisions),
  A.4 (squeeze update)

Use `Edit` to replace each `<!-- LLM_FILL: ... -->` with prose. Cite
the quotes from `press_release.txt` (with offsets) when material
numerical statements are made. Match your voice from the preview.

### Phase 7 — Audit (deterministic)

```bash
python3 "Earnings Analysis Agent/earnings_digest_runner.py" \
  --ticker {TICKER} --period {PERIOD} \
  --mode print --phase audit
```

Pass criteria: no remaining `LLM_FILL` markers. Extends to richer audit
(citation cross-checks, arithmetic verification) in v0.2.

If audit fails: fix and re-run.

### Phase 8 — Render PDF (deterministic)

```bash
python3 "Earnings Analysis Agent/earnings_digest_runner.py" \
  --ticker {TICKER} --period {PERIOD} \
  --mode print --phase render \
  --md "workspace/{TICKER}/outputs/digest_v1_print_{PERIOD}_{YYYYMMDD}.md" \
  --css "Earnings Analysis Agent/digest_style.css"
```

Output: `outputs/digest_v1_print_{PERIOD}_{YYYYMMDD}.pdf`

Verify rendered PDF: page count 5-8, all tables intact (count rows in
each), color classes render (beat=green, miss=red, in_line=gray),
no orphan section headers.

### Deliver

- Provide `computer://` link to the PDF
- Brief on key findings in chat (succinct, no postamble)

---

## Stage 2 — Transcript-Integrated, Post-Call

After you drop the transcript file:

1. Confirm transcript is at `workspace/{TICKER}/transcripts/{TICKER}_{PERIOD}_transcript.txt`
2. Re-run baseline + extraction phases in `--mode transcript` (TBD —
   Stage 2 phases not yet implemented in v0.1.0; build after Stage 1
   validates).

Stage 2 differences from Stage 1:
- Loads digest_v1 as additional baseline
- Parses prepared remarks vs Q&A
- Tags Q&A exchanges (substantive / hedged / dodged)
- Computes incremental disclosures vs press release
- Detects language changes vs prior 2 transcripts
- Emits `digest_v2_transcript_{PERIOD}_{YYYYMMDD}.{md,pdf}`

---

## Failure modes to watch for

1. **EDGAR latency** — the 8-K may not appear immediately after the company posts results.
   If the first fetch returns empty, retry every 2-3 min.

2. **Press release format change** — if extraction is unclear on a metric,
   note it explicitly in actuals.json with a "format_uncertain": true flag
   rather than guess.

3. **Metric name mismatch** — actuals.json metric names must match the
   preview's KPI table column names. Use the exact strings from
   `digest_baseline.json.kpi_tables`. The runner's `_match_baseline_row`
   does fuzzy substring matching but exact match is safer.

4. **Pandoc $ math bug** — runner uses `--from markdown-tex_math_dollars`.
   If table rows go missing in PDF, that's the cause — verify the flag
   is in the pandoc command.

5. **No deck on 8-K** — some companies file only the press release. If you want deck
   commentary, manually fetch via WebFetch from the company IR site (`ir_deck_url`).
