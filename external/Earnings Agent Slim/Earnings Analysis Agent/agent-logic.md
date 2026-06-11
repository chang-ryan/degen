# Agent Logic Flow — Earnings Analysis Agent

## Input Directory Structure
```
workspace/{TICKER}/
├── key_metrics.yaml              # per-ticker metric config (REQUIRED)
├── consensus.csv                 # manually-entered consensus (REQUIRED for pre-earnings)
├── thesis_snapshot.md            # current thesis document (optional but important)
├── stock_reaction.json           # required for algorithmic reaction assessment
├── press_release.txt             # post-earnings: earnings release
├── transcript.txt                # post-earnings: earnings call transcript
├── guidance/
│   ├── {TICKER}_prev1.txt        # prior guidance documents
│   └── {TICKER}_prev2.txt
├── transcripts/
│   ├── {TICKER}_prev1.txt        # prior quarter transcripts (up to 8)
│   └── {TICKER}_prev2.txt        # ... through prev8
└── outputs/
    ├── pre_{TICKER}_{DATE}.pdf
    ├── post_{TICKER}_{DATE}.pdf
    └── post_{TICKER}_{DATE}.md
```

## Step -1: Bootstrap (First Run for a Ticker)
If `workspace/{TICKER}/key_metrics.yaml` does not exist:
1. Check if `consensus.csv` exists
2. If yes: auto-generate `key_metrics.yaml` from CSV headers:
   - Parse the `Metric` column (or mapped equivalent) to extract all available metric names
   - Map field names to `universal_metrics` and `industry_kpis` lists
   - Set `transcript_quarters: 8` and `guidance_quarters: 6` as defaults
   - Write the generated file to `workspace/{TICKER}/key_metrics.yaml`
   - **HALT**: Display the generated file to the user and prompt: "key_metrics.yaml auto-generated from consensus CSV. Review and edit before proceeding. Continue? [y/n]"
   - Do NOT proceed to analysis until user confirms
3. If no CSV exists either: **HALT** with error: "Cannot bootstrap — neither key_metrics.yaml nor consensus.csv found for {TICKER}. Create key_metrics.yaml manually or provide consensus data."

## Step 0: Validation
Before any analysis:
1. Check `key_metrics.yaml` exists and parses cleanly → **HALT if missing or unparseable** (run Step -1 bootstrap first)
2. Check `consensus.csv` exists (if pre-earnings mode) → **HALT if missing** — this is a required input for pre-earnings. Error: "consensus.csv not found. Cannot run pre-earnings analysis without consensus data."
3. Apply column mapping from `key_metrics.yaml` → `column_mapping` section to resolve CSV column headers. If mapping fails (expected columns not found), **HALT** with error listing expected vs. actual column names.
4. Check `as_of_date` field: flag if > 7 days before earnings date (stale consensus warning, but proceed)
5. Check `N_estimates` < 3 for any metric → flag as thin coverage warning (proceed)
6. Count available prior transcripts — note how many of 8 quarters are present (proceed with whatever is available; minimum 0)
7. Warn if `thesis_snapshot.md` is missing (analysis proceeds but thesis mapping will output "not_applicable")
8. Log all warnings at top of output before analysis begins
9. For post-earnings mode: also validate `transcript.txt` and `press_release.txt` exist → **HALT if either is missing**

### Halt vs. Proceed Decision Matrix
| Condition | Action |
|-----------|--------|
| `key_metrics.yaml` missing or unparseable | **HALT** — run bootstrap or fix manually |
| `consensus.csv` missing (pre-earnings) | **HALT** — required input |
| `consensus.csv` column mapping fails | **HALT** — fix mapping in key_metrics.yaml |
| `transcript.txt` missing (post-earnings) | **HALT** — required input |
| `press_release.txt` missing (post-earnings) | **HALT** — required input |
| `consensus.csv` stale (>7 days) | **WARN** and proceed |
| Thin coverage (N_estimates < 3) | **WARN** and proceed |
| `thesis_snapshot.md` missing | **WARN** — thesis sections output "not_applicable" |
| `stock_reaction.json` missing | **WARN** — skip algorithmic reaction section |
| Prior transcripts < 8 quarters | **WARN** — use whatever is available |
| Prior transcripts = 0 | **WARN** — skip language change detection entirely |

## Step 1: Pre-Earnings Mode
### 1a. Expectations Stack Construction
For each key metric (from `key_metrics.yaml`):
- Extract: consensus mean, range (high/low), last guidance, implied bar assessment
- Assess where consensus is above/below last guidance (management setpoint)
- Flag coverage (N_estimates < 3 = thin coverage warning)

### 1b. Key Debates
Identify 3–5 contested areas where thesis has meaningful bull and bear case. For each:
- State the debate clearly
- Construct bull interpretation
- Construct bear interpretation
- State thesis relevance (which thesis pillar this maps to, if `thesis_snapshot.md` available)

### 1c. What to Watch
For each key metric and key debate:
- Affirmative triggers (language that confirms thesis)
- Risk triggers (language that challenges thesis)
- Omission flags (topics management should address but might not)
- Derive watch items from prior transcript analysis, not generic platitudes
- This is one of the highest-value deliverables — don't make it generic

### 1d. KPI Sensitivity Table
For each primary metric:
- Bear/Base/Bull scenario values
- For each scenario: estimate quantitative range of stock reaction (if `stock_reaction.json` history available)
- Assess what's priced in

### 1e. Positioning Context (if inputs provided)
- Whisper delta (if provided)
- Short interest (if provided)
- Options skew / implied move (if provided)
- Note what is and isn't available

### 1f. Pre-Earnings Output
- Generate pre-earnings HTML using the template structure in `pre-earnings-output.md`
- Convert HTML → PDF via weasyprint: `weasyprint input.html output.pdf`
- Save both PDF and markdown to `workspace/{TICKER}/outputs/`
- Filename: `pre_{TICKER}_{EARNINGS_DATE}.pdf` and `pre_{TICKER}_{EARNINGS_DATE}.md`
- Note: the markdown output includes the full watch list — this is read automatically in post-earnings mode

## Step 2: Post-Earnings Mode

### 2-pre. Pre-Earnings Watch List Retrieval (Automatic)
Before starting post-earnings analysis, retrieve the pre-earnings watch list:
1. Scan `workspace/{TICKER}/outputs/` for files matching `pre_{TICKER}_*.md`
2. Sort by date descending, take the most recent
3. Extract the watch list (affirmative triggers, risk triggers, omission flags)
4. Also extract the expectations stack and key debates for comparison
5. If no pre-earnings output exists: **WARN** — "No pre-earnings output found. Watch list comparison will be skipped. Language change detection will proceed without watch list context." Proceed with analysis but mark all watch-list-dependent sections as "pre-earnings watch list unavailable."

### 2a. Line-Item Comparison
- Load expectations from the most recent pre-earnings output (or re-derive from consensus CSV if pre-earnings output unavailable)
- For each key metric: compare actual vs consensus mean
- Beat/miss/in-line classification — define thresholds in `key_metrics.yaml`
- Magnitude: absolute and % vs consensus
- Segment breakdown where applicable

### 2b. Language Change Detection
- For each key topic in the watch list (from Step 2-pre):
  - Pull current transcript language on that topic
  - Compare to prior 8 quarters on same topic
  a. Changed: what shifted and direction
  b. New: topics introduced this quarter not present before
  c. Absent: topics expected (from watch list) that management did NOT address
- Language comparison requires fixed 8 quarters, not rolling 12 months (user calibration)
- Flag absent guidance as a signal, not a neutral data point

#### Transcript Parsing
Transcripts contain boilerplate that must be stripped before analysis. Canonical parsing rules are in `input-formats.md` → "Parsing Rules" section. Summary for quick reference:
1. **Strip header block**: Everything before the `PRESENTATION` section header (company identifier, date, participant lists, disclaimers)
2. **Strip footer block**: Everything after the closing operator statement ("This concludes today's conference call" or similar), including copyright notices
3. **Strip page markers**: Lines matching `Page N` or pagination artifacts
4. **Strip disclaimer blocks**: Any remaining "forward-looking statements", "safe harbor", or legal disclaimer language not already caught by Rule 1
5. **Handle formatting artifacts**: Collapse double-spaced lines, em-dash separator lines (`───`), and excess blank lines between speakers to single newlines
6. **Normalize speaker labels**: When the source uses `Full Name, Title` on its own line, normalize to `SPEAKER_NAME:` format for consistent cross-quarter comparison.
7. **Preserve section boundaries**: `PRESENTATION` and `QUESTIONS AND ANSWERS` headers delineate prepared remarks from Q&A. Tag each passage with its section.

#### Absent Topic Matching Logic
To determine whether a watch list item was "addressed" in the transcript:
1. For each watch item, extract 3-5 key terms (e.g., for "channel momentum" → ["channel", "momentum", "demand", "volume"])
2. Search the transcript for passages containing 2+ of those key terms within a 500-word window
3. If found: mark as "addressed" and extract the relevant passage with speaker and context
4. If NOT found: mark as "absent" — this is a signal, not neutral
5. For borderline cases (only 1 key term found, or tangentially related passage): mark as "partially addressed" and include the closest passage for analyst review
6. This is keyword + proximity matching, not semantic similarity — keeps it deterministic and auditable

### 2c. Algorithmic Reaction Assessment
- Map fundamental surprise composite across key metrics (beat/miss/in-line)
- Compare actual stock move to implied move (from `stock_reaction.json`)
- Compare vs sector ETF and market move
- Flag if reaction appears disconnected from fundamentals
- Output: "Revenue beat 1.1%, GM missed 80bps, stock +8% — reaction pricing in revenue beat, not penalizing margin miss"
- Do NOT render a verdict on whether the reaction is justified — provide the data and let analyst make the call

### 2d. Thesis Status
- Map each result to thesis pillar (from `thesis_snapshot.md`)
- Classification per pillar: confirming / neutral / threatening / ambiguous
- Aggregate to overall thesis status: Green / Yellow / Red
- Generate thesis update as **diff with commentary**:

#### Thesis Diff Format
The thesis update draft must be structured as a section-by-section diff against the current `thesis_snapshot.md`:
```
## Thesis Update Draft — {TICKER} Q{N} {YEAR} Earnings
Status: DRAFT — requires user confirmation before push

### Changes to: Thesis Points
CURRENT (Point 2): "Core segment growing at 15%+ driven by new-customer adoption"
PROPOSED: "Core segment growth decelerating — management shifted language from 'strong momentum' to 'normalizing' over Q2-Q4. Revised to mid-single-digit growth expectation."
RATIONALE: Three consecutive quarters of weakening language (cited: transcript Q2 p.4, Q3 p.5, Q4 p.3). Revenue beat but core segment missed by 180bps. Watch list item "core segment language" flagged as changed.

### Changes to: Current Confidence Level
CURRENT: "High — strong execution across all segments"
PROPOSED: "Medium — execution on revenue/EPS but core segment inflection emerging. Confidence contingent on Q1 segment data."
RATIONALE: Mixed signals — headline beat but thesis-critical segment showing deceleration pattern.

### No Changes to: Thesis Statement, Key Drivers, Bear Case, Expected Catalysts
(No earnings data this quarter contradicted or materially updated these sections.)
```
- Prompt: "Thesis update draft ready. Review diff above. Confirm push to thesis_snapshot.md? [y/n]"
- If user confirms: apply changes to `thesis_snapshot.md`, preserving unchanged sections
- If user declines: save diff to `workspace/{TICKER}/outputs/thesis_draft_{DATE}.md` for reference

### 2e. Follow-Up Questions
- Prioritized list of questions for the management call
- Include: unanswered pre-earnings watch items, language changes requiring clarification
- Ranked by priority

### 2f. Post-Earnings Output
- Generate post-earnings HTML using the template structure in `post-earnings-output.md`
- Convert HTML → PDF via weasyprint: `weasyprint input.html output.pdf`
- Save both PDF and markdown to `workspace/{TICKER}/outputs/`
- Filename: `post_{TICKER}_{EARNINGS_DATE}.pdf` and `post_{TICKER}_{EARNINGS_DATE}.md`
- Stage thesis update diff (do NOT auto-commit) — save to `workspace/{TICKER}/outputs/thesis_draft_{DATE}.md`
- Prompt user to confirm before writing changes to `thesis_snapshot.md`

## Build Sequence Recommendation
Build and validate in this order:
1. `key_validator` — document parsing and validated check of all input types before any analysis. This is where most failure modes will live. Includes bootstrap logic for key_metrics.yaml auto-generation.
2. Pre-earnings mode — Expectations Stack (requires the consensus CSV only)
3. Post-earnings mode — line-item comparison + language diff (includes watch list auto-retrieval and transcript parsing)
4. Algorithmic reaction assessment (requires `stock_reaction.json` — use `stock_reaction_helper.py` to populate)
5. Thesis status update — map results to thesis pillar; generate thesis diff with commentary; prompt before writing to `thesis_snapshot.md`
