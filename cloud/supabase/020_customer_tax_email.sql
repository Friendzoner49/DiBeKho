-- DiBeKho cloud, step 020 (customer's request 18/11/2026): two more facts about a customer, MST (tax code) and e-mail
-- (the new delivery note template has 'MST 税号' and 'email邮箱'; app migration 012, schema 12). Customers recorded
-- before stay empty. The app sends both columns when it syncs, so run this BEFORE the first app with schema 12 signs
-- in, and before the new web page is uploaded. Run AFTER 019 (it replaces web_issue again; run 015, 016 or 019 again
-- -> run this again). Safe to run again.
--
-- An app older than this (0.5.7, the Mac's Swift app) pushes customers without these keys: sync_push fills every
-- column of the table from the JSON (core_columns, 008), so they arrive as NULL. The trigger below keeps what the
-- cloud already has instead (as 018 does for the currency), and '' for a new row, before NOT NULL is checked.
--
-- web_issue (the owner's Phiếu xuất kho on the web) takes tax_code and email like phone and address: a new customer
-- gets them, an existing one gets them only where empty. Its lines are numbered from row 10 now (the issue note's
-- table header moved from row 8 to row 9 to make room for the MST / email row).

alter table public.customers add column if not exists tax_code text not null default '';
alter table public.customers add column if not exists email text not null default '';

create or replace function public.dbk_keep_customer_extra() returns trigger language plpgsql as $$
declare old_tax text; old_email text;
begin
    if new.tax_code is null or new.email is null then
        if tg_op = 'UPDATE' then
            old_tax := old.tax_code; old_email := old.email;
        else
            -- sync_push is an insert ... on conflict do update: the proposed row passes here first and becomes
            -- 'excluded', so it must already carry what the existing row has
            select c.tax_code, c.email into old_tax, old_email from public.customers c where c.id = new.id;
        end if;
        new.tax_code := coalesce(new.tax_code, old_tax, '');
        new.email := coalesce(new.email, old_email, '');
    end if;
    return new;
end $$;

drop trigger if exists customers_keep_extra on public.customers;
create trigger customers_keep_extra before insert or update on public.customers
    for each row execute function public.dbk_keep_customer_extra();

-- catalog.merge_customers keeps the first MST / e-mail found when the survivor has none (009 kept only the name)
create or replace function public.web_customer_merge(p_ids uuid[], p_name text) returns jsonb
language plpgsql security definer set search_path = public as $$
declare nm text := dbk_clean(p_name); keep uuid; n integer;
begin
    perform dbk_owner();
    select count(*) into n from customers where id = any(p_ids) and not deleted;
    if nm = '' or n < 2 or n <> cardinality(array(select distinct unnest(p_ids))) then
        raise exception 'Chọn từ 2 khách hàng trở lên và nhập tên khách hàng chung.';
    end if;
    select id into keep from customers where not deleted and dbk_unaccent(name) = dbk_unaccent(nm)
    order by created_at, id limit 1;
    if keep is null then
        select id into keep from customers where id = any(p_ids) order by created_at, id limit 1;
    end if;
    update customers k set
        tax_code = case when k.tax_code <> '' then k.tax_code else coalesce((select c.tax_code from customers c
            where c.id = any(p_ids) and not c.deleted and c.tax_code <> '' order by c.created_at, c.id limit 1), '') end,
        email = case when k.email <> '' then k.email else coalesce((select c.email from customers c
            where c.id = any(p_ids) and not c.deleted and c.email <> '' order by c.created_at, c.id limit 1), '') end
    where k.id = keep;
    update documents set customer_id = keep, origin = 'web'
    where customer_id = any(p_ids) and customer_id <> keep and not deleted;
    update customers set deleted = true, origin = 'web' where id = any(p_ids) and id <> keep and not deleted;
    update customers set name = nm, origin = 'web' where id = keep;
    return jsonb_build_object('id', keep);
end $$;

create or replace function public.web_api_version() returns integer language sql immutable as $$
    select 20
$$;

create or replace function public.web_issue(p jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
    v_at timestamp; v_day date; v_code text; doc uuid := gen_random_uuid(); cust uuid;
    v_name text := dbk_clean(p ->> 'customer'); v_phone text := dbk_clean(p ->> 'phone');
    v_norm text; e jsonb; i integer := 0; pid uuid; qm double precision; qo double precision; q double precision;
    price double precision; amt double precision; total double precision := 0; priced boolean := false;
    pr public.products; places integer[] := '{}'; line_place integer; made jsonb := '{}'::jsonb; k text;
    line_ids jsonb := '[]'::jsonb;
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
        insert into customers(id, name, contact, phone, phone_norm, address, tax_code, email, created_at, origin)
        values (cust, v_name, dbk_clean(p ->> 'contact'), v_phone, v_norm, dbk_clean(p ->> 'address'),
                dbk_clean(p ->> 'tax_code'), dbk_clean(p ->> 'email'), v_at, 'web');
    else
        update customers set contact = case when contact = '' then dbk_clean(p ->> 'contact') else contact end,
                             phone = case when phone = '' then v_phone else phone end,
                             phone_norm = case when phone_norm = '' then v_norm else phone_norm end,
                             address = case when address = '' then dbk_clean(p ->> 'address') else address end,
                             tax_code = case when tax_code = '' then dbk_clean(p ->> 'tax_code') else tax_code end,
                             email = case when email = '' then dbk_clean(p ->> 'email') else email end,
                             origin = 'web'
        where id = cust;
    end if;
    v_code := dbk_next_issue_code('W');
    insert into documents(id, kind, code, code_norm, doc_date, customer_id, created_at, location_id, location_set,
                          prices_read, source_file, origin)
    values (doc, 'delivery', v_code, v_code, v_day, cust, v_at, 1, true, true, 'PhieuXuat_' || v_code || '.xlsx', 'web');
    for e in select * from jsonb_array_elements(p -> 'lines') loop
        begin
            qm := coalesce(nullif(e ->> 'qty_main', '')::double precision, 0);
            qo := coalesce(nullif(e ->> 'qty_office', '')::double precision, 0);
            price := nullif(e ->> 'unit_price', '')::double precision;
        exception when others then
            raise exception 'Dòng hàng không hợp lệ.';
        end;
        if qm < 0 or qo < 0 or coalesce(price, 0) < 0 or qm = 'NaN' or qo = 'NaN' or price = 'NaN' then
            raise exception 'Số lượng và đơn giá không được âm.';
        end if;
        q := qm + qo;
        if q <= 0 then
            line_ids := line_ids || 'null'::jsonb;
            continue;
        end if;
        if jsonb_typeof(e -> 'new') = 'object' then
            if dbk_clean(e -> 'new' ->> 'name_vi') = '' then raise exception 'Mặt hàng mới phải có tên.'; end if;
            k := replace(dbk_unaccent(dbk_clean(e -> 'new' ->> 'name_vi')), ' ', '') || '|' ||
                 replace(dbk_unaccent(dbk_clean(e -> 'new' ->> 'spec')), ' ', '') || '|' ||
                 replace(dbk_unaccent(dbk_clean(e -> 'new' ->> 'variant')), ' ', '');
            if not made ? k then
                made := made || jsonb_build_object(k, web_product_add((e -> 'new') || '{"allow_duplicate": true}'::jsonb) ->> 'id');
            end if;
            pid := (made ->> k)::uuid;
        else
            begin
                pid := (e ->> 'product_id')::uuid;
            exception when others then
                raise exception 'Dòng hàng không hợp lệ.';
            end;
        end if;
        select * into pr from products where id = pid and not deleted;
        if not found then
            raise exception 'Mặt hàng không còn trong danh mục (đã bị gộp hoặc xoá). Hãy tải lại trang.';
        end if;
        line_ids := line_ids || to_jsonb(pid::text);
        i := i + 1;
        amt := case when price is null then null else round((q * price)::numeric, 2)::double precision end;
        if amt is not null then total := total + amt; priced := true; end if;
        line_place := case when qm > 0 and qo > 0 then null when qo > 0 then 2 else 1 end;
        insert into document_lines(id, document_id, line_no, product_id, qty, raw_name, raw_spec, note, unit_price,
                                   amount, location_id, origin)
        values (gen_random_uuid(), doc, 9 + i, pid, q,
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
    -- product_ids: the product of each line sent, in order (null = no quantity), so the page writes the new products'
    -- codes into the file it makes next
    return jsonb_build_object('id', doc, 'code', v_code, 'product_ids', line_ids);
end $$;

revoke all on function public.web_issue(jsonb) from public, anon;
grant execute on function public.web_issue(jsonb) to authenticated;
revoke all on function public.web_customer_merge(uuid[], text) from public, anon;
grant execute on function public.web_customer_merge(uuid[], text) to authenticated;
revoke all on function public.web_api_version() from public, anon;
grant execute on function public.web_api_version() to authenticated;
