-- Scene UI: backend additions for the 3D-scene rewrite.
-- - opportunities.notes: user-authored freeform notes, distinct from the
--   AI-authored reason_relevant (radar/moon panel).
-- - profiles.north_star_goal/name/interests/bio: new fields surfaced in the
--   ridge (profile) and star (north star) panels.
-- - messages index: defensive addition - every session-history/last-message
--   query depends on this and it wasn't confirmed to already exist.

alter table opportunities add column if not exists notes text;

alter table profiles add column if not exists north_star_goal text;
alter table profiles add column if not exists name text;
alter table profiles add column if not exists interests text;
alter table profiles add column if not exists bio text;

create index if not exists idx_messages_session_created on messages(session_id, created_at desc);
