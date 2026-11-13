-- DiBeKho cloud, step 010: "★ Mặt hàng mới" while entering goods on the web, like the app's receipt window.
-- Run AFTER 009_web_rpc.sql (it replaces web_receipt). Safe to run again.
--
-- A receipt line may carry {"new": {name_vi, name_zh, spec, variant, unit, category}} instead of a product_id:
-- the product is created INSIDE the same transaction as the receipt (receipts.save creates its NewProduct lines
-- the same way), so a receipt that fails leaves no stray product behind -- and no product code used up, since a
-- code freed by deleting is never given again. The web asks about look-alike products before sending (the
-- app's receipts.same_as_existing), so the product is created even when an exact twin exists.

create or replace function public.web_api_version() returns integer language sql immutable as $$
    select 10
$$;

create or replace function public.web_receipt(p jsonb, p_replaces uuid default null) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
    v_at timestamp; v_code text; old public.documents; sup uuid; cust uuid; doc uuid := gen_random_uuid();
    src text := p ->> 'source'; v_day date; loc integer; sname text;
    e jsonb; lines jsonb := '[]'::jsonb; made jsonb; keys text[] := '{}'; k text;
begin
    perform dbk_owner();
    v_at := dbk_now();
    v_day := dbk_date(p -> 'doc_date');
    loc := dbk_place(coalesce(p -> 'location_id', '1'));
    if src = 'supplier' then
        sname := dbk_clean(p ->> 'supplier_name');
        if sname = '' then raise exception 'Hãy ghi nguồn hàng.'; end if;
    elsif src = 'return' then
        begin
            cust := (p ->> 'customer_id')::uuid;
        exception when others then cust := null;
        end;
        if cust is null or not exists (select 1 from customers where id = cust and not deleted) then
            raise exception 'Hãy chọn khách trả lại hàng.';
        end if;
    else
        raise exception 'Hãy chọn hàng về từ đâu.';
    end if;
    if p -> 'lines' is null or jsonb_typeof(p -> 'lines') <> 'array' then
        raise exception 'Phiếu chưa có dòng hàng nào.';
    end if;
    v_code := dbk_next_doc_code('receipt', 'HV');
    if p_replaces is not null then
        old := dbk_doc(p_replaces);
        if old.kind <> 'receipt' then raise exception 'Chỉ sửa được phiếu hàng về.'; end if;
        perform dbk_close(p_replaces, 'replaced', v_at);
        v_code := coalesce(nullif(old.code, ''), v_code);
    end if;
    if src = 'supplier' then  -- receipts._supplier_id
        select id into sup from suppliers where not deleted and dbk_unaccent(name) = dbk_unaccent(sname)
        order by created_at limit 1;
        if sup is null then
            sup := gen_random_uuid();
            insert into suppliers(id, name, created_at, origin) values (sup, sname, v_at, 'web');
        end if;
    end if;
    -- receipts.save: the new products first (in line order, so their codes follow the app's), then the lines
    for e in select * from jsonb_array_elements(p -> 'lines') loop
        if jsonb_typeof(e -> 'new') = 'object' then
            if dbk_clean(e -> 'new' ->> 'name_vi') = '' then raise exception 'Mặt hàng mới phải có tên.'; end if;
            k := replace(dbk_unaccent(dbk_clean(e -> 'new' ->> 'name_vi')), ' ', '') || '|' ||
                 replace(dbk_unaccent(dbk_clean(e -> 'new' ->> 'spec')), ' ', '') || '|' ||
                 replace(dbk_unaccent(dbk_clean(e -> 'new' ->> 'variant')), ' ', '');
            if k = any(keys) then raise exception 'Một mặt hàng mới bị nhập hai lần.'; end if;
            keys := keys || k;
            made := web_product_add((e -> 'new') || '{"allow_duplicate": true}'::jsonb);
            e := (e - 'new') || jsonb_build_object('product_id', made ->> 'id');
        end if;
        lines := lines || jsonb_build_array(e);
    end loop;
    insert into documents(id, kind, code, code_norm, doc_date, customer_id, note, created_at, receipt_source,
                          supplier_id, ref_code, location_id, source_file, origin)
    values (doc, 'receipt', v_code, v_code, v_day, cust, dbk_clean(p ->> 'note'), v_at, src, sup,
            case when src = 'return' then dbk_clean(p ->> 'ref_code') else '' end, loc,
            'HangVe_' || v_code || '_' || v_day || case when p_replaces is null then '' else '_' || (
                select count(*) + 1 from documents where kind = 'receipt' and code = v_code and not deleted) end
            || '.xlsx', 'web');
    perform dbk_add_lines(doc, lines, 'receipt_in', 1, v_day, loc, null, v_at);
    return jsonb_build_object('id', doc, 'code', v_code);
end $$;

revoke all on function public.web_receipt(jsonb, uuid) from public, anon;
grant execute on function public.web_receipt(jsonb, uuid) to authenticated;
revoke all on function public.web_api_version() from public, anon;
grant execute on function public.web_api_version() to authenticated;
