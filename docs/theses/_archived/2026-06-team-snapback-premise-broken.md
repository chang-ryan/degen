---
slug: team-snapback-premise-broken
ticker: TEAM
status: invalidated
opened: 2026-06-02
closed: 2026-06-03
spot_at_open: 68              # thesis-write reference price (per original MACRO snapshot)
spot_at_close: 101.42         # first toolkit run, ~50% above the write-time premise
correlation_group: saas-phoenix
variance: high
---

# TEAM — convex snapback (premise broken before entry)

## Summary
The thesis ("−68% from highs, NRR 120%+, 'grower priced for death', Rovo 5M MAU
→ violent short-cover re-rate") was written against a ~$68 reference price.
First dashboard run on 2026-06-03 returned **$101.42** — the stock has already
rallied ~50% from the thesis-write level. The convex-snapback setup is gone:
the snapback already happened.

## Toolkit reads at archival (2026-06-03)
- Spot: $101.42 (vs write-time premise $68)
- 30d HV: 110.3% — extreme; stock has been moving violently
- 30-DTE ATM IV: 73.7% — high in absolute terms
- Dec-18 ATM IV: 78.9%, IV/HV 0.71
- 25Δ skew Dec-18: −0.015 (flat-to-slight call premium → chasers, not hedgers)
- Term slope: −0.122 (strong backwardation, near-term event premium)
- Liquidity: nontrivial OI in monthlies (16 strikes with OI ≥ 100 in Dec-18)

## Why this is invalidation, not "reduce size"
- The trade was *asymmetry*: small premium, multiple-bagger payoff if the
  market re-rated a left-for-dead grower.
- At $101, the easy 50% has already been paid. Remaining upside is no longer
  asymmetric in the way that justified the trade.
- Buying calls into a stock that has ripped 50% with HV 110% and rich front
  IV is the textbook CONSTITUTION violation: "don't chase parabolae" + "vol
  awareness — high IV → favor spreads."

## Lesson banked into the system
- **Thesis files now carry `spot_at_open` in the frontmatter.** Any future
  drift between write-price and current spot is loud on the first
  dashboard run. The TEAM premise broke silently between when it was
  written (in the MACRO snapshot) and when the toolkit was first run on it —
  this drift will not happen invisibly again.
- This is the first real test of the "process > outcome" line. The process
  killed a trade that would have looked attractive on a price chart alone,
  and would have been a chase. Log a JOURNAL entry on this when next
  reconciling: process check Y (gate caught it), P&L $0 (didn't trade),
  hypothetical-counterfactual to revisit at quarter end.

## Where TEAM goes from here
- Demoted from PROPOSED → WATCHLIST.
- Re-entry trigger (rule, not vibes): close back below $75 *and* IV rank
  meaningfully off the recent high (need store history to make this
  mechanical). Then reconsider with a spread structure to avoid paying up
  for rich vol.
- Background risk (Linear taking Jira share) is unchanged and remains the
  bear case for any future re-entry.

## Updates
- **2026-06-02:** thesis opened against ~$68 reference (per MACRO snapshot).
- **2026-06-03:** first toolkit run; spot $101.42, premise broken, archived.
