-- DiBeKho cloud, step 012: settings every browser shares, set by the account manager only (today: the page size).
-- Run AFTER 011 (it uses dbk_account_owner). Safe to run again. Not part of the synced shop data: the desktop app never sees it.

create table if not exists public.web_settings (key text primary key, value text not null);
alter table public.web_settings enable row level security;
drop policy if exists web_settings_read on public.web_settings;
create policy web_settings_read on public.web_settings for select to authenticated using (public.my_role() is not null);
revoke all on public.web_settings from anon, authenticated;
grant select on public.web_settings to authenticated;

-- only maychinh (the account manager) may change it, and only to a size the page offers
create or replace function public.web_setting_set(p_key text, p_value text) returns void language plpgsql
security definer set search_path = public as $$
begin
    perform public.dbk_account_owner();
    if p_key is distinct from 'ui_scale' or p_value not in ('100', '110', '120') then
        raise exception 'Cài đặt không hợp lệ.';
    end if;
    insert into public.web_settings(key, value) values (p_key, p_value)
    on conflict (key) do update set value = excluded.value;
end $$;
revoke all on function public.web_setting_set(text, text) from public, anon;
grant execute on function public.web_setting_set(text, text) to authenticated;
