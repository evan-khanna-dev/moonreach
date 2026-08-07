-- Example RLS policies for the new opportunities table.
-- These policies assume the backend uses a service role key for writes and the app key for reads.
-- Adjust the auth.uid() checks if you later introduce real user authentication.

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
