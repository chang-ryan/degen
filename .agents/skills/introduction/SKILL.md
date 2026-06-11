---
name: introduction
description: Introduce the degen toolkit — what this repo is, what it can do, and how to drive it. Use when the user (or a newcomer) asks what this app is, what they can do here, how to get started, or for a tour/overview of the system.
---

# Introduction — what degen is and what it can do

Give the user a tour grounded in the *current* state of the repo (read the files
below before describing them — don't recite this skill verbatim). Tailor depth
to the asker: a newcomer gets the philosophy + the three commands; the owner
asking "what can this do again?" gets the capability list.

## The one-paragraph pitch

degen is a local, Claude-Code-native trading system for a high-variance,
2–6 month options book. It does two jobs: **validate theses** (rule-based
entries, written invalidations, primary-source verification) and produce
**daily debriefs** that flag invalidations, supporting evidence, and entry
points. The edge it enforces is discipline, not signals — the code is the
guardrail, the markdown is the memory, the LLM writes the narrative. All data
is free/no-key (yfinance, FRED, SEC EDGAR, CNN F&G).

## The system in three layers

1. **Rules & memory (markdown)** — `CONSTITUTION.md` (risk rules — the gate),
   `MACRO.md` (weekly worldview), `POSITIONS.md` / `WATCHLIST.md` (live book +
   triggered candidates), `JOURNAL.md` (closed trades / edge measurement),
   `docs/INDEX.md` → theses (frontmatter + invalidation sections), dated
   inputs, daily briefs.
2. **Instruments (Python, `uv run python -m ...`)** —
   - `degen.daily` — the daily brief: macro regime, momentum/crowding legs,
     SPX-wide breadth (all 503 names), CTA threshold distances, Mag7
     concentration, per-ticker book tables → `docs/daily/YYYY-MM-DD.md`.
   - `degen.macro` — standalone regime verdict (credit/vol/breadth stress).
   - `degen.dashboard <TICKER>` — per-ticker pre-trade gate input (IV/HV, rank,
     skew, term structure, earnings dates).
   - `degen.edgar --ticker X` — SEC filings + exhibits (10-K/10-Q/8-K incl.
     earnings press releases) for primary-source thesis validation.
   - `degen.size` / `degen.heat` — CONSTITUTION sizing + correlation-netted
     portfolio heat. `degen.iv_store` — self-built IV rank history.
3. **Workflows (skills)** — `daily-debrief` (run the numbers, write the team
   memo, fold in tweets/articles); this introduction; more in
   `HANDOFF.md` §3 (built vs to-build).

## What the user can ask for (examples)

- "Run the daily debrief" → the full brief + narrative memo.
- "How does thesis X hold up against new data?" → re-read the thesis,
  check invalidation levels vs the tape, pull filings if earnings-related.
- "Put together a thesis on TICKER" → `docs/theses/_template.md` house style:
  evidence, real risks, invalidation levels, structure considerations.
- "Should I enter X / what's the size?" → dashboard + CONSTITUTION gate +
  sizing/heat math. (Numbers and rules, not advice.)
- "File this note/tweet/article" → dated `docs/inputs/` file linked to the
  theses it informs.
- Pre-trade checks, options-structure comparisons, EDGAR pulls, watchlist
  trigger reviews, weekly MACRO refreshes, staleness audits.

## House principles to mention

- **Process > outcome** — invalidations are written before entry; the gate has
  killed trades before (see the TEAM archive) and that's it working.
- **Tools emit deterministic facts; the LLM writes the prose** — memos must
  stay honest to the signal-digest numbers.
- **Measurement discipline** — breadth needs a representative sample, F&G is
  contrarian, pair-ratios are indicative; see `macro.py`'s docstring.
- **Defined risk by default; never chase parabolae; correlation is netted.**
- Start-of-session load order: `CONSTITUTION.md` + `MACRO.md` + `POSITIONS.md`
  (per `HANDOFF.md`).
