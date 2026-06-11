# Earnings Analysis Agent — 4-Stage Workflow

## Purpose
Four-stage agent covering the full earnings cycle: prep, rapid digest, first recap (press release + transcript), and forensic recap (10-Q/10-K + replay). Reads from a per-ticker workspace. Outputs structured PDFs (stages 1, 3, 4) and one-page markdown (stage 2). Every output is audited by the Audit Agent before delivery.

**Architecture:** see `4-stage-architecture.md` for the authoritative spec. This file supersedes the prior pre/post dual-mode design.

## Trigger Commands
- Stage 1 (Prep): `prep earnings for [TICKER]`
- Stage 2 (Rapid Digest): `digest [TICKER] print`
- Stage 3 (Recap 1): `recap [TICKER] call`
- Stage 4 (Recap 2): `deep recap [TICKER]`

## Operating Environment
- Runs locally via Claude Code
- Reads from a per-ticker workspace: `workspace/{TICKER}/`
- Outputs PDFs (stages 1, 3, 4) and markdown (stage 2) to `workspace/{TICKER}/outputs/`
- All extracted figures must be cited with source and page number
- Every output gets audited by the Audit Agent before delivery

## Free Data Sources
This agent uses only free/manual data sources:
- **Print date & headline KPIs:** the company IR site / latest 8-K
- **Consensus estimates:** entered manually into `workspace/{TICKER}/consensus.csv`
- **Sector/peer classification:** keyword-based, from the 10-K business + competition sections
- **Transcripts:** the company IR site or free transcript sources
- **SEC filings:** the free EDGAR fetcher — `python scripts/edgar_fetch.py --ticker {TICKER}` writes 10-K/10-Q/8-K extracts to `workspace/{TICKER}/filings/`
- **Short interest / implied move:** OPTIONAL manual inputs (stub if absent)
- **Position data:** OPTIONAL local `workspace/{TICKER}/position.json` the user may provide
- **Research notes:** OPTIONAL local `workspace/{TICKER}/research_notes/` folder

## PDF Generation Method
HTML → PDF via **weasyprint** (Python). The agent writes a styled HTML document, then converts it to PDF using weasyprint.

```bash
pip install weasyprint --break-system-packages
```

Generation flow:
1. Agent builds HTML string using the templates defined in `pre-earnings-output.md` / `post-earnings-output.md`
2. Agent writes HTML to a temp file
3. Agent calls weasyprint to render PDF
4. PDF saved to `workspace/{TICKER}/outputs/`
5. Temp HTML file deleted after successful PDF generation

## Reference Files
Read these in order before executing:
1. `4-stage-architecture.md` — authoritative 4-stage spec
2. `agent-logic.md` — step-by-step execution workflow
3. `key-metrics-schema.md` — how to parse key_metrics.yaml
4. `input-formats.md` — per-stage input contract
5. Stage-specific output specs:
   - `stage-1-output.md` — Prep output structure
   - `pre-earnings-output.md` / `post-earnings-output.md` — output structure references
6. `stock_reaction_helper.py` — utility script for Stage 2 rapid digest (stock reaction delta)

## Mode Detection
The agent auto-detects mode based on which files are present in `workspace/{TICKER}/`:
- If `transcript.txt` AND `press_release.txt` are present → **Post-earnings mode**
- If neither is present but `consensus.csv` is present → **Pre-earnings mode**
- If both or neither are present ambiguously → prompt user to clarify

## Critical Design Principles
1. **Every number must be cited**: source file + page/line. No exceptions.
2. **Flag what management didn't address** relative to the pre-earnings watch list.
3. **Language change detection is mandatory**: compare to prior 8 quarters of transcripts.
4. **Detect omissions and hedging**, not just what was said.
5. **Stale consensus check**: flag if `consensus.csv` has `as_of_date` more than 7 days before earnings date.
6. **Thesis update requires confirmation**: never auto-push to `thesis_snapshot.md`. Always stage and prompt.
7. **Algorithmic reaction assessment**: requires `stock_reaction.json` — if absent, skip that section and note it.

## Calibration (User Preferences)
- **Universal metrics**: Revenue, gross margin, EBITDA, FCF, EPS
- **Industry KPIs**: Company/sector-specific (system placements, NRR, churn, SSS, ASP, etc.) — defined in `key_metrics.yaml`
- **Consensus source**: manually entered CSV (`consensus.csv`). Column mapping configured in `key_metrics.yaml` under `column_mapping`. Agent ships with a default mapping; update if your CSV format differs.
- **Transcript format**: plain-text transcripts from the IR site or free transcript sources. Agent strips boilerplate (header block, disclaimers, page markers) during parsing. Speaker labels preserved.
- **Transcript comparison window**: Fixed 8 quarters (not rolling)
- **Guidance history**: 6 quarters
- **Algorithmic reaction assessment**: Yes — include both fundamental analysis AND stock reaction vs. implied move. `stock_reaction.json` populated via `stock_reaction_helper.py` (auto-pulls from Yahoo Finance). Implied move from options must be provided manually via `--implied-move` flag.
- **Post-earnings thesis update**: Stage as **diff with commentary** — show exactly what changed vs. current `thesis_snapshot.md` with rationale per change. Prompt for confirmation before writing.
- **Pre-earnings watch list comparison**: Automatic — agent reads most recent pre-earnings output from `workspace/{TICKER}/outputs/` in post-earnings mode.
- **key_metrics.yaml generation**: Auto-generated from consensus CSV headers on first run for a ticker. User reviews and edits before first analysis.
- **Sector-specific handling**: Some positions may lack meaningful EBITDA/EPS. The `universal_metrics` list in `key_metrics.yaml` supports a `skip` flag per metric per ticker. Agent skips flagged metrics gracefully — no penalty, no placeholder values.
- **PDF generation**: HTML → weasyprint (Python).
- **PDF structure**: Executive summary first, then detail, appendices last
- **Output format**: PDF (human) + markdown
