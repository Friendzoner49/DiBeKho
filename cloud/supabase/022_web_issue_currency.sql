-- DiBeKho cloud, step 022 (user, 21/11/2026): a Phiếu xuất kho made on the web while the ₫ | ¥ switch shows yuan is a
-- yuan note, as in the app: its prices stay yuan and the document says so (documents.currency 'CNY', fx_rate = the
-- dong for one yuan the window used, only to show '≈ … ₫'). Before this step web_issue ignored the currency and a yuan
-- note would have been counted as dong.
-- Run AFTER 021. Safe to run again. It changes no table and does not touch web_issue itself:
--   web_issue_money(p)  = web_issue(p), then the currency of p ({currency: 'VND' | 'CNY', fx_rate}) on the new note;
--   web_issue_edit(p)   = as in 021, then the currency of p on the corrected note.
-- The web checks web_api_version() >= 22 before it saves a yuan note.

create or replace function public.web_api_version() returns integer language sql immutable as $$
    select 22
$$;

create or replace function public.dbk_issue_set_money(doc uuid, p jsonb) returns void
language plpgsql security definer set search_path = public as $$
declare
    cny boolean := coalesce(p ->> 'currency', '') = 'CNY';
    rate double precision;
begin
    if cny then
        begin
            rate := nullif(p ->> 'fx_rate', '')::double precision;
        exception when others then
            rate := null;
        end;
        if rate is not null and rate <= 0 then rate := null; end if;
    end if;
    update documents set currency = case when cny then 'CNY' else 'VND' end,
                         fx_rate = case when cny then rate else null end, origin = 'web'
    where id = doc;
end $$;

create or replace function public.web_issue_money(p jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
    made jsonb;
begin
    made := web_issue(p);  -- checks the owner, writes the note, takes the stock
    perform dbk_issue_set_money((made ->> 'id')::uuid, p);
    return made;
end $$;

create or replace function public.web_issue_edit(p jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
    old public.documents; ids uuid[]; made jsonb; new_id uuid;
begin
    perform dbk_owner();
    begin
        select * into old from documents where id = (p ->> 'replaces')::uuid and not deleted;
    exception when others then
        raise exception 'Phiếu cần sửa không hợp lệ.';
    end;
    if not found or old.kind <> 'delivery' or old.status <> 'active' or old.code !~ '^\s*[AaWw][0-9]+\s*$' then
        raise exception 'Chỉ sửa được phiếu xuất kho còn hiệu lực (mã A… hoặc W…). Hãy tải lại trang.';
    end if;
    -- the note and its earlier versions (same code), as the app's issues.delete
    ids := array(select id from documents where kind = 'delivery' and not deleted and code_norm = old.code_norm);
    update stock_movements set deleted = true, origin = 'web' where document_id = any(ids) and not deleted;
    update document_lines set deleted = true, origin = 'web' where document_id = any(ids) and not deleted;
    update documents set deleted = true, origin = 'web' where id = any(ids) and not deleted;
    made := web_issue(p);
    new_id := (made ->> 'id')::uuid;
    update documents set code = old.code, code_norm = old.code_norm, source_file = 'PhieuXuat_' || old.code || '.xlsx',
                         origin = 'web'
    where id = new_id;
    perform dbk_issue_set_money(new_id, p);
    return made || jsonb_build_object('code', old.code);
end $$;

revoke all on function public.dbk_issue_set_money(uuid, jsonb) from public, anon, authenticated;
revoke all on function public.web_issue_money(jsonb) from public, anon;
grant execute on function public.web_issue_money(jsonb) to authenticated;
revoke all on function public.web_issue_edit(jsonb) from public, anon;
grant execute on function public.web_issue_edit(jsonb) to authenticated;
revoke all on function public.web_api_version() from public, anon;
grant execute on function public.web_api_version() to authenticated;
