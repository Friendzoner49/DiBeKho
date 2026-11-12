-- DiBeKho: the owner works on the shared data from the web, like in the app (docs/cloud/06-cloud-la-goc.md, step 4).
-- Run once in the Supabase SQL Editor after 007 and 008.
--
-- Each function is one transaction, re-implements ONE function of the app's core (named in its comment) and is tested
-- against it in tests/test_cloud_web_rpc.py: same input -> same documents, lines and stock movements once the app has
-- pulled them. Only the owner's account (role 'desktop') may call them; staff keep sending requests to web_inbox.
-- Times: created_at is the SHOP's wall clock like the app writes it (meta clock_offset_min, sent by the app; Vietnam
-- +7 h when missing), from the server's clock -- never the browser's.
-- Every UPDATE has a WHERE (Supabase loads pg_safeupdate).

-- ---------------------------------------------------------------- helpers

-- core.text.unaccent: lowercase, strip the accents, đ -> d
create or replace function public.dbk_unaccent(s text) returns text language sql immutable as $$
    select replace(regexp_replace(normalize(lower(coalesce(s, '')), NFKD), '[̀-ͯ]', '', 'g'), 'đ', 'd')
$$;

-- core.text.clean: NFC, whitespace collapsed, trimmed
create or replace function public.dbk_clean(s text) returns text language sql immutable as $$
    select btrim(regexp_replace(normalize(coalesce(s, ''), NFC), '\s+', ' ', 'g'))
$$;

create or replace function public.dbk_now() returns timestamp language sql stable as $$
    select date_trunc('second', (now() at time zone 'UTC') + make_interval(mins => coalesce(
        (select case when value ~ '^-?[0-9]+$' then value::int end from public.meta
         where key = 'clock_offset_min' and not deleted), 420)))
$$;

create or replace function public.dbk_code(p_prefix text, n bigint) returns text language sql immutable as $$
    select p_prefix || case when n < 1000 then lpad(n::text, 3, '0') else n::text end
$$;

-- stock.next_transfer_code / next_trial_code / receipts.next_code: highest number in use + 1
create or replace function public.dbk_next_doc_code(p_kind text, p_prefix text) returns text language sql stable as $$
    select public.dbk_code(p_prefix, coalesce(max(substr(code, 3)::bigint), 0) + 1)
    from public.documents where kind = p_kind and code ~ ('^' || p_prefix || '[0-9]+$')
$$;

create or replace function public.dbk_meta(p_key text) returns text language sql stable as $$
    select coalesce((select value from public.meta where key = p_key and not deleted), '')
$$;

create or replace function public.dbk_set_meta(p_key text, p_value text) returns void language sql as $$
    insert into public.meta(key, value, origin) values (p_key, p_value, 'web')
    on conflict (key) do update set value = excluded.value, origin = 'web', deleted = false
$$;

-- who may write, and only once the shop's data is on the cloud (otherwise nobody would ever read it)
create or replace function public.dbk_owner() returns void language plpgsql
security definer set search_path = public as $$
begin
    if public.my_role() is distinct from 'desktop' then
        raise exception 'Chỉ tài khoản của chủ mới làm được việc này.';
    end if;
    if not exists (select 1 from public.products where not deleted) then
        raise exception 'Dữ liệu chung chưa được bật: hãy mở app trên máy chính, vào Cài đặt → Cloud, bấm «Bật dữ liệu chung».';
    end if;
    perform pg_advisory_xact_lock(4242);  -- the same lock as every write (core_touch): codes are handed out in order
end $$;

create or replace function public.dbk_move(p_product uuid, p_qty double precision, p_doc uuid, p_kind text,
                                           p_on date, p_loc integer, p_at timestamp) returns void language sql as $$
    insert into public.stock_movements(id, product_id, qty, document_id, kind, occurred_on, created_at, location_id, origin)
    values (gen_random_uuid(), p_product, p_qty, p_doc, p_kind, p_on, p_at, p_loc, 'web')
$$;

create or replace function public.dbk_place(v jsonb) returns integer language plpgsql immutable as $$
begin
    if v is null or v::text not in ('1', '2', '"1"', '"2"') then raise exception 'Nơi chứa hàng không hợp lệ.'; end if;
    return (v #>> '{}')::integer;
end $$;

create or replace function public.dbk_date(v jsonb) returns date language plpgsql immutable as $$
begin
    if v is null or coalesce(v #>> '{}', '') !~ '^\d{4}-\d{2}-\d{2}$' then raise exception 'Ngày không hợp lệ.'; end if;
    return (v #>> '{}')::date;
end $$;

-- product + quantity rows: [{product_id, qty, note?}] -> checked (product exists, qty > 0, each product once)
create or replace function public.dbk_lines(p jsonb) returns setof jsonb language plpgsql stable as $$
declare e jsonb; seen uuid[] := '{}'; pid uuid; q double precision;
begin
    if p is null or jsonb_typeof(p) <> 'array' or jsonb_array_length(p) = 0 then
        raise exception 'Phiếu chưa có dòng hàng nào.';
    end if;
    for e in select * from jsonb_array_elements(p) loop
        begin
            pid := (e ->> 'product_id')::uuid;
            q := (e ->> 'qty')::double precision;
        exception when others then
            raise exception 'Dòng hàng không hợp lệ.';
        end;
        if not exists (select 1 from public.products where id = pid and not deleted) then
            raise exception 'Mặt hàng không còn trong danh mục (đã bị gộp hoặc xoá). Hãy tải lại trang.';
        end if;
        if q is null or q <= 0 or q = 'NaN' or q = 'Infinity' then raise exception 'Số lượng phải lớn hơn 0.'; end if;
        if pid = any(seen) then raise exception 'Một mặt hàng bị nhập hai lần.'; end if;
        seen := seen || pid;
        return next e;
    end loop;
end $$;

create or replace function public.dbk_doc(p_id uuid) returns public.documents language plpgsql stable as $$
declare d public.documents;
begin
    select * into d from public.documents where id = p_id and not deleted;
    if not found then raise exception 'Phiếu không còn (có thể vừa bị thay đổi ở máy khác). Hãy tải lại trang.'; end if;
    return d;
end $$;

-- stock.close_document: reverse movements, dated like the original; nothing is deleted
create or replace function public.dbk_close(p_doc uuid, p_status text, p_at timestamp) returns void language plpgsql as $$
declare d public.documents; r record; rev text;
begin
    d := public.dbk_doc(p_doc);
    if d.status <> 'active' then raise exception 'Phiếu không tồn tại hoặc đã huỷ.'; end if;
    rev := case d.kind when 'delivery' then 'delivery_reverse' when 'receipt' then 'receipt_reverse'
                       when 'stock_count' then 'count_reverse' when 'transfer' then 'transfer_reverse'
                       when 'trial' then 'trial_reverse' end;
    for r in select product_id, location_id, sum(qty) as q from public.stock_movements
             where document_id = p_doc and not deleted group by product_id, location_id loop
        if r.q <> 0 then perform public.dbk_move(r.product_id, -r.q, p_doc, rev, d.doc_date, r.location_id, p_at); end if;
    end loop;
    update public.documents set status = p_status, closed_at = p_at, origin = 'web' where id = p_doc;
end $$;

-- lines + movements of a new document (stock._insert_lines / transfer / record_trial_use)
create or replace function public.dbk_add_lines(p_doc uuid, p_lines jsonb, p_kind text, p_sign integer, p_on date,
                                                p_loc integer, p_to integer, p_at timestamp) returns void
language plpgsql as $$
declare e jsonb; i integer := 0; pid uuid; q double precision;
begin
    for e in select * from public.dbk_lines(p_lines) loop
        i := i + 1;
        pid := (e ->> 'product_id')::uuid;
        q := (e ->> 'qty')::double precision;
        insert into public.document_lines(id, document_id, line_no, product_id, qty, note, origin)
        values (gen_random_uuid(), p_doc, i, pid, q, public.dbk_clean(e ->> 'note'), 'web');
        if p_kind = 'transfer' then
            perform public.dbk_move(pid, -q, p_doc, 'transfer_out', p_on, p_loc, p_at);
            perform public.dbk_move(pid, q, p_doc, 'transfer_in', p_on, p_to, p_at);
        else
            perform public.dbk_move(pid, p_sign * q, p_doc, p_kind, p_on, p_loc, p_at);
        end if;
    end loop;
end $$;

-- ---------------------------------------------------------------- documents

-- receipts.save (goods in from the border / the parent company, or returned by a customer); p_replaces = editing
create or replace function public.web_receipt(p jsonb, p_replaces uuid default null) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
    v_at timestamp; v_code text; old public.documents; sup uuid; cust uuid; doc uuid := gen_random_uuid();
    src text := p ->> 'source'; v_day date; loc integer; sname text;
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
    insert into documents(id, kind, code, code_norm, doc_date, customer_id, note, created_at, receipt_source,
                          supplier_id, ref_code, location_id, source_file, origin)
    values (doc, 'receipt', v_code, v_code, v_day, cust, dbk_clean(p ->> 'note'), v_at, src, sup,
            case when src = 'return' then dbk_clean(p ->> 'ref_code') else '' end, loc,
            -- the Excel file the app writes for it when it pulls this receipt (receipts.export_file); an edit is a
            -- new version with a new file (_2, _3... as the app names them), never the old file left as it was
            'HangVe_' || v_code || '_' || v_day || case when p_replaces is null then '' else '_' || (
                select count(*) + 1 from documents where kind = 'receipt' and code = v_code and not deleted) end
            || '.xlsx', 'web');
    perform dbk_add_lines(doc, p -> 'lines', 'receipt_in', 1, v_day, loc, null, v_at);
    return jsonb_build_object('id', doc, 'code', v_code);
end $$;

-- stock.transfer; p_replaces = editing a transfer (keeps its code)
create or replace function public.web_transfer(p jsonb, p_replaces uuid default null) returns jsonb
language plpgsql security definer set search_path = public as $$
declare v_at timestamp; v_code text; old public.documents; doc uuid := gen_random_uuid(); v_day date; a integer; b integer;
begin
    perform dbk_owner();
    v_at := dbk_now();
    v_day := dbk_date(p -> 'date');
    a := dbk_place(p -> 'from');
    b := dbk_place(p -> 'to');
    if a = b then raise exception 'Nơi chuyển đi và nơi nhận phải khác nhau.'; end if;
    v_code := dbk_next_doc_code('transfer', 'CH');
    if p_replaces is not null then
        old := dbk_doc(p_replaces);
        if old.kind <> 'transfer' then raise exception 'Chỉ sửa được phiếu chuyển hàng.'; end if;
        perform dbk_close(p_replaces, 'replaced', v_at);
        v_code := coalesce(nullif(old.code, ''), v_code);
    end if;
    insert into documents(id, kind, code, code_norm, doc_date, note, created_at, location_id, to_location_id, origin)
    values (doc, 'transfer', v_code, v_code, v_day, dbk_clean(p ->> 'note'), v_at, a, b, 'web');
    perform dbk_add_lines(doc, p -> 'lines', 'transfer', 0, v_day, a, b, v_at);
    return jsonb_build_object('id', doc, 'code', v_code);
end $$;

-- stock.record_trial_use
create or replace function public.web_trial(p jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
declare v_at timestamp; v_code text; doc uuid := gen_random_uuid(); v_day date; loc integer;
begin
    perform dbk_owner();
    v_at := dbk_now();
    v_day := dbk_date(p -> 'date');
    loc := dbk_place(p -> 'location');
    v_code := dbk_next_doc_code('trial', 'DT');
    insert into documents(id, kind, code, code_norm, doc_date, note, created_at, location_id, origin)
    values (doc, 'trial', v_code, v_code, v_day, dbk_clean(p ->> 'note'), v_at, loc, 'web');
    perform dbk_add_lines(doc, p -> 'lines', 'trial_out', -1, v_day, loc, null, v_at);
    return jsonb_build_object('id', doc, 'code', v_code);
end $$;

-- stock.close_document(..., 'cancelled') -- Huỷ phiếu
create or replace function public.web_cancel(p_doc uuid) returns jsonb
language plpgsql security definer set search_path = public as $$
declare d public.documents;
begin
    perform dbk_owner();
    d := dbk_doc(p_doc);
    perform dbk_close(p_doc, 'cancelled', dbk_now());
    return jsonb_build_object('id', p_doc, 'code', d.code);
end $$;

-- stock.set_location: where a delivery note's goods were taken from (a receipt's put in)
create or replace function public.web_set_location(p_doc uuid, p_location integer) returns jsonb
language plpgsql security definer set search_path = public as $$
declare d public.documents;
begin
    perform dbk_owner();
    d := dbk_doc(p_doc);
    if d.kind not in ('delivery', 'receipt') or p_location not in (1, 2) then
        raise exception 'Không đổi được nơi lấy hàng của phiếu này.';
    end if;
    update stock_movements set location_id = p_location, origin = 'web' where document_id = p_doc and not deleted;
    update documents set location_id = p_location, location_set = true, origin = 'web' where id = p_doc;
    return jsonb_build_object('id', p_doc, 'code', d.code);
end $$;

-- stock.stock_count: lines [{product_id, location_id (1|2, or null = the total), qty >= 0}]. The difference is taken
-- against what the cloud held at this moment (created_at <= now), as the app does for a count recorded at `at`.
create or replace function public.web_stock_count(p jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
    v_at timestamp; doc uuid := gen_random_uuid(); v_day date; e jsonb; i integer := 0; pid uuid; loc integer;
    q double precision; have double precision; seen text[] := '{}';
begin
    perform dbk_owner();
    v_at := dbk_now();
    v_day := dbk_date(p -> 'count_date');
    if v_day > v_at::date then raise exception 'Ngày kiểm kê không được ở tương lai.'; end if;
    if jsonb_typeof(p -> 'lines') is distinct from 'array' or jsonb_array_length(p -> 'lines') = 0 then
        raise exception 'Chưa có mặt hàng nào được đếm.';
    end if;
    insert into documents(id, kind, doc_date, note, created_at, origin)
    values (doc, 'stock_count', v_day, dbk_clean(p ->> 'note'), v_at, 'web');
    for e in select * from jsonb_array_elements(p -> 'lines') loop
        i := i + 1;
        begin
            pid := (e ->> 'product_id')::uuid;
            q := (e ->> 'qty')::double precision;
        exception when others then
            raise exception 'Dòng kiểm kê không hợp lệ.';
        end;
        loc := case when e -> 'location_id' is null or e -> 'location_id' = 'null' then null
                    else dbk_place(e -> 'location_id') end;
        if not exists (select 1 from products where id = pid and not deleted) then
            raise exception 'Mặt hàng không còn trong danh mục. Hãy tải lại trang.';
        end if;
        if q is null or q < 0 or q = 'NaN' or q = 'Infinity' then
            raise exception 'Số đếm phải là số từ 0 trở lên.';
        end if;
        if (pid::text || ':' || coalesce(loc::text, '')) = any(seen) then
            raise exception 'Một mặt hàng bị nhập hai lần.';
        end if;
        seen := seen || (pid::text || ':' || coalesce(loc::text, ''));
        insert into document_lines(id, document_id, line_no, product_id, qty, location_id, origin)
        values (gen_random_uuid(), doc, i, pid, q, loc, 'web');
        select coalesce(sum(qty), 0) into have from stock_movements
        where product_id = pid and not deleted and occurred_on <= v_day and created_at <= v_at
          and (loc is null or location_id = loc);
        if abs(q - have) > 1e-9 then
            perform dbk_move(pid, q - have, doc, 'count_adjust', v_day, coalesce(loc, 1), v_at);
        end if;
    end loop;
    return jsonb_build_object('id', doc);
end $$;

-- ---------------------------------------------------------------- products and customers

-- catalog.guess_unit: '10KG/Thùng' -> 'thùng'
create or replace function public.dbk_guess_unit(p_spec text) returns text language sql immutable as $$
    select lower(btrim(regexp_replace(
        case when position('/' in s) > 0 then regexp_replace(s, '^.*/', '') else s end,
        '[0-9.,*]+\s*(kg|m|g|l)?', '', 'gi')))
    from (select public.dbk_clean(p_spec) as s) x
$$;

-- catalog.next_product_code (a code freed by a merge first) + create_product
create or replace function public.web_product_add(p jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
    v_at timestamp; v_code text; freed text[]; pid uuid := gen_random_uuid(); dup record;
    nv text := dbk_clean(p ->> 'name_vi'); sp text := dbk_clean(p ->> 'spec'); va text := dbk_clean(p ->> 'variant');
begin
    perform dbk_owner();
    v_at := dbk_now();
    if nv = '' then raise exception 'Mặt hàng phải có tên tiếng Việt.'; end if;
    if not coalesce((p ->> 'allow_duplicate')::boolean, false) then  -- catalog.find_same (the app also asks on near matches)
        select code, name_vi, spec into dup from products where not deleted
            and dbk_unaccent(name_vi) = dbk_unaccent(nv) and dbk_unaccent(spec) = dbk_unaccent(sp)
            and dbk_unaccent(variant) = dbk_unaccent(va) limit 1;
        if found then
            raise exception 'Đã có mặt hàng % (% %). Nếu đúng là mặt hàng mới, hãy chọn «Vẫn tạo dù có thể trùng».',
                dup.code, dup.name_vi, dup.spec;
        end if;
    end if;
    freed := array(select c from unnest(string_to_array(dbk_meta('freed_codes'), ',')) c where c ~ '^SP[0-9]+$'
                   order by substr(c, 3)::bigint);
    if array_length(freed, 1) > 0 then
        v_code := freed[1];
        perform dbk_set_meta('freed_codes', array_to_string(array_remove(
            string_to_array(dbk_meta('freed_codes'), ','), v_code), ','));
    else
        v_code := dbk_code('SP', greatest(
            coalesce((select max(substr(code, 3)::bigint) from products where code ~ '^SP[0-9]+$' and not deleted), 0),
            coalesce(nullif(dbk_meta('product_code_max'), '')::bigint, 0)) + 1);
    end if;
    insert into products(id, code, name_vi, name_zh, spec, unit, category, min_stock, variant, created_at, origin)
    values (pid, v_code, nv, dbk_clean(p ->> 'name_zh'), sp,
            coalesce(nullif(dbk_clean(p ->> 'unit'), ''), dbk_guess_unit(sp)), dbk_clean(p ->> 'category'), 0, va,
            v_at, 'web');
    return jsonb_build_object('id', pid, 'code', v_code);
end $$;

-- catalog.update_product (Sửa / ngừng dùng)
create or replace function public.web_product_edit(p_id uuid, p jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
declare r public.products;
begin
    perform dbk_owner();
    select * into r from products where id = p_id and not deleted;
    if not found then raise exception 'Mặt hàng không còn trong danh mục. Hãy tải lại trang.'; end if;
    if p ? 'name_vi' and dbk_clean(p ->> 'name_vi') = '' then raise exception 'Mặt hàng phải có tên tiếng Việt.'; end if;
    update products set
        name_vi = case when p ? 'name_vi' then dbk_clean(p ->> 'name_vi') else name_vi end,
        name_zh = case when p ? 'name_zh' then dbk_clean(p ->> 'name_zh') else name_zh end,
        spec = case when p ? 'spec' then dbk_clean(p ->> 'spec') else spec end,
        variant = case when p ? 'variant' then dbk_clean(p ->> 'variant') else variant end,
        unit = case when p ? 'unit' then dbk_clean(p ->> 'unit') else unit end,
        category = case when p ? 'category' then dbk_clean(p ->> 'category') else category end,
        stock_note = case when p ? 'stock_note' then dbk_clean(p ->> 'stock_note') else stock_note end,
        active = case when p ? 'active' then (p ->> 'active')::boolean else active end,
        origin = 'web'
    where id = p_id;
    return jsonb_build_object('id', p_id, 'code', r.code);
end $$;

-- catalog.merge_products: the larger SPxxx goes into the smaller one, its code is freed
create or replace function public.web_product_merge(p_a uuid, p_b uuid) returns jsonb
language plpgsql security definer set search_path = public as $$
declare a public.products; b public.products; keep public.products; drp public.products; freed text[];
begin
    perform dbk_owner();
    select * into a from products where id = p_a and not deleted;
    select * into b from products where id = p_b and not deleted;
    if a.id is null or b.id is null or a.id = b.id then raise exception 'Chọn hai mặt hàng khác nhau để gộp.'; end if;
    if (case when a.code ~ '^SP[0-9]+$' then substr(a.code, 3)::bigint else -1 end)
       <= (case when b.code ~ '^SP[0-9]+$' then substr(b.code, 3)::bigint else -1 end) then
        keep := a; drp := b;
    else
        keep := b; drp := a;
    end if;
    update document_lines set product_id = keep.id, origin = 'web' where product_id = drp.id and not deleted;
    update stock_movements set product_id = keep.id, origin = 'web' where product_id = drp.id and not deleted;
    update product_aliases set product_id = keep.id, origin = 'web' where product_id = drp.id and not deleted;
    update products set
        name_zh = case when btrim(name_zh) = '' and btrim(drp.name_zh) <> '' then drp.name_zh else name_zh end,
        category = case when btrim(category) = '' and btrim(drp.category) <> '' then drp.category else category end,
        stock_note = case when btrim(stock_note) = '' and btrim(drp.stock_note) <> '' then drp.stock_note else stock_note end,
        min_stock = case when coalesce(min_stock, 0) = 0 and coalesce(drp.min_stock, 0) <> 0 then drp.min_stock else min_stock end,
        origin = 'web'
    where id = keep.id;
    update products set deleted = true, origin = 'web' where id = drp.id;
    if drp.code ~ '^SP[0-9]+$' then
        freed := array(select c from unnest(string_to_array(dbk_meta('freed_codes'), ',')) c where c <> '');
        if not drp.code = any(freed) then perform dbk_set_meta('freed_codes', array_to_string(freed || drp.code, ',')); end if;
    end if;
    return jsonb_build_object('id', keep.id, 'code', keep.code, 'dropped', drp.code);
end $$;

-- catalog.merge_customers: a customer already named so is kept, otherwise the oldest of them, renamed
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
    update documents set customer_id = keep, origin = 'web'
    where customer_id = any(p_ids) and customer_id <> keep and not deleted;
    update customers set deleted = true, origin = 'web' where id = any(p_ids) and id <> keep and not deleted;
    update customers set name = nm, origin = 'web' where id = keep;
    return jsonb_build_object('id', keep);
end $$;

-- ---------------------------------------------------------------- who may call them

do $$
declare f text;
begin
    foreach f in array array['web_receipt(jsonb, uuid)', 'web_transfer(jsonb, uuid)', 'web_trial(jsonb)',
                             'web_cancel(uuid)', 'web_set_location(uuid, integer)', 'web_stock_count(jsonb)',
                             'web_product_add(jsonb)', 'web_product_edit(uuid, jsonb)', 'web_product_merge(uuid, uuid)',
                             'web_customer_merge(uuid[], text)'] loop
        execute format('revoke all on function public.%s from public, anon', f);
        execute format('grant execute on function public.%s to authenticated', f);
    end loop;
end $$;

-- the helpers are only called from the functions above (which run as their owner): nobody calls them directly
do $$
declare f record;
begin
    for f in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
             where n.nspname = 'public' and p.proname like 'dbk\_%' loop
        execute format('revoke all on function %s from public, anon, authenticated', f.sig);
    end loop;
end $$;
