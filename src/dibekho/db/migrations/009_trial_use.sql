-- New document kind 'trial' (28/10/2026, "Xuất dùng thử"): goods taken out of stock for internal trial/testing
-- use, so staff no longer need a sham delivery note to self-deduct stock for this. No customer; location_id =
-- the place it was taken from (every stock movement needs a place).
-- documents is rebuilt again because SQLite cannot alter a CHECK constraint in place (same technique as 008;
-- location_id/to_location_id/location_set must be copied too, or every document silently resets to Kho tổng).
CREATE TABLE documents_new (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('delivery', 'receipt', 'stock_count', 'transfer', 'trial')),
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
                          prices_read, location_id, to_location_id, location_set)
    SELECT id, kind, code, code_norm, doc_date, customer_id, note, status, source_file, source_hash,
           created_at, closed_at, receipt_source, supplier_id, ref_code, fee_amount, note_total,
           prices_read, location_id, to_location_id, location_set
    FROM documents;
DROP TABLE documents;
ALTER TABLE documents_new RENAME TO documents;
CREATE UNIQUE INDEX ux_documents_active_delivery
    ON documents(code_norm) WHERE kind = 'delivery' AND status = 'active';
CREATE INDEX ix_documents_date ON documents(doc_date);
CREATE INDEX ix_documents_customer ON documents(customer_id);
