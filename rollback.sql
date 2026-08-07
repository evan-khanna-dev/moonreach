drop policy if exists opportunities_delete_policy on opportunities;
drop policy if exists opportunities_update_policy on opportunities;
drop policy if exists opportunities_insert_policy on opportunities;
drop policy if exists opportunities_select_policy on opportunities;
drop index if exists idx_opportunities_updated_at;
drop index if exists idx_opportunities_priority_score;
drop index if exists idx_opportunities_status;
drop index if exists idx_opportunities_session_id;
drop table if exists opportunities;
