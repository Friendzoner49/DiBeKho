-- Cloud as the source of truth (docs/cloud/06-cloud-la-goc.md): the local database stays the working copy and
-- the offline queue. These tables only record what must travel; the triggers that fill sync_outbox are created
-- by dibekho.db.sync_schema.ensure_triggers() on every open (so a later migration that rebuilds a table cannot
-- silently drop them). Nothing here changes how the app works while sync is off (the customer's local mode).

-- local id <-> cloud uuid, for tables keyed by an integer (text-keyed tables use their key on both sides)
CREATE TABLE IF NOT EXISTS sync_map (
    tbl       TEXT NOT NULL,
    local_id  TEXT NOT NULL,
    uid       TEXT NOT NULL UNIQUE,
    PRIMARY KEY (tbl, local_id)
);

-- rows changed here since the last push (op: U = inserted or updated, D = deleted; uid kept for deletes)
CREATE TABLE IF NOT EXISTS sync_outbox (
    seq       INTEGER PRIMARY KEY AUTOINCREMENT,
    tbl       TEXT NOT NULL,
    local_id  TEXT NOT NULL,
    op        TEXT NOT NULL CHECK (op IN ('U', 'D')),
    uid       TEXT,
    at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- enabled = 1 in cloud mode only; applying = 1 while rows pulled from the cloud are written (not queued again)
CREATE TABLE IF NOT EXISTS sync_flags (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
INSERT OR IGNORE INTO sync_flags(key, value) VALUES ('enabled', '0'), ('applying', '0');
