# Deploy — Supabase + Vercel

The dashboard reads from Supabase in prod and from local SQLite in dev (auto-detected
by whether `SUPABASE_URL` is set). The Python exporter pushes each day's row to Supabase.

**Key split (important).** Supabase's new key format (`anon`/`service_role` are legacy):
- **secret** key (`sb_secret_…`) → repo-root `.env`, used ONLY by the local Python exporter (bypasses RLS, can write). Never goes to Vercel or the browser.
- **publishable** key (`sb_publishable_…`) → Vercel env (+ optional `web/.env` to test locally). Browser-safe, read-only via RLS.
- You do **not** need the JWKS URL for this pipeline (that's for verifying end-user JWTs).
- New keys are not JWTs, so they're sent in the **`apikey` header only** — the exporter already does this.

---

## 1. Supabase project

1. Create the project (defaults are fine: Data API on, automatic RLS off).
2. **SQL Editor → New query →** paste `web/supabase/schema.sql` → **Run**. Creates the
   `briefs` table, enables RLS, and grants public read.
3. **Settings → API Keys**, copy:
   - Project URL → `SUPABASE_URL`
   - **Publishable** key (`sb_publishable_…`) → `SUPABASE_PUBLISHABLE_KEY` (the web reader)
   - **Secret** key (`sb_secret_…`) → `SUPABASE_SECRET_KEY` (the Python writer)

## 2. Push data from your machine

Add to the **repo-root `.env`** (gitignored):

```bash
SUPABASE_URL=https://YOUR-PROJECT.supabase.co
SUPABASE_SECRET_KEY=sb_secret_your-secret-key
```

Then run the exporter — it writes local SQLite *and* upserts to Supabase:

```bash
uv run python -m degen.webexport
# … [wrote 2026-06-23 → …/briefs.db · 20 panels · window SHUT]
# [supabase: ok (201)]
```

History in Supabase starts from your first push (forward-only, as designed). The locally
seeded 06-21/06-22 demo rows stay SQLite-only unless you choose to push them.

## 3. (optional) Test the Supabase read locally before deploying

```bash
cp web/.env.example web/.env     # fill SUPABASE_URL + SUPABASE_PUBLISHABLE_KEY
cd web && npm run dev            # now reads Supabase instead of SQLite
```

## 4. Vercel

1. **Add New → Project →** import this Git repo.
2. **Root Directory: `web`** (Vercel auto-detects Nuxt). Node 20+.
3. **Environment Variables** — add the two **public** values (NOT the secret key):
   - `SUPABASE_URL`
   - `SUPABASE_PUBLISHABLE_KEY`
4. **Deploy.**

The page is `noindex` and shows only the sanitized gauges (no book, synopsis is the
privacy-cleaned one). Share the URL with colleagues. To lock it down later: add Supabase
Auth, a Vercel password (Pro), or Vercel Access Protection.

## 5. (later) Schedule the daily push

Wrap `uv run python -m degen.webexport` in launchd/cron on the machine where the data
lives (mirror `scripts/com.degen.*.plist`). That's the only recurring step — Vercel just
serves whatever is in Supabase.
