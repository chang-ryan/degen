# Earnings Analysis Agent — 4-Stage Architecture

**Supersedes:** the original pre/post-earnings two-mode design.

**Note:** Stage 2 (Rapid Digest) and Stage 3 (Recap 1) are full post-print analyses (~5-8 page PDF), not a ≤500-word 1-pager. See `DIGEST_AGENT_SPEC.md` for the canonical spec and `DIGEST_RUN_GUIDE.md` for the operator runbook.

The earnings workflow has four distinct stages, each with different inputs, latency targets, and outputs. Collapsing them into pre/post loses the speed-sensitivity of the post-print digest and the forensic depth of the post-10-K review. Four stages, four runner modes.

---

## Stage summary

| # | Stage | Trigger phrase | Latency | Primary inputs | Output | Size |
|---|-------|----------------|---------|----------------|--------|------|
| 1 | Prep | `prep earnings for {TICKER}` | Any time pre-print (typically T-7 to T-1) | key_metrics.yaml, consensus CSV, thesis snapshot, 8 prior transcripts, guidance history | PDF: positioning, estimates, KPI sensitivities, scenarios | ~10-15 pages |
| 2 | Rapid Digest | `digest {TICKER} print` | Under 5 min post-tape | Press release only (or 8-K + headline slide deck) | 1-page markdown: beats/misses vs consensus, algorithmic read, thesis claims touched | 1 page |
| 3 | Recap 1 | `recap {TICKER} call` | Same day | Press release + earnings call transcript | PDF: claim-by-claim thesis update, guidance read, management tone, surprise decomposition | ~5-8 pages |
| 4 | Recap 2 | `deep recap {TICKER}` | T+3 to T+7 | 10-Q/10-K + Q&A review + follow-up commentary | PDF: Schilit-style forensic review, working capital, capex/FCF quality, thesis v2 | ~8-12 pages |

Each stage runs the Audit Agent before delivery. Stages 2-4 may stage updates to `workspace/{TICKER}/thesis_current.md` — those updates require user confirmation before push.

---

## Stage design principles

### Stage 1 — Prep

**Principle:** Comprehensive. No latency pressure. Goal is to eliminate surprise — every KPI that could move the stock is analyzed for expectation vs variant vs consensus.

**Must answer:**
- What is consensus expecting (with explicit numbers)?
- What is the variant thesis expecting (from thesis_current.md)?
- Where is the spread largest, and what's the sensitivity of stock reaction?
- What are the confirming signals for each open thesis claim?
- What specific commentary should the analyst listen for on the call?
- What do the last 8 quarters tell us about management's guidance pattern + language change?

**Output structure:** Executive summary → positioning → estimates grid → KPI sensitivities → scenarios (beat/in-line/miss reaction paths) → what to watch → thesis tie-in.

---

### Stage 2 — Rapid Digest

**Principle:** Speed. Output is read on a phone within 5 minutes of the print. Format is 1-page markdown, NOT PDF. Zero narrative fluff — tables and bullets only.

**Must answer (and nothing else):**
- Did they beat/miss on each core metric? By how much vs consensus?
- Is the algorithmic read bullish/bearish/mixed?
- Which open thesis claims are directly touched by these headline numbers?
- Is there anything in the headline that demands immediate attention (guidance cut, restructuring, CEO change)?

**Hard constraints:**
- Total output ≤ 500 words
- Must be produced from press release alone (do NOT wait for transcript)
- No forward-looking analysis — that's Stage 3
- `output_tier="tier_2"` for audit (relaxed sources weighting)

(Note: the digest spec now expands Stage 2 to a full post-print analysis; see `DIGEST_AGENT_SPEC.md`. The constraints above describe the original rapid-1-pager intent, retained here for the architectural slot.)

---

### Stage 3 — Recap 1

**Principle:** Thesis-first. The call transcript tells you what management emphasized, what they downplayed, what the analyst Q&A revealed. Map every material disclosure to open thesis claims.

**Must answer:**
- For each open thesis claim (TC-01 ... TC-0N): what did this call do to the evidence?
- What did management guide? Where is the guidance vs consensus spread?
- What language changed vs the last 2 calls? (Specific word-level tracking.)
- Which analyst questions touched the most important uncertainties?
- Where did management dodge a question or give conspicuously brief answers?
- What is the recommended sizing action (TRIM / MAINTAIN / ADD / EXIT)?

**Output structure:** Executive summary + sizing rec → claim-by-claim updates → guidance delta → management tone analysis → Q&A highlights → follow-up action list.

---

### Stage 4 — Recap 2

**Principle:** Forensic. The 10-Q/10-K and the full replay expose things the transcript didn't. Quality-of-earnings, working capital cadence, off-balance-sheet detail, MD&A language scrutiny.

**Must answer:**
- Schilit forensic flags: accruals vs cash, DSO/DPO trends, revenue recognition changes
- Working capital build or release — is it organic or financing-driven?
- Capex quality — maintenance vs growth, vs depreciation
- FCF conversion vs reported net income — any gap?
- Balance sheet changes — net cash direction, debt maturities
- Off-balance-sheet items — lease commitments, contingent liabilities
- MD&A language deltas vs prior 10-Q (specific sentence-level diff if material)
- Does this filing confirm, modify, or break the variant thesis?

**Output structure:** Executive summary (forensic flags) → quality of earnings → balance sheet review → MD&A language scrutiny → thesis integrity check → updated evidence log entries → recommended thesis document revision (staged, requires analyst confirmation).

---

## Inputs required per stage

### Stage 1 inputs
- `workspace/{TICKER}/key_metrics.yaml`
- `workspace/{TICKER}/consensus.csv` (manually entered)
- `workspace/{TICKER}/thesis_current.md`
- `workspace/{TICKER}/transcripts/` (last 8 quarters)
- `workspace/{TICKER}/guidance/` (guidance history)

### Stage 2 inputs
- Press release (text or PDF)
- Consensus estimates (same CSV as Stage 1)
- key_metrics.yaml
- thesis_current.md (for claim-touch mapping)

### Stage 3 inputs
- Press release (same as Stage 2)
- Full earnings call transcript
- Consensus estimates
- key_metrics.yaml, thesis_current.md
- Prior 2 transcripts (for language change detection)

### Stage 4 inputs
- 10-Q or 10-K filing (via `python scripts/edgar_fetch.py --ticker {TICKER}` → `workspace/{TICKER}/filings/`)
- Full call replay / transcript (Q&A section prioritized)
- Prior period 10-Q/10-K (for diff)
- thesis_current.md, evidence_log.json

---

## Stage identifiers

Each stage has its own `agent_id` used in output filenames and audit records:
- `earnings-analysis-stage-1` — Prep
- `earnings-analysis-stage-2` — Rapid Digest
- `earnings-analysis-stage-3` — Recap 1
- `earnings-analysis-stage-4` — Recap 2

Each output includes the audit block per the Audit Agent spec.

---

## File reconciliation

| File | Role |
|----------|-------------|
| `pre-earnings-output.md` | → Prep output structure reference (see also `stage-1-output.md`) |
| `post-earnings-output.md` | → Post-print output structure reference |
| `agent-logic.md` | → 4-stage flow |
| `SKILL.md` | → References this file |
| `input-formats.md` | → Per-stage input contract |
| `key-metrics-schema.md` | → Schema valid across stages |
| `stock_reaction_helper.py` | → Used by Stage 2 (rapid digest) |

---

## Build order

Stage 1 first. Then Stage 2 (rapid digest). Then Stages 3 and 4. Runner code follows the skill files.
