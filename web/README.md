# degen · gauges — dashboard POC

A one-page visual of the daily macro-top instrumentation (the gauges from
`docs/daily/YYYY-MM-DD.md`, **minus the private Book sections**). Defaults to the
latest day; page back through history with the date pager.

## Stack

- **Nuxt 4** (Vue 3) + Nitro server routes — app code lives in `app/`, server in `server/`.
- **Tailwind v4** (CSS-first) via the `@tailwindcss/vite` plugin — the theme is in
  `app/assets/css/main.css` under `@theme`; there is no `tailwind.config.js`.
- **Dual-backend reader** (`server/utils/db.ts`): reads **Supabase** (Postgres) when
  `SUPABASE_URL` is set (prod/Vercel), else the local **`node:sqlite`** file
  `data/briefs.db` (dev — no native module to compile). Same 3 API routes either way.
  → **Deploying? See [`DEPLOY.md`](./DEPLOY.md).**
- **ESLint** — antfu's flat config, composed through `@nuxt/eslint` so it understands
  Nuxt auto-imports. `npm run lint` / `npm run lint:fix`.
- Custom SVG/CSS viz (no chart lib): F&G arc dial, regime stress-meter, momentum
  drawdown bars, CTA distance track, breadth meters.

## Run

```bash
cd web
npm install            # also runs `nuxt prepare` (generates types + eslint config)
npm run dev            # http://localhost:3000
npm run lint           # antfu + nuxt flat config

# real data: run the live exporter from the repo root (Python).
# This runs the actual gauges and upserts today's row into web/data/briefs.db.
cd .. && uv run python -m degen.webexport

# (optional) reset to the demo seed instead:
cd web && npm run seed
```

## Architecture

```
scripts/seed.mjs ──► data/briefs.db  (table: briefs(date PK, payload JSON))
                          │
server/api/briefs/*  ◄────┘   GET /api/briefs        -> { dates: [...] }
                              GET /api/briefs/:date   -> one day (":date"=latest ok)
                          │
app/app.vue + app/components/ ◄┘  PanelRenderer dispatches each panel by `kind`
```

The frontend is a **dumb generic renderer**. Every gauge is a normalized *panel*:

```jsonc
{ "key", "title", "group", "kind": "metric|dial|stress|legs|cta|breadth",
  "status": "good|warn|bad|neutral",
  "headline": { "value", "label", "sub" },
  "rows": [ { "label", "value", "delta?", "state?" } ],
  "extra": { /* kind-specific: legs[], levels[], subs[], pct50… */ },
  "note": "…" }
```
Groups: `header` (dials) · `clockA` · `clockB` · `magnitude` · `backdrop`,
plus top-level `posture` (gates + triggers), `synopsis`, `what_changed`.

## Seed-data caveat

- **2026-06-23** is a faithful transcription of the real brief (synopsis
  privacy-cleaned — no accounts/institutions/sizing).
- **2026-06-21 / 06-22** carry each day's *real* dynamic values (vix, breadth,
  F&G, STRC, mag7, legs, EWY from `data/snapshots/`); slow-moving cards
  (consumer, distribution, ROI, valuation) are reused from 06-23 and a few
  fields are approximated — purely to make pagination feel real.

## Real data — `degen.webexport` (done)

`src/degen/webexport.py` is the live generator. It runs the same gauge functions
as the daily brief, maps each frozen dataclass to the panel shape above, derives
`posture` from gauge fields (legs_basing / vix+vvix / crypto_credit.band; triggers
STRC<90/<80, VIX>22, CTA breach, VVIX>100), computes `what_changed` from the
existing `data/snapshots/` diff, and upserts one row/day into `web/data/briefs.db`.

```bash
uv run python -m degen.webexport
```

Still to do (post-POC):
- **Synopsis** — currently a placeholder. Add a `publish-synopsis` step that takes
  the hand/LLM-authored, privacy-scanned memo and patches it onto today's row.
- **Schedule** — wrap the export in cron/launchd (mirror `scripts/com.degen.*.plist`).
- **Postgres** — swap SQLite for Supabase by changing `_write()` here and `server/utils/db.ts`;
  the frontend and panel shape don't change.
