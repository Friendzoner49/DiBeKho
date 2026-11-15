-- DiBeKho cloud 018: the currency of a note (app migration 011; user, 15/11/2026: an order priced in yuan).
-- documents.currency: 'VND' | 'CNY' | '' (not looked at yet, counted as dong); documents.fx_rate: dong for one yuan
-- when the note was read (only to show "about ... dong"). The app 0.5.5 sends both columns when it syncs, so run this
-- BEFORE the first 0.5.5 signs in. Safe to run again. The web reads the two columns with the rows.
--
-- An app older than 0.5.5 (still on a Mac, a staff machine) pushes documents without these keys: sync_push fills
-- every column of the table from the JSON (core_columns, 008), so they arrive as NULL. The trigger below keeps what
-- the cloud already has instead (a yuan order stays yuan), and '' for a new row, before NOT NULL is checked.

alter table public.documents add column if not exists currency text not null default '';
alter table public.documents add column if not exists fx_rate double precision;

create or replace function public.dbk_keep_currency() returns trigger language plpgsql as $$
begin
    if new.currency is null then
        if tg_op = 'UPDATE' then
            new.currency := old.currency;
            new.fx_rate := old.fx_rate;
        else
            -- sync_push is an insert ... on conflict do update: the proposed row passes here first and becomes
            -- 'excluded', so it must already carry what the existing row has
            select d.currency, d.fx_rate into new.currency, new.fx_rate from public.documents d where d.id = new.id;
            new.currency := coalesce(new.currency, '');
        end if;
    end if;
    return new;
end $$;

drop trigger if exists documents_keep_currency on public.documents;
create trigger documents_keep_currency before insert or update on public.documents
    for each row execute function public.dbk_keep_currency();
