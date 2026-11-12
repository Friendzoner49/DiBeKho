"""Two-way sync with the cloud's real tables (docs/cloud/06-cloud-la-goc.md, cloud/supabase/008_sync_rpc.sql).

A round: PULL everything newer than what this machine saw -> MERGE here (the business rules are this app's) -> PUSH
this machine's queued changes with the rev it saw; refused when someone wrote in between, then the round repeats.

Merging, in order:
- a pulled row that equals a queued local row is our own earlier push whose reply was lost (echo): nothing to do;
- a pulled row that differs from a queued local row is a CONFLICT: neither is applied nor pushed until the user
  chooses (everything else keeps syncing);
- shared meta keys merge by rule (count_checked: union, freed_codes: intersection, product_code_max: maximum);
- codes this app hands out (SPxxx, HV/CH/DTxxx) that clash with a pulled row are renumbered HERE, every version of a
  document together, and a receipt's Excel file follows its new code (user's choice 11/11/2026);
- a delivery note pulled from another machine with the same file as one read here is the same note: ours goes; a
  different note with the same order code becomes a separate order (code_norm 76#2, as "Nhập thành đơn riêng");
- a document deleted elsewhere (reset) forgets this machine's scan record of it, as a local reset does.

The network calls (fetch, send) touch no database; merge/finish touch no network, so a caller can run them on
different threads."""

import json
from dataclasses import dataclass, field
from datetime import datetime

from dibekho import db
from dibekho.core import catalog
from dibekho.core.cloud import replica
from dibekho.db.sync_schema import BY_NAME, SYNCED

CURSOR_KEY = "sync_cursor"  # per machine (not in SHARED_META): the highest cloud rev merged here
CONFLICTS_KEY = "sync_conflicts"  # per machine: JSON list of unresolved conflicts
PREFIX = {"receipt": "HV", "transfer": "CH", "trial": "DT"}


@dataclass
class Conflict:
    table: str
    uid: str
    local: dict
    cloud: dict


@dataclass
class Merged:
    applied: int = 0
    renamed: list[tuple[str, str, str]] = field(default_factory=list)  # (table, old code, new code)
    duplicates: int = 0  # delivery notes read on two machines
    separated: list[str] = field(default_factory=list)  # order codes that became separate orders
    conflicts: list[Conflict] = field(default_factory=list)  # new ones this round
    receipts_to_export: list[int] = field(default_factory=list)  # local ids whose Excel file must follow a new code
    receipt_files: list[tuple[int, str]] = field(default_factory=list)  # receipts made on the web: (local id, file)


# ---- small state ------------------------------------------------------------------------------------------------

def cursor(conn) -> int:
    return int(db.get_meta(conn, CURSOR_KEY, "0") or 0)


def conflicts(conn) -> list[Conflict]:
    return [Conflict(**c) for c in json.loads(db.get_meta(conn, CONFLICTS_KEY, "[]") or "[]")]


def _save_conflicts(conn, items: list[Conflict]) -> None:
    db.set_meta(conn, CONFLICTS_KEY, json.dumps([c.__dict__ for c in items], ensure_ascii=False))


def held(conn) -> set[tuple[str, str]]:
    """(table, local id or key) of rows in conflict: not pushed until resolved."""
    out = set()
    for c in conflicts(conn):
        t = BY_NAME[c.table]
        out.add((c.table, c.uid if t.natural else str(replica.local_for(conn, c.table, c.uid))))
    return out


# ---- network ------------------------------------------------------------------------------------------------------

def fetch(client, token: str, after: int) -> dict:
    return client.rpc("sync_pull", {"p_after": after}, token)


def send(client, token: str, device: str, expected: int, batch: dict) -> dict:
    return client.rpc("sync_push", {"p_device": device, "p_expected": expected, "p_batch": batch}, token)


# ---- merge --------------------------------------------------------------------------------------------------------

def _queued(conn) -> set[tuple[str, str]]:
    return {(r[0], r[1]) for r in conn.execute("SELECT tbl, local_id FROM sync_outbox")}


def _same(t, local: dict, cloud: dict) -> bool:
    """Equal as values (the cloud writes timestamps as 2026-11-02T10:00:00, numbers may come back as int)."""
    def norm(col, v):
        if v is not None and col in t.timestamps:
            return str(v)[:19].replace("T", " ")
        return v
    keys = (set(local) | set(cloud)) - {"rev", "deleted"}
    return (all(norm(k, local.get(k)) == norm(k, cloud.get(k)) for k in keys)
            and bool(local.get("deleted")) == bool(cloud.get("deleted")))


def _merge_meta(key: str, mine: str, theirs: str) -> str:
    split = lambda s: [x for x in (s or "").split(",") if x]  # noqa: E731
    if key == "count_checked":
        return ",".join(dict.fromkeys(split(theirs) + split(mine)))
    if key == "freed_codes":  # a code reused on either side must not be handed out again: keep what both still free
        theirs_set = set(split(theirs))
        return ",".join(c for c in split(mine) if c in theirs_set)
    if key == "product_code_max":
        return str(max(int(mine or 0), int(theirs or 0)))
    return mine  # last writer wins: ours is pushed right after


def _next_number(codes, prefix: str) -> int:
    best = 0
    for code in codes:
        if code and code.startswith(prefix) and code[len(prefix):].isdigit():
            best = max(best, int(code[len(prefix):]))
    return best + 1


def merge(conn, pulled: dict) -> Merged:
    tables = {t.name: list(pulled.get("tables", {}).get(t.name, [])) for t in SYNCED}
    out = Merged()
    queued = _queued(conn)
    open_conflicts = conflicts(conn)
    with db.transaction(conn):
        _conflicts_and_echoes(conn, tables, queued, out)
        _merge_shared_meta(conn, tables, queued)
        _renumber_products(conn, tables, out)
        _renumber_documents(conn, tables, out)
        dup_hashes = _deliveries(conn, tables, out)
        _forget_scans_of_deleted(conn, tables)
    replica.apply(conn, tables)
    # a receipt entered on the web names the Excel file the app writes for it (cloud 009: no file hash yet)
    for r in _live(tables["documents"]):
        if r["kind"] == "receipt" and r["status"] == "active" and r.get("source_file") and not r.get("source_hash"):
            local = replica.local_for(conn, "documents", r["id"])
            if local is not None:
                out.receipt_files.append((local, r["source_file"]))
    with db.transaction(conn):
        for h in dup_hashes:  # the scan record of a note read on both machines points at the cloud's document now
            doc = conn.execute("SELECT id FROM documents WHERE kind = 'delivery' AND source_hash = ? AND status = 'active'",
                               (h,)).fetchone()
            if doc is not None:
                conn.execute("UPDATE scanned_files SET document_id = ? WHERE hash = ?", (doc[0], h))
        if out.conflicts:  # a row already in conflict that changed again keeps only its newest cloud version
            fresh = {(c.table, c.uid) for c in out.conflicts}
            _save_conflicts(conn, [c for c in open_conflicts if (c.table, c.uid) not in fresh] + out.conflicts)
        db.set_meta(conn, CURSOR_KEY, str(max(cursor(conn), int(pulled.get("max_rev") or 0))))
    out.applied = sum(len(v) for v in tables.values())
    return out


def _conflicts_and_echoes(conn, tables: dict, queued: set, out: Merged) -> None:
    deleted_here = {r[0] for r in conn.execute("SELECT uid FROM sync_outbox WHERE op = 'D' AND uid IS NOT NULL")}
    for t in SYNCED:
        keep = []
        for r in tables[t.name]:
            if t.natural:
                local_id = r[t.key]
            else:
                local = replica.local_for(conn, t.name, r["id"])
                local_id = None if local is None else str(local)
            uid = r.get("key") if t.natural else r["id"]
            if local_id is None and uid in deleted_here:  # deleted here, not pushed yet: our delete wins
                if r.get("deleted"):  # ...and it is already gone there (our push, reply lost)
                    conn.execute("DELETE FROM sync_outbox WHERE op = 'D' AND uid = ?", (uid,))
                continue
            if local_id is None or (t.name, local_id) not in queued or t.name == "meta":
                keep.append(r)
                continue
            row = conn.execute(f"SELECT {'rowid AS _rowid, ' if t.key == 'rowid' else ''}* FROM {t.name} "
                               f"WHERE {'rowid' if t.key == 'rowid' else t.key} = ?", (local_id,)).fetchone()
            if row is None:  # gone here since it was queued: its delete (above) decides
                continue
            mine = replica.to_cloud(conn, t, row)
            if _same(t, mine, r):  # our own push, its reply lost: it is on the cloud already
                conn.execute("DELETE FROM sync_outbox WHERE tbl = ? AND local_id = ?", (t.name, local_id))
                continue
            if t.natural:  # names learned / lines ignored: ours wins, it is pushed right after
                continue
            out.conflicts.append(Conflict(t.name, r["id"], mine, r))
        tables[t.name] = keep


def _merge_shared_meta(conn, tables: dict, queued: set) -> None:
    keep = []
    for r in tables["meta"]:
        if ("meta", r["key"]) in queued and not r.get("deleted"):
            mine = db.get_meta(conn, r["key"], "")
            db.set_meta(conn, r["key"], _merge_meta(r["key"], mine, r["value"]))  # queued again: pushed merged
            continue
        keep.append(r)
    tables["meta"] = keep


def _live(rows: list[dict]) -> list[dict]:
    return [r for r in rows if not r.get("deleted")]


def _renumber_products(conn, tables: dict, out: Merged) -> None:
    pulled = {r["code"]: r["id"] for r in _live(tables["products"])}
    going = {r["id"] for r in tables["products"] if r.get("deleted")}  # e.g. merged away, its code given out again
    all_codes = set(pulled) | {r[0] for r in conn.execute("SELECT code FROM products")}
    for code, uid in pulled.items():
        row = conn.execute("SELECT id FROM products WHERE code = ?", (code,)).fetchone()
        mine = None if row is None else replica.uid_for(conn, "products", row[0], create=False)
        if row is None or mine == uid or (mine is not None and mine in going):
            continue
        used = int(db.get_meta(conn, catalog.CODE_MAX_KEY, "0") or 0)
        new = f"SP{max(_next_number(all_codes, 'SP'), used + 1):03d}"
        conn.execute("UPDATE products SET code = ? WHERE id = ?", (new, row[0]))
        db.set_meta(conn, catalog.CODE_MAX_KEY, str(int(new[2:])))
        all_codes.add(new)
        out.renamed.append(("products", code, new))


def _renumber_documents(conn, tables: dict, out: Merged) -> None:
    for kind, prefix in PREFIX.items():
        pulled = {(r["code"], r["id"]) for r in _live(tables["documents"])
                  if r["kind"] == kind and r["status"] != "replaced" and r["code"]}
        pulled_uids = {r["id"] for r in tables["documents"] if r["kind"] == kind}
        codes = {r["code"] for r in tables["documents"] if r["kind"] == kind}
        codes |= {r[0] for r in conn.execute("SELECT code FROM documents WHERE kind = ?", (kind,))}
        for code, uid in sorted(pulled):
            mine = conn.execute("SELECT id FROM documents WHERE kind = ? AND code = ? AND status <> 'replaced'",
                                (kind, code)).fetchone()
            if mine is None or replica.uid_for(conn, "documents", mine[0], create=False) in pulled_uids:
                continue
            new = f"{prefix}{_next_number(codes, prefix):03d}"
            ids = [r[0] for r in conn.execute("SELECT id FROM documents WHERE kind = ? AND code = ?", (kind, code))
                   if replica.uid_for(conn, "documents", r[0], create=False) not in pulled_uids]
            for doc_id in ids:  # every version of it (an edited receipt keeps its code on the replaced one)
                conn.execute("UPDATE documents SET code = ?, code_norm = ? WHERE id = ?", (new, new, doc_id))
            codes.add(new)
            out.renamed.append(("documents", code, new))
            if kind == "receipt":
                out.receipts_to_export += [i for i in ids if conn.execute(
                    "SELECT status FROM documents WHERE id = ?", (i,)).fetchone()[0] == "active"]


def _deliveries(conn, tables: dict, out: Merged) -> list[str]:
    dup_hashes = []
    for r in _live(tables["documents"]):
        if r["kind"] != "delivery" or r["status"] != "active":
            continue
        mine = conn.execute("SELECT id, source_hash FROM documents WHERE kind = 'delivery' AND status = 'active' "
                            "AND code_norm = ?", (r["code_norm"],)).fetchone()
        if mine is None or replica.uid_for(conn, "documents", mine["id"], create=False) == r["id"]:
            continue
        if mine["source_hash"] and mine["source_hash"] == r["source_hash"]:
            # the same note read here too and not pushed yet: the cloud's copy stays, ours goes (never pushed)
            for table in ("stock_movements", "document_lines", "document_skipped_lines"):
                conn.execute(f"DELETE FROM {table} WHERE document_id = ?", (mine["id"],))
            conn.execute("UPDATE scanned_files SET document_id = NULL WHERE document_id = ?", (mine["id"],))
            conn.execute("DELETE FROM documents WHERE id = ?", (mine["id"],))
            dup_hashes.append(r["source_hash"])
            out.duplicates += 1
            continue
        n = 2
        while conn.execute("SELECT 1 FROM documents WHERE kind = 'delivery' AND code_norm = ?",
                           (f"{r['code_norm']}#{n}",)).fetchone():
            n += 1
        conn.execute("UPDATE documents SET code_norm = ? WHERE id = ?", (f"{r['code_norm']}#{n}", mine["id"]))
        out.separated.append(r["code"])
    return dup_hashes


def _forget_scans_of_deleted(conn, tables: dict) -> None:
    for r in tables["documents"]:
        if r.get("deleted"):
            local = replica.local_for(conn, "documents", r["id"])
            if local is not None:
                conn.execute("DELETE FROM scanned_files WHERE document_id = ?", (local,))


# ---- push ---------------------------------------------------------------------------------------------------------

CLOCK_KEY = "clock_offset_min"


def clock_offset() -> int:
    """This machine's clock, minutes from UTC (Vietnam: 420)."""
    return round(datetime.now().astimezone().utcoffset().total_seconds() / 60)


def stamp_clock(conn) -> None:
    """The shared data's clock, set once by the first machine that syncs: the web writes created_at in it, as the
    app writes its local time (cloud/supabase/009_web_rpc.sql, dbk_now)."""
    if not db.get_meta(conn, CLOCK_KEY, ""):
        with db.transaction(conn):
            db.set_meta(conn, CLOCK_KEY, str(clock_offset()))


def prepare(conn) -> tuple[dict, int, set]:
    """(batch, last outbox seq in it, rows held back by conflicts)."""
    stamp_clock(conn)
    hold = held(conn)
    batch, seq = replica.pending(conn, exclude=hold)
    return batch, seq, hold


def finish(conn, seq: int, max_rev: int, hold: set) -> None:
    with db.transaction(conn):
        replica.clear_outbox(conn, seq, keep=hold)
        db.set_meta(conn, CURSOR_KEY, str(max_rev))


def empty(batch: dict) -> bool:
    return not any(batch.values())


# ---- resolving a conflict -----------------------------------------------------------------------------------------

def resolve(conn, conflict: Conflict, keep_mine: bool) -> None:
    """keep_mine: this machine's version is pushed (overwrites the cloud's). Otherwise the cloud's is written here."""
    rest = [c for c in conflicts(conn) if not (c.table == conflict.table and c.uid == conflict.uid)]
    if keep_mine:
        with db.transaction(conn):
            _save_conflicts(conn, rest)
        return
    local = replica.local_for(conn, conflict.table, conflict.uid)
    replica.apply(conn, {conflict.table: [conflict.cloud]})
    with db.transaction(conn):
        if local is not None:
            conn.execute("DELETE FROM sync_outbox WHERE tbl = ? AND local_id = ?", (conflict.table, str(local)))
        _save_conflicts(conn, rest)


# ---- one whole round (tests, and callers that do not need threads) ------------------------------------------------

@dataclass
class Round:
    merged: list[Merged] = field(default_factory=list)
    pushed: int = 0


def sync_round(conn, client, token: str, device: str, tries: int = 3) -> Round:
    result = Round()
    for _ in range(tries):
        result.merged.append(merge(conn, fetch(client, token, cursor(conn))))
        batch, seq, hold = prepare(conn)
        if empty(batch):
            return result
        answer = send(client, token, device, cursor(conn), batch)
        if answer.get("ok"):
            finish(conn, seq, int(answer["max_rev"]), hold)
            result.pushed = sum(len(v) for v in batch.values())
            return result
    return result


def export_renamed(conn, ws, merged: Merged) -> None:
    """A receipt renumbered by a merge: its Excel file follows the new code (the old file would carry a code that
    now belongs to another machine's receipt)."""
    from dibekho.core import receipts

    for doc_id, name in merged.receipt_files:  # entered on the web: the file only, the row stays as the web wrote it
        if receipts.exported_file(ws, name) is None:
            try:
                receipts.write_file(conn, ws, doc_id, name)
            except OSError:
                pass  # the folder is not writable now: the data is right anyway
    for doc_id in merged.receipts_to_export:
        row = conn.execute("SELECT source_file FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if row is None:
            continue
        old = receipts.exported_file(ws, row[0])
        receipts.export_file(conn, ws, doc_id)
        if old is not None:
            try:
                old.unlink()
            except OSError:
                pass  # open in Excel: the new file exists anyway


# ---- turning cloud mode on ----------------------------------------------------------------------------------------

def cloud_empty(pulled: dict) -> bool:
    return not any(pulled.get("tables", {}).get(t.name) for t in SYNCED)


def start_from_this_machine(conn) -> None:
    """The cloud holds nothing yet: this machine's data becomes the shared data (everything queued for the push)."""
    replica.queue_all(conn)
    with db.transaction(conn):
        replica.set_enabled(conn, True)


def start_from_cloud(conn) -> None:
    """The cloud already holds the shared data: this machine's own copy is put aside (the caller backed it up) and the
    next round pulls everything. Scan records go too; reading the notes again finds their documents by file."""
    with db.transaction(conn):
        replica.set_enabled(conn, False)  # clearing is not a change to send
        for t in reversed(SYNCED):
            if t.name == "documents":
                conn.execute("DELETE FROM scanned_files")
            where = f" WHERE key IN ({', '.join('?' for _ in t.only_keys)})" if t.only_keys else ""
            conn.execute(f"DELETE FROM {t.name}{where}", t.only_keys)
        conn.execute("DELETE FROM sync_map")
        conn.execute("DELETE FROM sync_outbox")
        db.set_meta(conn, CURSOR_KEY, "0")
        db.set_meta(conn, CONFLICTS_KEY, "[]")
        replica.set_enabled(conn, True)


def stop(conn) -> None:
    """Back to working alone. Queued changes stay queued; turning it on again takes the cloud's data."""
    with db.transaction(conn):
        replica.set_enabled(conn, False)


def queued_count(conn) -> int:
    return conn.execute("SELECT COUNT(DISTINCT tbl || ':' || local_id) FROM sync_outbox").fetchone()[0]
