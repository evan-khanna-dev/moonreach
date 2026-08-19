-- Profile/chat split for MoonReach.
-- Adds an app-level `profiles` table (one per anonymous browser/device) so
-- university/major/year are captured once, while `sessions` becomes a pure
-- per-chat record (its existing `goals` column already means "what this
-- chat/pursuit is about"). Also adds a durable North Star snapshot log to
-- replace the in-memory cache, and closes RLS gaps on tables that never had
-- a committed policy file (`sessions`, `messages`, `plans`).
--
-- Non-destructive: no existing column is dropped or renamed. `sessions.
-- university/major/year` are left in place but the app stops reading/writing
-- them going forward in favor of the profiles join.

create table if not exists profiles (
  id bigserial primary key,
  university text not null default '',
  major text not null default '',
  year text not null default '',
  device_id text not null unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_profiles_device_id on profiles(device_id);

alter table profiles enable row level security;

create policy if not exists profiles_select_policy
  on profiles for select
  using (true);

create policy if not exists profiles_insert_policy
  on profiles for insert
  with check (true);

create policy if not exists profiles_update_policy
  on profiles for update
  using (true)
  with check (true);

-- Link chats to a profile. Nullable so pre-existing session rows are not
-- broken; they simply remain unscoped ("orphaned") until re-onboarded.
alter table sessions add column if not exists profile_id bigint references profiles(id) on delete cascade;
create index if not exists idx_sessions_profile_id on sessions(profile_id);

-- `sessions` and `messages` predate this project's RLS policy files and were
-- likely configured by hand in the Supabase dashboard. Declaring them here
-- explicitly (idempotent) removes the guesswork the next time something
-- looks like a silent RLS failure.
create policy if not exists sessions_select_policy
  on sessions for select
  using (true);

create policy if not exists sessions_insert_policy
  on sessions for insert
  with check (true);

create policy if not exists sessions_update_policy
  on sessions for update
  using (true)
  with check (true);

create policy if not exists messages_select_policy
  on messages for select
  using (true);

create policy if not exists messages_insert_policy
  on messages for insert
  with check (true);

-- `plans` has been referenced by the backend since commit 88fd1db but was
-- never given a committed migration or RLS file - it was created ad hoc.
-- Declaring it here (create table if not exists) makes it reproducible and
-- guarantees RLS policies exist regardless of how it was originally set up.
create table if not exists plans (
  id bigserial primary key,
  session_id bigint not null references sessions(id) on delete cascade,
  plan_items jsonb not null default '[]',
  created_at timestamptz not null default now()
);

create index if not exists idx_plans_session_id on plans(session_id);

alter table plans enable row level security;

create policy if not exists plans_select_policy
  on plans for select
  using (true);

create policy if not exists plans_insert_policy
  on plans for insert
  with check (true);

-- Durable North Star history per profile. Replaces the in-memory
-- NORTH_STAR_CACHE dict (never invalidated on writes -> stale reads) with a
-- real, correctly-scoped log, and powers the "last updated" / "what's new"
-- indicators.
create table if not exists north_star_snapshots (
  id bigserial primary key,
  profile_id bigint not null references profiles(id) on delete cascade,
  payload jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_north_star_snapshots_profile_id_created_at
  on north_star_snapshots(profile_id, created_at desc);

alter table north_star_snapshots enable row level security;

create policy if not exists north_star_snapshots_select_policy
  on north_star_snapshots for select
  using (true);

create policy if not exists north_star_snapshots_insert_policy
  on north_star_snapshots for insert
  with check (true);

-- Optional backfill for pre-existing session rows (skip if you'd rather just
-- delete old demo sessions and re-onboard fresh):
--
-- insert into profiles (university, major, year)
-- select distinct university, major, year from sessions
-- where profile_id is null and coalesce(university, '') <> '';
--
-- update sessions s set profile_id = p.id
-- from profiles p
-- where s.profile_id is null
--   and s.university = p.university and s.major = p.major and s.year = p.year;
