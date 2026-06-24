// Dual-backend reader for the dashboard.
//   • SUPABASE_URL + SUPABASE_PUBLISHABLE_KEY → read Supabase (Vercel / prod).
//   • otherwise                               → read the local SQLite file (dev).
// The frontend and the panel shape never change; only the source does.
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

// NOTE: do NOT `import process from 'node:process'` here — Nitro/unenv already
// injects `process` as a global in the server bundle, and an explicit import is a
// duplicate declaration that crashes the Vercel runtime ("Identifier 'process'
// has already been declared"). Use the global directly.
const SUPABASE_URL = process.env.SUPABASE_URL
// new-format publishable key (sb_publishable_*); falls back to the legacy anon key.
const SUPABASE_KEY = process.env.SUPABASE_PUBLISHABLE_KEY ?? process.env.SUPABASE_ANON_KEY
const useSupabase = Boolean(SUPABASE_URL && SUPABASE_KEY)

export interface Brief { date: string, [k: string]: unknown }

// payload is jsonb in Supabase (already an object) but a JSON string in SQLite.
function expand(date: string, payload: unknown): Brief {
  const obj = typeof payload === 'string' ? JSON.parse(payload) : payload
  return { date, ...(obj as object) }
}

// ---------- Supabase backend (lazy singleton) ----------
let _supa: ReturnType<typeof import('@supabase/supabase-js')['createClient']> | null = null
async function supa() {
  if (!_supa) {
    const { createClient } = await import('@supabase/supabase-js')
    _supa = createClient(SUPABASE_URL!, SUPABASE_KEY!, { auth: { persistSession: false } })
  }
  return _supa
}

// ---------- SQLite backend (lazy singleton; node:sqlite is dev-only) ----------
const here = dirname(fileURLToPath(import.meta.url))
const DB_PATH = resolve(here, '../../data/briefs.db')
let _db: any = null
async function sqlite() {
  if (!_db) {
    const { DatabaseSync } = await import('node:sqlite')
    _db = new DatabaseSync(DB_PATH, { readOnly: true })
  }
  return _db
}

export async function getBrief(date: string): Promise<Brief | null> {
  if (useSupabase) {
    const { data } = await (await supa())
      .from('briefs')
      .select('date, payload')
      .eq('date', date)
      .maybeSingle()
    return data ? expand(data.date, data.payload) : null
  }
  const row = (await sqlite())
    .prepare('SELECT date, payload FROM briefs WHERE date = ?')
    .get(date) as
    { date: string, payload: string } | undefined
  return row ? expand(row.date, row.payload) : null
}

export async function getLatestBrief(): Promise<Brief | null> {
  if (useSupabase) {
    const { data } = await (await supa())
      .from('briefs')
      .select('date, payload')
      .order('date', { ascending: false })
      .limit(1)
      .maybeSingle()
    return data ? expand(data.date, data.payload) : null
  }
  const row = (await sqlite())
    .prepare('SELECT date, payload FROM briefs ORDER BY date DESC LIMIT 1')
    .get() as
    { date: string, payload: string } | undefined
  return row ? expand(row.date, row.payload) : null
}

export async function listDates(): Promise<string[]> {
  if (useSupabase) {
    const { data } = await (await supa())
      .from('briefs')
      .select('date')
      .order('date', { ascending: false })
    return (data ?? []).map(r => r.date as string)
  }
  const rows = (await sqlite())
    .prepare('SELECT date FROM briefs ORDER BY date DESC')
    .all() as { date: string }[]
  return rows.map(r => r.date)
}
