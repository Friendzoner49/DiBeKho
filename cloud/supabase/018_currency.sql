-- DiBeKho cloud 018: the currency of a note (app migration 011; user, 15/11/2026: an order priced in yuan).
-- documents.currency: 'VND' | 'CNY' | '' (not looked at yet, counted as dong); documents.fx_rate: dong for one yuan
-- when the note was read (only to show "about ... dong"). The app 0.5.5 sends both columns when it syncs, so run this
-- BEFORE the first 0.5.5 signs in. Safe to run again. No function changes: the web reads them with the rows.

alter table public.documents add column if not exists currency text not null default '';
alter table public.documents add column if not exists fx_rate double precision;
