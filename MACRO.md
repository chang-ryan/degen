# MACRO.md — Working Worldview

> Snapshot as of **2026-06-10** (prior: 2026-06-02). This is a living file — update weekly. It exists so
> each Claude Code session continues the thread instead of restarting cold.

## The master chain (everything routes through this)
**De-escalation → oil → inflation → Fed → risk assets.**
Still a mild oil-driven stagflation; de-escalation remains the key that unlocks the bullish case:
- US–Iran war since late Feb 2026; Hormuz largely shut → war premium in oil. The 60-day MOU remains unsigned and **fraying**: Apache helicopter down off Oman (6/09) — the re-escalation tail is live, and USO bounced +2.3% on it (6/10).
- April CPI 3.8% YoY (highest since May 2023), oil-driven. Fed on hold at 3.50–3.75%. **June CPI printed ~6/10 — not yet ingested; read it and update this line** (it gates the whole chain).
- The strategist note (6/10 input) frames the bull path: Iran passes → oil "materially below $60" → cuts repriced → "8 handles on spoos." Same chain, optimistic branch. Our USO puts are the trade on it; the Sept leg is the thesis-survivor, the July legs are a this-week decision (see POSITIONS).
- **New cross-current discovered 6/09-10 (Lee's "lose/lose"):** higher rates are *breaking momo* (healthy) but the same rates *hit the broadening/cyclical trade* (NAIL, housing, cyclicals). Rate path now cuts both ways — there is no clean "rates up = rotation works" lane.

## Market structure — the unwind arrived; flush in progress, credit calm
The fragility flagged in the 6/02 snapshot **broke**, and it broke the healthy way (so far):
- **Momentum unwind, day 3 (6/10):** basket -8 to -30%/5d (optics, power semis worst), SMH/SOXX -10 to -12%/5d, SPHB/SPLV -11.6% off-hi. Mag7 concentration collapsed 6/7 → **1/7** above 50dma (AAPL alone). F&G 48→33→**27** (contrarian: constructive, not a warning). VIX 22, VVIX 108.
- **Credit refuses to confirm:** HY OAS ~2.78%, 20th pctile, flat; VIX term structure still (barely) contango. **Scenario B — positioning flush, not macro contagion.** The abort tell remains credit cracking *first*.
- **Systematic supply turned ON:** SPX closed 7,267 vs the CTA short-term threshold 7,312 → **breached** (medium 7,017, long 6,611; levels asof 6/09, `cta_levels.json`). CTA positioning was ~$46B vs $26B avg — real supply ahead. This is the forced-selling phase `macro.py` exists to instrument.
- **Breadth, measured properly** (team rule 2026-06-10): load-bearing read = `spx_breadth()` (6/10 first print: **52% >50dma, 59% >200dma**, n=502) + RSP/SPY. **Not washed out yet.** Mag7 n/7 is concentration color only; F&G is contrarian; no rule may depend on the n=7 count.
- **Destinations:** Lee's 50dma tests — QQQ ~676 (-2.4% away), SOXX ~472 (-13%). S&P ~7,000 = the medium CTA threshold ≈ the bigger support.
- **Stance:** the volcano went off; now it's an *entry-timing* problem. Tranche plan (see WATCHLIST): ~25% at the QQQ 50dma zone (sell put spreads — get paid for fear), ~50% when a momo leg bases + VIX settles, rest on confirmation. Abort everything if HY OAS cracks.

## AI-capex backdrop (the engine under the high-beta complex)
- Hyperscaler capex story intact; the flush is positioning, not a capex cut — no hyperscaler blinked.
- **Memory > optics near-term (Lee, 6/09):** NAND supply discipline holding, customers paying at margin → memory is the preferred scale-in sleeve (MU first). **Optics impaired:** SemiAnalysis CPO delay 2027→2029 woodshedded LITE/AAOI/SIVEF; capacity-addition + rising Chinese transceiver player count = margin compression as the cycle matures. Net positive MRVL (longer DSP tail). Don't bottom-fish optics.
- Power semis in freefall (NVTS -33%/5d, WOLF -30%) — too violent to catch; wait for basing.
- Latent risk unchanged: a capex/ROI blink or credit tightening unwinds the complex reflexively. That's the Scenario-A path; credit is the tell.

## The rotation + SaaS phoenix framework
- **CRM — the framework's surviving bet, now confirmed.** FQ1 primary sources (via `degen.edgar`): **Agentforce ARR $1.2B +205% Y/Y** (gate closed), AI+Data ARR $3.4B, **$25B ASR ~80% delivered** (structural bid through the window), organic acceleration guided for 2H FY27 — i.e. proof lands on the Sep-2/Dec prints. Spot $171 (vs $192 at revision) — the unwind is *gifting* the entry. Top of the shopping list; thesis: `crm-dinosaur-rerate.md`.
- **TEAM — invalidated 6/03** (premise broke: written vs $68, found at $101). Now $91.5 and falling toward the <$75 re-entry trigger; would need full re-underwriting vs the Linear threat. Expect nothing.
- Phoenix winners (SNOW/DDOG/OKTA) finally getting their reset (-8 to -16%/5d) — "quality on pullback" rows are live again, but only post-basing.
- **New since 6/02 — two non-AI theses:**
  - **NAIL/ITB/XHB** (housing cyclical barbell, `nail-housing-cyclical.md`): rotation destination thesis, but the 6/09 +11.5% pop round-tripped in one day and the lose/lose rate tension is biting. Proposed, no chase; ITB 50dma close = invalidation.
  - **ABVX** (`abvx-ph3-idio.md`): post-malignancy-scare Ph3 binary, June/July readout (IV surface dates it between Jun-18 and Jul-17 expiries), Lee 2:1. Genuinely uncorrelated. July tenor only, smallest bucket.

## Current synthesis / playbook
**From barbell-and-wait to staged accumulation.** The de-gross we hedged against (and never placed the hedge for — see POSITIONS process note) is here, flushing into calm credit — the best entry regime this framework defines. Plan: pre-committed tranches (WATCHLIST) — index put-spreads at the 50dma zones, then CRM spreads + MU on basing, ABVX on its own clock. USO July legs need a bank/hold decision this week. No long premium into rising IV; sell the fear where structure allows.

## Open questions to track
- **June CPI (printed ~6/10) — ingest it.** Does inflation roll over and free the Fed? This gates everything.
- Iran: does the MOU survive the helicopter incident? Re-escalation = USO up-tail + the Scenario-A overlay.
- Does credit stay asleep through the CTA-supply flush? (HY OAS is the single abort tell.)
- Where does SPX breadth trough — does %>50dma wash to the 20-30% zone that marks durable lows, or base early?
- CRM organic (ex-Informatica) acceleration in the Sep-2 print — the thesis catalyst.
- ABVX Ph3 update date — pin it (IV says post-Jun-18).
