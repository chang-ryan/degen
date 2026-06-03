# HANDOFF.md — Structured Trading System (read this first)

A context + workflow system for a high-variance, 2–6 month options book, designed to
run inside **Claude Code**. The point is **discipline and process**, not idea volume —
for a leveraged account, the controllable edge is risk management, not more signals.
*Not financial advice; this imposes a process, it does not guarantee returns.*

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

## 3. Workflows to build (as Claude Code skills / slash-prompts)
Each is a reusable prompt or script that enforces the constitution.

1. **`pre-trade`** — input: ticker, thesis, catalyst, structure idea. Output: runs the CONSTITUTION gate (invalidation set? defined-risk? expiry past catalyst? not chasing a parabola?), pulls IV context (UW), computes **size** from the rules, prints **max loss / max payoff / breakevens**, checks **heat** with correlated names netted. Returns PASS/FAIL + the POSITIONS.md block to paste.
2. **`size`** — position-sizing calculator. Defined-risk: premium = 1–2% of port. Naked/margin: solve notional so a 2–3σ adverse gap ≤ ~5% of port (needs underlying vol input).
3. **`heat`** — portfolio risk report. Aggregate max-loss, Greeks, concentration by thesis/correlation group, and a scenario stress ("semis −15% overnight: what does the whole book do, longs + hedge together?").
4. **`weekly`** — refresh MACRO.md + POSITIONS.md, recompute heat, flag any breach, list catalysts in the next 2 weeks.
5. **`journal`** — on close, append a JOURNAL.md entry from the template and update the quarterly rollup.

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

## 7. Immediate open thread to resume in Claude Code
**Spec the semis/optics/mem PUT hedge** — strikes, expiries, and size as real insurance against the long-term equity book (WDC/SNDK/STX/GEV + AVGO/ARM/AMD/NVDA) and the correlated phoenix longs. The friend's note argues for doing this **sooner and possibly larger** given corroboration. Pick up here.
