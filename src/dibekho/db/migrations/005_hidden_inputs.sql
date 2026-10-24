-- Files in input/ the app cannot use and the user chose to hide. The file itself is never moved;
-- it stays hidden until its content changes (identified by SHA-256).
CREATE TABLE hidden_inputs (
    hash        TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
