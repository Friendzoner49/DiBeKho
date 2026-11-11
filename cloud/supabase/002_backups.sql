-- DiBeKho Cloud v2: private bucket for FULL database backups (docs/cloud/04-thiet-ke-chot.md, section 4).
-- The desktop uploads a copy of kho.sqlite after every push and keeps the newest 30; only the 'desktop'
-- account can write, list, read or delete them. Run once in the Supabase SQL editor.

insert into storage.buckets (id, name, public, file_size_limit)
values ('backups', 'backups', false, 52428800)   -- private, 50 MB per file (the database is well under 1 MB)
on conflict (id) do nothing;

create policy backups_desktop_insert on storage.objects for insert to authenticated
    with check (bucket_id = 'backups' and public.my_role() = 'desktop');
create policy backups_desktop_select on storage.objects for select to authenticated
    using (bucket_id = 'backups' and public.my_role() = 'desktop');
create policy backups_desktop_delete on storage.objects for delete to authenticated
    using (bucket_id = 'backups' and public.my_role() = 'desktop');
