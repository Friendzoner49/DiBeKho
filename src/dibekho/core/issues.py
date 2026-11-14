"""Phiếu xuất kho: the user picks a customer and the goods, says how many come from Kho tổng and how many from
Văn phòng, and the app writes a stock issue note (excel/issue_note.py) and records it at once, through the very
path a delivery note dropped into phieu-giao-hang/ takes. So the note is an ordinary delivery: it lowers the
stock of each place, its prices count in the customer's revenue, it can be cancelled or read again, and the file
put back into the folder later is recognised (same content) and never counted twice.

Files:
- output/phieu-xuat/PhieuXuat_<code>.xlsx: the copy for the user (print, send);
- phieu-giao-hang/da-xu-ly/PhieuXuat_<code>.xlsx: the copy the scan sees, so 'Đặt lại tồn kho' and a data
  package read it again like the other notes.
Hoàn tác (local data) puts the database back, then after_undo() moves that second copy out of the folder,
otherwise the next scan would record the note again.

Codes (user's choice 14/11/2026): A + the number after the highest order number so far (orders up to 159 -> A160);
the web page writes W160 (webapp/xlsx.js nextCode), so the app and the web never take the same code. The shop's own
notes (160) stay apart too: '160' and 'A160' are different codes (text.normalize_code keeps the letter).
"""

import re
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dibekho import db
from dibekho.core.stock import MAIN, OFFICE, stock_levels
from dibekho.core.text import clean
from dibekho.core.workspace import Workspace
from dibekho.excel.issue_note import IssueHead, IssueRow, write_issue_note

PREFIX = "A"  # made in the app; "W" on the web page
_NUMBERED = re.compile(r"^\s*[AaWw]?\s*0*(\d{1,9})\s*$")  # an order number, maybe with the app's or the web's letter
FILE_PREFIX = "PhieuXuat_"
FOLDER = "phieu-xuat"
UNDONE = "da-hoan-tac"
DELETED = "da-xoa"
_ISSUE_CODE = re.compile(r"^\s*[AaWw]\d+\s*$")


@dataclass
class IssueLineInput:
    product_id: int | None
    qty_main: float = 0.0
    qty_office: float = 0.0
    unit_price: float | None = None
    note: str = ""

    @property
    def qty(self) -> float:
        return (self.qty_main or 0) + (self.qty_office or 0)


@dataclass
class IssueInput:
    doc_date: date
    customer_name: str
    phone: str = ""
    contact: str = ""
    address: str = ""
    lines: list[IssueLineInput] = field(default_factory=list)

    def filled(self) -> list[IssueLineInput]:
        return [ln for ln in self.lines if ln.product_id and ln.qty > 0]


def next_code(codes, prefix: str = PREFIX) -> str:
    """prefix + 1 + the highest order number among codes ('159', '076', 'A160', 'W161'); other codes are not counted.
    The same rule as webapp/xlsx.js nextCode."""
    numbers = [int(m.group(1)) for m in (_NUMBERED.match(str(c or "")) for c in codes) if m]
    return f"{prefix}{max(numbers, default=0) + 1}"


def new_code(conn) -> str:
    """The code of a new issue note: every delivery ever recorded counts, cancelled ones too (a number is never reused)."""
    return next_code([r[0] for r in conn.execute("SELECT code FROM documents WHERE kind = 'delivery'")])


def problems(conn, data: IssueInput) -> list[tuple[str, dict]]:
    """What stops the note from being saved: (i18n key, values)."""
    found: list[tuple[str, dict]] = []
    if not clean(data.customer_name):
        found.append(("issue.need_customer", {}))
    if not data.filled():
        found.append(("issue.need_lines", {}))
    seen: set[int] = set()
    for ln in data.filled():
        if ln.product_id in seen:
            found.append(("issue.same_product_twice", {"id": ln.product_id}))
        seen.add(ln.product_id)
        if (ln.qty_main or 0) < 0 or (ln.qty_office or 0) < 0 or (ln.unit_price or 0) < 0:
            found.append(("issue.negative", {"id": ln.product_id}))
    return found


def short_of(conn, data: IssueInput) -> list[tuple[int, int, float, float]]:
    """Lines asking for more than a place has now: (product_id, location_id, asked, in stock). Only a warning:
    stock may go below zero (the app never blocks it, the row turns red)."""
    levels = stock_levels(conn, by_location=True)
    result = []
    for ln in data.filled():
        for loc, qty in ((MAIN, ln.qty_main), (OFFICE, ln.qty_office)):
            have = levels.get((ln.product_id, loc), 0.0)
            if qty and qty > have:
                result.append((ln.product_id, loc, qty, have))
    return result


def last_price(conn, customer_name: str, product_id: int | None) -> float | None:
    """The price of this product on the customer's latest order with a price, else on anyone's latest order."""
    if not product_id:
        return None
    base = ("SELECT l.unit_price FROM document_lines l JOIN documents d ON d.id = l.document_id "
            "LEFT JOIN customers c ON c.id = d.customer_id "
            "WHERE d.kind = 'delivery' AND d.status = 'active' AND l.product_id = ? AND l.unit_price IS NOT NULL")
    order = " ORDER BY d.doc_date DESC, d.id DESC, l.line_no LIMIT 1"
    if clean(customer_name):
        row = conn.execute(base + " AND c.name = ?" + order, (product_id, clean(customer_name))).fetchone()
        if row:
            return row[0]
    row = conn.execute(base + order, (product_id,)).fetchone()
    return row[0] if row else None


def note_rows(conn, data: IssueInput) -> list[IssueRow]:
    """The table of the file: one row per product, like a delivery note; where it is taken from (Kho tổng and/or
    Văn phòng) goes in the hidden 'Lấy từ kho' column."""
    rows = []
    for ln in data.filled():
        p = conn.execute("SELECT * FROM products WHERE id = ?", (ln.product_id,)).fetchone()
        name_vi = " ".join(x for x in (p["name_vi"], p["variant"]) if x)
        places = [(loc, qty) for loc, qty in ((MAIN, ln.qty_main), (OFFICE, ln.qty_office)) if qty and qty > 0]
        amount = None if ln.unit_price is None else round(ln.qty * ln.unit_price, 2)
        rows.append(IssueRow(p["code"], name_vi, p["name_zh"] or "", p["spec"] or "", ln.qty, places,
                             ln.unit_price, amount, clean(ln.note)))
    return rows


def _free(path: Path) -> Path:
    n = 2
    candidate = path
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        n += 1
    return candidate


def save(conn, ws: Workspace, data: IssueInput) -> tuple[int, Path]:
    """Write the note and record it. Returns (document id, the user's copy). Raises ValueError on a problem."""
    from dibekho.core import deliveries  # imported here: deliveries -> receipts -> ... must not loop back

    if problems(conn, data):
        raise ValueError("Phiếu xuất kho chưa đủ thông tin.")
    code = new_code(conn)
    head = IssueHead(code, data.doc_date, clean(data.customer_name), clean(data.phone), clean(data.contact),
                     clean(data.address), deliveries.letterhead(conn))
    user_copy = _free(ws.output / FOLDER / f"{FILE_PREFIX}{code}.xlsx")
    write_issue_note(user_copy, head, note_rows(conn, data))
    ws.deliveries_done.mkdir(parents=True, exist_ok=True)
    scanned = _free(ws.deliveries_done / user_copy.name)
    shutil.copy2(user_copy, scanned)
    rel = scanned.relative_to(ws.deliveries).as_posix()
    h = deliveries.file_hash(scanned)
    deliveries.process_file(conn, ws, scanned, rel, h)
    row = conn.execute("SELECT document_id, status, message FROM scanned_files WHERE hash = ?", (h,)).fetchone()
    if row is None or row["status"] != "imported" or not row["document_id"]:
        scanned.unlink(missing_ok=True)  # not recorded: the scan must not find it either
        raise ValueError(row["message"] if row and row["message"] else "Không ghi được phiếu xuất kho.")
    db.log(conn, "issue_note", f"{code} ({len(data.filled())} mặt hàng)")
    return row["document_id"], user_copy


def known_issue_files(conn, ws: Workspace) -> dict:
    """Issue notes in the delivery folders that the data knows: {path: hash}. Taken just before Hoàn tác."""
    from dibekho.core import deliveries

    result = {}
    for path in deliveries.delivery_files(ws):
        if not path.name.startswith(FILE_PREFIX):
            continue
        try:
            h = deliveries.file_hash(path)
        except OSError:
            continue
        if conn.execute("SELECT 1 FROM scanned_files WHERE hash = ?", (h,)).fetchone():
            result[path] = h
    return result


def after_undo(conn, ws: Workspace, before: dict) -> int:
    """After Hoàn tác: issue notes the data no longer knows (the undone action recorded them) leave the delivery
    folder for output/phieu-xuat/da-hoan-tac/, so the next scan does not record them again. Returns how many."""
    moved = 0
    for path, h in before.items():
        if conn.execute("SELECT 1 FROM scanned_files WHERE hash = ?", (h,)).fetchone() or not path.exists():
            continue
        target = _free(ws.output / FOLDER / UNDONE / path.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.replace(target)
        except OSError:
            continue
        moved += 1
    return moved


def is_issue_code(code) -> bool:
    """A160 (made in the app) or W160 (made on the web): a stock issue note, which may be deleted."""
    return bool(_ISSUE_CODE.match(str(code or "")))


def delete(conn, ws: Workspace, doc_id: int) -> int:
    """Delete a stock issue note entirely (user's request 14/11/2026: the shop counts its revenue by these numbers, a
    wrong note must leave no hole): the document and its earlier versions (same code, edited in Excel), their lines and
    stock movements, so the stock is as if it never was; its number is free again (new_code). Its files leave the
    notes folder and output/phieu-xuat/ for output/phieu-xuat/da-xoa/, otherwise the next scan would record it
    again; the stored copy in data/phieu-goc/ stays, so Hoàn tác can bring the file back. On shared data the deletes
    go to the cloud like any change. Run inside a transaction. Returns how many files were moved."""
    from dibekho.core import deliveries

    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None or doc["kind"] != "delivery" or not is_issue_code(doc["code"]):
        raise ValueError("Chỉ xoá được phiếu xuất kho (mã A… hoặc W…).")
    ids = [r[0] for r in conn.execute("SELECT id FROM documents WHERE kind = 'delivery' AND code_norm = ?",
                                      (doc["code_norm"],))]
    hashes = {r[0] for i in ids for r in conn.execute(
        "SELECT hash FROM scanned_files WHERE document_id = ?", (i,))} | \
        {r[0] for i in ids for r in conn.execute("SELECT source_hash FROM documents WHERE id = ? AND source_hash <> ''",
                                                 (i,))}
    for i in ids:
        for table in ("stock_movements", "document_lines", "document_skipped_lines"):
            conn.execute(f"DELETE FROM {table} WHERE document_id = ?", (i,))
        conn.execute("DELETE FROM scanned_files WHERE document_id = ?", (i,))
        conn.execute("DELETE FROM documents WHERE id = ?", (i,))
    for h in hashes:
        conn.execute("DELETE FROM scanned_files WHERE hash = ?", (h,))
    db.touch(conn)
    db.log(conn, "issue_deleted", f"{doc['code']} #{doc_id}")
    files = [p for p in deliveries.delivery_files(ws) + sorted((ws.output / FOLDER).glob("*.xlsx"))]
    moved = 0
    for path in files:
        try:
            if deliveries.file_hash(path) not in hashes:
                continue
            target = _free(ws.output / FOLDER / DELETED / path.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            path.replace(target)
        except OSError:
            continue  # open in Excel: the user is told by the scan (it is read again), Hoàn tác is there
        moved += 1
    return moved


def customer_choices(conn) -> list:
    return conn.execute("SELECT id, name, phone, contact, address FROM customers ORDER BY name").fetchall()
