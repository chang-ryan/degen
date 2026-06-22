# HANDOFF.md — Structured Trading System (read this first)

A context + workflow system for a high-variance, 2–6 month options book, designed to
run inside **Claude Code**. The point is **discipline and process**, not idea volume —
for a leveraged account, the controllable edge is risk management, not more signals.
*Not financial advice; this imposes a process, it does not guarantee returns.*

---

## 0. How we work — the operating model
The division of labor that makes this repo worth having:
- **You (the human) are the sensor + pattern-finder.** Real-world interactions, domain skills, the team/Lee network, the "this feels off" intuition (Uber drivers on memory, friends on IREN) — that's the **alpha source**, and it's in no data feed. You gather signal and find patterns, then dump them here.
- **The repo is the instrumentation + discipline + memory.** It converts your patterns into *falsifiable watch-items*, holds you to written invalidation levels, remembers what was concluded and why, and tells you when a signal fires.
- **A thesis session outputs gauges, not verdicts.** "I don't think the economic value matches the infra spend in this timeframe" is a *hypothesis that names what to monitor* — not a call to act. We decide where to look, what data to inspect, what would confirm or break it over time, then instrument that. This is the regime-instrumentation philosophy ("instrument forced-selling, don't time tops") generalized to the whole research process.
- **So every rant ends with: what's the gauge?** Each thesis names (a) the signal that confirms it, (b) the signal that breaks it (invalidation), (c) where that data lives — a `degen` panel, a manual watch, or a source to add. Then it lives in a thesis file and the daily brief watches it. Beware contaminated proxies (e.g. lab ARR for token demand — it's inflated by VC-subsidized startup burn and circular financing); prefer the cleanest signal you can instrument.

---

## 1. What's in this repo
| File | Role |
|---|---|
| `CONSTITUTION.md` | Risk rules + discipline. The guardrail. Every trade checks against it. |
| `MACRO.md` | Living worldview (de-escalation/oil/Fed, crowding, rotation, phoenixes). Update weekly. |
| `POSITIONS.md` | Open + proposed trades, each with thesis/invalidation/size. |
| `WATCHLIST.md` | Candidate setups with triggers. Proactive item = the hedge. |
| `JOURNAL.md` | Every closed trade. The edge-measurement / feedback loop. |
| `HANDOFF.md` | This file: stack, setup, workflows, roadmap. |
| `docs/INDEX.md` | Table of contents for theses (`docs/theses/`), inputs (`docs/inputs/`), daily briefs (`docs/daily/`). |
| `tickers.txt` | The book + watchlist + thematic basket — input to `degen.daily` and the IV store. |
| `cta_levels.json` | Hand-entered CTA thresholds (asof-stamped) → `macro.cta()`. |
| `.agents/skills/daily-debrief/` | The daily-debrief skill: run `degen.daily`, write the memo, fold qualitative inputs. |

**Start every session by loading `CONSTITUTION.md` + `MACRO.md` + `POSITIONS.md`** so Claude has the rules, the worldview, and the live book in context.

---

## 2. The data stack (tuned to: no live data, 2–6mo horizon, options/LETF)
You don't need real-time feeds. Spend only where it matters for options (vol/flow).

- **Options flow / vol / positioning — the one paid tool worth it: Unusual Whales MCP.**
  Flow, dark pool, gamma/dealer exposure, IV/vol, congressional. Drives the crowding/IV lens.
  `claude mcp add unusualwhales -e UW_API_KEY=<key> -- npx -y @erikmaday/unusual-whales-mcp`
  (Also an official `@unusualwhales/mcp` / hosted endpoint at `unusualwhales.com/public-api/mcp`.) *Paid API token.*
- **OHLC + fundamentals (free/delayed is plenty):**
  - Financial Datasets MCP (OAuth, OHLCV + financials + filings + screener), or
  - Alpha Vantage MCP (free key, OHLCV + 50+ built-in indicators).
- **Optional broader/options data:** Polygon MCP (`polygon-io/mcp_polygon`, options chains + Greeks; free server, paid for real-time you don't need).
- **Your Robinhood book:** no official stocks/options API. Either **CSV export** of positions/trades into the repo (preferred — no credential risk), or `robin_stocks` locally (unofficial, hits private endpoints, ToS + credential risk, slow).
- **Compute layer (free, your edge): local Python in Claude Code** — Black-Scholes/Greeks, IV, payoff diagrams, position-sizing, portfolio-heat, light backtests (`pandas`, `numpy`, `scipy`; `pandas-ta` for indicators).

> ⚠️ Verify exact MCP package names / install commands against current docs before relying on them — the ecosystem moves fast and these change.

---

## 3. Workflows (skills / scripts — status as of 2026-06-10)
Each is a reusable prompt or script that enforces the constitution.

**Built:**
- **`daily-debrief`** (skill, `.agents/skills/daily-debrief/`) — runs `degen.daily` (regime, momentum/crowding, SPX breadth + CTA, Mag7 concentration, book tables), then the LLM writes the team memo and folds qualitative inputs. The de facto daily driver.
- **`size` / `heat`** — `degen.size`, `degen.heat` (Python, per CONSTITUTION rules).
- **Per-ticker gate input** — `degen.dashboard`; **regime layer** — `degen.macro`; **IV history** — `degen.iv_store` (launchd snapshot job in `scripts/`).
- **Primary sources** — `degen.edgar` (SEC filings + exhibits → `data/filings/`; used to close the CRM Agentforce gate from the actual press release).

**Still to build:**
1. **`pre-trade`** — input: ticker, thesis, catalyst, structure idea. Output: runs the CONSTITUTION gate (invalidation set? defined-risk? expiry past catalyst? not chasing a parabola?), pulls IV context, computes **size**, prints **max loss / max payoff / breakevens**, checks **heat** netted. Returns PASS/FAIL + the POSITIONS.md block. (Pieces all exist; needs the wrapper.)
2. **`weekly`** — refresh MACRO.md + POSITIONS.md, recompute heat, flag breaches, list catalysts in the next 2 weeks. (Done by hand 2026-06-10; codify it.)
3. **`journal`** — on close, append a JOURNAL.md entry from the template and update the quarterly rollup.

### Recently built (2026-06)
- **`degen.edgar`** — SEC filings + exhibits (closed the CRM Agentforce gate from the press release).
- **`degen.etrade`** — read-only OAuth client; reconciled the long-term book (revealed heavy AI-correlation across the combined book).
- **`macro.crypto_credit()`** — STRC/Strategy-pref + MSTR-vs-BTC gauge (the crypto-credit dress rehearsal for AI-infra leverage), rendered in the daily brief + digest.
- **Delta snapshots** (`data/snapshots/`) — each `degen.daily` run persists state; the next opens with a "What changed" lede. (Gleaned from the atlas-brief engine.)

### Tooling roadmap (from the atlas-brief recon + data-subscription review)
- **Build (free):** the credit panel could extend to BDC discounts / neocloud (CRWV) credit; the z-score regime composite (replaces the binary label that misfired 6/09); importance/tier ranking for the brief.
- **Buy (ranked):** Unusual Whales ($50/mo web — flow/dealer-gamma, the crowding instrument); Polygon/"Massive" (historical IV → instant IV-rank); SemiAnalysis (AI-infra research, the central-bet edge). See the chat thread for the full build-vs-buy rationale.
- **atlas-brief patterns still un-ported:** Pydantic Brief schema (JSON export for Discord), deterministic-context injection into thesis-validation search prompts, analyst earnings-revisions breadth.

---

## 4. Build roadmap
- **Phase 1 — wire it up.** New repo, drop in these 5 context files. `claude mcp add` Unusual Whales + a free OHLC/fundamentals MCP. Confirm Claude can read both the files and the data.
- **Phase 2 — quant scripts.** Build `size` and `heat` in Python (Greeks, payoff, gap-sizing, correlation-netted heat). These are the math guardrails.
- **Phase 3 — workflows.** Wrap `pre-trade`, `weekly`, `journal` as skills/slash-prompts that read CONSTITUTION + POSITIONS automatically.
- **Phase 4 — feedback loop.** Backfill JOURNAL.md with recent trades; start the quarterly edge-measurement. Only adjust sizing dials once there's a track record.

---

## 5. How to drive it (session pattern)
1. Load CONSTITUTION + MACRO + POSITIONS.
2. New idea → run `pre-trade`. If FAIL, stop. If PASS, paste the block into POSITIONS.md.
3. After any fill, run `heat` to confirm you're inside limits (correlated names as one bet).
4. Weekly → `weekly`. On every close → `journal`.
5. Quarterly → read JOURNAL rollup; decide if edge is measured before touching size.

---

## 6. Standing reminders (the lessons baked in)
- The 5x is **historical and luck-acknowledged** — not a benchmark, not an edge. Earn size-ups in the journal.
- **Naked/margin = gap risk.** Your true per-trade risk is the overnight gap you can't react to, not the planned loss. Size to that.
- **Correlation kills** in a de-gross — this book is one big risk-on bet; net it.
- **Barbell, not bravado:** under-owned longs + cheap hedge, neither requiring a market-timing call.
- **Don't lid the volcano.** Fragility is high and severe-if-it-breaks, but timing is unknowable and the tape can stay hot; trade what's in front, hedge cheaply, don't short the trend.

---

## 7. Immediate open threads to resume in Claude Code (2026-06-10)
1. **USO July legs (150P/145P 7/17) — bank or hold, this week.** Theta accelerating, re-escalation up-tail moving (helicopter incident); Sept leg holds either way. See POSITIONS.
2. **Ingest the June CPI print (~6/10)** into MACRO.md — it gates the whole de-escalation→Fed chain.
3. **Run the tranche plan:** watch for QQQ 670-680 / a momo leg basing / credit cracking. Tranche 1 = index put spreads; tranche 2 = CRM spreads (gate confirmed) + MU. See WATCHLIST.
4. _Closed thread (lesson logged in POSITIONS):_ the semis hedge was never specced and the de-gross happened — insurance window passed; re-spec only if the book re-grosses post-flush.
