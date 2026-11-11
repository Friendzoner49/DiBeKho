-- DiBeKho Cloud v3: the web colours stock rows like the app, so the app's alarm level travels with each push.
-- For a project created before this change: run once in the Supabase SQL editor (fresh installs already have
-- both parts in 001_init.sql). Rows below the level show orange, negative stock red; 0 turns the alarm off.

alter table public.sync_state add column if not exists low_stock_default double precision not null default 30;

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
    truncate table mirror_document_lines, mirror_documents, mirror_stock, mirror_products, mirror_customers;
    insert into mirror_products  select * from jsonb_populate_recordset(null::mirror_products,  payload->'products');
    insert into mirror_customers select * from jsonb_populate_recordset(null::mirror_customers, payload->'customers');
    insert into mirror_documents select * from jsonb_populate_recordset(null::mirror_documents, payload->'documents');
    insert into mirror_document_lines
        select * from jsonb_populate_recordset(null::mirror_document_lines, payload->'document_lines');
    insert into mirror_stock     select * from jsonb_populate_recordset(null::mirror_stock,     payload->'stock');

    insert into mirror_snapshot(device_id, device_name, app_version, schema_version, payload)
    values (payload->>'device_id', payload->>'device_name', payload->>'app_version',
            (payload->>'schema_version')::int, payload)
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
