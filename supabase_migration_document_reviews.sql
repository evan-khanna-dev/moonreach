-- Appointments: document reviews (resume feedback first; CV/cover letter/LinkedIn later).
-- Intentionally separate from messages, plans, and north_star_snapshots -
-- document reviews must never be counted as career radar opportunities or
-- fed into North Star's goal-tracking; they're a distinct activity type.

create table if not exists document_reviews (
  id bigserial primary key,
  session_id bigint not null references sessions(id) on delete cascade,
  document_type text not null default 'resume',
  document_content text not null,
  intent text,
  role_context jsonb,
  ai_feedback jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_document_reviews_session_id on document_reviews(session_id);

alter table document_reviews enable row level security;

drop policy if exists document_reviews_select_policy on document_reviews;
create policy document_reviews_select_policy
  on document_reviews for select
  using (true);

drop policy if exists document_reviews_insert_policy on document_reviews;
create policy document_reviews_insert_policy
  on document_reviews for insert
  with check (true);
