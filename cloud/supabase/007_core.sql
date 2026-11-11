-- DiBeKho: the cloud becomes the source of truth (docs/cloud/06-cloud-la-goc.md, decided 11/11/2026).
-- Real tables, one per synced SQLite table (dibekho/db/sync_schema.py), same column names. Rows are keyed by uuid
-- (text-keyed tables keep their text key), so machines working offline never hand out the same id.
-- Extra columns on every table:
--   rev        server order of the last change: a machine pulls "rev > what I saw last time"
--   deleted    soft delete, so other machines learn about it
--   updated_at server time of the last change;  origin  the device that wrote it
-- Writes come only through functions added in the next steps (no direct write policy here). The mirror_* tables
-- and web_inbox of 001-006 stay as they are until the switch is finished.
-- Run once in the Supabase SQL Editor. Safe to read: it creates new tables only.

create sequence if not exists public.core_rev;

create table public.suppliers (
    id uuid primary key,
    name text not null,
    created_at timestamp not null
);
create table public.customers (
    id uuid primary key,
    name text not null,
    contact text not null default '',
    phone text not null default '',
    phone_norm text not null default '',
    address text not null default '',
    created_at timestamp not null
);
create table public.products (
    id uuid primary key,
    code text not null,
    name_vi text not null,
    name_zh text not null default '',
    spec text not null default '',
    unit text not null default '',
    category text not null default '',
    min_stock double precision not null default 0,
    active boolean not null default true,
    created_at timestamp not null,
    variant text not null default '',
    stock_note text not null default ''
);
create table public.product_aliases (
    key text primary key,
    product_id uuid not null references public.products(id) deferrable initially deferred,
    label text not null default ''
);
create table public.ignored_lines (
    key text primary key,
    label text not null default '',
    created_at timestamp not null
);
create table public.documents (
    id uuid primary key,
    kind text not null check (kind in ('delivery', 'receipt', 'stock_count', 'transfer', 'trial')),
    code text not null default '',
    code_norm text not null default '',
    doc_date date not null,
    customer_id uuid references public.customers(id) deferrable initially deferred,
    note text not null default '',
    status text not null default 'active' check (status in ('active', 'cancelled', 'replaced')),
    source_file text not null default '',
    source_hash text not null default '',
    created_at timestamp not null,
    closed_at timestamp,
    receipt_source text not null default '',
    supplier_id uuid references public.suppliers(id) deferrable initially deferred,
    ref_code text not null default '',
    fee_amount double precision,
    note_total double precision,
    prices_read boolean not null default false,
    location_id integer not null default 1,
    to_location_id integer,
    location_set boolean not null default true
);
create table public.document_lines (
    id uuid primary key,
    document_id uuid not null references public.documents(id) deferrable initially deferred,
    line_no integer not null,
    product_id uuid not null references public.products(id) deferrable initially deferred,
    qty double precision not null,
    raw_name text not null default '',
    raw_spec text not null default '',
    note text not null default '',
    unit_price double precision,
    amount double precision,
    location_id integer
);
create table public.stock_movements (
    id uuid primary key,
    product_id uuid not null references public.products(id) deferrable initially deferred,
    qty double precision not null,
    document_id uuid not null references public.documents(id) deferrable initially deferred,
    kind text not null,
    occurred_on date not null,
    created_at timestamp not null,
    lot_id integer,
    location_id integer
);
create table public.document_skipped_lines (
    id uuid primary key,
    document_id uuid not null references public.documents(id) deferrable initially deferred,
    key text not null,
    raw_name text not null default ''
);
create table public.meta (
    key text primary key,
    value text not null
);

create or replace function public.core_touch() returns trigger language plpgsql as $$
begin
    new.rev := nextval('public.core_rev');
    new.updated_at := now();
    return new;
end $$;

do $$
declare t text;
begin
    foreach t in array array['suppliers', 'customers', 'products', 'product_aliases', 'ignored_lines', 'documents',
                             'document_lines', 'stock_movements', 'document_skipped_lines', 'meta'] loop
        execute format('alter table public.%I add column rev bigint not null default 0, '
                       'add column deleted boolean not null default false, '
                       'add column updated_at timestamptz not null default now(), '
                       'add column origin text not null default %L', t, '');
        execute format('create index %I on public.%I (rev)', t || '_rev', t);
        execute format('create trigger %I before insert or update on public.%I '
                       'for each row execute function public.core_touch()', t || '_touch', t);
        execute format('alter table public.%I enable row level security', t);
        -- every signed-in account with a role reads everything (as the mirror today); writes come later via functions
        execute format('create policy %I on public.%I for select using (public.my_role() is not null)', t || '_read', t);
    end loop;
end $$;

-- the same rules the app keeps (codes it hands out are unique; one active delivery per order code)
create unique index products_code_unique on public.products (code) where not deleted;
create unique index documents_code_unique on public.documents (kind, code)
    where kind in ('receipt', 'transfer', 'trial') and status <> 'replaced' and not deleted;
create unique index documents_active_delivery on public.documents (code_norm)
    where kind = 'delivery' and status = 'active' and not deleted;
create index stock_movements_product on public.stock_movements (product_id, occurred_on);
create index document_lines_document on public.document_lines (document_id);
