---
slug: crm-dinosaur-rerate
ticker: CRM
status: proposed
opened: 2026-06-02
revised: 2026-06-03
spot_at_revision: 192.04
catalyst: 2026-09-02 print (next, after May print already happened) → 2026-12 print
correlation_group: saas-phoenix
variance: low
---

# CRM — cushioned dinosaur re-rating (post-print continuation)

> **Thesis revision — 2026-06-03.** First toolkit run flagged that CRM's late-May
> earnings already happened (5-day close sequence $176→$191→$209→$200→$192 is a
> textbook gap + sell-the-news). Original thesis framed the trade as a *pre-print
> setup*; the real opportunity now is the *post-print continuation* into the
> September (verified 2026-09-02) and December prints. **Before sizing, read the actual May print:** if
> Agentforce ARR confirmed the $1B+ ramp, the thesis is alive; if not, it's dead
> and this file gets archived. **Gate resolved 2026-06-10 from the actual press
> release (primary source): Agentforce ARR $1.2B, +205% Y/Y — confirmed.** See
> the 2026-06-10 update.

## One-sentence thesis
CRM is the lower-variance bet that a profitable, washed-out per-seat incumbent that *just delivered* an agentic-pivot print re-rates into the next two prints as the crowd that missed it the first time hunts for the next OKTA.

## Why now
The OKTA-style violent intraday re-rate is past — CRM already had its $176→$209 spike. What's left is the slower, larger continuation: when the chase-the-next-OKTA crowd realizes CRM *is* the next OKTA, they bid the multiple from ~10x fwd toward 13–15x fwd over the next two prints. SNOW/DDOG/OKTA have all already re-rated; the cohort is hot; CRM is the one that's barely moved on the y-axis (the May rip notwithstanding, the stock is back to where it was pre-print). The trade is now *between* prints, not *into* one.

## The setup
- **What's mispriced:** the market treated the May print as a one-day event and let the stock round-trip. The multiple hasn't actually re-rated yet — ~10x fwd still prices terminal decay.
- **What the crowd believes:** CRM had a print, the rally happened, move on. Per-seat dinosaur narrative intact.
- **What changes the price:** (a) the next print (2026-09-02) confirms the Agentforce ARR trajectory in a second consecutive quarter, (b) sellside multiple targets get raised, (c) buyback pace sustains the floor through any tape-wide de-gross.

## Evidence
- 5-day close sequence around May print: $176 → $191 → $209 → $200 → $192. **Sell-the-news, not thesis failure.** The post-print fade in a stock that gapped 8.5% then 9.6% is mechanical (gamma unwind, hedge-flow), not fundamental rejection.
- Toolkit reads vol as *cheap*: 30-DTE ATM IV 45.4% vs 30d realized 58.7% → IV/HV 0.81. Front-Oct ATM IV 47.5%, IV/HV 0.81 on the trade-relevant tenor. (Caveat: HV inflated by the post-print swing.)
- 25Δ skew −0.05 → flat/inverted on the Oct expiry. Downside puts not bid up. The crowd isn't worried about a CRM crash; nobody's hedging.
- Cohort already priced (SNOW +37% May, DDOG +66% YTD ~80x fwd, OKTA $90→$135 on 5/28). CRM has *not* re-rated yet despite having the same agentic-product print.

## Risks (real ones, not boilerplate)
- **The May print was not what I'm assuming.** If Agentforce ARR missed or net-new ARR decelerated, the post-print fade *is* fundamental rejection and the spike was a head-fake. **Mitigation: read the print before placing.** This is the gating risk.
- **Tape-wide de-gross before the Sep-2 print.** Correlated semis-led drawdown pulls SaaS phoenix with it. Tell: SMH −8% in a week with no CRM news. The hedge leg (semis puts) is the protection here, not CRM-specific.
- **Multiple stays at 10x.** The expanded narrative needs a second confirming print; if the Sep-2 print is just "in-line, no upside surprise," the re-rating stalls and the time-stop bites.

## Invalidation
- **Pre-sizing:** ~~if the May print's Agentforce / net-new ARR numbers don't confirm the thesis (verify before placing), don't enter.~~ **Resolved 2026-06-10: confirmed** (Agentforce ARR $1.2B +205% Y/Y, per the FQ1 press release). Residual caveat: headline growth leans on Informatica (~3pts of the ~12% guide); the *organic* acceleration is guided for 2H FY27, i.e. it lands across the Sep/Dec prints this thesis trades.
- **Price stop:** close below $170 on heavy volume with no broad-tape selloff (washout that the buyback isn't catching).
- **Catalyst stop:** Sep-2 print misses or in-lines on Agentforce ARR → thesis broken, exit even if structure is green.
- **Time stop:** if the Sep-2 print is a clean beat but stock fails to break above $220 within 6 weeks, the re-rating bid isn't there; cut and recycle.

## Structure considerations
- Defined risk only (gate-default).
- **Expiry must sit past the 2026-09-02 print.** This is the correction that killed the original Aug-21 idea — an August expiry would have settled 12 days *before* the catalyst, i.e. zero event exposure. A Sep-18 (or later) expiry is the earliest that catches the Sep print; Jan-2027 covers both the Sep and Dec prints for one ticket.
- **Choice between LEAP and bull call spread depends on IV rank at entry** (not yet available — store needs ~20 days of history). Interim heuristic via IV/HV:
  - IV/HV < 0.8 and skew flat → favor LEAP (vol cheap, simple long).
  - IV/HV > 1.0 or skew rich → favor spread (sell the upper leg, don't pay up).
  - Current read (2026-06-03): IV/HV 0.81, skew flat → **borderline; spread for capital efficiency at this account size.**
- **Sizing constraint surfaced by the toolkit:** a 0.65Δ Jan-27 LEAP costs $3,272/contract — even one contract breaches the 1% defined-risk gate at this book size (size off the live port in POSITIONS.md; the older $100k figure here was stale). Either (a) take the $200/$260 Jan-27 spread at $1,560 debit (fits 1 contract at the 2% cap, breakeven +12.3%), or (b) tighten to $200/$240 spread (cheaper debit, lower max payoff), or (c) wait for an entry where IV is meaningfully lower.

## Supporting inputs
- Primary sources pulled via `degen.edgar` (2026-06-10): `data/filings/CRM/latest_10Q.txt` (FQ1 ended 2026-04-30, filed 5/28) + `latest_earnings_8K.txt`. Note: the 8-K is the stub only — Exhibit 99.1 (the press release with the Agentforce ARR figure) is not fetched; the ARR gate needs the press release or call transcript.

## Updates
- **2026-06-02:** thesis opened. Sized at "proposed" pending dashboard run + CONSTITUTION gate.
- **2026-06-03:** **major revision.** Toolkit run revealed (a) May print already occurred — original "pre-print" framing is wrong, (b) vol is cheap by IV/HV not by IV rank (no history yet), (c) LEAP doesn't fit the 1% gate at this account size. Reframed as post-print continuation; gated on actually reading the May print before sizing.
- **2026-06-10:** **GATE CLOSED — thesis confirmed from the press release** (pulled via `degen.edgar` 8-K exhibit support; `data/filings/CRM/latest_earnings_8K_ex99.txt`). FQ1: **Agentforce ARR $1.2B, +205% Y/Y** (the $1B+ ramp, confirmed); combined AI+Data ARR $3.4B +200% (incl. $1.1B Informatica Cloud); AWUs 3.8B, +111% Q/Q; Agentforce premium-SKU bookings +60% Y/Y. Bonus for the buyback-floor leg: **$25B ASR** with 103M shares (~80%) already delivered, settling Q3 FY27 — a structural bid under the stock through the thesis window. Caveats: FY27 guide ~12% Y/Y includes ~3pts Informatica (organic ~9%); CFO guides *organic acceleration in 2H FY27* — i.e. the proof lands on the Sep/Dec prints, which is exactly the bet. Status: thesis alive and de-risked; entry decision now purely price/vol/timing.
- **2026-06-10:** **first primary-source read + stop-level stress.** From the FQ1 10-Q (Apr-30 quarter): total RPO **$67.9B +11% YoY**, current RPO **$33.6B +14% YoY** (the metric the tape trades — accelerating), Agentforce Apps segment revenue **$6.91B +9% YoY** (65% of revenue, implying total ~+14% — but "bolstered by the acquisition of Informatica," so the *organic* composition is unverified). The specific "$1B+ Agentforce ARR" gate number is NOT in the 10-Q — it lives in the press release (Exhibit 99.1) / call, still unread; gate remains open, leaning supportive. Price: $170.92, -10.3%/5d, sitting $0.92 above the $170 stop — but the stop's own qualifier excuses it: this is a broad-tape de-gross (SMH -10.5%/5d), exactly the "tape-wide de-gross" risk, not CRM-specific rejection. IV/HV 0.85, vol still cheapish. No position to stop out of; if the premise survives the press-release read, the unwind is *improving* the entry, not breaking the thesis. Real trigger to watch: CRM below $170 *after* the tape stabilizes. Wired `get_earnings_dates` (yfinance) into the toolkit; it verified the next CRM print is **2026-09-02**, not "August" as this file assumed. The originally-proposed Aug-21 spread would have expired 12 days *before* the catalyst — zero event exposure. Corrected every date reference and the structure rule: expiry must sit past Sep-2 (Sep-18+ for the near-print bet, Jan-27 to span both Sep and Dec). Exact debits to be re-pulled at entry — option prices have drifted since the 6/03 reads above and the IV store still lacks rank history.
