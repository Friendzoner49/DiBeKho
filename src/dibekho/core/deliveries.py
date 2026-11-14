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
import json
import shutil
import stat
import tempfile
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path

from dibekho import db
from dibekho.core import catalog
from dibekho.core.stock import (MAIN, Line, add_lines, close_document, insert_document, is_mixed, stock_count,
                                 stock_levels)
from dibekho.core.text import clean, fmt_qty, match_key, nfc, normalize_code, normalize_phone, unaccent
from dibekho.core.workspace import PROCESSED, Workspace
from dibekho.excel.delivery_note import (
    DeliveryNote,
    DeliveryNoteError,
    NotDeliveryNote,
    read_delivery_note,
)

PENDING_STATUSES = ("error", "needs_mapping", "changed", "missing")
OTHER_ORDER_DAYS = 31  # an edit may fix a wrong date by a few days; further apart it is likely another order
LETTERHEAD_KEY = "note_letterhead"  # meta: JSON list, the lines above the title of the shop's delivery notes
LETTERHEAD_TRIED_KEY = "letterhead_backfilled"  # meta, this machine only: the stored notes were searched once
COUNT_CHECKED_KEY = "count_checked"  # meta: notes (by file hash) the user decided about after a stock count


@dataclass
class ScanResult:
    imported: list[str] = field(default_factory=list)
    pending: int = 0
    copies: list[str] = field(default_factory=list)  # files with the same content as another one: counted once


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


OLD_EXCEL_MESSAGE = ("File Excel đời cũ (.xls), app chỉ đọc được .xlsx. Hãy mở file bằng Excel, chọn Lưu thành "
                     "(Save As) kiểu 'Excel Workbook (.xlsx)', rồi bấm Quét lại.")


def old_excel_files(ws: Workspace) -> list[Path]:
    """Notes saved in the Excel 97-2003 format: not readable, but the user must be told, not left wondering
    why the order never came in."""
    return sorted(p for p in ws.deliveries.rglob("*") if p.is_file() and p.suffix.lower() == ".xls"
                  and not p.name.startswith(("~$", ".")))


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
    unreadable = False
    for path in old_excel_files(ws):
        try:
            h = file_hash(path)
        except OSError:
            unreadable = True
            continue
        seen.add(h)
        row = conn.execute("SELECT status FROM scanned_files WHERE hash = ?", (h,)).fetchone()
        if row is None or row["status"] == "error":
            _record(conn, h, nfc(path.relative_to(ws.deliveries).as_posix()), "error", OLD_EXCEL_MESSAGE)
    for path in delivery_files(ws):
        rel = nfc(path.relative_to(ws.deliveries).as_posix())
        try:
            h = file_hash(path)
        except OSError:
            unreadable = True  # being written / locked / not downloaded yet; next scan will get it
            continue
        if h in seen:  # a copy of a file met in this scan (copied back into the folder): the same note, once
            result.copies.append(rel)
            found.append((path, rel, h))  # still sorted into da-xu-ly/ like the note it copies
            continue
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
    # A file that could not be read this time may be one of them: wait for a scan that sees every file.
    for row in conn.execute(
        "SELECT s.hash FROM scanned_files s JOIN documents d ON d.id = s.document_id "
        "WHERE s.status IN ('imported', 'needs_mapping') AND d.status = 'active'"
    ).fetchall():
        if row["hash"] not in seen and not unreadable:
            conn.execute("UPDATE scanned_files SET message = status, status = 'missing' WHERE hash = ?",
                         (row["hash"],))
    # The old version of a note edited in Excel (its document replaced), or of a cancelled order, is no longer
    # 'lost' nor 'waiting': nothing is left to decide about it. If it comes back it counts as done.
    for row in conn.execute(
        "SELECT s.hash FROM scanned_files s JOIN documents d ON d.id = s.document_id "
        "WHERE s.status IN ('missing', 'needs_mapping') AND d.status <> 'active'"
    ).fetchall():
        if row["hash"] not in seen:
            conn.execute("UPDATE scanned_files SET message = '', status = 'missing_ignored' WHERE hash = ?",
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
    backfill_customers(conn, ws)
    backfill_prices(conn, ws)
    backfill_letterhead(conn, ws)
    from dibekho.core import receipts  # receipts imports this module

    receipts.backfill_return_prices(conn)  # after the notes have their prices: a return takes its price from them
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
        try:
            path.replace(target)
        except OSError:  # open in Excel (or its lock file): left where it is
            continue
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
    unknown = [ln for ln in goods if line_product(conn, ln) is None]
    waiting = f"{len(unknown)} dòng hàng chưa nhận ra"

    existing = _active_delivery(conn, note.code_norm, h, note)
    if existing is not None and existing["source_hash"] != h and _separate_code(conn, h):
        existing = None  # recorded before as another order with this code, now read again: it stays apart
    if existing is not None and existing["source_hash"] != h:
        message = f"Mã đơn {note.code} đã có từ file '{existing['source_file']}'"
        reason = other_order_reason(existing, note)
        if reason:
            message += f" — nhưng {reason}: có thể là ĐƠN KHÁC trùng mã"
        _record(conn, h, rel, "changed", message, existing["id"])
        return False
    if existing is not None:  # this very file was imported before, maybe only partly: add what is known now
        with db.transaction(conn):
            _add_known_lines(conn, existing["id"], note)
            set_money(conn, existing["id"], note)
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
        pid = line_product(conn, ln)
        if pid is not None and ln.row not in rows:
            lines.append(Line(pid, ln.qty, ln.raw_name, ln.spec, ln.note, line_no=ln.row,
                              unit_price=ln.unit_price, amount=ln.amount,
                              location_id=ln.places[0][0] if len(ln.places) == 1 else None, places=ln.places))
    return lines


def _add_known_lines(conn, doc_id: int, note: DeliveryNote) -> None:
    rows = {r[0] for r in conn.execute("SELECT line_no FROM document_lines WHERE document_id = ?", (doc_id,))}
    new = _note_lines(conn, note, rows)
    if not note_places(note):
        new = [replace(ln, location_id=None, places=()) for ln in new]
    if new:
        add_lines(conn, doc_id, new)
        db.log(conn, "delivery_lines_added", f"{note.code}: {len(new)}")


def _separate_code(conn, h: str) -> str:
    """The matching key of a note recorded earlier as another order with a reused code ('76#2'), if that order
    was read again (replaced) and the key is free; '' otherwise."""
    row = conn.execute("SELECT code_norm FROM documents WHERE kind = 'delivery' AND source_hash = ? "
                       "AND status = 'replaced' ORDER BY id DESC LIMIT 1", (h,)).fetchone()
    if row is None or "#" not in row["code_norm"]:
        return ""
    taken = conn.execute("SELECT 1 FROM documents WHERE kind = 'delivery' AND status = 'active' AND code_norm = ?",
                         (row["code_norm"],)).fetchone()
    return "" if taken else row["code_norm"]


def _free_separate_code(conn, code_norm: str) -> str:
    n = 2
    while conn.execute("SELECT 1 FROM documents WHERE kind = 'delivery' AND code_norm = ?",
                       (f"{code_norm}#{n}",)).fetchone():
        n += 1
    return f"{code_norm}#{n}"


def _import(conn, ws: Workspace, path: Path, rel: str, h: str, note: DeliveryNote, replaces: int | None = None,
            separate: str = "") -> int:
    ws.originals.mkdir(parents=True, exist_ok=True)
    copy = ws.originals / f"{h}.xlsx"
    if not copy.exists():
        shutil.copy2(path, copy)
    customer_id = catalog.upsert_customer(conn, note.customer_name, note.phone, note.contact, note.address)
    lines = _note_lines(conn, note)
    # a note read again (same file) or its edited version (replaces) keeps the place chosen for it; a new one
    # waits for the user in Cần xử lý, its goods taken from Kho tổng meanwhile, so the total is right at once.
    # Not by order code alone: a code may come back years later on another order.
    if replaces is not None:
        prev = conn.execute("SELECT location_id, location_set, code_norm FROM documents WHERE id = ?",
                            (replaces,)).fetchone()
    else:
        prev = conn.execute(
            "SELECT location_id, location_set FROM documents WHERE kind = 'delivery' AND source_hash = ? "
            "AND status = 'replaced' ORDER BY id DESC LIMIT 1", (h,)).fetchone()
    # another order that reused a code keeps its own matching key ('76#2'); the code shown stays '76'
    code_norm = separate or (prev["code_norm"] if replaces is not None else _separate_code(conn, h)) or note.code_norm
    location_id, location_set = (prev["location_id"] if prev else MAIN), bool(prev and prev["location_set"])
    if note_places(note):  # a stock issue note says the place of each line itself: nothing to choose
        places = {loc for ln in note.lines for loc, _ in ln.places}
        location_id, location_set = (places.pop() if len(places) == 1 else MAIN), True
    else:
        lines = [replace(ln, location_id=None, places=()) for ln in lines]  # some lines only: the note's place
        if replaces is not None and is_mixed(conn, replaces):
            location_set = False  # it took from both places and the edit lost the split: ask again
    doc_id = insert_document(
        conn, "delivery", note.doc_date, lines, code=note.code, code_norm=code_norm,
        customer_id=customer_id, source_file=rel, source_hash=h,
        location_id=location_id, location_set=location_set,
    )
    for ln in note.lines:
        if catalog.is_ignored(conn, ln.key):
            conn.execute("INSERT INTO document_skipped_lines(document_id, key, raw_name) VALUES(?,?,?)",
                         (doc_id, ln.key, ln.raw_name))
    set_money(conn, doc_id, note)
    keep_letterhead(conn, note)
    _record(conn, h, rel, "imported", "", doc_id)
    db.log(conn, "delivery_imported", f"{note.code} ({rel})")
    return doc_id


def set_money(conn, doc_id: int, note: DeliveryNote) -> None:
    """Prices of a recorded delivery note, from the note itself: each document line gets the unit price and
    amount of its line on the note, the document its fees (rows that are not goods) and the printed total.
    A document line is matched by name + packing + quantity (Excel row only to break ties: notes recorded by
    early versions numbered their lines 1..n); a line that matches nothing keeps NULL prices."""
    priced = bool(note.fees) or any(ln.amount is not None for ln in note.lines)  # a printed 0 over empty cells is no price
    fees = sum(a for _, a in note.fees) + sum(ln.amount or 0 for ln in note.lines if catalog.is_ignored(conn, ln.key))
    conn.execute("UPDATE documents SET fee_amount = ?, note_total = ?, prices_read = 1 WHERE id = ?",
                 (fees if priced else None, note.total, doc_id))
    free = list(note.lines)
    for row in conn.execute("SELECT id, line_no, qty, raw_name, raw_spec FROM document_lines WHERE document_id = ? "
                            "ORDER BY line_no", (doc_id,)).fetchall():
        key = match_key(row["raw_name"], row["raw_spec"])
        same = [ln for ln in free if ln.key == key and abs(ln.qty - row["qty"]) < 1e-9]
        if not same:
            continue
        ln = next((x for x in same if x.row == row["line_no"]), same[0])
        free.remove(ln)
        conn.execute("UPDATE document_lines SET unit_price = ?, amount = ? WHERE id = ?",
                     (ln.unit_price, ln.amount, row["id"]))


def backfill_prices(conn, ws: Workspace) -> int:
    """Notes recorded before prices were read (version 0.3.0 and earlier, or a data package from it): read their
    stored copies once. A note without a stored copy is marked so it is not tried again. Returns the number
    of notes read."""
    done = 0
    for d in conn.execute(
        "SELECT id, source_hash FROM documents WHERE kind = 'delivery' AND prices_read = 0"
    ).fetchall():
        path = original_copy(ws, d["source_hash"]) if d["source_hash"] else None
        try:
            note = read_delivery_note(path) if path else None
        except (OSError, NotDeliveryNote, DeliveryNoteError):
            note = None
        with db.transaction(conn):
            if note is None:
                conn.execute("UPDATE documents SET prices_read = -1 WHERE id = ?", (d["id"],))
            else:
                set_money(conn, d["id"], note)
                done += 1
    return done


def line_product(conn, ln) -> int | None:
    """The product of a note line: by its 'Mã hàng' (stock issue notes written by the app), else by the name +
    spec learned before. A code that is not in the catalog (merged away) falls back to the name."""
    if ln.product_code:
        row = conn.execute("SELECT id FROM products WHERE code = ?", (ln.product_code,)).fetchone()
        if row is not None:
            return row[0]
    return catalog.alias_product(conn, ln.key)


def note_places(note: DeliveryNote) -> bool:
    """Every goods line says where it is taken from (the hidden 'Lấy từ kho' column of a stock issue note)."""
    return bool(note.lines) and all(ln.places for ln in note.lines)


def keep_letterhead(conn, note: DeliveryNote) -> None:
    """The company name and address printed above the title of the shop's own delivery notes, kept in meta for the
    stock issue notes (app and web) to print the same way. Never taken from an issue note, and never written in the
    code: the repository is public."""
    if not note.letterhead or not any(m in unaccent(note.title) or m in note.title for m in ("phieu giao hang", "销售单")):
        return
    value = json.dumps(note.letterhead[:3], ensure_ascii=False)
    if db.get_meta(conn, LETTERHEAD_KEY, "") != value:
        db.set_meta(conn, LETTERHEAD_KEY, value)


def letterhead(conn) -> list[str]:
    try:
        lines = json.loads(db.get_meta(conn, LETTERHEAD_KEY, "") or "[]")
    except ValueError:
        return []
    return [str(x) for x in lines if isinstance(x, str)][:3] if isinstance(lines, list) else []


def backfill_letterhead(conn, ws: Workspace) -> None:
    """Data recorded before the letterhead was kept: read it once from the latest delivery note's stored copy."""
    if db.get_meta(conn, LETTERHEAD_KEY, "") or db.get_meta(conn, LETTERHEAD_TRIED_KEY, ""):
        return
    db.set_meta(conn, LETTERHEAD_TRIED_KEY, "1")  # once per machine: a scan never re-reads old files for nothing
    for d in conn.execute("SELECT source_hash FROM documents WHERE kind = 'delivery' AND source_hash <> '' "
                          "ORDER BY doc_date DESC, id DESC LIMIT 20").fetchall():
        path = original_copy(ws, d["source_hash"])
        try:
            note = read_delivery_note(path) if path else None
        except (OSError, NotDeliveryNote, DeliveryNoteError):
            continue
        if note is not None and note.letterhead:
            keep_letterhead(conn, note)
            if db.get_meta(conn, LETTERHEAD_KEY, ""):
                return


def goods_lines(conn, note: DeliveryNote):
    """Lines of a note without the ones the user marked as 'not goods' (fees)."""
    return [ln for ln in note.lines if not catalog.is_ignored(conn, ln.key)]


def _active_delivery(conn, code_norm: str, h: str = "", note: DeliveryNote | None = None):
    """The active order with this code. A code reused by another customer may have been imported as a separate
    order ('Nhập thành đơn riêng'), so prefer the one from this very file, then the one of the same customer."""
    rows = conn.execute(
        "SELECT d.*, COALESCE(c.name, '') AS customer_name, COALESCE(c.phone_norm, '') AS customer_phone "
        "FROM documents d LEFT JOIN customers c ON c.id = d.customer_id "
        "WHERE d.kind = 'delivery' AND d.status = 'active' "
        "AND (d.code_norm = ?1 OR substr(d.code_norm, 1, length(?1) + 1) = ?1 || '#') ORDER BY d.id DESC",
        (code_norm,),
    ).fetchall()
    if not rows:
        return None
    return max(rows, key=lambda r: (bool(h) and r["source_hash"] == h,
                                    note is not None and not _other_customer(r, note)))


def _other_customer(doc, note: DeliveryNote) -> bool:
    name_a, name_b = unaccent(clean(doc["customer_name"])), unaccent(clean(note.customer_name))
    phone_a, phone_b = doc["customer_phone"], normalize_phone(note.phone)
    return bool((name_a and name_b and name_a != name_b) or (phone_a and phone_b and phone_a != phone_b))


def other_order_reason(doc, note: DeliveryNote) -> str:
    """Why an edited-looking note (same order code, other content) may in fact be another order: another
    customer, or a date far from the recorded one. '' when it looks like an edit of the same order."""
    reasons = []
    if _other_customer(doc, note):
        reasons.append(f"khác khách hàng ({doc['customer_name']} ≠ {note.customer_name or note.phone})")
    if abs((note.doc_date - date.fromisoformat(doc["doc_date"])).days) > OTHER_ORDER_DAYS:
        reasons.append(f"khác ngày ({date.fromisoformat(doc['doc_date']):%d/%m/%Y} ≠ {note.doc_date:%d/%m/%Y})")
    return ", ".join(reasons)


def looks_like_other_order(conn, ws: Workspace, h: str) -> bool:
    """For Cần xử lý: offer 'Nhập thành đơn riêng' on a 'changed' note only when it looks like another order."""
    row = conn.execute("SELECT * FROM scanned_files WHERE hash = ?", (h,)).fetchone()
    try:
        note = read_delivery_note(note_path(ws, row["rel_path"]))
    except (OSError, NotDeliveryNote, DeliveryNoteError):
        return False
    old = _changed_target(conn, row, note)
    return old is not None and bool(other_order_reason(old, note))


def _changed_target(conn, row, note: DeliveryNote):
    """The recorded order an edited note is compared with: the one found when it was scanned, if still active."""
    if row["document_id"]:
        doc = conn.execute(
            "SELECT d.*, COALESCE(c.name, '') AS customer_name, COALESCE(c.phone_norm, '') AS customer_phone "
            "FROM documents d LEFT JOIN customers c ON c.id = d.customer_id WHERE d.id = ? AND d.status = 'active'",
            (row["document_id"],)).fetchone()
        if doc is not None:
            return doc
    return _active_delivery(conn, note.code_norm, row["hash"], note)


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


def unplaced(conn):
    """Recorded delivery notes whose place (Kho tổng / Văn phòng) the user has not chosen yet, oldest first."""
    return conn.execute(
        "SELECT d.id, d.code, d.doc_date, COALESCE(c.name, '') AS customer, "
        "(SELECT COUNT(*) FROM document_lines x WHERE x.document_id = d.id) AS line_count, "
        "(SELECT COALESCE(SUM(x.qty), 0) FROM document_lines x WHERE x.document_id = d.id) AS total_qty "
        "FROM documents d LEFT JOIN customers c ON c.id = d.customer_id "
        "WHERE d.kind = 'delivery' AND d.status = 'active' AND d.location_set = 0 ORDER BY d.doc_date, d.id"
    ).fetchall()


def unplaced_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM documents WHERE kind = 'delivery' AND status = 'active' "
                        "AND location_set = 0").fetchone()[0]


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
            if line_product(conn, ln) is not None:
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


@dataclass
class NoteLine:
    row: int  # Excel row of the line
    raw_name: str
    name_vi: str
    name_zh: str
    spec: str
    qty: float
    key: str
    product_id: int | None  # known (learned) product; None = waiting for a decision, or 'not goods'
    ignored: bool = False  # 'not goods' (a fee)


@dataclass
class WaitingNote:
    """A delivery note in 'Cần xử lý' with all its lines, so the user checks a whole order at once."""
    rel_path: str
    code: str
    doc_date: date | None
    customer: str
    lines: list[NoteLine]

    @property
    def unknown(self) -> list[NoteLine]:
        return [ln for ln in self.lines if ln.product_id is None and not ln.ignored]


def waiting_notes(conn, ws: Workspace) -> list[WaitingNote]:
    """Notes waiting for a decision, oldest first, each with every line (known ones too, to compare)."""
    result = []
    for row in conn.execute("SELECT * FROM scanned_files WHERE status = 'needs_mapping'").fetchall():
        try:
            note = read_delivery_note(note_path(ws, row["rel_path"]))
        except (OSError, NotDeliveryNote, DeliveryNoteError):
            continue
        lines = [NoteLine(ln.row, ln.raw_name, ln.name_vi, ln.name_zh, ln.spec, ln.qty, ln.key,
                          line_product(conn, ln), catalog.is_ignored(conn, ln.key))
                 for ln in note.lines]
        waiting = WaitingNote(row["rel_path"], note.code, note.doc_date, note.customer_name, lines)
        if waiting.unknown:
            result.append(waiting)
    return sorted(result, key=lambda n: (n.doc_date or date.max, normalize_code(n.code), n.rel_path))


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


def backfill_customers(conn, ws: Workspace) -> int:
    """Notes recorded without a customer name because the reader missed a Chinese-only label ('客户名称 Khách Mẫu'):
    the customer is missing, or named by its phone number. Read their stored copies again and fill the name
    in. Returns the number of notes fixed."""
    fixed = 0
    for d in conn.execute(
        "SELECT d.id, d.source_hash, c.name, c.phone_norm FROM documents d LEFT JOIN customers c ON c.id = d.customer_id "
        "WHERE d.kind = 'delivery' AND d.source_hash <> ''"
    ).fetchall():
        if d["name"] is not None and not (d["phone_norm"] and normalize_phone(d["name"]) == d["phone_norm"]):
            continue  # has a real name
        path = original_copy(ws, d["source_hash"])
        try:
            note = read_delivery_note(path) if path else None
        except (OSError, NotDeliveryNote, DeliveryNoteError):
            note = None
        if note is not None and note.customer_name:
            customer_id = catalog.upsert_customer(conn, note.customer_name, note.phone, note.contact, note.address)
            conn.execute("UPDATE documents SET customer_id = ? WHERE id = ?", (customer_id, d["id"]))
            fixed += 1
    return fixed


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


@dataclass
class LearnedLine:
    key: str
    label: str  # the line as written on the note
    qty: float
    product_id: int | None  # None = dropped as 'not goods'
    documents: list[int]  # every active note with this line (forgetting reads them all again)


@dataclass
class LearnedOrder:
    doc_id: int | None  # None: names learned but no longer in any active note
    code: str
    doc_date: str
    customer: str
    lines: list[LearnedLine]


def learned_by_order(conn, ws: Workspace) -> list[LearnedOrder]:
    """What the app learned, grouped by delivery note (newest first), so a wrong choice is found from the
    order it spoiled. Names in no active note come last."""
    names = {n.key: n for n in learned_names(conn, ws)}
    orders, used = [], set()
    docs = conn.execute(
        "SELECT d.id, d.code, d.doc_date, COALESCE(c.name, '') AS customer FROM documents d "
        "LEFT JOIN customers c ON c.id = d.customer_id WHERE d.kind = 'delivery' AND d.status = 'active' "
        "ORDER BY d.doc_date DESC, d.id DESC"
    ).fetchall()
    for d in docs:
        lines = []
        for r in conn.execute("SELECT line_no, raw_name, raw_spec, qty FROM document_lines WHERE document_id = ? "
                              "ORDER BY line_no", (d["id"],)):
            key = match_key(r["raw_name"], r["raw_spec"])
            if key in names:
                lines.append(LearnedLine(key, " ".join(x for x in (r["raw_name"], r["raw_spec"]) if x), r["qty"],
                                         names[key].product_id, names[key].documents))
        for r in conn.execute("SELECT key, raw_name FROM document_skipped_lines WHERE document_id = ?", (d["id"],)):
            if r["key"] in names:
                lines.append(LearnedLine(r["key"], r["raw_name"] or names[r["key"]].label, 0, None,
                                         names[r["key"]].documents))
        if lines:
            used.update(ln.key for ln in lines)
            orders.append(LearnedOrder(d["id"], d["code"], d["doc_date"], d["customer"], lines))
    rest = [LearnedLine(n.key, n.label, 0, n.product_id, []) for n in names.values() if n.key not in used]
    if rest:
        orders.append(LearnedOrder(None, "", "", "", rest))
    return orders


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


def _check_rereadable(conn, ws: Workspace, doc_ids) -> None:
    """Before forgetting anything: every note that will be read again must still have its file or its stored
    copy, otherwise the names would be forgotten and only some of the notes read again."""
    lost = []
    for doc_id in sorted(doc_ids):
        doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        row = conn.execute("SELECT rel_path FROM scanned_files WHERE document_id = ?", (doc_id,)).fetchone()
        rel = row["rel_path"] if row else (doc["source_file"] if doc else "")
        if doc is None or not doc["source_hash"] or not (
                (rel and note_path(ws, rel).exists()) or original_copy(ws, doc["source_hash"])):
            lost.append(doc["code"] if doc else f"#{doc_id}")
    if lost:
        raise ValueError(f"Không đọc lại được vì không còn file phiếu của đơn {', '.join(lost)}. Không có gì bị thay đổi.")


def _order_keys(conn, doc_id: int) -> set[str]:
    return {match_key(r["raw_name"], r["raw_spec"]) for r in conn.execute(
        "SELECT raw_name, raw_spec FROM document_lines WHERE document_id = ?", (doc_id,))}


def documents_sharing_names(conn, doc_id: int) -> list[int]:
    """Other active delivery notes that share at least one learned name with this one: forget_order() rereads
    them too, because forgetting a name is global, not per-order. Shown in the confirm dialog before acting."""
    docs: set[int] = set()
    for key in _order_keys(conn, doc_id):
        docs.update(documents_with_key(conn, key))
    docs.discard(doc_id)
    return sorted(docs)


def forget_order(conn, ws: Workspace, doc_id: int) -> int:
    """Forget every name learned from this note's goods lines ('not goods' lines are left alone -- unignoring
    a fee like 'Phí vận chuyển' would reread nearly every order) and read every active note containing any of
    those names again, including this one. Returns the number of notes re-read.

    This is what makes 'Đọc lại phiếu' actually change something: read alone, with the names unchanged, it
    only reproduces the same note (see doc.confirm_reread before this existed)."""
    backfill_skipped_lines(conn, ws)
    doc = conn.execute(
        "SELECT 1 FROM documents WHERE id = ? AND kind = 'delivery' AND status = 'active'", (doc_id,)
    ).fetchone()
    if doc is None:
        raise ValueError("Chỉ đọc lại được phiếu giao hàng đang hiệu lực.")
    keys = _order_keys(conn, doc_id)
    docs = {doc_id} | {d for key in keys for d in documents_with_key(conn, key)}
    _check_rereadable(conn, ws, docs)
    for key in keys:
        catalog.forget_alias(conn, key)
    for d in sorted(docs):
        reread_document(conn, ws, d)
    return len(docs)


def forget_name(conn, ws: Workspace, key: str) -> int:
    """Forget a learned name and read again the notes containing it. Returns the number of notes."""
    backfill_skipped_lines(conn, ws)
    docs = documents_with_key(conn, key)
    _check_rereadable(conn, ws, docs)
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
    unknown = [ln for ln in goods if line_product(conn, ln) is None]
    if goods and len(unknown) == len(goods):
        raise ValueError("Phiếu mới có dòng hàng chưa nhận ra.")
    with db.transaction(conn):
        old = _changed_target(conn, row, note)
        if old is not None:
            close_document(conn, old["id"], "replaced")
        doc_id = _import(conn, ws, path, row["rel_path"], h, note, replaces=old["id"] if old is not None else None)
        if unknown:
            _record(conn, h, row["rel_path"], "needs_mapping", f"{len(unknown)} dòng hàng chưa nhận ra", doc_id)


def import_separately(conn, ws: Workspace, h: str) -> None:
    """User chose 'another order with the same code' for a note that looked edited: record it as a new order
    next to the old one, which is left as it is."""
    row = conn.execute("SELECT * FROM scanned_files WHERE hash = ?", (h,)).fetchone()
    path = note_path(ws, row["rel_path"])
    note = read_delivery_note(path)
    # unknown lines wait in Cần xử lý and are added to this order once decided (it is found by its file then)
    unknown = [ln for ln in goods_lines(conn, note) if line_product(conn, ln) is None]
    with db.transaction(conn):
        doc_id = _import(conn, ws, path, row["rel_path"], h, note, separate=_free_separate_code(conn, note.code_norm))
        if unknown:
            _record(conn, h, row["rel_path"], "needs_mapping", f"{len(unknown)} dòng hàng chưa nhận ra", doc_id)
        db.log(conn, "delivery_separate", f"{note.code} ({row['rel_path']})")


def keep_old(conn, h: str) -> None:
    conn.execute("UPDATE scanned_files SET status = 'ignored', message = '' WHERE hash = ?", (h,))


# ---- deleted files ---------------------------------------------------------

def restore_missing(conn, ws: Workspace, h: str) -> Path:
    row = conn.execute("SELECT * FROM scanned_files WHERE hash = ?", (h,)).fetchone()
    original = original_copy(ws, h)
    if original is None:
        raise ValueError("Không còn bản sao của phiếu này trong data/phieu-goc để khôi phục. "
                         "Nếu còn file phiếu ở nơi khác, hãy chép lại vào thư mục phiếu giao hàng.")
    target = note_path(ws, row["rel_path"])
    if target.exists():
        target = target.with_name(f"{target.stem} (khoi phuc){target.suffix}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, target)
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


def viewing_copy(ws: Workspace, source_hash: str, name: str = "") -> Path | None:
    """A read-only copy of the stored original in the system's temp folder, to open in Excel: the stored copy
    is never opened itself, so Excel leaves no lock file in data/phieu-goc and cannot save over it."""
    src = original_copy(ws, source_hash)
    if src is None:
        return None
    folder = Path(tempfile.gettempdir()) / "DiBeKho" / source_hash[:12]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (Path(name).name if name.lower().endswith(".xlsx") else f"{source_hash[:12]}.xlsx")
    try:
        if target.exists():
            target.chmod(stat.S_IWRITE | stat.S_IREAD)
        shutil.copyfile(src, target)
        target.chmod(stat.S_IREAD)
    except OSError:  # already open in Excel: open that one again
        if not target.exists():
            return src
    return target


# ---- notes read after a stock count ------------------------------------------

def _checked(conn) -> list[str]:
    return [x for x in db.get_meta(conn, COUNT_CHECKED_KEY, "").split(",") if x]


def count_conflicts(conn) -> list:
    """Orders dated on or before a stock count but first read into the app after that count. If their goods
    had already left when the shelf was counted, the count includes them and the order subtracts them a
    second time. Only orders whose place is chosen (that is where the goods were taken from). One row per
    order, with the latest such count; orders the user already decided about are left out."""
    checked, seen, result = set(_checked(conn)), set(), []
    for r in _conflicts_of(conn):
        if r["id"] not in seen and (r["source_hash"] or f"#{r['id']}") not in checked:
            seen.add(r["id"])
            result.append(r)
    return result


def _conflicts_of(conn, doc_id: int | None = None) -> list:
    """(order, count) pairs as described in count_conflicts, latest count first; one order or all."""
    return conn.execute(
        """
        SELECT d.id, d.code, d.doc_date, d.source_hash, COALESCE(cu.name, '') AS customer,
               c.id AS count_id, c.doc_date AS count_date
        FROM documents d
        JOIN documents c ON c.kind = 'stock_count' AND c.status = 'active' AND c.doc_date >= d.doc_date
        LEFT JOIN customers cu ON cu.id = d.customer_id
        WHERE d.kind = 'delivery' AND d.status = 'active' AND d.location_set = 1
          AND c.created_at < {_FIRST_IN}
          -- the count covered where the goods were taken from: that place, or the total
          AND EXISTS (SELECT 1 FROM stock_movements m JOIN document_lines cl ON cl.product_id = m.product_id
                      AND (cl.location_id IS NULL OR cl.location_id = m.location_id)
                      WHERE m.document_id = d.id AND m.kind = 'delivery_out' AND cl.document_id = c.id)
          AND (? IS NULL OR d.id = ?)
        ORDER BY d.doc_date, d.id, c.doc_date DESC, c.id DESC
        """.format(_FIRST_IN=_FIRST_IN), (doc_id, doc_id)
    ).fetchall()


# when an order first came into the app (a note read again or edited later keeps its first time)
_FIRST_IN = """(SELECT MIN(x.created_at) FROM documents x WHERE x.kind = 'delivery' AND x.code_norm = d.code_norm
                AND (x.source_hash = d.source_hash OR x.customer_id IS d.customer_id))"""


def _mark_checked(conn, doc_id: int) -> None:
    doc = conn.execute("SELECT source_hash FROM documents WHERE id = ?", (doc_id,)).fetchone()
    key = doc["source_hash"] or f"#{doc_id}"
    checked = _checked(conn)
    if key not in checked:
        db.set_meta(conn, COUNT_CHECKED_KEY, ",".join(checked + [key]))


def keep_counted(conn, doc_id: int) -> None:
    """'The count was right': give back exactly this order's quantities, product by product and place by
    place, wherever a count made before the order came in already saw the goods gone (that place counted, or
    the total). The correction is a count adjustment dated on the earliest such count, so receipts, other
    orders and decisions made since stay as they are, and later counts line up by themselves."""
    code = conn.execute("SELECT code FROM documents WHERE id = ?", (doc_id,)).fetchone()["code"]
    rows = conn.execute(
        f"""
        SELECT m.product_id, m.location_id, SUM(m.qty) AS qty,
               (SELECT MIN(c.doc_date) FROM documents c JOIN document_lines cl ON cl.document_id = c.id
                WHERE c.kind = 'stock_count' AND c.status = 'active' AND c.doc_date >= d.doc_date
                  AND c.created_at < {_FIRST_IN} AND cl.product_id = m.product_id
                  AND (cl.location_id IS NULL OR cl.location_id = m.location_id)) AS day
        FROM stock_movements m JOIN documents d ON d.id = m.document_id
        WHERE m.document_id = ? AND m.kind = 'delivery_out'
        GROUP BY m.product_id, m.location_id
        """, (doc_id,)).fetchall()
    by_day: dict[str, list] = {}
    for r in rows:
        if r["day"] and r["qty"]:
            by_day.setdefault(r["day"], []).append(r)
    with db.transaction(conn):
        for day, items in sorted(by_day.items()):
            d = date.fromisoformat(day)
            placed = stock_levels(conn, as_of=d, by_location=True)
            counted = {(r["product_id"], r["location_id"]):
                       placed.get((r["product_id"], r["location_id"]), 0.0) - r["qty"] for r in items}
            stock_count(conn, d, counted, f"Giữ số kiểm kê ngày {d:%d/%m/%Y} (đơn {code})")
        _mark_checked(conn, doc_id)


def subtract_too(conn, doc_id: int) -> None:
    """'The goods left after the count': the order stays subtracted, nothing to change."""
    with db.transaction(conn):
        _mark_checked(conn, doc_id)
        db.touch(conn)
