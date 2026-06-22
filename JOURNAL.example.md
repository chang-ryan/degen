# JOURNAL.example.md — copy to `JOURNAL.md` (which is gitignored)

> Your **closed-trade log** — real P&L, so the working copy `JOURNAL.md` is
> gitignored. Log every closed trade; grade the **process**, not just the P&L.
> Over enough entries this is what tells you whether there's a real edge.

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

## Quarterly rollup (fill each quarter)
- # trades / win rate / avg win / avg loss / expectancy
- % of trades that passed the gate cleanly
- Largest drawdown vs heat cap (did limits hold?)
- Edge verdict: measurable yet, or still variance? → sizing decision for next quarter
