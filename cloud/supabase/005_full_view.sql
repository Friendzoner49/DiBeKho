-- DiBeKho Cloud v5: the web can show everything the app shows (product history, statistics, customer detail)
-- and owner commands can name rows safely. For a project created before this file: run once in the Supabase SQL
-- editor (fresh installs already have all of this in 001_init.sql). After it, press "Đồng bộ ngay" in the app once.

alter table public.mirror_products  add column if not exists created_at text;
alter table public.mirror_customers add column if not exists created_at text;
alter table public.mirror_documents add column if not exists created_at text;
alter table public.mirror_documents add column if not exists location_set boolean;
alter table public.mirror_documents add column if not exists receipt_source text;
alter table public.mirror_documents add column if not exists ref_code text;
alter table public.mirror_documents add column if not exists source_file text;
alter table public.mirror_documents add column if not exists supplier_name text;

create table if not exists public.mirror_movements (
    id integer primary key, product_id integer not null, qty double precision not null,
    document_id integer not null, kind text not null, occurred_on date not null, location_id integer not null
);
create index if not exists mirror_movements_product on public.mirror_movements (product_id, occurred_on);
alter table public.mirror_movements enable row level security;
drop policy if exists mirror_movements_read on public.mirror_movements;
create policy mirror_movements_read on public.mirror_movements for select using (public.my_role() is not null);

create or replace function public.replace_mirror(payload jsonb, force boolean default false)
returns jsonb language plpgsql security definer set search_path = public as
$$
declare
    current_push bigint;
    new_id bigint;
begin
    if public.my_role() <> 'desktop' then
        raise exception 'only the desktop account may push';
    end if;
    select last_push_id into current_push from sync_state where id;
    if not force and current_push is not null
       and current_push is distinct from (payload->>'based_on_push')::bigint then
        return jsonb_build_object('conflict', true, 'last_push',
            (select to_jsonb(s) from sync_state s where id));
    end if;

    -- TRUNCATE, not DELETE: Supabase preloads pg_safeupdate, which rejects DELETE without WHERE
    truncate table mirror_movements, mirror_document_lines, mirror_documents, mirror_stock, mirror_products,
                   mirror_customers;
    insert into mirror_products  select * from jsonb_populate_recordset(null::mirror_products,  payload->'products');
    insert into mirror_customers select * from jsonb_populate_recordset(null::mirror_customers, payload->'customers');
    insert into mirror_documents select * from jsonb_populate_recordset(null::mirror_documents, payload->'documents');
    insert into mirror_document_lines
        select * from jsonb_populate_recordset(null::mirror_document_lines, payload->'document_lines');
    insert into mirror_movements select * from jsonb_populate_recordset(null::mirror_movements, payload->'movements');
    insert into mirror_stock     select * from jsonb_populate_recordset(null::mirror_stock,     payload->'stock');

    insert into mirror_snapshot(device_id, device_name, app_version, schema_version, payload)
    values (payload->>'device_id', payload->>'device_name', payload->>'app_version',
            (payload->>'schema_version')::int, payload - 'movements')
    returning id into new_id;
    delete from mirror_snapshot where id not in (select id from mirror_snapshot order by id desc limit 30);

    insert into sync_state(id, last_push_id, last_push_at, device_id, device_name, low_stock_default)
    values (true, new_id, now(), payload->>'device_id', payload->>'device_name',
            coalesce((payload->>'low_stock_default')::double precision, 30))
    on conflict (id) do update set last_push_id = excluded.last_push_id,
        last_push_at = excluded.last_push_at, device_id = excluded.device_id,
        device_name = excluded.device_name, low_stock_default = excluded.low_stock_default;
    return jsonb_build_object('conflict', false, 'push_id', new_id);
end
$$;
