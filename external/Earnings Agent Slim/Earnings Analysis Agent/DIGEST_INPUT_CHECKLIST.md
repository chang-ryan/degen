# Digest Agent — Input Checklist

The digest agent runs in two stages, sequentially. Stage 1 starts when
the print hits; Stage 2 starts when the transcript is dropped.

## Stage 1 — Post-Print, Pre-Call

### What the agent needs from you
Most inputs are auto-pulled. Your inputs:

- [REQUIRED] Confirm the ticker and period being digested
  (e.g., `digest XYZ print` for C1Q26)
- [OPTIONAL] Override the post-print action recommendation
  (the agent will draft HOLD/ADD/TRIM/EXIT — you can change before delivery)
- [OPTIONAL] Provide pre-print read updates if anything has changed
  vs the preview's framing in the last 24 hours
- [OPTIONAL] Drop any post-print desk / fast-money commentary
  into `Reference Files/{TICKER}/post_print/` for the agent to incorporate

### What the agent auto-pulls
- The most recent preview output (parsed as the comparison spine)
- The 8-K filed today via the EDGAR fetcher (`python scripts/edgar_fetch.py --ticker {TICKER}`, Item 2.02)
  - Press release (Exhibit 99.1)
  - Slide deck (Exhibit 99.2 if filed)
  - Prepared remarks (Exhibit 99.3 if filed)
- IR website fallback for tickers that file deck only on IR site
- consensus.csv (the cons baseline used by the preview, entered manually)
- positioning.json if present (SI, implied move, surprise→price corr — all OPTIONAL)
- key_metrics.yaml (metric definitions)
- /guidance/ folder (prior 6Q guidance for delta math)

### Trigger
```
digest [TICKER] print
```

The agent does not poll. Trigger manually after seeing the headline cross.

---

## Stage 2 — Transcript-Integrated, Post-Call

### What the agent needs from you
- [REQUIRED] Drop the earnings call transcript file into
  `workspace/{TICKER}/transcripts/`
  (filename pattern: `{TICKER}_{period}_transcript.txt`)
- [OPTIONAL] Free-form notes / impressions from the call
  (drop into `transcripts/{TICKER}_{period}_notes.md`)
- [OPTIONAL] Override the updated action recommendation

### What the agent auto-pulls
- digest_v1_print_*.md and digest_v1_print_*.json (Stage 1 read)
- The new transcript file
- Last 2 prior transcripts (for language change detection)

### Trigger
```
digest [TICKER] transcript
```

---

## Per-ticker config (one-time setup)

Stored at `workspace/{TICKER}/config.yaml`:

```yaml
ticker: TICKER
ir_deck_url: https://...   # IR site fallback for tickers that file PR-only
historical_print_pattern: "AMC | T+0 | ~16:05 ET"
files_deck_in_8k: false   # some companies true, some false
files_prepared_remarks: false   # some companies true, some false
```

If `ir_deck_url` is missing, the agent will skip the deck-fetch step
and note it in the digest. Press release alone is sufficient for
most companies.

---

## Outputs delivered

### Stage 1
- `workspace/{TICKER}/outputs/digest_v1_print_{period}_{YYYYMMDD}.md`
- `workspace/{TICKER}/outputs/digest_v1_print_{period}_{YYYYMMDD}.pdf`
- `workspace/{TICKER}/outputs/digest_v1_print_{period}_{YYYYMMDD}.audit.json`

### Stage 2
- `workspace/{TICKER}/outputs/digest_v2_transcript_{period}_{YYYYMMDD}.md`
- `workspace/{TICKER}/outputs/digest_v2_transcript_{period}_{YYYYMMDD}.pdf`
- `workspace/{TICKER}/outputs/digest_v2_transcript_{period}_{YYYYMMDD}.audit.json`

Stage 1 markdown/PDF is preserved unmodified. Stage 2 references it but
does not overwrite.
