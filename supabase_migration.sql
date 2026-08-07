-- Career Radar schema for MoonReach
-- Add a durable opportunities table so each session has a persistent radar.

create table if not exists opportunities (
  id bigserial primary key,
  session_id bigint not null references sessions(id) on delete cascade,
  title text not null,
  category text not null default 'Other',
  description text not null default '',
  reason_relevant text not null default '',
  source_url text,
  priority_score integer not null default 5 check (priority_score between 1 and 10),
  status text not null default 'suggested' check (status in ('suggested','interested','exploring','applied','completed','archived')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_opportunities_session_id on opportunities(session_id);
create index if not exists idx_opportunities_status on opportunities(status);
create index if not exists idx_opportunities_priority_score on opportunities(priority_score);
create index if not exists idx_opportunities_updated_at on opportunities(updated_at desc);

alter table opportunities enable row level security;
