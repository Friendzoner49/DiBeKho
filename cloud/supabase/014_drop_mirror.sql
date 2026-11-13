-- DiBeKho: drop the old one-way mirror of 001-005 (replaced by the real tables of 007 and two-way sync of 008).
-- No app since 0.5.0 and no web page reads or writes them any more; mirror_snapshot alone kept 30 whole copies of
-- the data as jsonb. The cloud's free space is limited (user, 13/11/2026), so they go.
-- Safe to run again. Kept: my_role(), profiles, web_inbox and everything from 007 on.

drop function if exists public.replace_mirror(jsonb, boolean);
drop table if exists public.mirror_snapshot;
drop table if exists public.mirror_movements;
drop table if exists public.mirror_document_lines;
drop table if exists public.mirror_documents;
drop table if exists public.mirror_stock;
drop table if exists public.mirror_products;
drop table if exists public.mirror_customers;
