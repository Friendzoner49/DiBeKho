-- DiBeKho Cloud schema v1 (Supabase Postgres).
-- Model: desktop SQLite is the single source of truth. The cloud keeps
--   (a) a full read-only MIRROR the desktop replaces on each push, and
--   (b) a WEB_INBOX of write requests from the webapp that the desktop pulls and applies locally.
-- See docs/cloud/04-thiet-ke-chot.md. Run in the Supabase SQL editor on a fresh project.
-- No client ever uses the service role key: the desktop signs in as a user whose profile role is 'desktop'.

-- ---------------------------------------------------------------- roles
create table public.profiles (
    user_id      uuid primary key references auth.users(id) on delete cascade,
    display_name text not null default '',
    role         text not null default 'viewer' check (role in ('viewer', 'editor', 'desktop')),
    created_at   timestamptz not null default now()
);

create or replace function public.my_role() returns text
language sql stable security definer set search_path = public as
$$ select role from public.profiles where user_id = auth.uid() $$;

-- ------------------------------------------------- mirror (web reads, desktop replaces)
-- Flat tables mirror the SQLite business tables; columns mirror what the web needs to show.
create table public.mirror_products (
    id integer primary key, code text not null, name_vi text not null, name_zh text not null default '',
    spec text not null default '', variant text not null default '', unit text not null default '',
    category text not null default '', stock_note text not null default '', active boolean not null default true
);
create table public.mirror_customers (
    id integer primary key, name text not null, contact text not null default '',
    phone text not null default '', address text not null default ''
);
create table public.mirror_documents (
    id integer primary key, kind text not null, code text not null default '', doc_date date not null,
    customer_id integer, status text not null, note text not null default '',
    location_id integer, to_location_id integer, fee_amount double precision, note_total double precision
);
create table public.mirror_document_lines (
    id integer primary key, document_id integer not null, line_no integer not null,
    product_id integer not null, qty double precision not null, note text not null default '',
    unit_price double precision, amount double precision, location_id integer
);
create table public.mirror_stock (
    product_id integer not null, location_id integer not null, qty double precision not null,
    primary key (product_id, location_id)
);

-- Each push also stores the complete payload: the newest rows double as the off-machine backup.
create table public.mirror_snapshot (
    id bigint generated always as identity primary key,
    pushed_at timestamptz not null default now(),
    device_id text not null, device_name text not null,
    app_version text not null, schema_version integer not null,
    payload jsonb not null
);

create table public.sync_state (
    id boolean primary key default true check (id),  -- single row
    last_push_id bigint not null,
    last_push_at timestamptz not null default now(),
    device_id text not null, device_name text not null,
    low_stock_default double precision not null default 30  -- the app's alarm level; 0 = off
);

-- ------------------------------------------------- web inbox (web writes, desktop consumes)
create table public.web_inbox (
    id uuid primary key default gen_random_uuid(),
    kind text not null check (kind in ('receipt', 'delivery_file', 'stock_count')),
    payload jsonb not null,
    created_by uuid not null default auth.uid() references auth.users(id),
    created_at timestamptz not null default now(),
    status text not null default 'pending' check (status in ('pending', 'applied', 'rejected')),
    result jsonb, applied_at timestamptz
);

-- ---------------------------------------------------------------- RLS
alter table public.profiles             enable row level security;
alter table public.mirror_products      enable row level security;
alter table public.mirror_customers     enable row level security;
alter table public.mirror_documents     enable row level security;
alter table public.mirror_document_lines enable row level security;
alter table public.mirror_stock         enable row level security;
alter table public.mirror_snapshot      enable row level security;
alter table public.sync_state           enable row level security;
alter table public.web_inbox            enable row level security;

create policy profiles_own_read on public.profiles for select using (user_id = auth.uid());
-- the desktop shows who sent a web_inbox item (my_role() is security definer, so no recursion here)
create policy profiles_desktop_read on public.profiles for select using (public.my_role() = 'desktop');

-- every signed-in role may read the mirror and sync state
do $$
declare t text;
begin
    foreach t in array array['mirror_products','mirror_customers','mirror_documents',
                             'mirror_document_lines','mirror_stock','sync_state'] loop
        execute format('create policy %I_read on public.%I for select using (public.my_role() is not null)', t, t);
    end loop;
end $$;

-- snapshots (the backups) are for the desktop only
create policy snapshot_desktop_read  on public.mirror_snapshot for select using (public.my_role() = 'desktop');

-- inbox: editors create and see their own items; the desktop sees and updates everything
create policy inbox_insert on public.web_inbox for insert
    with check (public.my_role() in ('editor', 'desktop') and created_by = auth.uid());
create policy inbox_own_read on public.web_inbox for select
    using (created_by = auth.uid() or public.my_role() = 'desktop');
create policy inbox_desktop_update on public.web_inbox for update
    using (public.my_role() = 'desktop');

-- Mirror tables get NO insert/update/delete policies: all writes go through replace_mirror below,
-- which runs as definer after checking the caller's role itself.

-- ------------------------------------------------- RPC: the desktop replaces the whole mirror
-- payload: {"products": [...], "customers": [...], "documents": [...], "document_lines": [...],
--           "stock": [...], "device_id": "...", "device_name": "...", "app_version": "...",
--           "schema_version": 9, "based_on_push": <last push id this machine saw, or null>}
-- Refuses when someone else pushed after based_on_push (the desktop then asks the user; pass
-- force => true to overwrite once the user chose to).
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

revoke all on function public.replace_mirror(jsonb, boolean) from public, anon;
grant execute on function public.replace_mirror(jsonb, boolean) to authenticated;
