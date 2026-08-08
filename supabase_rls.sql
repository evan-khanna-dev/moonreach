-- Example RLS policies for the opportunities table.
-- The app is session-based and does not rely on user authentication, so these policies are intentionally permissive.
-- If you later introduce real authentication, tighten these rules around session ownership instead of auth.uid().

create policy if not exists opportunities_select_policy
  on opportunities for select
  using (true);

create policy if not exists opportunities_insert_policy
  on opportunities for insert
  with check (true);

create policy if not exists opportunities_update_policy
  on opportunities for update
  using (true)
  with check (true);

create policy if not exists opportunities_delete_policy
  on opportunities for delete
  using (true);
