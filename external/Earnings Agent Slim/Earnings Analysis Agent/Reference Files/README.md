# Reference Files

This folder holds the per-ticker source material the agent reads during analysis.
Everything here is **whatever you provide** — there are no paid data feeds.

## How to use

1. Copy the `_TEMPLATE/` folder and rename it to your ticker, e.g. `XYZ/`.
2. Drop the relevant source files into the subfolders (all optional — the agent
   works with whatever is present and flags what's missing).

```
Reference Files/
  _TEMPLATE/              ← copy this for each new ticker
    notes.txt             ← your own notes / thesis (free text)
    sell_side_notes/      ← broker PDFs you have access to (optional)
    transcripts/          ← prior earnings-call transcripts (1 file per quarter)
    filings/              ← 10-K / 10-Q / 8-K text (auto-filled by edgar_fetch.py)
    models/               ← your own spreadsheet/model exports (optional)
  XYZ/                    ← example: your ticker
    ...
```

## Where to get the source material (all free)

| Input | Free source |
|-------|-------------|
| 10-K / 10-Q / 8-K filings | SEC EDGAR — auto-pulled by `scripts/edgar_fetch.py`, or download from https://www.sec.gov/edgar |
| Earnings-call transcripts | Company investor-relations site, or free transcript sites |
| Consensus estimates | Manual entry into `consensus.csv` (see `input-formats.md`) |
| Stock prices / reaction | Yahoo Finance — auto-pulled by `stock_reaction_helper.py` |
| Sell-side notes | Whatever broker research you personally have access to (optional) |

Nothing in this folder is required to be present for the agent to run — missing
inputs are reported in the output rather than silently assumed.
