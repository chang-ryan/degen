-- degen · gauges — Supabase schema.
-- Run once in the Supabase SQL editor (Dashboard → SQL → New query → paste → Run).

create table if not exists public.briefs (
  date       date primary key,
  payload    jsonb not null,
  updated_at timestamptz not null default now()
);

-- Row Level Security: the public (anon) role may READ; writes happen only with the
-- service_role key, which the local Python exporter uses and which bypasses RLS.
alter table public.briefs enable row level security;

drop policy if exists "public read briefs" on public.briefs;
create policy "public read briefs"
  on public.briefs
  for select
  to anon, authenticated
  using (true);

-- Belt-and-suspenders: ensure the Data API roles hold table SELECT even if
-- "Automatically expose new tables" was turned off at project creation.
grant select on public.briefs to anon, authenticated;
