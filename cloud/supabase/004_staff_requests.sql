-- DiBeKho Cloud v4: staff requests from the web -- Excel delivery notes and stock counts, besides goods-in slips.
-- Run once in the Supabase SQL editor (after 001 and 002). Nothing here lets staff change the books: a request
-- only waits in web_inbox until the owner approves it on the main machine (docs/cloud/04-thiet-ke-chot.md).

-- 1. the kinds of request web_inbox accepts
alter table public.web_inbox drop constraint if exists web_inbox_kind_check;
alter table public.web_inbox add constraint web_inbox_kind_check
    check (kind in ('receipt', 'delivery_file', 'stock_count'));

-- a request is a few KB (a count of 60 products ~3 KB): refuse anything past 256 KB so one account
-- cannot fill the 500 MB free database
alter table public.web_inbox drop constraint if exists web_inbox_payload_size;
alter table public.web_inbox add constraint web_inbox_payload_size check (pg_column_size(payload) <= 262144);

-- 2. private bucket for the uploaded Excel delivery notes: .xlsx only, 2 MB at most
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('inbox-files', 'inbox-files', false, 2097152,
        array['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'])
on conflict (id) do update set file_size_limit = excluded.file_size_limit,
                               allowed_mime_types = excluded.allowed_mime_types;

-- staff (editor) and the desktop may upload; only the desktop may read or delete what was uploaded
drop policy if exists inbox_files_staff_insert on storage.objects;
create policy inbox_files_staff_insert on storage.objects for insert to authenticated
    with check (bucket_id = 'inbox-files' and public.my_role() in ('editor', 'desktop'));
drop policy if exists inbox_files_desktop_select on storage.objects;
create policy inbox_files_desktop_select on storage.objects for select to authenticated
    using (bucket_id = 'inbox-files' and public.my_role() = 'desktop');
drop policy if exists inbox_files_desktop_delete on storage.objects;
create policy inbox_files_desktop_delete on storage.objects for delete to authenticated
    using (bucket_id = 'inbox-files' and public.my_role() = 'desktop');
