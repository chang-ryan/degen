---
slug: memory-supercycle
ticker: MU, WDC, SNDK, STX
status: open
opened: 2026-06-22
catalyst: 3Q26/4Q26 contract-price prints (super-bull +40-50% QoQ vs consensus); MU FQ3 (6/24) guide
correlation_group: ai-infra
variance: high
---

# Memory super-cycle — supply discipline + AI capex, tops ~2028 (not now)

> **The core long, and the single biggest exposure.** DRAM/NAND/HDD (MU, WDC, SNDK,
> STX) is the picks-and-shovels of the AI build — "buy what the hyperscalers are
> buying, not the hyperscalers themselves" (Lee). The names have gone vertical, and
> the question isn't *whether* it's worked — it's whether the run has more room. The
> supply/pricing data says **yes, to ~2028.**

## One-sentence thesis
Memory is in a supply-disciplined, AI-capex-driven super-cycle where contract prices
re-rate far above consensus (CSPs locking 50-70% of capacity via LTAs), and the
cycle tops on supply growth + China catch-up around **2028** — so the memory names
have ~2 years of pricing power, and trimming them is a *concentration/sizing*
decision, not a *timing* call.

## Why now
- **Jefferies memory expert (via Lee, 2026-06-22):** 3Q26 prices **+40-50% QoQ**, 4Q26
  **+30-40%** — *far* above consensus (15-20% / <30%). 2027 **+40-45% YoY**.
- **CSP long-term agreements take 50% of capacity (could go 70%)** → less supply for
  consumer electronics — which *explains the Micron Crucial exit* (allocating away from
  consumer to feed the data-center LTAs).
- **China is not a threat in 2026/7** (tech gap), though NAND could catch up by 2028.
- It's the cleaner expression of the AI build than the hyperscalers ([[ai-infra-cycle-top]]):
  the suppliers capture the spend even if the buyers (Mag7) de-rate.

## The setup
- **What's mispriced:** consensus is modeling 15-20% QoQ; the expert sees 40-50%. If contract
  prints land closer to the bull, the names have large earnings upside not yet in numbers.
- **What the crowd believes:** "memory is cyclical and already ran — don't chase the top."
- **What changes the price:** the actual **3Q/4Q26 contract prints** + the memory names' guidance
  (starting MU FQ3, 6/24). Prints > consensus = the re-rate continues.

## Evidence
- The price action: DRAM/NAND/HDD names up an order of magnitude off their pre-AI base; the rip
  is the supply-discipline + AI-capex story made real.
- CSP LTAs at 50% (→70%) of capacity; the Micron Crucial consumer exit (Dec 2025) corroborates
  the allocate-to-data-center thesis.
- Team conviction: Inspector Lee — "buy what the hyperscalers are buying"; the Jefferies expert call.
  See [[2026-06-22-inspector-lee-memory-supercycle-oil-warsh]].

## Risks (real ones, not boilerplate)
- **2028 ASP fall — the dated cycle-top.** 15-20% supply growth from new capacity + slowing demand
  + China NAND catching up. This is the thesis's own expiry; pre-set it as the marker, not "feels toppy."
- **The AI-capex tail is the demand.** CSPs are 50-70% of capacity, so memory demand *is* AI-infra
  demand — if AI capex blinks ([[ai-infra-cycle-top]] / the credit gauge cracks), memory demand blinks
  with it, hard. Memory is not diversified *from* the AI bet; it's the supply side of the same bet.
- **Consensus is right / China early.** If contract prints come in at 15-20% (not 40-50%), the
  super-cycle premise is wrong and the names de-rate to a normal cycle. The gauge catches this.
- **Concentration + leverage (book-level).** This complex is the largest exposure across accounts;
  even with the bull thesis intact, sizing it at a large share of the book is a separate risk (see below).

## Invalidation
- **Contract prints land at/below consensus** (≤ ~20% QoQ in 3Q26) → super-cycle premise broken; cut to a normal-cycle weight.
- **China NAND catch-up arrives early** (pre-2028 capacity/tech surprise) → the top marker pulls forward.
- **Credit cracks** (STRC gauge / HY OAS) → the AI-capex demand under memory is at risk regardless of the supply story.

## Structure considerations
- **Core long, held as shares** (not the 3x LETFs). The thesis is multi-quarter, so equity > short-dated calls.
- **Trimming = sizing, not timing.** Believe the run to 2028 *and* still trim for concentration: don't hold
  an oversized share of the book in one correlated, partly-options-levered bet. What would make you trim for *timing* is
  the gauge (prints miss) or credit cracking — not a vibe. (Odd-lot share counts can't be cleanly collared;
  trim, or hedge the cluster via SMH/SOXX puts. Size off the live POSITIONS.md.)
- **Vehicle quality:** MU/WDC/STX have liquid options; SNDK is high-IV and odd-lot-awkward. Prefer cluster
  hedges (SMH/SOXX) over single-name memory options for protection.

## The gauge (the crux)
`degen.macro.memory_prices()` (hand-entered `memory_prices.json`, rendered in the daily brief) tracks
contract-price prints vs the +40-50% forecast and the 15-20% consensus. **This is the single signal that
resolves bull-vs-bear.** Drop in each print (TrendForce/DRAMeXchange, or the names' guidance) as it lands;
start with the MU FQ3 guide on 6/24.

## Supporting inputs
- [[2026-06-22-inspector-lee-memory-supercycle-oil-warsh]] — the Jefferies +40-50% QoQ call + "buy suppliers not buyers."

## Updates
- **2026-06-22:** thesis opened. Super-bull memory forecast (Jefferies, via Lee) >> consensus; cycle-top
  marker set to ~2028. Gauge wired (`memory_prices.json`), awaiting the first print (MU 6/24).
