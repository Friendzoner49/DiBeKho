"""Scanning the phieu-giao-hang/ folder and turning delivery notes into documents.

The database is the source of truth; files are only input:
- a file is identified by the SHA-256 of its content, so renaming/moving it changes nothing;
- the same content is never imported twice;
- deleting a file never changes stock, the user is asked what to do instead;
- every imported file is copied to data/phieu-goc/<hash>.xlsx so it can be reopened or restored.
"""

import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from dibekho import db
from dibekho.core import catalog
from dibekho.core.stock import Line, close_document, insert_document
from dibekho.core.text import fmt_qty, match_key, nfc
from dibekho.core.workspace import Workspace
from dibekho.excel.delivery_note import (
    DeliveryNote,
    DeliveryNoteError,
    NotDeliveryNote,
    read_delivery_note,
)

PENDING_STATUSES = ("error", "needs_mapping", "changed", "missing")


@dataclass
class ScanResult:
    imported: list[str] = field(default_factory=list)
    pending: int = 0


@dataclass
class UnknownLine:
    key: str
    name_vi: str
    name_zh: str
    spec: str
    files: list[str]
    suggestion: int | None
    raw_name: str = ""
    orders: list[str] = field(default_factory=list)  # "76 · Khách A · SL 2" for each note containing the line
    is_fee: bool = False  # looks like 'Phí vận chuyển' -> the UI pre-selects 'not goods'


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def delivery_files(ws: Workspace) -> list[Path]:
    files = []
    for path in ws.deliveries.rglob("*"):
        name = path.name
        # '~$x.xlsx' = Excel lock file, '._x' = macOS metadata file
        if path.is_file() and path.suffix.lower() == ".xlsx" and not name.startswith(("~$", ".")):
            files.append(path)
    return sorted(files)


def scan(conn, ws: Workspace) -> ScanResult:
    result = ScanResult()
    seen: set[str] = set()
    for path in delivery_files(ws):
        rel = nfc(path.relative_to(ws.deliveries).as_posix())
        try:
            h = file_hash(path)
        except OSError:
            continue  # file being written / locked; next scan will get it
        seen.add(h)
        row = conn.execute("SELECT * FROM scanned_files WHERE hash = ?", (h,)).fetchone()
        if row and row["status"] in ("imported", "missing", "missing_ignored", "ignored"):
            status = "imported" if row["status"] in ("missing", "missing_ignored") else row["status"]
            conn.execute(
                "UPDATE scanned_files SET rel_path = ?, status = ?, last_seen = datetime('now','localtime') "
                "WHERE hash = ?",
                (rel, status, h),
            )
            continue
        if process_file(conn, ws, path, rel, h):
            result.imported.append(rel)

    # Imported files that disappeared from the folder (their document is still active).
    for row in conn.execute(
        "SELECT s.hash FROM scanned_files s JOIN documents d ON d.id = s.document_id "
        "WHERE s.status = 'imported' AND d.status = 'active'"
    ).fetchall():
        if row["hash"] not in seen:
            conn.execute("UPDATE scanned_files SET status = 'missing' WHERE hash = ?", (row["hash"],))
    # Waiting files (unknown names, errors, edited notes) that are not in the folder any more, e.g. rows
    # that came with a data package from another computer: nothing was imported from them, so forget them.
    # If the file is put back, the next scan asks again.
    for row in conn.execute(
        "SELECT hash FROM scanned_files WHERE status IN ('error', 'needs_mapping', 'changed')"
    ).fetchall():
        if row["hash"] not in seen:
            conn.execute("DELETE FROM scanned_files WHERE hash = ?", (row["hash"],))
    result.pending = pending_count(conn)
    return result


def process_file(conn, ws: Workspace, path: Path, rel: str, h: str) -> bool:
    """Try to import one file. Returns True when a document was created."""
    try:
        note = read_delivery_note(path)
    except (NotDeliveryNote, DeliveryNoteError) as exc:
        _record(conn, h, rel, "error", str(exc))
        return False

    # The customer is a fact on the note: record them now, even if the note waits for product names.
    catalog.upsert_customer(conn, note.customer_name, note.phone, note.contact, note.address)

    unknown = [ln for ln in goods_lines(conn, note) if catalog.alias_product(conn, ln.key) is None]
    if unknown:
        _record(conn, h, rel, "needs_mapping", f"{len(unknown)} dòng hàng chưa nhận ra")
        return False

    existing = _active_delivery(conn, note.code_norm)
    if existing is not None and existing["source_hash"] != h:
        _record(conn, h, rel, "changed",
                f"Mã đơn {note.code} đã có từ file '{existing['source_file']}'", existing["id"])
        return False
    if existing is not None:
        _record(conn, h, rel, "imported", "", existing["id"])
        return False

    with db.transaction(conn):
        doc_id = _import(conn, ws, path, rel, h, note)
    return doc_id is not None


def _import(conn, ws: Workspace, path: Path, rel: str, h: str, note: DeliveryNote) -> int:
    ws.originals.mkdir(parents=True, exist_ok=True)
    copy = ws.originals / f"{h}.xlsx"
    if not copy.exists():
        shutil.copy2(path, copy)
    customer_id = catalog.upsert_customer(conn, note.customer_name, note.phone, note.contact, note.address)
    lines = [
        Line(catalog.alias_product(conn, ln.key), ln.qty, ln.raw_name, ln.spec, ln.note)
        for ln in goods_lines(conn, note)
    ]
    doc_id = insert_document(
        conn, "delivery", note.doc_date, lines, code=note.code, code_norm=note.code_norm,
        customer_id=customer_id, source_file=rel, source_hash=h,
    )
    for ln in note.lines:
        if catalog.is_ignored(conn, ln.key):
            conn.execute("INSERT INTO document_skipped_lines(document_id, key, raw_name) VALUES(?,?,?)",
                         (doc_id, ln.key, ln.raw_name))
    _record(conn, h, rel, "imported", "", doc_id)
    db.log(conn, "delivery_imported", f"{note.code} ({rel})")
    return doc_id


def goods_lines(conn, note: DeliveryNote):
    """Lines of a note without the ones the user marked as 'not goods' (fees)."""
    return [ln for ln in note.lines if not catalog.is_ignored(conn, ln.key)]


def _active_delivery(conn, code_norm: str):
    return conn.execute(
        "SELECT * FROM documents WHERE kind = 'delivery' AND status = 'active' AND code_norm = ?",
        (code_norm,),
    ).fetchone()


def _record(conn, h, rel, status, message, document_id=None) -> None:
    conn.execute(
        """
        INSERT INTO scanned_files(hash, rel_path, document_id, status, message) VALUES(?,?,?,?,?)
        ON CONFLICT(hash) DO UPDATE SET
            rel_path = COALESCE(excluded.rel_path, scanned_files.rel_path),
            document_id = COALESCE(excluded.document_id, scanned_files.document_id),
            status = excluded.status, message = excluded.message,
            last_seen = datetime('now','localtime')
        """,
        (h, rel, document_id, status, message),
    )


def pending_count(conn) -> int:
    marks = ",".join("?" * len(PENDING_STATUSES))
    return conn.execute(
        f"SELECT COUNT(*) FROM scanned_files WHERE status IN ({marks})", PENDING_STATUSES
    ).fetchone()[0]


def pending_files(conn):
    marks = ",".join("?" * len(PENDING_STATUSES))
    return conn.execute(
        f"SELECT s.*, d.code AS doc_code FROM scanned_files s LEFT JOIN documents d ON d.id = s.document_id "
        f"WHERE s.status IN ({marks}) ORDER BY s.status, s.rel_path",
        PENDING_STATUSES,
    ).fetchall()


# ---- unknown product names -------------------------------------------------

def unknown_lines(conn, ws: Workspace) -> list[UnknownLine]:
    """Distinct unrecognised lines across all files waiting for mapping."""
    found: dict[str, UnknownLine] = {}
    for row in conn.execute("SELECT * FROM scanned_files WHERE status = 'needs_mapping'").fetchall():
        try:
            note = read_delivery_note(ws.deliveries / row["rel_path"])
        except (OSError, NotDeliveryNote, DeliveryNoteError):
            continue
        for ln in goods_lines(conn, note):
            if catalog.alias_product(conn, ln.key) is not None:
                continue
            item = found.get(ln.key)
            if item is None:
                fee = catalog.looks_like_fee(ln.raw_name)
                item = found[ln.key] = UnknownLine(
                    ln.key, ln.name_vi, ln.name_zh, ln.spec, [],
                    None if fee else catalog.suggest_product(conn, ln.raw_name, ln.spec),
                    raw_name=ln.raw_name, is_fee=fee,
                )
            if row["rel_path"] not in item.files:
                item.files.append(row["rel_path"])
            item.orders.append(" · ".join(x for x in (note.code, note.customer_name, f"SL {fmt_qty(ln.qty)}") if x))
    return list(found.values())


def line_label(line) -> str:
    return " ".join(x for x in (line.name_vi or line.raw_name, line.spec) if x)


def map_line(conn, key: str, product_id: int, label: str = "") -> None:
    catalog.set_alias(conn, key, product_id, label)


def ignore_unknown(conn, line: UnknownLine) -> None:
    """'Not goods': drop this line from every note, now and later."""
    catalog.ignore_line(conn, line.key, line_label(line))


def create_product_for_line(conn, line: UnknownLine, category: str = "") -> int:
    with db.transaction(conn):
        product_id = catalog.create_product(conn, line.name_vi, line.name_zh, line.spec, category=category)
        catalog.set_alias(conn, line.key, product_id, line_label(line))
    return product_id


# After mapping, call scan() again: rows with status error/needs_mapping/changed are re-processed.


# ---- undo: read a note again / forget a learned name -------------------------

@dataclass
class LearnedName:
    key: str
    label: str
    product_id: int | None  # None = 'not goods'
    documents: list[int]  # active delivery notes containing this line


def backfill_skipped_lines(conn, ws: Workspace) -> None:
    """Notes imported before migration 004 have no record of their dropped lines: read their stored copies once."""
    if db.get_meta(conn, "skipped_lines_backfilled"):
        return
    ignored = {r["key"] for r in catalog.ignored_lines(conn)}
    if ignored:
        docs = conn.execute(
            "SELECT id, source_hash FROM documents WHERE kind = 'delivery' AND status = 'active' AND source_hash <> '' "
            "AND id NOT IN (SELECT document_id FROM document_skipped_lines)"
        ).fetchall()
        for d in docs:
            path = original_copy(ws, d["source_hash"])
            try:
                note = read_delivery_note(path) if path else None
            except (OSError, NotDeliveryNote, DeliveryNoteError):
                note = None
            for ln in note.lines if note else []:
                if ln.key in ignored:
                    conn.execute("INSERT INTO document_skipped_lines(document_id, key, raw_name) VALUES(?,?,?)",
                                 (d["id"], ln.key, ln.raw_name))
    db.set_meta(conn, "skipped_lines_backfilled", "1")


def documents_with_key(conn, key: str) -> list[int]:
    ids = {r[0] for r in conn.execute(
        "SELECT s.document_id FROM document_skipped_lines s JOIN documents d ON d.id = s.document_id "
        "WHERE s.key = ? AND d.status = 'active'", (key,))}
    for r in conn.execute(
        "SELECT l.document_id, l.raw_name, l.raw_spec FROM document_lines l JOIN documents d ON d.id = l.document_id "
        "WHERE d.kind = 'delivery' AND d.status = 'active'"
    ):
        if match_key(r["raw_name"], r["raw_spec"]) == key:
            ids.add(r["document_id"])
    return sorted(ids)


def learned_names(conn, ws: Workspace) -> list[LearnedName]:
    """Every name the user taught the app (matched to a product or dropped as 'not goods')."""
    backfill_skipped_lines(conn, ws)
    lines = conn.execute(
        "SELECT l.document_id, l.raw_name, l.raw_spec FROM document_lines l JOIN documents d ON d.id = l.document_id "
        "WHERE d.kind = 'delivery' AND d.status = 'active'"
    ).fetchall()
    by_key: dict[str, list] = {}
    for r in lines:
        by_key.setdefault(match_key(r["raw_name"], r["raw_spec"]), []).append(r)
    result = []
    for a in conn.execute("SELECT * FROM product_aliases").fetchall():
        rows = by_key.get(a["key"], [])
        label = a["label"] or (" ".join(x for x in (rows[0]["raw_name"], rows[0]["raw_spec"]) if x) if rows
                               else a["key"])
        result.append(LearnedName(a["key"], label, a["product_id"], sorted({r["document_id"] for r in rows})))
    for g in catalog.ignored_lines(conn):
        result.append(LearnedName(g["key"], g["label"] or g["key"], None, documents_with_key(conn, g["key"])))
    return sorted(result, key=lambda x: x.label.casefold())


def reread_document(conn, ws: Workspace, doc_id: int) -> None:
    """Undo the import of one delivery note so the next scan reads it again with the current names.

    The old document is kept as 'replaced' (stock reversed), nothing is deleted.
    """
    row = conn.execute("SELECT * FROM scanned_files WHERE document_id = ?", (doc_id,)).fetchone()
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None or doc["kind"] != "delivery" or doc["status"] != "active" or not doc["source_hash"]:
        raise ValueError("Chỉ đọc lại được phiếu giao hàng đang hiệu lực.")
    rel = row["rel_path"] if row else doc["source_file"]
    target = ws.deliveries / rel
    if not target.exists():  # file deleted or moved away: put the stored copy back
        original = original_copy(ws, doc["source_hash"])
        if original is None:
            raise ValueError("Không còn file phiếu để đọc lại.")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
    with db.transaction(conn):
        close_document(conn, doc_id, "replaced")
        conn.execute("DELETE FROM scanned_files WHERE hash = ?", (doc["source_hash"],))
        db.log(conn, "delivery_reread", f"{doc['code']} ({rel})")


def forget_name(conn, ws: Workspace, key: str) -> int:
    """Forget a learned name and read again the notes containing it. Returns the number of notes."""
    backfill_skipped_lines(conn, ws)
    docs = documents_with_key(conn, key)
    catalog.forget_alias(conn, key)
    catalog.unignore_line(conn, key)
    for doc_id in docs:
        reread_document(conn, ws, doc_id)
    return len(docs)


# ---- edited files ----------------------------------------------------------

def replace_changed(conn, ws: Workspace, h: str) -> None:
    """User chose 'use the new version' for an edited delivery note."""
    row = conn.execute("SELECT * FROM scanned_files WHERE hash = ?", (h,)).fetchone()
    path = ws.deliveries / row["rel_path"]
    note = read_delivery_note(path)
    if any(catalog.alias_product(conn, ln.key) is None for ln in goods_lines(conn, note)):
        raise ValueError("Phiếu mới có dòng hàng chưa nhận ra.")
    with db.transaction(conn):
        old = _active_delivery(conn, note.code_norm)
        if old is not None:
            close_document(conn, old["id"], "replaced")
        _import(conn, ws, path, row["rel_path"], h, note)


def keep_old(conn, h: str) -> None:
    conn.execute("UPDATE scanned_files SET status = 'ignored', message = '' WHERE hash = ?", (h,))


# ---- deleted files ---------------------------------------------------------

def restore_missing(conn, ws: Workspace, h: str) -> Path:
    row = conn.execute("SELECT * FROM scanned_files WHERE hash = ?", (h,)).fetchone()
    target = ws.deliveries / row["rel_path"]
    if target.exists():
        target = target.with_name(f"{target.stem} (khoi phuc){target.suffix}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ws.originals / f"{h}.xlsx", target)
    conn.execute(
        "UPDATE scanned_files SET status = 'imported', rel_path = ? WHERE hash = ?",
        (nfc(target.relative_to(ws.deliveries).as_posix()), h),
    )
    return target


def cancel_missing(conn, h: str) -> None:
    row = conn.execute("SELECT document_id FROM scanned_files WHERE hash = ?", (h,)).fetchone()
    with db.transaction(conn):
        close_document(conn, row["document_id"], "cancelled")
        conn.execute("UPDATE scanned_files SET status = 'missing_ignored' WHERE hash = ?", (h,))


def ignore_missing(conn, h: str) -> None:
    conn.execute("UPDATE scanned_files SET status = 'missing_ignored' WHERE hash = ?", (h,))


def dismiss_error(conn, h: str) -> None:
    """Hide a file that is not a delivery note (stays hidden until its content changes)."""
    conn.execute("UPDATE scanned_files SET status = 'ignored' WHERE hash = ?", (h,))


def original_copy(ws: Workspace, source_hash: str) -> Path | None:
    p = ws.originals / f"{source_hash}.xlsx"
    return p if p.exists() else None
