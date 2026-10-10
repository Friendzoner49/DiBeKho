-- Lines on delivery notes that are not goods (phí vận chuyển, phí dịch vụ...).
-- Same key as product_aliases (normalized name|spec); such lines never change stock.
CREATE TABLE ignored_lines (
    key         TEXT PRIMARY KEY,
    label       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
