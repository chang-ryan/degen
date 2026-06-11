# Input File Format Specifications

## consensus.csv — Manually-Entered Consensus Format

You enter consensus estimates by hand (from any free source) into `workspace/{TICKER}/consensus.csv`.

### Default Column Mapping
The agent ships with this default assumed column structure:
```
Ticker | Metric | Period | Mean | High | Low | N_Estimates | As_Of_Date
XYZ    | SALES  | 2026Q1 | 38100 | 39200 | 36800 | 42 | 2026-02-22
```

### Column Mapping Abstraction
**Your CSV may use different column headers.** The agent resolves columns via the `column_mapping` section in `key_metrics.yaml`. If your CSV uses different headers (e.g., `Number of Estimates` instead of `N_Estimates`), update the mapping there — no code changes needed.

Default mapping (override in `key_metrics.yaml` → `column_mapping`):
```yaml
column_mapping:
  ticker: "Ticker"           # Column containing the ticker symbol
  metric: "Metric"           # Column containing the metric field name (SALES, EPS, etc.)
  period: "Period"           # Column containing the fiscal period (2026Q1, FY2026, etc.)
  mean: "Mean"               # Consensus mean estimate
  high: "High"               # Highest estimate
  low: "Low"                 # Lowest estimate
  n_estimates: "N_Estimates" # Number of contributing estimates
  as_of_date: "As_Of_Date"  # Date consensus was last updated
```

If a mapped column name is not found in the CSV headers, the agent **HALTs** with an error listing expected vs. actual column names and instructs the user to update `column_mapping` in `key_metrics.yaml`.

### Validation Checks
1. `as_of_date` must not be more than 7 days before earnings date — **WARN** if stale (proceed)
2. `n_estimates` < 3 for any key metric — **WARN** as thin coverage (proceed)
3. All columns in `column_mapping` must resolve to actual CSV headers — **HALT** if any are missing
4. `mean` values must be numeric — **HALT** if non-numeric values found in mean column
5. Delimiter auto-detection: try comma first, then pipe, then tab. If none parse cleanly, **HALT** with error.

## stock_reaction.json — Required Schema
```json
[{
  "ticker": "XYZ",
  "earnings_date": "2026-02-26",
  "report_time": "AMC",
  "pre_earnings_close": 131.50,
  "afterhours_move_pct": 3.2,
  "next_day_open": 135.80,
  "next_day_close": 133.60,
  "next_day_move_pct": 1.6,
  "sector_etf": "XLK",
  "sector_etf_next_day_move_pct": 0.4,
  "spy_next_day_move_pct": 0.1,
  "implied_move_options": 7.5,
  "notes": "optional free text"
}]
```

### Population Method
Use `stock_reaction_helper.py` to auto-pull price data from Yahoo Finance:
```bash
python stock_reaction_helper.py XYZ 2026-04-23 AMC --sector-etf XLV --implied-move 5.2
```
- Price data (pre-close, next-day open/close, SPY, sector ETF) is auto-populated
- `implied_move_options` must be provided manually via `--implied-move` — the script cannot reliably scrape options data
- Use `--append` to add new earnings to an existing `stock_reaction.json` (preserves history)

If `stock_reaction.json` is absent or all entries have `null` price fields, the algorithmic reaction assessment section will be skipped with a warning.

### Notes Field
The `notes` field is optional free text. If present, it is:
- Included verbatim in the Algorithmic Reaction Assessment narrative section of the PDF (Section 4)

## thesis_snapshot.md — Required Structure
The agent expects the thesis document to follow this structure for pillar-by-pillar mapping:
```markdown
## Thesis Statement
[1-2 sentence core thesis]

## Thesis Points
1. [Discrete, falsifiable claim 1]
2. [Discrete, falsifiable claim 2]
3. [Discrete, falsifiable claim 3]

## Key Drivers to Monitor
- [Specific KPI or event 1]
- [Specific KPI or event 2]

## Bear Case
[What would make this thesis wrong]

## Expected Catalysts
- [Catalyst 1 with rough timing]

## Current Confidence Level
[High / Medium / Low] — [rationale]
```

If the thesis document doesn't follow this structure, the agent will produce a lower-quality thesis mapping. It will flag this and prompt you to restructure.

## Prior Transcripts — Naming Convention
```
workspace/{TICKER}/transcripts/
├── {TICKER}_prev1.txt    # most recent prior quarter
├── {TICKER}_prev2.txt    # 2 quarters ago
├── {TICKER}_prev3.txt    # 3 quarters ago
...
└── {TICKER}_prev8.txt    # 8 quarters ago (oldest)
```

### Transcript Format
Transcripts (from the company IR site or free transcript sources) often include boilerplate that must be handled during parsing. Typical structure:

```
───────────────────────────────────────────
COMPANY NAME
Event: Q4 2025 Earnings Call
Date: February 26, 2026
───────────────────────────────────────────
CORPORATE PARTICIPANTS
  Jane Smith, Chief Executive Officer
  John Doe, Chief Financial Officer
───────────────────────────────────────────
CONFERENCE CALL PARTICIPANTS
  Analyst Name, Firm Name
  ...
───────────────────────────────────────────
PRESENTATION
───────────────────────────────────────────
Operator

Good morning. Welcome to the Q4 2025 earnings conference call...

Jane Smith, Chief Executive Officer

Thank you, Operator. Good morning everyone...
...
───────────────────────────────────────────
QUESTIONS AND ANSWERS
───────────────────────────────────────────
Operator

Our first question comes from Analyst Name with Firm Name.

Analyst Name, Firm Name

Thanks for taking my question...
...
───────────────────────────────────────────
Operator

This concludes today's conference call. Thank you for participating.
───────────────────────────────────────────
```

### Parsing Rules (Canonical — agent-logic.md references this section)
1. **Strip header block**: Everything before the `PRESENTATION` section header — company identifier, date, participant lists, disclaimers are metadata, not analysis content
2. **Strip footer block**: Everything after the closing operator statement ("This concludes today's conference call" or similar) — post-call boilerplate and copyright notices
3. **Strip page markers**: Lines matching `Page N` or pagination artifacts
4. **Strip disclaimer blocks**: Any remaining "forward-looking statements", "safe harbor", or legal disclaimer language not already caught by Rule 1
5. **Handle formatting artifacts**: Double-spaced lines, em-dash separator lines (`───`), and excess blank lines between speakers should be collapsed to single newlines
6. **Normalize speaker labels**: When the source uses `Full Name, Title` on its own line, normalize to `SPEAKER_NAME:` format for consistent cross-quarter comparison.
7. **Preserve section boundaries**: `PRESENTATION` and `QUESTIONS AND ANSWERS` headers delineate prepared remarks from Q&A. Tag each passage with its section for the language change log.

## guidance/ directory — Prior Guidance Documents
Same naming convention as transcripts. Used for guidance history analysis (Appendix B of pre-earnings memo).
