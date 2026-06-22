---
slug: mstr-strc-contagion
ticker: MSTR, STRC (watch), + miners basket (exposure)
status: research
opened: 2026-06-18
spot_at_open: MSTR 112.53, STRC 88.59, BTC 64,553
catalyst: none dated — reflexive crypto-credit tail; STRC-discount-to-par as the live gauge
correlation_group: crypto-ai-compute
variance: extreme (tail scenario)
---

# MSTR / STRC collapse — the crypto-credit tail under the miners trade

> **Why this file exists.** Our [[miners-ai-compute]] basket is sold as "AI-compute
> re-rating + BTC beta." This documents the *hidden third leg*: the basket is also
> short the MSTR/crypto-credit tail. MSTR is the leverage node of the entire
> BTC-treasury complex; if it is forced to de-lever or sell BTC, the miners are in
> the blast radius. **A literal 2026 margin-call is a tail, not a base case — but
> it's a fattening tail, and STRC gives us a free public gauge of it.**

## The setup (public data, 2026-06-18)
- **MSTR:** ~843,738 BTC, avg cost **~$66,385**. BTC is **$64,553 — now *below* MSTR's cost basis.** MSTR $112.53, **−42.6% off its 6mo high**, sitting near the 6mo low ($107). mNAV compressing toward 1.
- **Debt:** ~$6.7B convertible notes (was $8.2B; retired $1.5B at an 8% discount May 2026). Maturities **2028–2030** — no imminent wall, unsecured, no BTC-margin trigger.
- **Preferred stack — the real pressure:** **STRC ~$10.49B notional**, variable rate **now 11.50%** (effective yield **12.98%**), plus STRK (conv pref, $60), STRF (fixed, $91), STRD/STRE. Combined preferred dividends ≈ **$1.5–2B/yr cash**. The legacy software business does **not** cover this.
- **STRC is breaking its own peg.** It is *designed* to trade at $100 par via monthly dividend resets — yet it sits at **$88.59 even after raising the rate to 11.5%.** The market is repricing Strategy credit faster than the coupon can chase. **STRC's discount to par is a live distress gauge.**
- **Critical structural fact (from the STRC disclaimer):** the preferreds are **NOT collateralized by the bitcoin** — only a claim on residual assets. Cuts both ways (below).

## How a "collapse" actually happens (mechanics, not vibes)
MSTR is **not** margin-lent against its BTC, so there's no classic fund-style margin call / liquidation trigger. The vulnerability is a **reverse flywheel**, slower and reflexive:
1. **Funding the dividends needs equity issuance.** The machine runs on issuing MSTR common/preferred at a premium to NAV (mNAV > 1) to buy BTC *and* fund the preferred coupons via ATM.
2. **mNAV compresses** as BTC falls and sentiment sours → issuing equity becomes dilutive/impossible → the equity-funding window **closes**.
3. **Forced choice** to fund ~$1.5–2B/yr of preferred dividends: (a) **sell BTC** (the forced-selling scenario), (b) **raise the STRC rate** to defend par (raises cash burn further — already happening at 11.5%), or (c) **suspend/accumulate** the cumulative preferred dividends (compounds, signals distress, craters the preferreds).
4. Any of (a)/(b)/(c) **signals distress → BTC and MSTR down → mNAV down further.** That's the spiral. The trigger isn't a covenant; it's confidence + the funding window.

**Steelman the bear-of-the-bear:** maturities are 2028–30, they're actively managing the wall (bought back $1.5B at a discount), convertibles are unsecured with no liquidation trigger, and BTC-below-cost is psychological, not a covenant breach. **So a hard 2026 default is unlikely.** The realistic 2026 risk is the *reflexive funding/sentiment* version via the preferreds, not bankruptcy.

## Contagion map (concentric — why this is our problem)
- **Circle 0 — MSTR + prefs (STRC/STRK/STRF/STRD).** Direct. Forced de-lever or dividend stress → MSTR to deep NAV discount, preferreds reprice to distressed yields.
- **Circle 1 — BTC.** MSTR holds **~3.4% of all BTC**. Even fractional forced selling into a weak tape is mechanical pressure **plus** a massive psychological blow (the largest, most ideological holder capitulating). BTC could overshoot from $64k toward the **$45–50k** zone.
- **Circle 2 — THE MINERS (our basket).** Levered BTC beta. BTC $64k → $45–50k **guts the mining-economics floor** under RIOT/MARA/HUT/WULF/IREN/GLXY. The AI-compute optionality does **not** protect against a crypto-credit de-gross — BTC beta dominates and the re-rate story gets shelved. **[[GLXY]] is the weakest link** (Galaxy is a crypto *financial* — trading/lending/counterparty exposure, not just a miner).
- **Circle 3 — BTC-treasury copycats + crypto credit.** Every "treasury premium" name (Metaplanet, Semler, MARA's own BTC stash, the long tail) breaks at once; crypto lenders/exchanges (COIN) see a vol/credit spike.
- **Circle 4 — our book's correlation.** This is a Lee/Nobel-laureate **left-tail "phase change."** Usually contained to crypto — *unless* it coincides with a broad de-gross. We have **direct** exposure via the miners sleeve.

## Trade implications (what to actually do)
- **The miners basket carries an unpriced short-credit/short-vol leg.** Reinforces the existing flags in [[miners-ai-compute]]: keep it **small** (already over at ~9.4% premium-at-risk), **defined-risk only** (it is — long calls), and trim.
- **Instrument it — STRC is a free leading indicator.** STRC's discount to par is a public, daily crypto-credit-stress gauge that *leads* the miners. This is the regime-instrumentation philosophy ([[project-regime-instrumentation]]) applied to crypto: **don't predict the MSTR spiral, instrument it.**
  - **STRC < ~$90 and falling** (now $88.59) = stress building → de-risk miners.
  - **STRC < ~$80** = the peg is openly failing → the reverse flywheel is engaging → cut miner exposure hard.
  - Corroborate with **MSTR mNAV → 1** and **BTC below ~$60k** (psychological, under the $66k cost basis).
- **GLXY is the first to shed** on any crypto-credit wobble; MARA (pure BTC beta, no AI tail, near-dated Aug calls) second.
- **The reflexive hedge:** if conviction builds, the clean expression of "MSTR de-levers" is defined-risk MSTR puts / put spreads — but that's a *new* bet, not required to manage the miners. First just instrument STRC and size the basket for this tail.

## How to read the gauge (operational) + LIVE STATE 2026-06-18
The logic: MSTR's **funding stress shows up in its own securities BEFORE it forces BTC selling**, and BTC selling is what hits the miners. So watch the leading edge (MSTR cap structure) to front-run the lagging edge (BTC → miners). Signal ladder, leading → lagging:

1. **STRC discount to par** (the cleanest funding-stress gauge; par = $100):
   - $95–100 normal · $90–95 stress building · **$85–90 peg FAILING** · <$85 open distress (equity-funding window shut) · <$80 crisis (forced sell-BTC / suspend-div territory).
   - **NOW: $88.59, −7.3%/5d, at its 3-month low — squarely in the "peg failing" band.** Staircase down: 95.5 → 93.8 → 95.2 → 91.8 → 89.0 → 88.6. The 11.5% coupon implies a ~13% yield-to-par — distressed-adjacent, not default-priced, but the dividend resets can no longer hold the peg.
2. **Whole pref stack moving together** = credit/systemic, not idiosyncratic (confirmation). **NOW: all four cracking, junior worst — STRK −8.6%/5d, STRD −9.3%, STRC −7.3%, STRF (most senior) −1.3%.** The seniority ordering is textbook credit stress, not random selling. **Confirmed.**
3. **MSTR vs BTC (mNAV proxy):** when MSTR falls *faster* than BTC, the premium-to-NAV is compressing → the accretive-equity-issuance window is closing. **NOW: MSTR −31.6%/21d vs BTC −12.4%/21d — MSTR falling ~2.5× BTC, at a 3mo low ($112.53 from $196).** The reverse flywheel is engaging.
4. **BTC vs levels:** $66,385 (MSTR cost basis) · $60k (round/support). **NOW: $64,475 — already below MSTR's cost basis, grinding toward $60k.**
5. **The forcing events (lagging — by the time these print, the move is underway):** an MSTR 8-K announcing BTC sales to fund dividends; a STRC rate hike beyond 11.5%; a dividend deferral. Watch via `degen.edgar --ticker MSTR`.

**Net read: the gauge is already flashing amber→red.** Three of the four leading signals are lit (STRC peg failing, full stack cracking by seniority, MSTR underperforming BTC ~2.5×). This is no longer hypothetical tail-watching — the reverse flywheel is in its early innings. Caveat / steelman: prefs are uncollateralized (no forced-liquidation trigger), maturities are 2028–30, and a BTC bounce re-pegs everything — so this is a **de-risk-and-hedge signal, not a sell-everything panic.**

## How to front-run the contagion (actions)
The miners basket is the exposure; front-running = cut/hedge BEFORE the BTC leg breaks, not after.
- **Trim the miners now** — the basket is already flagged oversized (~9.4% premium-at-risk) and the gauge gives the trigger. **Order: GLXY first** (crypto *financial* — direct counterparty/credit exposure, the weakest link in a crypto-credit event), **then MARA** (pure BTC beta, no AI tail, near-dated Aug calls). Keep smaller positions in the real-AI-hosting names (IREN, RIOT/WULF) but reduce gross.
- **Optional reflexive hedge (defined-risk):** the cleanest *active* bet on the contagion is defined-risk **MSTR puts / put spreads** — it's the leverage node and falls fastest (already −2.5× BTC). Not required; trimming the miners is the simpler de-risk.
- **Instrument it:** add a crypto-credit line to the daily brief (STRC-to-par, pref-stack breadth, MSTR-vs-BTC ratio) so the gauge prints automatically — the [[project-regime-instrumentation]] philosophy applied to crypto.

## Open questions to track
- STRC discount to par — does it keep widening (stress) or does a BTC bounce re-peg it?
- MSTR mNAV — premium or discount to NAV? (Discount = the equity-funding window is shut.)
- Any MSTR 8-K signaling BTC sales to fund dividends, or a preferred dividend rate hike beyond 11.5% (`degen.edgar --ticker MSTR`).
- BTC vs the $66,385 MSTR cost basis and the $60k psychological line.

## Supporting inputs
- STRC dashboard screenshot (strategy.com/strc/learn, 2026-06-18): $88.59, 11.50% variable / 12.98% effective, $10.49B notional, BTC Rating 3.1x, prefs explicitly uncollateralized by BTC.
- Public: convertible buyback ($1.5B at discount, May 2026); ~843,738 BTC; debt $6.7B (Bitcoin Magazine, CoinDesk, Investing.com — see chat sources).
