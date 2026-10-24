-- Two places goods are kept (24/10/2026): 1 = Kho tổng (main warehouse), 2 = Văn phòng (office).
-- Names are shown through i18n (loc.<code>); the ids are fixed.
CREATE TABLE locations (
    id    INTEGER PRIMARY KEY,
    code  TEXT NOT NULL UNIQUE
);
INSERT INTO locations(id, code) VALUES (1, 'main'), (2, 'office');

-- Everything recorded before this version was in the main warehouse.
UPDATE stock_movements SET location_id = 1 WHERE location_id IS NULL;
CREATE INDEX ix_movements_location ON stock_movements(location_id);

-- Stock counts: the place a counted line was counted at (NULL = a count of the total, adjusted at Kho tổng).
ALTER TABLE document_lines ADD COLUMN location_id INTEGER;

-- documents is rebuilt to allow kind 'transfer' (goods moved between the two places).
-- location_id: delivery = taken from, receipt = put in, transfer = from; to_location_id: transfer = to.
-- location_set: a delivery note whose place the user has not chosen yet is 0 (shown in Cần xử lý).
CREATE TABLE documents_new (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('delivery', 'receipt', 'stock_count', 'transfer')),
    code            TEXT NOT NULL DEFAULT '',
    code_norm       TEXT NOT NULL DEFAULT '',
    doc_date        TEXT NOT NULL,
    customer_id     INTEGER REFERENCES customers(id),
    note            TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled', 'replaced')),
    source_file     TEXT NOT NULL DEFAULT '',
    source_hash     TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    closed_at       TEXT,
    receipt_source  TEXT NOT NULL DEFAULT '',
    supplier_id     INTEGER REFERENCES suppliers(id),
    ref_code        TEXT NOT NULL DEFAULT '',
    fee_amount      REAL,
    note_total      REAL,
    prices_read     INTEGER NOT NULL DEFAULT 0,
    location_id     INTEGER NOT NULL DEFAULT 1,
    to_location_id  INTEGER,
    location_set    INTEGER NOT NULL DEFAULT 1
);
INSERT INTO documents_new(id, kind, code, code_norm, doc_date, customer_id, note, status, source_file, source_hash,
                          created_at, closed_at, receipt_source, supplier_id, ref_code, fee_amount, note_total,
                          prices_read)
    SELECT id, kind, code, code_norm, doc_date, customer_id, note, status, source_file, source_hash,
           created_at, closed_at, receipt_source, supplier_id, ref_code, fee_amount, note_total, prices_read
    FROM documents;
DROP TABLE documents;
ALTER TABLE documents_new RENAME TO documents;
CREATE UNIQUE INDEX ux_documents_active_delivery
    ON documents(code_norm) WHERE kind = 'delivery' AND status = 'active';
CREATE INDEX ix_documents_date ON documents(doc_date);
CREATE INDEX ix_documents_customer ON documents(customer_id);

-- A note per product kept with the stock (boxes damaged, misprinted, expired...): shown and edited on the
-- Tồn kho and Kiểm kê pages, exported to Excel.
ALTER TABLE products ADD COLUMN stock_note TEXT NOT NULL DEFAULT '';
