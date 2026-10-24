-- Prices read from delivery notes (24/10/2026). NULL = unknown (not on the note, or not read yet), never 0.
ALTER TABLE document_lines ADD COLUMN unit_price REAL;
ALTER TABLE document_lines ADD COLUMN amount REAL;

-- fee_amount: money on the note that is not goods (shipping fee rows without quantity, lines marked 'not goods').
-- note_total: the 'Tổng cộng' amount printed on the note, kept only to check against.
-- prices_read: 0 = not read yet (notes imported before this version), 1 = read, -1 = no stored copy to read.
ALTER TABLE documents ADD COLUMN fee_amount REAL;
ALTER TABLE documents ADD COLUMN note_total REAL;
ALTER TABLE documents ADD COLUMN prices_read INTEGER NOT NULL DEFAULT 0;
