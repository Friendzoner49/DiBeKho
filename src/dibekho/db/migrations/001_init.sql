-- DiBeKho schema v1.
-- Rule: stock is never edited directly. Every change is a row in stock_movements;
-- current stock = SUM(stock_movements.qty).

CREATE TABLE products (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name_vi     TEXT NOT NULL,
    name_zh     TEXT NOT NULL DEFAULT '',
    spec        TEXT NOT NULL DEFAULT '',
    unit        TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT '',
    min_stock   REAL NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Text seen on delivery notes (normalized name|spec) -> product. Learned when the user maps a line.
CREATE TABLE product_aliases (
    key         TEXT PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products(id)
);

CREATE TABLE customers (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    contact     TEXT NOT NULL DEFAULT '',
    phone       TEXT NOT NULL DEFAULT '',
    phone_norm  TEXT NOT NULL DEFAULT '',
    address     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX ix_customers_phone ON customers(phone_norm);

-- delivery = phiếu giao hàng (stock out), receipt = hàng về (stock in), stock_count = kiểm kê.
-- status: active | cancelled | replaced (an edited delivery note replaced by its new version).
CREATE TABLE documents (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('delivery', 'receipt', 'stock_count')),
    code         TEXT NOT NULL DEFAULT '',
    code_norm    TEXT NOT NULL DEFAULT '',
    doc_date     TEXT NOT NULL,              -- business date, YYYY-MM-DD
    customer_id  INTEGER REFERENCES customers(id),
    note         TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled', 'replaced')),
    source_file  TEXT NOT NULL DEFAULT '',   -- file name as seen by the user
    source_hash  TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    closed_at    TEXT                         -- when cancelled/replaced
);
CREATE UNIQUE INDEX ux_documents_active_delivery
    ON documents(code_norm) WHERE kind = 'delivery' AND status = 'active';
CREATE INDEX ix_documents_date ON documents(doc_date);
CREATE INDEX ix_documents_customer ON documents(customer_id);

CREATE TABLE document_lines (
    id           INTEGER PRIMARY KEY,
    document_id  INTEGER NOT NULL REFERENCES documents(id),
    line_no      INTEGER NOT NULL,
    product_id   INTEGER NOT NULL REFERENCES products(id),
    qty          REAL NOT NULL,              -- delivery/receipt: quantity; stock_count: counted quantity
    raw_name     TEXT NOT NULL DEFAULT '',   -- text exactly as on the source file
    raw_spec     TEXT NOT NULL DEFAULT '',
    note         TEXT NOT NULL DEFAULT ''    -- shown only, never interpreted
);
CREATE INDEX ix_lines_document ON document_lines(document_id);
CREATE INDEX ix_lines_product ON document_lines(product_id);

-- kind: delivery_out | delivery_reverse | receipt_in | receipt_reverse | count_adjust | count_reverse
CREATE TABLE stock_movements (
    id           INTEGER PRIMARY KEY,
    product_id   INTEGER NOT NULL REFERENCES products(id),
    qty          REAL NOT NULL,
    document_id  INTEGER NOT NULL REFERENCES documents(id),
    kind         TEXT NOT NULL,
    occurred_on  TEXT NOT NULL,              -- business date used by reports
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    lot_id       INTEGER,                    -- reserved for future lot tracking
    location_id  INTEGER                     -- reserved for future locations
);
CREATE INDEX ix_movements_product_date ON stock_movements(product_id, occurred_on);
CREATE INDEX ix_movements_document ON stock_movements(document_id);

-- One row per distinct file content seen in phieu-giao-hang/.
-- status: imported | error | needs_mapping | changed | missing | missing_ignored
CREATE TABLE scanned_files (
    hash         TEXT PRIMARY KEY,
    rel_path     TEXT NOT NULL,              -- relative to phieu-giao-hang/
    document_id  INTEGER REFERENCES documents(id),
    status       TEXT NOT NULL,
    message      TEXT NOT NULL DEFAULT '',
    first_seen   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    last_seen    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE TABLE app_log (
    id      INTEGER PRIMARY KEY,
    at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    action  TEXT NOT NULL,
    detail  TEXT NOT NULL DEFAULT ''
);
