# Earnings Analysis Agent (Slim / Personal Edition)

A portable, single-user earnings-analysis agent that runs on **free data sources
only** — no paid market-data terminals, no institutional MCP feeds, no shared
infrastructure. Point it at a ticker, drop in whatever source material you have,
and it produces a structured earnings preview/recap as a PDF + markdown.

This is a slimmed, genericized fork of an institutional earnings workflow. All
firm-, person-, and company-specific content has been removed; everything paid
(consensus terminals, portfolio-analytics feeds, filings APIs) has been replaced
with free equivalents or manual inputs.

---

## What it does — the 4 stages

| Stage | Trigger | Inputs | Output |
|-------|---------|--------|--------|
| 1 — Prep | `prep earnings for {TICKER}` | key_metrics.yaml, consensus.csv, prior transcripts, optional thesis | Pre-earnings preview PDF: expectations, KPI sensitivities, what-to-watch |
| 2 — Rapid Digest | `digest {TICKER} print` | press release / 8-K, consensus | Fast post-print read: beats/misses vs consensus |
| 3 — Recap 1 | `recap {TICKER} call` | transcript + press release | Claim-by-claim thesis update, guidance read, tone |
| 4 — Recap 2 | `deep recap {TICKER}` | 10-Q/10-K + replay | Forensic review: quality of earnings, working capital, FCF |

Every output is run through a deterministic **audit gate** (numeric provenance,
freshness, arithmetic consistency, style) before it's considered final.

---

## Data model — everything is free or provided by you

| Input | How you get it (free) |
|-------|------------------------|
| SEC filings (10-K / 10-Q / 8-K, earnings release) | Auto-pulled by `scripts/edgar_fetch.py` from SEC EDGAR (no key) |
| Stock price / earnings reaction | Auto-pulled by `stock_reaction_helper.py` (Yahoo Finance) |
| Consensus estimates | You enter them into `consensus.csv` (see `input-formats.md`) |
| Earnings-call transcript | Company IR site / free transcript sources → `transcript.txt` |
| Sell-side notes (optional) | Whatever broker PDFs you personally have → `Reference Files/{TICKER}/sell_side_notes/` |
| Your position / notes (optional) | `position.json` / `research_notes/` in the workspace |

Nothing is fabricated: a missing input shows up as a visible "not provided"
placeholder, never a silent guess.

---

## Setup

Requires Python 3.10+. Install the optional rendering/data dependencies:

```bash
pip install pyyaml weasyprint yfinance jsonschema
# PDF rendering also needs pandoc on your PATH: https://pandoc.org/installing.html
```

(The core checks run without weasyprint/pandoc; you just won't get PDFs.)

Set a contact string for SEC EDGAR (their fair-access policy asks callers to
identify themselves):

```bash
# PowerShell
$env:SEC_USER_AGENT = "Your Name your@email.com"
# bash
export SEC_USER_AGENT="Your Name your@email.com"
```

---

## Workspace layout

Each ticker gets one folder under `workspace/`:

```
workspace/
  XYZ/
    config.yaml          # ticker config (auto-generatable, then you review)
    key_metrics.yaml     # which metrics matter for this name
    consensus.csv        # consensus estimates you entered
    transcript.txt       # earnings-call transcript (when available)
    filings/             # 10-K/10-Q/8-K extracts (filled by edgar_fetch.py)
    synthesis/           # sell-side synthesis (if you have broker PDFs)
    outputs/             # the PDFs + markdown the agent produces
    data/                # internal provenance manifest
```

Source material you want the agent to read goes under
`Earnings Analysis Agent/Reference Files/{TICKER}/` — copy the provided
`_TEMPLATE/` folder to start.

---

## Quick start

```bash
cd "Earnings Analysis Agent"

# 1. Pull free SEC filings for the ticker
python scripts/edgar_fetch.py --ticker XYZ

# 2. (Optional) auto-generate a draft config.yaml from the 10-K business section
python scripts/standalone_config_gen.py --ticker XYZ

# 3. Enter consensus into workspace/XYZ/consensus.csv (see input-formats.md)

# 4. Run the prep stage
python earnings_stage1_runner.py --ticker XYZ --earnings-date 2026-04-29 --report-time AMC
```

Or drive the full preview pipeline stage-by-stage:

```bash
python scripts/preview_runner.py --ticker XYZ --mode standalone --all
```

`--mode standalone` skips the interactive "your view" questions and produces a
defensible first-pass from primary sources alone. `--mode symbiotic` (default)
pauses to ask for your decision/score/variant.

---

## Key files

- `Earnings Analysis Agent/SKILL.md` — the agent's operating spec (read this first).
- `Earnings Analysis Agent/PREVIEW_AGENT_SPEC.md` — preview workflow.
- `Earnings Analysis Agent/DIGEST_AGENT_SPEC.md` — post-print digest workflow.
- `Earnings Analysis Agent/input-formats.md` — exact input file formats.
- `Earnings Analysis Agent/scripts/` — the runner + helper scripts.

## Running the tests

```bash
cd "Earnings Analysis Agent"
pytest
```

## What this edition does NOT include

- No paid terminals (consensus, fundamentals, vol surface) — enter what you need manually.
- No portfolio-analytics / position feed — drop an optional `position.json` if you track one.
- No shared dashboard or multi-analyst workspace — it's single-user, local-only.
