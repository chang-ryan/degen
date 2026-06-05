---
name: daily-debrief
description: Generate the daily market debrief — run degen.daily for the numbers, then write the narrative team memo and fold in qualitative inputs (X posts, articles). Use when the user asks for the daily brief/debrief/market read, or a fresh look at the tape.
---

# Daily debrief

Produce `docs/daily/YYYY-MM-DD.md`: a numbers-only macro + book snapshot with a hand-written team memo on top. The tool emits the data and a memo placeholder; you write the prose.

**The debrief is fully self-contained — it needs no external input.** Run it standalone every time. External context (tweets, articles) is *optional enrichment*: ask the user once whether they have any to fold in; if not, finish the debrief from the numbers alone and leave the qualitative section as its placeholder. Never block or wait on external info.

## Steps

1. **Generate the brief.** Run `uv run python -m degen.daily` (full book from `tickers.txt`, ~3 min — it pulls ~34 names + macro/momentum/Mag7 panels). For an ad-hoc subset: `uv run python -m degen.daily CRM TEAM`. Note: re-running **overwrites** the file, wiping any memo/qualitative edits — so generate first, then write prose.

2. **Write the memo.** Replace the `<!-- MEMO: ... -->` placeholder under `## Synopsis` with a brief, dense narrative (team-memo voice, "numbers only, not advice"). It must be grounded in the signal-digest line directly below it — keep the prose honest to those numbers. Cover, in flowing prose (not bullets):
   - **Surface vs internals** — regime verdict, VIX/credit (the calm) against breadth/momentum/Mag7 (the internals).
   - **The momentum unwind state** — how far legs are off their 63d highs (`off-hi`), how much run is left (`run63`), how many are basing (`5d ≥ 0`). Call out the most stretched sleeve.
   - **Where the day's damage clustered** — scan the book table for the worst sub-groups (power semis, memory, optics, miners) and whether the cyclical barbell (NAIL/XHB, energy) held.
   - **Mag7 concentration** — breadth (n/7 above 50dma); are the leaders propping the tape or rolling.
   - **Net / so-what** — positioning shakeout vs macro contagion, and whether the entry window is open.

3. **Qualitative inputs (optional — ask first).** After the memo is written, ask the user once: *"Any tweets or articles to fold in, or ship as-is?"* — then:
   - If they share an X post: pull text with `degen.daily.fetch_xpost(url)` and add it under `## Qualitative inputs` as a blockquote (author/handle/date) plus a one-line `_Read:_` tying it to today's signals. Same for articles/sellside notes they paste.
   - If they have nothing: leave `## Qualitative inputs` as its placeholder and finish. The debrief is complete on the numbers alone.

## The read framework (entry/abort logic)

The book is high-leverage long-premium; the standing question is *when* to enter the momentum drawdown, not whether. See memory `project-momo-unwind`.

- **Dip-buy window opens** when leadership legs base (5d ≥ 0) *while* VIX settles / VIX term-structure re-contangos *and* credit stays calm (HY OAS low, HYG flat).
- **Abort the constructive read** if credit cracks *first* (the macro-contagion path — the big 63d factor gains become downside fuel), or if Mag7 breadth slips toward 3-4/7 (the concentrated prop coming out from under the index).
- Don't buy long calls into a falling factor + rising IV (double jeopardy); prefer defined-risk or selling premium on names you'd want to own.

## Notes

- All data is free/no-key (yfinance, FRED CSV, CNN F&G). FRED series flake per-series (NFCI/TIPS/Wilshire often time out → render `n/a`); that's expected, not a bug.
- Promote anything durable from a daily page into an `inputs/YYYY-MM/` file linked from a thesis — the daily pages are dated scratch.
