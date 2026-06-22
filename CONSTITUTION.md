# CONSTITUTION.md — Risk Rules & Trading Discipline

> This is the guardrail file. Every proposed trade is checked against it **before**
> sizing or execution. Edit the dials to match your own tolerances — the numbers
> below are the agreed starting framework, not law. Not financial advice.

## Account context
- **Sleeve:** speculative / high-variance "for fun" options book.
- **Size:** kept in the local (gitignored) `POSITIONS.md`, not here — any past multiple is a lucky sample, **not** a measured edge. Sizing rules below are expressed as **% of port**, so they're account-size-agnostic and this file stays shareable.
- **Broker:** live read access via the broker MCP / `degen.etrade`; the live book is reconciled into the local `POSITIONS.md`.
- **Instruments:** long options, spreads, naked options, margin, leveraged ETFs.
- **Liquidity:** no near-term need; this capital is risk-on by design and segregated from the long-term equities account.

## Core philosophy
1. **Process > outcome.** A good process can lose; a bad process can win. We grade the process, logged in JOURNAL.md.
2. **Capital preservation first.** The game now is protecting house money, not chasing the next multiple. The same leverage that built the book can round-trip it.
3. **Earn the right to size up.** Do not increase size off a lucky streak. Size up only after JOURNAL.md shows a real, measured edge over enough trades.
4. **Adversarial by default.** Every thesis must survive its own steelmanned opposite before it sizes a trade. The book-talker (you) and the agreeable assistant will both drift toward confirmation — so the standing job is to argue the *other* side, name what would prove the thesis wrong, and count whether a bearish/bullish lean has actually cost P&L. Critically constructive, never negative for its own sake: the aim is a better-tested position, not a gloomier one. (See HANDOFF §0.)

## Risk limits (the framework)
- **Defined-risk trades** (long options / spreads, where max loss = premium): risk **1–2% of total port** per trade. Start at **1%** until edge is proven.
- **Naked / margin / leveraged-ETF positions** (loss is *not* capped): size to the **gap scenario, not the expected loss.** A 2–3σ adverse overnight gap must still land **≤ ~5% of total port.** This almost always means smaller notional than instinct wants.
- **Total portfolio heat:** sum of all open max-losses **≤ ~8% of total port.**
- **Correlation rule:** count correlated positions as **one bet.** This book skews AI / semis / risk-on — those move together, so "2% × 8 names" becomes ~16% in a de-gross. Net correlated names into a single risk number against the heat cap.
- **Scaling:** as the account grows, hold or *reduce* the per-trade %; do not let absolute-dollar comfort inflate risk.

## Structural discipline (hard rules)
- **Prefer defined risk.** Naked/margin only when the edge clearly justifies the gap tail, and always gap-sized per above.
- **Every trade needs a written invalidation level** (price/date/thesis-break) before entry. No invalidation = no trade.
- **Expiry sits *past* the catalyst, never on it.** Avoid buying front-month premium into an earnings/event IV ramp and eating the crush. (Oil-puts lesson.)
- **Don't catch the knife / don't chase parabolae.** No adding to the most crowded trade in the tape (currently semis, ~99% positioning). Buy the under-owned, not the freshly-ripped.
- **Vol awareness.** Know IV rank / term structure / skew before buying premium. High IV → favor spreads (sell the rich leg) over naked longs.
- **One book.** Longs and hedges are evaluated together (barbell), not as separate bets.

## Pre-trade gate (must pass ALL before placing)
1. Thesis stated in one sentence + the catalyst + the invalidation level.
2. Structure chosen for the vol regime (defined-risk default; spread if IV is rich).
3. Expiry past the catalyst.
4. Size computed from the rules above (defined-risk %; naked/margin gap-sized).
5. Added to current heat — still ≤ 8% with correlated names netted?
6. Not adding to an already-crowded/parabolic position.
7. Logged in POSITIONS.md on entry, JOURNAL.md on exit.

## Review cadence
- **Per trade:** journal on close (entry, exit, rationale, outcome, lesson, did-I-follow-process Y/N).
- **Weekly:** update MACRO.md + POSITIONS.md; recompute portfolio heat; flag any constitution breach.
- **Quarterly:** review JOURNAL.md — is there a measurable edge yet, or was it variance? Only then revisit sizing dials.
