"""Rows between the local database and the cloud's real tables (docs/cloud/06-cloud-la-goc.md).

The local database keeps its integer ids (every screen and core function uses them); the cloud keys rows by uuid so
machines working offline never collide. sync_map links the two. A cloud row has the same columns as the SQLite row,
with references turned into uuids, 0/1 into booleans, plus 'deleted'. Which tables travel: dibekho.db.sync_schema."""

import uuid

from dibekho.db import transaction
from dibekho.db.sync_schema import BY_NAME, SYNCED, SyncTable


def set_enabled(conn, on: bool) -> None:
    """Cloud mode on/off for this database: only then do the triggers queue changes in sync_outbox."""
    conn.execute("UPDATE sync_flags SET value = ? WHERE key = 'enabled'", ("1" if on else "0",))


def enabled(conn) -> bool:
    row = conn.execute("SELECT value FROM sync_flags WHERE key = 'enabled'").fetchone()
    return row is not None and row[0] == "1"


def columns(conn, t: SyncTable) -> list[str]:
    """The table's columns as they are in this database (a new column travels without code changes)."""
    return [r[1] for r in conn.execute(f"PRAGMA table_info({t.name})")]


def cloud_columns(conn, t: SyncTable) -> list[str]:
    """The cloud table's business columns: the same, plus 'id' for a table SQLite keys by rowid."""
    cols = columns(conn, t)
    return cols if t.key != "rowid" else ["id", *cols]


# ---- ids ------------------------------------------------------------------------------------------------------

def uid_for(conn, table: str, local_id, create: bool = True) -> str | None:
    row = conn.execute("SELECT uid FROM sync_map WHERE tbl = ? AND local_id = ?", (table, str(local_id))).fetchone()
    if row is not None:
        return row[0]
    if not create:
        return None
    uid = str(uuid.uuid4())
    conn.execute("INSERT INTO sync_map(tbl, local_id, uid) VALUES (?, ?, ?)", (table, str(local_id), uid))
    return uid


def local_for(conn, table: str, uid: str) -> int | None:
    row = conn.execute("SELECT local_id FROM sync_map WHERE tbl = ? AND uid = ?", (table, uid)).fetchone()
    return int(row[0]) if row is not None else None


# ---- local -> cloud ---------------------------------------------------------------------------------------------

def _select(t: SyncTable) -> str:
    where = f" WHERE key IN ({', '.join('?' for _ in t.only_keys)})" if t.only_keys else ""
    rowid = "rowid AS _rowid, " if t.key == "rowid" else ""
    return f"SELECT {rowid}* FROM {t.name}{where}"


def to_cloud(conn, t: SyncTable, row) -> dict:
    out = {}
    for col in columns(conn, t):
        value = row[col]
        if value is not None and col in t.refs:
            value = uid_for(conn, t.refs[col], value)
        elif value is not None and col in t.booleans:
            value = bool(value)
        out[col] = value
    if not t.natural:
        local = row["_rowid"] if t.key == "rowid" else row[t.key]
        out["id"] = uid_for(conn, t.name, local)
    out["deleted"] = False
    return out


def snapshot(conn) -> dict[str, list[dict]]:
    """Every synced row as cloud rows (the first push of a database, and the one-time move to the cloud).
    Writes sync_map for rows that had no uuid yet, so it runs in a transaction."""
    with transaction(conn):
        return {t.name: [to_cloud(conn, t, r) for r in conn.execute(_select(t), t.only_keys).fetchall()]
                for t in SYNCED}


def pending(conn) -> tuple[dict[str, list[dict]], int]:
    """What changed since the last push, as cloud rows (deleted ones carry only their id/key) + the last outbox
    seq included (clear_outbox(conn, seq) once the cloud has them). A row changed several times travels once."""
    with transaction(conn):
        last = conn.execute("SELECT MAX(seq) FROM sync_outbox").fetchone()[0] or 0
        out: dict[str, list[dict]] = {t.name: [] for t in SYNCED}
        # Deletes first and each on its own: SQLite may give a deleted id to a new row, so "latest entry per local
        # id" would lose the delete of the old row. A delete without uuid was never pushed: nothing to tell the cloud.
        for tbl, uid in conn.execute("SELECT DISTINCT tbl, uid FROM sync_outbox WHERE op = 'D' AND uid IS NOT NULL "
                                     "ORDER BY seq").fetchall():
            t = BY_NAME[tbl]
            out[tbl].append({t.key if t.natural else "id": uid, "deleted": True})
        changed = conn.execute("SELECT tbl, local_id FROM sync_outbox WHERE op = 'U' GROUP BY tbl, local_id "
                               "ORDER BY MIN(seq)").fetchall()
        for tbl, local_id in changed:
            t = BY_NAME[tbl]
            key = "rowid" if t.key == "rowid" else t.key
            row = conn.execute(f"{_select(t).split(' WHERE')[0]} WHERE {key} = ?", (local_id,)).fetchone()
            if row is None:
                continue  # deleted since: its delete is above
            if t.natural:  # deleted then written again: the write wins
                out[tbl] = [r for r in out[tbl] if r.get(t.key) != local_id]
            out[tbl].append(to_cloud(conn, t, row))
        return out, last


def clear_outbox(conn, upto_seq: int) -> None:
    conn.execute("DELETE FROM sync_outbox WHERE seq <= ?", (upto_seq,))


# ---- cloud -> local ---------------------------------------------------------------------------------------------

def _local_value(conn, t: SyncTable, col: str, value):
    if value is None:
        return None
    if col in t.refs:
        local = local_for(conn, t.refs[col], value)
        if local is None:
            raise ValueError(f"{t.name}.{col}: {t.refs[col]} {value} is not here")
        return local
    if col in t.booleans:
        return 1 if value else 0
    if col in t.timestamps:
        return str(value)[:19].replace("T", " ")  # Postgres JSON writes 2026-11-02T10:00:00
    return value


def apply(conn, rows: dict[str, list[dict]]) -> None:
    """Write rows pulled from the cloud into this database, in one transaction, without queueing them again.
    Parents first; deletions children first."""
    with transaction(conn):
        conn.execute("UPDATE sync_flags SET value = '1' WHERE key = 'applying'")
        for t in reversed(SYNCED):
            for r in rows.get(t.name, []):
                if r.get("deleted"):
                    _delete(conn, t, r)
        for t in SYNCED:
            for r in rows.get(t.name, []):
                if not r.get("deleted"):
                    _upsert(conn, t, r)
        conn.execute("UPDATE sync_flags SET value = '0' WHERE key = 'applying'")


def _delete(conn, t: SyncTable, r: dict) -> None:
    if t.natural:
        conn.execute(f"DELETE FROM {t.name} WHERE {t.key} = ?", (r[t.key],))
        return
    local = local_for(conn, t.name, r["id"])
    if local is not None:
        conn.execute(f"DELETE FROM {t.name} WHERE {'rowid' if t.key == 'rowid' else t.key} = ?", (local,))


def _upsert(conn, t: SyncTable, r: dict) -> None:
    if t.only_keys and r.get("key") not in t.only_keys:
        return
    cols = [c for c in columns(conn, t) if c in r and not (not t.natural and c == t.key)]
    values = [_local_value(conn, t, c, r[c]) for c in cols]
    if t.natural:
        sets = ", ".join(f"{c} = excluded.{c}" for c in cols if c != t.key)
        conn.execute(f"INSERT INTO {t.name}({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
                     f"ON CONFLICT({t.key}) DO UPDATE SET {sets}", values)
        return
    key = "rowid" if t.key == "rowid" else t.key
    local = local_for(conn, t.name, r["id"])
    if local is not None:
        conn.execute(f"UPDATE {t.name} SET {', '.join(f'{c} = ?' for c in cols)} WHERE {key} = ?", (*values, local))
        return
    cur = conn.execute(f"INSERT INTO {t.name}({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", values)
    conn.execute("INSERT INTO sync_map(tbl, local_id, uid) VALUES (?, ?, ?)", (t.name, str(cur.lastrowid), r["id"]))


# ---- SQL for the cloud side ---------------------------------------------------------------------------------------

def cloud_insert_sql(conn, t: SyncTable) -> str:
    """INSERT of a JSON array of cloud rows ($1) into the cloud table, tagging them with the device ($2)."""
    cols = ", ".join(cloud_columns(conn, t))
    return (f"insert into public.{t.name} ({cols}, origin) select {cols}, $2 "
            f"from jsonb_populate_recordset(null::public.{t.name}, $1::jsonb)")


def cloud_select_sql(t: SyncTable) -> str:
    """Every row of a cloud table as JSON, without the server's bookkeeping columns (deleted is kept)."""
    return (f"select to_jsonb(x) - 'rev' - 'updated_at' - 'origin' as r from public.{t.name} x "
            f"order by {'key' if t.natural else 'id'}")
