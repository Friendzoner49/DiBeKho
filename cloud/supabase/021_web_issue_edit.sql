-- DiBeKho cloud, step 021 (customer's request 19/11/2026): the owner can correct a Phiếu xuất kho already issued (prices,
-- quantities, goods, customer), like the app's issues.edit. Only notes made by the app or the web (codes A… / W…).
-- Run AFTER 020. Safe to run again. It changes no table and no other function: the old note is deleted the way the
-- app deletes one (document, lines, movements: the stock is as if it never left) and web_issue records the corrected
-- one in the same transaction, which then takes the old code back (so A160 stays A160, no number is lost).
--
-- web_issue_edit(p): p = what web_issue takes + {replaces: the document id of the note being corrected}.
-- Returns what web_issue returns, with the old code.

create or replace function public.web_api_version() returns integer language sql immutable as $$
    select 21
$$;

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
    return made || jsonb_build_object('code', old.code);
end $$;

revoke all on function public.web_issue_edit(jsonb) from public, anon;
grant execute on function public.web_issue_edit(jsonb) to authenticated;
revoke all on function public.web_api_version() from public, anon;
grant execute on function public.web_api_version() to authenticated;
