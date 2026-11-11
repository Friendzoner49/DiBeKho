"""Which tables travel to the cloud, and the triggers that queue their changes (docs/cloud/06-cloud-la-goc.md).

Plain data + SQL, no Qt and no core imports: used by dibekho.db (triggers on open) and by core.cloud.replica
(building and applying the rows). The columns are read from the database itself, so a new column travels without
touching this file; tests/test_cloud_core_schema.py checks the cloud has a column for each of them."""

from dataclasses import dataclass, field

# meta keys that describe the shared data (the rest belong to one machine: cloud_*, last_*, device...)
SHARED_META = ("low_stock_default", "freed_codes", "count_checked", "skipped_lines_backfilled", "product_code_max")


@dataclass(frozen=True)
class SyncTable:
    name: str
    key: str  # "id", "rowid" (no declared key) or the text key column
    refs: dict = field(default_factory=dict)  # column -> table it points to (translated id <-> uuid)
    natural: bool = False  # keyed by text: the same key on both sides, no sync_map
    only_keys: tuple = ()  # meta: the shared keys only
    booleans: tuple = ()  # 0/1 here, boolean on the cloud
    timestamps: tuple = ()  # 'YYYY-MM-DD HH:MM:SS' here, timestamp on the cloud


# parents before children (pushing and applying go in this order; deleting goes backwards)
SYNCED = (
    SyncTable("suppliers", "id", timestamps=("created_at",)),
    SyncTable("customers", "id", timestamps=("created_at",)),
    SyncTable("products", "id", booleans=("active",), timestamps=("created_at",)),
    SyncTable("product_aliases", "key", refs={"product_id": "products"}, natural=True),
    SyncTable("ignored_lines", "key", natural=True, timestamps=("created_at",)),
    SyncTable("documents", "id", refs={"customer_id": "customers", "supplier_id": "suppliers"},
              booleans=("prices_read", "location_set"), timestamps=("created_at", "closed_at")),
    SyncTable("document_lines", "id", refs={"document_id": "documents", "product_id": "products"}),
    SyncTable("stock_movements", "id", refs={"product_id": "products", "document_id": "documents"},
              timestamps=("created_at",)),
    SyncTable("document_skipped_lines", "rowid", refs={"document_id": "documents"}),
    SyncTable("meta", "key", natural=True, only_keys=SHARED_META),
)
BY_NAME = {t.name: t for t in SYNCED}

_ON = "(SELECT value FROM sync_flags WHERE key = 'enabled') = '1' AND (SELECT value FROM sync_flags WHERE key = 'applying') = '0'"


def _when(t: SyncTable, row: str) -> str:
    only = ""
    if t.only_keys:
        only = f" AND {row}.key IN ({', '.join(repr(k) for k in t.only_keys)})"
    return _ON + only


def trigger_sql(t: SyncTable) -> list[str]:
    key_new, key_old = f"NEW.{t.key}", f"OLD.{t.key}"
    queue = (f"INSERT INTO sync_outbox(tbl, local_id, op) VALUES ('{t.name}', {{k}}, 'U')")
    out = [
        f"CREATE TRIGGER IF NOT EXISTS sync_{t.name}_ins AFTER INSERT ON {t.name} WHEN {_when(t, 'NEW')} "
        f"BEGIN {queue.format(k=key_new)}; END",
        f"CREATE TRIGGER IF NOT EXISTS sync_{t.name}_upd AFTER UPDATE ON {t.name} WHEN {_when(t, 'NEW')} "
        f"BEGIN {queue.format(k=key_new)}; END",
    ]
    if t.natural:
        out.append(
            f"CREATE TRIGGER IF NOT EXISTS sync_{t.name}_del AFTER DELETE ON {t.name} WHEN {_when(t, 'OLD')} "
            f"BEGIN INSERT INTO sync_outbox(tbl, local_id, op, uid) VALUES ('{t.name}', {key_old}, 'D', {key_old}); END")
    else:
        # The uuid is captured for the cloud, then the mapping always goes: SQLite may give a deleted id to a new row,
        # which must not inherit the old row's uuid.
        out.append(
            f"CREATE TRIGGER IF NOT EXISTS sync_{t.name}_del AFTER DELETE ON {t.name} BEGIN "
            f"INSERT INTO sync_outbox(tbl, local_id, op, uid) SELECT '{t.name}', {key_old}, 'D', "
            f"(SELECT uid FROM sync_map WHERE tbl = '{t.name}' AND local_id = {key_old}) WHERE {_ON}; "
            f"DELETE FROM sync_map WHERE tbl = '{t.name}' AND local_id = {key_old}; END")
    return out


def ensure_triggers(conn) -> None:
    """Create any missing sync trigger (idempotent; cheap on every open). No-op before migration 010."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sync_outbox'").fetchone() is None:
        return
    for t in SYNCED:
        for statement in trigger_sql(t):
            conn.execute(statement)


def trigger_names() -> set[str]:
    return {f"sync_{t.name}_{op}" for t in SYNCED for op in ("ins", "upd", "del")}
