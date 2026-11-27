-- DiBeKho cloud, step 024 (user, 27/11/2026): 'Thông tin công ty' (the two lines printed on top of a Phiếu xuất kho,
-- meta note_letterhead, the same one the app keeps and syncs) can be changed on the web too, by the owner's role.
-- Run AFTER 023. Safe to run again. It adds one function and changes no table.
-- Run it BEFORE the web is uploaded; without it the web only says it cannot save.

create or replace function public.web_letterhead_set(p_name text, p_address text) returns void
language plpgsql security definer set search_path = public as $$
declare name_lines text; address_lines text;
begin
    perform public.dbk_owner();
    -- as the app's deliveries.set_letterhead: each text may hold several rows, each row cleaned, empty rows dropped
    select coalesce(string_agg(public.dbk_clean(r), E'\n' order by i), '') into name_lines
    from unnest(string_to_array(coalesce(p_name, ''), E'\n')) with ordinality t(r, i) where public.dbk_clean(r) <> '';
    select coalesce(string_agg(public.dbk_clean(r), E'\n' order by i), '') into address_lines
    from unnest(string_to_array(coalesce(p_address, ''), E'\n')) with ordinality t(r, i) where public.dbk_clean(r) <> '';
    if length(name_lines) > 300 or length(address_lines) > 300 then
        raise exception 'Thông tin công ty dài quá (tối đa 300 chữ mỗi ô).';
    end if;
    perform public.dbk_set_meta('note_letterhead', case when name_lines = '' and address_lines = '' then ''
                                else jsonb_build_array(name_lines, address_lines)::text end);
end $$;

revoke all on function public.web_letterhead_set(text, text) from public, anon;
grant execute on function public.web_letterhead_set(text, text) to authenticated;
