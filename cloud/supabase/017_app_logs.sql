-- DiBeKho cloud, step 017 (user's request 15/11/2026): every account's activity log, for the maychinh login only.
-- Run AFTER 011 (it uses dbk_account_owner) and 016. Safe to run again.
--
-- Each app (owner, staff, any role) sends its own data/app.log, one row per account + machine + day, replaced while
-- the day lasts, kept 30 days. The app removes names before sending (core/cloud/logs.py: file names, quoted texts,
-- phone numbers, e-mails, paths; scan/apply/receipt lines keep only their counts) and the user can switch it off
-- (Cài đặt → Cloud). Only maychinh reads the rows (web: Cài đặt → Nhật ký); the other owners never see them: no policy
-- on the table, reads only through log_list / log_get, which call dbk_account_owner().
-- Replaces the gzip files of nhat-ky/ in the 'backups' bucket (any owner could read those): they are deleted below.

create or replace function public.web_api_version() returns integer language sql immutable as $$
    select 17
$$;

create table if not exists public.app_logs (
    user_id     uuid not null references auth.users(id) on delete cascade,
    device      text not null,
    day         date not null,
    sender      text not null default '',
    version     text not null default '',
    content     text not null default '',
    updated_at  timestamptz not null default now(),
    primary key (user_id, device, day)
);
create index if not exists app_logs_day on public.app_logs (day);

alter table public.app_logs enable row level security;
revoke all on public.app_logs from anon, authenticated;

-- any signed-in account with a role: send (or replace) one day of this machine's log
create or replace function public.log_send(p_device text, p_version text, p_day date, p_content text)
returns void language plpgsql security definer set search_path = public as $$
declare v_name text;
begin
    if auth.uid() is null or public.my_role() is null then raise exception 'not allowed'; end if;
    if p_device is null or length(p_device) not between 1 and 80 or length(coalesce(p_version, '')) > 40
       or p_day is null or p_day > current_date + 1 or p_day < current_date - 30 then
        raise exception 'bad request';
    end if;
    if length(coalesce(p_content, '')) > 300000 then  -- a day is a few KB; never let one machine fill the database
        p_content := right(p_content, 300000);
    end if;
    select coalesce(nullif(p.display_name, ''), split_part(u.email, '@', 1), '') into v_name
    from auth.users u left join public.profiles p on p.user_id = u.id where u.id = auth.uid();
    insert into public.app_logs(user_id, device, day, sender, version, content, updated_at)
    values (auth.uid(), p_device, p_day, coalesce(v_name, ''), coalesce(p_version, ''), coalesce(p_content, ''), now())
    on conflict (user_id, device, day) do update
        set sender = excluded.sender, version = excluded.version, content = excluded.content, updated_at = now();
    delete from public.app_logs where day < current_date - 30;
end $$;

-- maychinh: what is there (no content), newest first
create or replace function public.log_list() returns jsonb language plpgsql stable
security definer set search_path = public as $$
begin
    perform public.dbk_account_owner();
    return coalesce((select jsonb_agg(jsonb_build_object(
                'user_id', user_id, 'sender', sender, 'device', device, 'day', day, 'version', version,
                'bytes', octet_length(content), 'updated_at', updated_at,
                'errors', (length(content) - length(replace(content, '[error]', ''))) / 7
                        + (length(content) - length(replace(content, '[crash]', ''))) / 7)
            order by day desc, sender, device)
        from public.app_logs), '[]'::jsonb);
end $$;

-- maychinh: one day of one machine
create or replace function public.log_get(p_user uuid, p_device text, p_day date) returns text language plpgsql stable
security definer set search_path = public as $$
begin
    perform public.dbk_account_owner();
    return (select content from public.app_logs where user_id = p_user and device = p_device and day = p_day);
end $$;

revoke all on function public.log_send(text, text, date, text) from public, anon;
revoke all on function public.log_list() from public, anon;
revoke all on function public.log_get(uuid, text, date) from public, anon;
grant execute on function public.log_send(text, text, date, text) to authenticated;
grant execute on function public.log_list() to authenticated;
grant execute on function public.log_get(uuid, text, date) to authenticated;

-- the old per-machine files (they held names, and every owner could read them)
do $$
begin
    delete from storage.objects where bucket_id = 'backups' and name like 'nhat-ky/%';
exception when others then null;  -- no storage schema (tests), or Supabase refuses: each app deletes its own file
end $$;
