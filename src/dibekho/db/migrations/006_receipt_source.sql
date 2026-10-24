-- Where goods in come from (17/10/2026). receipt_source: '' (older receipts, unknown),
-- 'supplier' = border gate / parent company (named in suppliers), 'return' = goods a customer sent back
-- (documents.customer_id is that customer; documents.ref_code the order it came from, optional).
CREATE TABLE suppliers (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
ALTER TABLE documents ADD COLUMN receipt_source TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN supplier_id INTEGER REFERENCES suppliers(id);
ALTER TABLE documents ADD COLUMN ref_code TEXT NOT NULL DEFAULT '';
