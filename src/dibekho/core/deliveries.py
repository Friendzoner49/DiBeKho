"""Scanning the phieu-giao-hang/ folder and turning delivery notes into documents.

The database is the source of truth; files are only input:
- a file is identified by the SHA-256 of its content, so renaming/moving it changes nothing;
- the same content is never imported twice;
- deleting a file never changes stock, the user is asked what to do instead;
- every imported file is copied to data/phieu-goc/<hash>.xlsx so it can be reopened or restored;
- a note that is fully recorded is moved to phieu-giao-hang/da-xu-ly/ (same sub-folders), and back out if it
  needs a decision again, so the folder itself shows what is done and what is not.
"""

import hashlib
import shutil
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from dibekho import db
from dibekho.core import catalog
from dibekho.core.stock import Line, add_lines, close_document, insert_document, stock_count
from dibekho.core.text import fmt_qty, match_key, nfc
from dibekho.core.workspace import PROCESSED, Workspace
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
    first_date: date | None = None  # earliest delivery date among the notes containing the line


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


def note_path(ws: Workspace, rel: str) -> Path:
    """The file for a stored rel_path. rel_path is kept in NFC, but a name written in NFD (files that went
    through a Mac or a chat app) is a different name for Windows: then look the file up among the notes."""
    path = ws.deliveries / rel
    if path.exists():
        return path
    for candidate in delivery_files(ws):
        if nfc(candidate.relative_to(ws.deliveries).as_posix()) == rel:
            return candidate
    return path


def scan(conn, ws: Workspace, allow_partial: bool = False) -> ScanResult:
    """allow_partial=True only right after the user pressed 'Apply': waiting notes are then imported with
    the lines that are known; the remaining lines are added to the same document once they are decided."""
    result = ScanResult()
    seen: set[str] = set()
    found: list[tuple[Path, str, str]] = []
    for path in delivery_files(ws):
        rel = nfc(path.relative_to(ws.deliveries).as_posix())
        try:
            h = file_hash(path)
        except OSError:
            continue  # file being written / locked; next scan will get it
        seen.add(h)
        found.append((path, rel, h))
        row = conn.execute("SELECT * FROM scanned_files WHERE hash = ?", (h,)).fetchone()
        if row and row["status"] in ("imported", "missing", "missing_ignored", "ignored"):
            status = row["status"]
            if status in ("missing", "missing_ignored"):  # file is back: resume where it was
                status = "needs_mapping" if row["message"] == "needs_mapping" else "imported"
            conn.execute(
                "UPDATE scanned_files SET rel_path = ?, status = ?, last_seen = datetime('now','localtime') "
                "WHERE hash = ?",
                (rel, status, h),
            )
            if status != "needs_mapping":  # done, or hidden by the user
                continue
        if process_file(conn, ws, path, rel, h, allow_partial):
            result.imported.append(rel)

    # Imported (or partly imported) files that disappeared from the folder; their document is still active.
    # message keeps the previous status so a restored partial note asks for its remaining lines again.
    for row in conn.execute(
        "SELECT s.hash FROM scanned_files s JOIN documents d ON d.id = s.document_id "
        "WHERE s.status IN ('imported', 'needs_mapping') AND d.status = 'active'"
    ).fetchall():
        if row["hash"] not in seen:
            conn.execute("UPDATE scanned_files SET message = status, status = 'missing' WHERE hash = ?",
                         (row["hash"],))
    # Waiting files (unknown names, errors, edited notes) that are not in the folder any more, e.g. rows
    # that came with a data package from another computer: nothing was imported from them, so forget them.
    # If the file is put back, the next scan asks again.
    for row in conn.execute(
        "SELECT hash FROM scanned_files WHERE status IN ('error', 'needs_mapping', 'changed') "
        "AND document_id IS NULL"
    ).fetchall():
        if row["hash"] not in seen:
            conn.execute("DELETE FROM scanned_files WHERE hash = ?", (row["hash"],))
    sort_files(conn, ws, found)
    result.pending = pending_count(conn)
    return result


def _in_done(rel: str) -> bool:
    return rel.split("/", 1)[0].lower() == PROCESSED


def _is_done(row) -> bool:
    """Fully recorded, or an edited copy the user decided to ignore (keep the old version)."""
    return row is not None and (row["status"] == "imported" or (row["status"] == "ignored" and row["document_id"]))


def sort_files(conn, ws: Workspace, found) -> None:
    """Move finished notes into phieu-giao-hang/da-xu-ly/ and notes that wait for a decision back out.
    Sub-folders are kept (2026-09/x.xlsx <-> da-xu-ly/2026-09/x.xlsx). A file that cannot be moved now
    (open in Excel on Windows) is moved on a later scan."""
    for path, rel, h in found:
        row = conn.execute("SELECT status, document_id FROM scanned_files WHERE hash = ?", (h,)).fetchone()
        inside = _in_done(rel)
        if _is_done(row) == inside:
            continue
        target = (ws.deliveries / rel.split("/", 1)[1]) if inside else (ws.deliveries_done / rel)
        target = _free_name(target)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            path.replace(target)
        except OSError:
            continue
        conn.execute("UPDATE scanned_files SET rel_path = ? WHERE hash = ? AND rel_path = ?",
                     (nfc(target.relative_to(ws.deliveries).as_posix()), h, rel))
        _remove_empty_folders(path.parent, ws)


def _free_name(target: Path) -> Path:
    n = 2
    candidate = target
    while candidate.exists():
        candidate = target.with_name(f"{target.stem} ({n}){target.suffix}")
        n += 1
    return candidate


def _remove_empty_folders(folder: Path, ws: Workspace) -> None:
    """Sub-folders emptied by a move (never phieu-giao-hang/ or da-xu-ly/ themselves)."""
    while folder not in (ws.deliveries, ws.deliveries_done) and ws.deliveries in folder.parents:
        try:
            folder.rmdir()  # only succeeds when empty
        except OSError:
            return
        folder = folder.parent


def move_all_out(ws: Workspace) -> int:
    """Put every file of phieu-giao-hang/da-xu-ly/ back into phieu-giao-hang/ (reset: read everything again)."""
    moved = 0
    if not ws.deliveries_done.exists():
        return 0
    for path in sorted(p for p in ws.deliveries_done.rglob("*") if p.is_file()):
        target = _free_name(ws.deliveries / path.relative_to(ws.deliveries_done))
        target.parent.mkdir(parents=True, exist_ok=True)
        path.replace(target)
        moved += 1
    for folder in sorted((p for p in ws.deliveries_done.rglob("*") if p.is_dir()), reverse=True):
        try:
            folder.rmdir()
        except OSError:
            pass
    return moved


def process_file(conn, ws: Workspace, path: Path, rel: str, h: str, allow_partial: bool = False) -> bool:
    """Try to import one file. Returns True when a document was created."""
    try:
        note = read_delivery_note(path)
    except (NotDeliveryNote, DeliveryNoteError) as exc:
        _record(conn, h, rel, "error", str(exc))
        return False

    goods = goods_lines(conn, note)
    unknown = [ln for ln in goods if catalog.alias_product(conn, ln.key) is None]
    waiting = f"{len(unknown)} dòng hàng chưa nhận ra"

    existing = _active_delivery(conn, note.code_norm)
    if existing is not None and existing["source_hash"] != h:
        _record(conn, h, rel, "changed",
                f"Mã đơn {note.code} đã có từ file '{existing['source_file']}'", existing["id"])
        return False
    if existing is not None:  # this very file was imported before, maybe only partly: add what is known now
        with db.transaction(conn):
            _add_known_lines(conn, existing["id"], note)
            _record(conn, h, rel, "needs_mapping" if unknown else "imported", waiting if unknown else "",
                    existing["id"])
        return False
    if unknown and not (allow_partial and len(unknown) < len(goods)):
        _record(conn, h, rel, "needs_mapping", waiting)
        return False

    with db.transaction(conn):
        doc_id = _import(conn, ws, path, rel, h, note)
        if unknown:
            _record(conn, h, rel, "needs_mapping", waiting, doc_id)
    return doc_id is not None


def _note_lines(conn, note: DeliveryNote, rows=()) -> list[Line]:
    """Known goods lines of a note as ledger lines, except the Excel rows already in the document."""
    lines = []
    for ln in goods_lines(conn, note):
        pid = catalog.alias_product(conn, ln.key)
        if pid is not None and ln.row not in rows:
            lines.append(Line(pid, ln.qty, ln.raw_name, ln.spec, ln.note, line_no=ln.row))
    return lines


def _add_known_lines(conn, doc_id: int, note: DeliveryNote) -> None:
    rows = {r[0] for r in conn.execute("SELECT line_no FROM document_lines WHERE document_id = ?", (doc_id,))}
    new = _note_lines(conn, note, rows)
    if new:
        add_lines(conn, doc_id, new)
        db.log(conn, "delivery_lines_added", f"{note.code}: {len(new)}")


def _import(conn, ws: Workspace, path: Path, rel: str, h: str, note: DeliveryNote) -> int:
    ws.originals.mkdir(parents=True, exist_ok=True)
    copy = ws.originals / f"{h}.xlsx"
    if not copy.exists():
        shutil.copy2(path, copy)
    customer_id = catalog.upsert_customer(conn, note.customer_name, note.phone, note.contact, note.address)
    lines = _note_lines(conn, note)
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
            note = read_delivery_note(note_path(ws, row["rel_path"]))
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
            if note.doc_date and (item.first_date is None or note.doc_date < item.first_date):
                item.first_date = note.doc_date
            item.orders.append(" · ".join(x for x in (note.code, note.customer_name, f"SL {fmt_qty(ln.qty)}") if x))
    return list(found.values())


def line_label(line) -> str:
    return " ".join(x for x in (line.name_vi or line.raw_name, line.spec) if x)


def map_line(conn, key: str, product_id: int, label: str = "") -> None:
    catalog.set_alias(conn, key, product_id, label)


def ignore_unknown(conn, line: UnknownLine) -> None:
    """'Not goods': drop this line from every note, now and later."""
    catalog.ignore_line(conn, line.key, line_label(line))


def create_product_for_line(conn, line: UnknownLine, category: str = "", opening: float | None = None,
                            note: str = "") -> int:
    """opening: the stock on hand before the first note containing this line (a new product has no
    history yet). Recorded as a stock count on the day before that note, so the note is subtracted from it."""
    with db.transaction(conn):
        product_id = catalog.create_product(conn, line.name_vi, line.name_zh, line.spec, category=category)
        catalog.set_alias(conn, line.key, product_id, line_label(line))
        if opening is not None:
            day = (line.first_date or date.today()) - timedelta(days=1)
            stock_count(conn, day, {product_id: opening}, note)
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
    target = note_path(ws, rel)
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
    path = note_path(ws, row["rel_path"])
    note = read_delivery_note(path)
    goods = goods_lines(conn, note)
    unknown = [ln for ln in goods if catalog.alias_product(conn, ln.key) is None]
    if goods and len(unknown) == len(goods):
        raise ValueError("Phiếu mới có dòng hàng chưa nhận ra.")
    with db.transaction(conn):
        old = _active_delivery(conn, note.code_norm)
        if old is not None:
            close_document(conn, old["id"], "replaced")
        doc_id = _import(conn, ws, path, row["rel_path"], h, note)
        if unknown:
            _record(conn, h, row["rel_path"], "needs_mapping", f"{len(unknown)} dòng hàng chưa nhận ra", doc_id)


def keep_old(conn, h: str) -> None:
    conn.execute("UPDATE scanned_files SET status = 'ignored', message = '' WHERE hash = ?", (h,))


# ---- deleted files ---------------------------------------------------------

def restore_missing(conn, ws: Workspace, h: str) -> Path:
    row = conn.execute("SELECT * FROM scanned_files WHERE hash = ?", (h,)).fetchone()
    target = note_path(ws, row["rel_path"])
    if target.exists():
        target = target.with_name(f"{target.stem} (khoi phuc){target.suffix}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ws.originals / f"{h}.xlsx", target)
    conn.execute(
        "UPDATE scanned_files SET status = CASE WHEN message = 'needs_mapping' THEN 'needs_mapping' "
        "ELSE 'imported' END, message = '', rel_path = ? WHERE hash = ?",
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
