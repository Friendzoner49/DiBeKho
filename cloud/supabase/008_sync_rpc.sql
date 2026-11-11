-- DiBeKho: two-way sync with the cloud's real tables (007). Run once in the Supabase SQL Editor after 007.
-- docs/cloud/06-cloud-la-goc.md. A machine always PULLS first (everything with rev > what it saw), merges on its own
-- side (the business rules live in the app's Python: renumbering clashing codes, duplicate notes, conflicts), then
-- PUSHES with the rev it saw. If anything was written in between, the push is refused and the machine pulls again.
--
-- Every write takes one exclusive lock (in core_touch) until its transaction ends, and a pull takes it shared:
-- revs therefore become visible in order and a pull never sees half of a write. A pull reports the highest rev it
-- returned, never the sequence (a rolled-back write uses a number too).

create or replace function public.core_touch() returns trigger language plpgsql as $$
begin
    perform pg_advisory_xact_lock(4242);
    new.rev := nextval('public.core_rev');
    new.updated_at := now();
    return new;
end $$;

create or replace function public.core_tables() returns text[] language sql immutable as $$
    select array['suppliers', 'customers', 'products', 'product_aliases', 'ignored_lines', 'documents',
                 'document_lines', 'stock_movements', 'document_skipped_lines', 'meta']
$$;

create or replace function public.core_max_rev() returns bigint language plpgsql stable
security definer set search_path = public as $$
declare t text; m bigint := 0; x bigint;
begin
    foreach t in array core_tables() loop
        execute format('select coalesce(max(rev), 0) from public.%I', t) into x;
        m := greatest(m, x);
    end loop;
    return m;
end $$;

-- business columns of a cloud table (without the server's bookkeeping)
create or replace function public.core_columns(t text) returns text[] language sql stable as $$
    select array_agg(column_name::text order by ordinal_position) from information_schema.columns
    where table_schema = 'public' and table_name = t and column_name not in ('rev', 'updated_at', 'origin', 'deleted')
$$;

create or replace function public.sync_pull(p_after bigint) returns jsonb
language plpgsql security definer set search_path = public as $$
declare t text; rows jsonb; out jsonb := '{}'; top bigint := p_after; x bigint;
begin
    if public.my_role() is null then raise exception 'not allowed'; end if;
    perform pg_advisory_xact_lock_shared(4242);
    foreach t in array core_tables() loop
        execute format('select coalesce(jsonb_agg(to_jsonb(x) - ''updated_at'' - ''origin'' order by rev), ''[]''), '
                       'coalesce(max(rev), 0) from public.%I x where rev > $1', t) into rows, x using p_after;
        out := out || jsonb_build_object(t, rows);
        top := greatest(top, x);
    end loop;
    return jsonb_build_object('tables', out, 'max_rev', top);
end $$;

create or replace function public.sync_push(p_device text, p_expected bigint, p_batch jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
    t text; tabs text[] := core_tables(); i int; cols text[]; collist text; pk text; rows jsonb; sets text;
begin
    if public.my_role() is distinct from 'desktop' then raise exception 'not allowed'; end if;
    perform pg_advisory_xact_lock(4242);
    if core_max_rev() > p_expected then
        return jsonb_build_object('ok', false, 'reason', 'behind', 'max_rev', core_max_rev());
    end if;
    -- deletes first, children first (a code freed by a delete may be taken by a new row in the same batch)
    for i in reverse array_length(tabs, 1) .. 1 loop
        t := tabs[i];
        pk := case when t in ('product_aliases', 'ignored_lines', 'meta') then 'key' else 'id' end;
        rows := coalesce(p_batch -> t, '[]');
        -- a uuid the cloud never received updates nothing (the push that created it was lost with its reply)
        execute format('update public.%I x set deleted = true, origin = $2 from jsonb_array_elements($1) e '
                       'where (e ->> ''deleted'')::boolean and x.%I::text = e ->> %L and not x.deleted', t, pk, pk)
            using rows, p_device;
    end loop;
    for i in 1 .. array_length(tabs, 1) loop
        t := tabs[i];
        pk := case when t in ('product_aliases', 'ignored_lines', 'meta') then 'key' else 'id' end;
        cols := core_columns(t);
        select string_agg(format('%I = excluded.%I', c, c), ', ') into sets from unnest(cols) c where c <> pk;
        select string_agg(quote_ident(c), ', ') into collist from unnest(cols) c;
        rows := (select coalesce(jsonb_agg(e), '[]') from jsonb_array_elements(coalesce(p_batch -> t, '[]')) e
                 where not coalesce((e ->> 'deleted')::boolean, false));
        if jsonb_array_length(rows) = 0 then continue; end if;
        execute format('insert into public.%I (%s, origin, deleted) select %s, $2, false '
                       'from jsonb_populate_recordset(null::public.%I, $1) on conflict (%I) do update set %s, '
                       'origin = excluded.origin, deleted = false',
                       t, collist, collist, t, pk, sets)
            using rows, p_device;
    end loop;
    return jsonb_build_object('ok', true, 'max_rev', core_max_rev());
end $$;

revoke all on function public.sync_push(text, bigint, jsonb) from public, anon;
revoke all on function public.sync_pull(bigint) from public, anon;
grant execute on function public.sync_push(text, bigint, jsonb) to authenticated;
grant execute on function public.sync_pull(bigint) to authenticated;
