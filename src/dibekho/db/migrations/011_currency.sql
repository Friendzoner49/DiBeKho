-- The money of a note is not always dong (user, 15/11/2026: order 155 was priced in yuan, read as 4,800 dong).
-- currency: 'VND' | 'CNY' | '' (not looked at yet: counted as dong; deliveries.backfill_currency reads the stored
-- copy of the note once). fx_rate: dong for one yuan when the note was read, only to show a yuan amount as
-- "about … dong" next to it; NULL until a rate is known. Amounts stay as printed, in the note's own currency.
ALTER TABLE documents ADD COLUMN currency TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN fx_rate REAL;
