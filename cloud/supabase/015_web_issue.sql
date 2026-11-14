-- DiBeKho cloud, step 015: a Phiếu xuất kho made on the web page by the owner (role desktop) takes the stock at once
-- (user's request 14/11/2026: the web is the reference data, the owner works there, no scan or approval in between).
-- Run AFTER 009 (it uses its helpers; run 009 again -> run this again). Safe to run again.
--
-- web_issue(p) records what core/issues.save records in the app: one 'delivery' document, the customer found by phone
-- then by name (catalog.upsert_customer) or added, one line per product with its price, and the stock taken from
-- Kho tổng and/or Văn phòng (a line taken from both has no single place, its movements say where).
-- The code is W + the highest order number so far + 1 (core/issues.next_code: '159', 'A160', 'W161' count, cancelled
-- ones too); the page writes the Excel file with that code afterwards. When that file is put into a main machine's
-- notes folder the app recognises the order by its code and never takes the stock twice (deliveries.process_file).
-- Lines are numbered like the rows of the file (the first item is row 9), as a note read by the app would be.
--
-- p = {doc_date 'yyyy-mm-dd', customer, phone, contact, address,
--      lines: [{product_id, qty_main, qty_office, unit_price (null = no price), note}]}

create or replace function public.web_api_version() returns integer language sql immutable as $$
    select 15
$$;

create or replace function public.dbk_next_issue_code(p_prefix text) returns text language sql stable as $$
    select p_prefix || (coalesce(max((regexp_match(code, '([0-9]+)'))[1]::bigint), 0) + 1)::text
    from public.documents
    where kind = 'delivery' and not deleted and code ~ '^\s*[AaWw]?\s*[0-9]{1,9}\s*$'
$$;

create or replace function public.dbk_phone(p text) returns text language sql immutable as $$
    select case when d ~ '^84' and length(d) >= 11 then '0' || substr(d, 3) else d end
    from (select regexp_replace(coalesce(p, ''), '\D', '', 'g') as d) x
$$;

create or replace function public.web_issue(p jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
    v_at timestamp; v_day date; v_code text; doc uuid := gen_random_uuid(); cust uuid;
    v_name text := dbk_clean(p ->> 'customer'); v_phone text := dbk_clean(p ->> 'phone');
    v_norm text; e jsonb; i integer := 0; pid uuid; qm double precision; qo double precision; q double precision;
    price double precision; amt double precision; total double precision := 0; priced boolean := false;
    pr public.products; places integer[] := '{}'; line_place integer; seen uuid[] := '{}';
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
        if pid = any(seen) then raise exception 'Một mặt hàng bị nhập hai lần.'; end if;
        seen := seen || pid;
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
revoke all on function public.web_api_version() from public, anon;
grant execute on function public.web_api_version() to authenticated;
revoke all on function public.dbk_next_issue_code(text) from public, anon, authenticated;
revoke all on function public.dbk_phone(text) from public, anon, authenticated;
