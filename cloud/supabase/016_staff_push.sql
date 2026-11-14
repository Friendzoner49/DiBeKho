-- DiBeKho cloud, step 016 (user's requests 15/11/2026). Run AFTER 015 (run 009 or 015 again -> run this again).
-- Safe to run again.
--
-- 1. Staff accounts in the app. The app now asks for the account when it opens and works on the shared data at
--    once. Only the owner (role 'desktop') writes the shared data (sync_push, 008). A staff account (role 'editor')
--    keeps working on its own machine; what that machine would push waits here, in push_requests, until the owner
--    approves it in the app (Cần xử lý): then the very batch the owner saw is written, through sync_push, under the
--    staff machine's device name, so that machine recognises its own rows at its next pull. One waiting request per
--    account and machine: the machine sends its whole queue again whenever it changes. Refused: the request stays
--    with the owner's reason; the staff machine shows it, and sends again once something changed.
--    A batch that touches a row someone changed after the staff machine last pulled (rev > base_rev), or that clashes
--    with what happened meanwhile (a code taken by someone else), is not written: the answer says 'stale' and the
--    request is closed with reason '__stale__'; the staff machine merges at its next round (a row changed on both
--    sides becomes a conflict there) and sends again.
-- 2. web_issue: the same product may stand on several lines (another quantity, another price), as in the app.

create or replace function public.web_api_version() returns integer language sql immutable as $$
    select 16
$$;

grant execute on function public.my_role() to authenticated;

create table if not exists public.push_requests (
    id          uuid primary key default gen_random_uuid(),
    created_by  uuid not null references auth.users(id) on delete cascade,
    sender      text not null default '',
    device      text not null default '',
    base_rev    bigint not null default 0,
    batch       jsonb not null default '{}',
    summary     jsonb not null default '[]',
    status      text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
    reason      text not null default '',
    created_at  timestamptz not null default now(),
    decided_at  timestamptz,
    decided_by  uuid,
    max_rev     bigint
);
create index if not exists push_requests_waiting on public.push_requests (status, created_at);

alter table public.push_requests enable row level security;
-- read only, and only through the functions below (security definer); no policy = no direct access
revoke all on public.push_requests from anon, authenticated;

-- the staff machine: send (or replace) what it wants to write
create or replace function public.push_request_send(p_device text, p_base bigint, p_batch jsonb, p_summary jsonb)
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_id uuid; v_name text;
begin
    if public.my_role() is distinct from 'editor' then raise exception 'not allowed'; end if;
    if jsonb_typeof(p_batch) is distinct from 'object' or jsonb_typeof(p_summary) is distinct from 'array' then
        raise exception 'bad request';
    end if;
    select coalesce(nullif(p.display_name, ''), split_part(u.email, '@', 1), '') into v_name
    from auth.users u left join public.profiles p on p.user_id = u.id where u.id = auth.uid();
    delete from public.push_requests where status <> 'pending' and decided_at < now() - interval '30 days';
    update public.push_requests set batch = p_batch, summary = p_summary, base_rev = p_base, created_at = now(),
                                    sender = coalesce(v_name, '')
    where created_by = auth.uid() and device = p_device and status = 'pending' returning id into v_id;
    if v_id is null then
        insert into public.push_requests(created_by, sender, device, base_rev, batch, summary)
        values (auth.uid(), coalesce(v_name, ''), p_device, p_base, p_batch, p_summary) returning id into v_id;
    end if;
    return jsonb_build_object('id', v_id);
end $$;

-- the staff machine: its newest request (to show 'waiting', 'approved' or the owner's reason)
create or replace function public.push_request_mine(p_device text) returns jsonb
language sql stable security definer set search_path = public as $$
    select coalesce((select jsonb_build_object('id', r.id, 'status', r.status, 'reason', r.reason,
                                               'created_at', r.created_at, 'decided_at', r.decided_at)
                     from public.push_requests r
                     where r.created_by = auth.uid() and r.device = p_device
                     order by r.created_at desc limit 1), 'null'::jsonb)
$$;

-- the staff machine gave its changes up (took the cloud's data again): nothing left to approve
create or replace function public.push_request_cancel(p_device text) returns void
language sql security definer set search_path = public as $$
    delete from public.push_requests where created_by = auth.uid() and device = p_device and status = 'pending'
$$;

-- the owner: what waits (without the batches: the summary is what the owner reads)
create or replace function public.push_requests_pending() returns jsonb
language plpgsql stable security definer set search_path = public as $$
begin
    if public.my_role() is distinct from 'desktop' then raise exception 'not allowed'; end if;
    return coalesce((select jsonb_agg(jsonb_build_object('id', r.id, 'sender', r.sender, 'device', r.device,
                                                         'summary', r.summary, 'created_at', r.created_at)
                                      order by r.created_at)
                     from public.push_requests r where r.status = 'pending'), '[]'::jsonb);
end $$;

-- the owner: approve (the batch is written as the staff machine's push) or refuse with a reason
create or replace function public.push_request_decide(p_id text, p_approve boolean, p_reason text default '')
returns jsonb language plpgsql security definer set search_path = public as $$
declare r public.push_requests; answer jsonb; t text; pk text; hit boolean := false;
begin
    if public.my_role() is distinct from 'desktop' then raise exception 'not allowed'; end if;
    select * into r from public.push_requests where id::text = p_id for update;
    if not found or r.status <> 'pending' then
        return jsonb_build_object('ok', false, 'reason', 'gone');
    end if;
    if not p_approve then
        update public.push_requests set status = 'rejected', reason = coalesce(p_reason, ''), decided_at = now(),
                                        decided_by = auth.uid() where id = r.id;
        return jsonb_build_object('ok', true);
    end if;
    perform pg_advisory_xact_lock(4242);
    foreach t in array public.core_tables() loop
        pk := case when t in ('product_aliases', 'ignored_lines', 'meta') then 'key' else 'id' end;
        execute format('select exists (select 1 from public.%I x join jsonb_array_elements($1) e '
                       'on x.%I::text = e ->> %L where x.rev > $2)', t, pk, pk)
            into hit using coalesce(r.batch -> t, '[]'::jsonb), r.base_rev;
        if hit then exit; end if;
    end loop;
    if not hit then
        begin
            answer := public.sync_push(r.device, public.core_max_rev(), r.batch);
        exception when unique_violation or foreign_key_violation or not_null_violation or check_violation then
            hit := true;
        end;
    end if;
    if hit then
        update public.push_requests set status = 'rejected', reason = '__stale__', decided_at = now(),
                                        decided_by = auth.uid() where id = r.id;
        return jsonb_build_object('ok', false, 'reason', 'stale');
    end if;
    update public.push_requests set status = 'approved', decided_at = now(), decided_by = auth.uid(),
                                    max_rev = (answer ->> 'max_rev')::bigint, batch = '{}'
    where id = r.id;
    return jsonb_build_object('ok', true, 'max_rev', (answer ->> 'max_rev')::bigint);
end $$;

revoke all on function public.push_request_send(text, bigint, jsonb, jsonb) from public, anon;
revoke all on function public.push_request_mine(text) from public, anon;
revoke all on function public.push_request_cancel(text) from public, anon;
revoke all on function public.push_requests_pending() from public, anon;
revoke all on function public.push_request_decide(text, boolean, text) from public, anon;
grant execute on function public.push_request_send(text, bigint, jsonb, jsonb) to authenticated;
grant execute on function public.push_request_mine(text) to authenticated;
grant execute on function public.push_request_cancel(text) to authenticated;
grant execute on function public.push_requests_pending() to authenticated;
grant execute on function public.push_request_decide(text, boolean, text) to authenticated;

-- ---------------------------------------------------------------------------------------------------------------
-- web_issue as in 015, without "a product only once"

create or replace function public.web_issue(p jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
    v_at timestamp; v_day date; v_code text; doc uuid := gen_random_uuid(); cust uuid;
    v_name text := dbk_clean(p ->> 'customer'); v_phone text := dbk_clean(p ->> 'phone');
    v_norm text; e jsonb; i integer := 0; pid uuid; qm double precision; qo double precision; q double precision;
    price double precision; amt double precision; total double precision := 0; priced boolean := false;
    pr public.products; places integer[] := '{}'; line_place integer;
begin
    perform dbk_owner();
    v_at := dbk_now();
    v_day := dbk_date(p -> 'doc_date');
    if v_name = '' then raise exception 'Hãy chọn hoặc ghi tên khách.'; end if;
    if p -> 'lines' is null or jsonb_typeof(p -> 'lines') <> 'array' or jsonb_array_length(p -> 'lines') = 0 then
        raise exception 'Phiếu chưa có dòng hàng nào.';
    end if;
    v_norm := dbk_phone(v_phone);
    if v_norm <> '' then
        select id into cust from customers where not deleted and phone_norm = v_norm order by created_at limit 1;
    end if;
    if cust is null then
        select id into cust from customers where not deleted and dbk_unaccent(name) = dbk_unaccent(v_name)
        order by created_at limit 1;
    end if;
    if cust is null then
        cust := gen_random_uuid();
        insert into customers(id, name, contact, phone, phone_norm, address, created_at, origin)
        values (cust, v_name, dbk_clean(p ->> 'contact'), v_phone, v_norm, dbk_clean(p ->> 'address'), v_at, 'web');
    else
        update customers set contact = case when contact = '' then dbk_clean(p ->> 'contact') else contact end,
                             phone = case when phone = '' then v_phone else phone end,
                             phone_norm = case when phone_norm = '' then v_norm else phone_norm end,
                             address = case when address = '' then dbk_clean(p ->> 'address') else address end,
                             origin = 'web'
        where id = cust;
    end if;
    v_code := dbk_next_issue_code('W');
    insert into documents(id, kind, code, code_norm, doc_date, customer_id, created_at, location_id, location_set,
                          prices_read, source_file, origin)
    values (doc, 'delivery', v_code, v_code, v_day, cust, v_at, 1, true, true, 'PhieuXuat_' || v_code || '.xlsx', 'web');
    for e in select * from jsonb_array_elements(p -> 'lines') loop
        begin
            pid := (e ->> 'product_id')::uuid;
            qm := coalesce(nullif(e ->> 'qty_main', '')::double precision, 0);
            qo := coalesce(nullif(e ->> 'qty_office', '')::double precision, 0);
            price := nullif(e ->> 'unit_price', '')::double precision;
        exception when others then
            raise exception 'Dòng hàng không hợp lệ.';
        end;
        select * into pr from products where id = pid and not deleted;
        if not found then
            raise exception 'Mặt hàng không còn trong danh mục (đã bị gộp hoặc xoá). Hãy tải lại trang.';
        end if;
        if qm < 0 or qo < 0 or coalesce(price, 0) < 0 or qm = 'NaN' or qo = 'NaN' or price = 'NaN' then
            raise exception 'Số lượng và đơn giá không được âm.';
        end if;
        q := qm + qo;
        if q <= 0 then continue; end if;
        i := i + 1;
        amt := case when price is null then null else round((q * price)::numeric, 2)::double precision end;
        if amt is not null then total := total + amt; priced := true; end if;
        line_place := case when qm > 0 and qo > 0 then null when qo > 0 then 2 else 1 end;
        insert into document_lines(id, document_id, line_no, product_id, qty, raw_name, raw_spec, note, unit_price,
                                   amount, location_id, origin)
        values (gen_random_uuid(), doc, 8 + i, pid, q,
                case when pr.name_zh <> '' and trim(pr.name_vi || ' ' || coalesce(pr.variant, '')) <> ''
                     then pr.name_zh || E'\n' || trim(pr.name_vi || ' ' || coalesce(pr.variant, ''))
                     else coalesce(nullif(trim(pr.name_vi || ' ' || coalesce(pr.variant, '')), ''), pr.name_zh) end,
                pr.spec, dbk_clean(e ->> 'note'), price, amt, line_place, 'web');
        if qm > 0 then
            perform dbk_move(pid, -qm, doc, 'delivery_out', v_day, 1, v_at);
            places := array_append(places, 1);
        end if;
        if qo > 0 then
            perform dbk_move(pid, -qo, doc, 'delivery_out', v_day, 2, v_at);
            places := array_append(places, 2);
        end if;
    end loop;
    if i = 0 then raise exception 'Phiếu chưa có dòng hàng nào.'; end if;
    update documents set location_id = case when 2 = all(places) then 2 else 1 end,
                         fee_amount = case when priced then 0 end,
                         note_total = case when priced then total end
    where id = doc;
    return jsonb_build_object('id', doc, 'code', v_code);
end $$;

revoke all on function public.web_issue(jsonb) from public, anon;
grant execute on function public.web_issue(jsonb) to authenticated;
