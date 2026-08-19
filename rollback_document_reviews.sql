drop policy if exists document_reviews_insert_policy on document_reviews;
drop policy if exists document_reviews_select_policy on document_reviews;
drop index if exists idx_document_reviews_session_id;
drop table if exists document_reviews;
