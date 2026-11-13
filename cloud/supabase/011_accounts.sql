-- DiBeKho cloud, step 011: the owner manages accounts from the web page (Cài đặt → Tài khoản).
-- Run AFTER 009 (it uses dbk_clean; profiles and my_role come from 001). Safe to run again. Needs no products, no shared data: only the owner role.
--
-- What lives where:
--   * creating an account and setting its password need Supabase's admin API, whose key must never reach a browser:
--     that is the Edge Function `accounts` (cloud/supabase/functions/accounts/index.ts).
--   * everything else is plain SQL below: list the accounts, give / change a role, take the role away.
-- The role lives in public.profiles (Supabase itself has no such thing); no row = signed in but allowed to read nothing.

create or replace function public.dbk_account_owner() returns uuid language plpgsql stable
security definer set search_path = public as $$
begin
    -- only ONE account manages accounts (customer's decision 13/11/2026: the main machine's login, not every owner)
    if auth.uid() is null or public.my_role() is distinct from 'desktop'
       or (select lower(email) from auth.users where id = auth.uid()) is distinct from 'maychinh@dibekho.local' then
        raise exception 'Chỉ tài khoản của chủ mới quản lý được tài khoản.';
    end if;
    return auth.uid();
end $$;

-- every account with its role ('' = no role yet): only ids and e-mails of auth.users are read
create or replace function public.web_accounts_list() returns jsonb language plpgsql stable
security definer set search_path = public as $$
begin
    perform public.dbk_account_owner();
    return coalesce((select jsonb_agg(jsonb_build_object(
                'id', u.id, 'email', u.email, 'display_name', coalesce(p.display_name, ''), 'role', coalesce(p.role, ''))
            order by u.email)
        from auth.users u left join public.profiles p on p.user_id = u.id), '[]'::jsonb);
end $$;

-- give an account a role, or change it (also brings back an account whose role was taken away)
create or replace function public.web_account_set_role(p_user uuid, p_role text, p_name text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare me uuid := public.dbk_account_owner(); mail text; cur public.profiles; nm text;
begin
    if p_role is null or p_role not in ('desktop', 'editor', 'viewer') then
        raise exception 'Vai trò không hợp lệ.';
    end if;
    select email into mail from auth.users where id = p_user;
    if not found then raise exception 'Không tìm thấy tài khoản này.'; end if;
    if p_user = me and p_role <> 'desktop' then
        raise exception 'Không tự hạ quyền của chính mình được (sẽ không còn ai quản lý). Nhờ chủ khác làm.';
    end if;
    select * into cur from public.profiles where user_id = p_user;
    nm := coalesce(nullif(public.dbk_clean(p_name), ''), nullif(cur.display_name, ''), split_part(coalesce(mail, ''), '@', 1));
    insert into public.profiles (user_id, display_name, role) values (p_user, left(nm, 60), p_role)
    on conflict (user_id) do update set display_name = excluded.display_name, role = excluded.role;
    if not exists (select 1 from public.profiles where role = 'desktop') then  -- cannot happen: the caller stays; belt and braces
        raise exception 'Phải còn ít nhất một tài khoản chủ.';
    end if;
    return jsonb_build_object('id', p_user, 'role', p_role);
end $$;

-- take the role away: the account can still sign in but reads and writes nothing (kept, not deleted: requests it
-- sent still point to it)
create or replace function public.web_account_revoke(p_user uuid) returns jsonb language plpgsql
security definer set search_path = public as $$
declare me uuid := public.dbk_account_owner();
begin
    if p_user = me then
        raise exception 'Không tự thu hồi quyền của chính mình được. Nhờ chủ khác làm.';
    end if;
    if not exists (select 1 from auth.users where id = p_user) then
        raise exception 'Không tìm thấy tài khoản này.';
    end if;
    delete from public.profiles where user_id = p_user;
    if not exists (select 1 from public.profiles where role = 'desktop') then
        raise exception 'Phải còn ít nhất một tài khoản chủ.';
    end if;
    return jsonb_build_object('id', p_user, 'role', '');
end $$;

revoke all on function public.dbk_account_owner() from public, anon, authenticated;
do $$
declare f text;
begin
    foreach f in array array['web_accounts_list()', 'web_account_set_role(uuid, text, text)', 'web_account_revoke(uuid)'] loop
        execute format('revoke all on function public.%s from public, anon', f);
        execute format('grant execute on function public.%s to authenticated', f);
    end loop;
end $$;
