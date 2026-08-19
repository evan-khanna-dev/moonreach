drop policy if exists north_star_snapshots_insert_policy on north_star_snapshots;
drop policy if exists north_star_snapshots_select_policy on north_star_snapshots;
drop index if exists idx_north_star_snapshots_profile_id_created_at;
drop table if exists north_star_snapshots;

drop policy if exists plans_insert_policy on plans;
drop policy if exists plans_select_policy on plans;
drop index if exists idx_plans_session_id;
drop table if exists plans;

drop policy if exists messages_insert_policy on messages;
drop policy if exists messages_select_policy on messages;

drop policy if exists sessions_update_policy on sessions;
drop policy if exists sessions_insert_policy on sessions;
drop policy if exists sessions_select_policy on sessions;

drop index if exists idx_sessions_profile_id;
alter table sessions drop column if exists profile_id;

drop policy if exists profiles_update_policy on profiles;
drop policy if exists profiles_insert_policy on profiles;
drop policy if exists profiles_select_policy on profiles;
drop index if exists idx_profiles_device_id;
drop table if exists profiles;
