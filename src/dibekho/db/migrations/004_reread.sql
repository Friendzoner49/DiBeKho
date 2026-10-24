-- Readable text for learned names (the key is normalized and hard to read).
ALTER TABLE product_aliases ADD COLUMN label TEXT NOT NULL DEFAULT '';

-- Lines of an imported delivery note that were skipped as 'not goods' (fees),
-- so 'forget' can find and re-read the notes that contained them.
CREATE TABLE document_skipped_lines (
    document_id  INTEGER NOT NULL REFERENCES documents(id),
    key          TEXT NOT NULL,
    raw_name     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX ix_skipped_key ON document_skipped_lines(key);
