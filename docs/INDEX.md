# docs/INDEX.md — live theses + recent inputs

> The only file in `docs/` that's auto-loaded each session. Keep it short.
> Each line is a pointer; the detail lives in the linked file.

## Active theses

| Thesis | Ticker(s) | Status | Catalyst | Group |
|---|---|---|---|---|
| [CRM dinosaur re-rating](theses/crm-dinosaur-rerate.md) | CRM | proposed (revised 2026-06-03 — post-print continuation) | Sep 2 + Dec 2026 prints | saas-phoenix |
| Semis/optics/mem hedge — _no thesis file; see [POSITIONS.md](../POSITIONS.md)_ | SMH, SOXX | window passed (never placed — see POSITIONS 6/10 note) | none (insurance) | ai-semis-hedge |
| Oil deflation — _no thesis file; see [POSITIONS.md](../POSITIONS.md)_ | USO | open | Hormuz reopening | oil |
| [NAIL — housing cyclical barbell](theses/nail-housing-cyclical.md) | NAIL (express via ITB/XHB) | proposed (2026-06-09 — chase flag, await pullback) | none dated — rotation + rate-path | cyclical-rotation |
| [ABVX post-scare Ph3 idio](theses/abvx-ph3-idio.md) | ABVX | proposed (2026-06-09 — chase flag, binary event) | June Ph3 update (lands Jun-18–Jul-17 per IV) | idio-biotech |

## Recently archived

- [TEAM snapback — premise broken](theses/_archived/2026-06-team-snapback-premise-broken.md) — invalidated 2026-06-03 before entry. Stock at $101 vs thesis-write reference $68; ~50% rally already happened. Demoted to WATCHLIST with a $75-reset re-entry trigger. **First real test of the gate working.**

Status legend: `proposed` (in WATCHLIST/POSITIONS, not all legs placed) · `open` (live in book) · `closed` (banked, see JOURNAL) · `invalidated` (thesis broke, see JOURNAL).

Archived theses live in [`theses/_archived/`](theses/_archived/).

## Recent inputs (last ~30 days)

> Dated raw material — friend notes, sellside, news, own analyses — that fed a live thesis. Linked from the thesis itself; listed here only if loading on its own adds context this session.

- [2026-06-09 — Inspector Lee: Discord notes](inputs/2026-06/2026-06-09-inspector-lee-discord-notes.md) — ABVX idio long (→ thesis), INTC core posture, GEV trim, optics CPO delay, the NAIL lose/lose.
- [2026-06-05 — Inspector Lee: "strong data, weak stocks"](inputs/2026-06/2026-06-05-inspector-lee-strong-data-weak-stocks.md) — jobs-print selloff as the *healthier* (Scenario B) correction; flush-the-leverage thesis. Informs semis-hedge + the momo-unwind entry hunt.
- [2026-05-26 — Inspector Lee: cyclical barbell](inputs/2026-06/2026-05-26-inspector-lee-cyclical-barbell.md) — "housing is the most cyclical sector"; the NAIL/XHB barbell call behind the NAIL thesis.

## Latest reviews

- Weekly: 2026-06-10 — MACRO.md refreshed (unwind day 3, CTA breach, Scenario B intact; full staleness audit across WATCHLIST/POSITIONS/HANDOFF)
- Quarterly: _none yet_

---

## How to use this folder

- **New thesis:** copy `theses/_template.md` → `theses/<slug>.md`, fill frontmatter, link supporting inputs.
- **New input** (article, friend note, sellside, own writeup): copy `inputs/_template.md` → `inputs/YYYY-MM/YYYY-MM-DD-<slug>.md`, set `informs:` to the thesis slug(s) it feeds, then add a line to the relevant thesis's "Supporting inputs" section.
- **Primary sources (filings):** `uv run python -m degen.edgar --ticker CRM` pulls the latest 10-K/10-Q/8-Ks from SEC EDGAR into `data/filings/{TICKER}/` (gitignored), with rev-rec / critical-accounting sections carved out. Run it around earnings catalysts — validation questions live in the filings, not the tape.
- **Daily brief:** `uv run python -m degen.daily` writes a numbers-only macro + book snapshot to `daily/YYYY-MM-DD.md` (regime verdict, Fear & Greed, cross-asset, per-ticker table). Paste articles / X posts into its "Qualitative inputs" section — pull X text with `degen.daily.fetch_xpost(url)`. These are dated scratch pages, not theses; promote anything durable into an `inputs/` file linked from a thesis.
- **Close a thesis:** move to `theses/_archived/YYYY-MM-<slug>.md`, set `status: closed|invalidated`, then write the JOURNAL entry.
- **Update this INDEX** whenever a thesis changes status. It's the table of contents — let it drift and the whole system stops loading the right context.
