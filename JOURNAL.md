# JOURNAL.md — Trade Log & Feedback Loop

> The most important file for the long game. Log **every** closed trade. Over enough
> entries this is what tells you whether there's a real edge or it was variance —
> which you cannot know yet. Grade the **process**, not just the P&L.

## Why this exists
A 5x year is one lucky sample. Edge-based sizing-up (Kelly et al.) requires a *measured*
win rate and payoff. This log is how you measure it. Until it shows a real track record,
sizing stays at the conservative end of CONSTITUTION.md.

## Entry template
```
### [YYYY-MM-DD → YYYY-MM-DD] <Ticker> <structure>
- Thesis (at entry):
- Catalyst + expiry:
- Invalidation (set at entry):
- Entry: price / IV rank / underlying ref
- Size: % of port (defined-risk) or naked gap-size
- Exit: price / reason (target / invalidation / time / discretionary)
- P&L: $ and % of port
- Process check: did it pass the gate? did I follow the plan? Y/N + what broke
- Lesson:
```

## Example (template demo — not a real closed trade)
```
### [2026-06-02 → 2026-06-13] USO 150P 7/17 (1)
- Thesis: Iran de-escalation deflates Hormuz oil premium → USO down.
- Catalyst + expiry: MOU sign-off / Hormuz reopening; 7/17 (past near-term events).
- Invalidation: USO new highs / re-escalation; loss capped at premium.
- Entry: bought when USO ~$150; IV elevated (war premium).
- Size: defined-risk, ~1% of port in premium.
- Exit: banked into USO ~$126 drop (oil −20% from peak on ceasefire optimism).
- P&L: +<x>$ / +<x>% of port.
- Process check: Y — defined risk, expiry past catalyst, invalidation set. Followed plan.
- Lesson: most of the move was *priced optimism*, not physical reopening; banked
  the July leg vs theta/seasonal, kept Sept for the reopening second-leg-down.
```

## Quarterly rollup (fill each quarter)
- # trades / win rate / avg win / avg loss / expectancy
- % of trades that passed the gate cleanly
- Largest drawdown vs heat cap (did limits hold?)
- Edge verdict: measurable yet, or still variance? → sizing decision for next quarter
