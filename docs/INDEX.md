# docs/INDEX.md — live theses + recent inputs

> The only file in `docs/` that's auto-loaded each session. Keep it short.
> Each line is a pointer; the detail lives in the linked file.

## Active theses

| Thesis | Ticker(s) | Status | Catalyst | Group |
|---|---|---|---|---|
| [CRM dinosaur re-rating](theses/crm-dinosaur-rerate.md) | CRM | proposed | 2026-08-21 earnings | saas-phoenix |
| [TEAM snapback](theses/team-snapback.md) | TEAM | proposed | late-Jul/Aug earnings | saas-phoenix |
| [Semis/optics/mem hedge](theses/semis-hedge.md) | SMH, SOXX | proposed | none (insurance) | ai-semis-hedge |
| [Oil deflation](theses/oil-deflation.md) | USO | open | Hormuz reopening | oil |

Status legend: `proposed` (in WATCHLIST/POSITIONS, not all legs placed) · `open` (live in book) · `closed` (banked, see JOURNAL) · `invalidated` (thesis broke, see JOURNAL).

Archived theses live in [`theses/_archived/`](theses/_archived/).

## Recent inputs (last ~30 days)

> Dated raw material — friend notes, sellside, news, own analyses — that fed a live thesis. Linked from the thesis itself; listed here only if loading on its own adds context this session.

- _none yet — populate as inputs arrive_

## Latest reviews

- Weekly: _none yet_
- Quarterly: _none yet_

---

## How to use this folder

- **New thesis:** copy `theses/_template.md` → `theses/<slug>.md`, fill frontmatter, link supporting inputs.
- **New input** (article, friend note, sellside, own writeup): copy `inputs/_template.md` → `inputs/YYYY-MM/YYYY-MM-DD-<slug>.md`, set `informs:` to the thesis slug(s) it feeds, then add a line to the relevant thesis's "Supporting inputs" section.
- **Close a thesis:** move to `theses/_archived/YYYY-MM-<slug>.md`, set `status: closed|invalidated`, then write the JOURNAL entry.
- **Update this INDEX** whenever a thesis changes status. It's the table of contents — let it drift and the whole system stops loading the right context.
