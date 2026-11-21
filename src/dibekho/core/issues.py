"""Phiếu xuất kho: the user picks a customer and the goods, says how many come from Kho tổng and how many from
Văn phòng, and the app writes a stock issue note (excel/issue_note.py) and records it at once, through the very
path a delivery note dropped into phieu-giao-hang/ takes. So the note is an ordinary delivery: it lowers the
stock of each place, its prices count in the customer's revenue, it can be cancelled or read again, and the file
put back into the folder later is recognised (same content) and never counted twice.

Files:
- output/phieu-xuat/PhieuXuat_<code>.xlsx: the copy for the user (print, send);
- phieu-giao-hang/da-xu-ly/PhieuXuat_<code>.xlsx: the copy the scan sees, so 'Đặt lại tồn kho' and a data
  package read it again like the other notes.
A wrong note is deleted (delete(), from the order's window: Huỷ phiếu → Xoá hẳn) and typed again.

A draft order (customer's request 21/11/2026, «Lưu nháp»): the same file with NHÁP in the title and its own code
(N1, N2…), in output/phieu-xuat/nhap/. Nothing is recorded: no stock, no revenue, no new product. «Xuất từ phiếu
nháp…» reads the file back into the form; once saved as a real note the draft moves to output/phieu-xuat/nhap/da-chot/.

A line may be a product not in the catalog yet (★ Mặt hàng mới, customer's request 15/11/2026): it is created on
save, its stock goes below zero, and the next Hàng về of that product (picked from the catalog) brings it back.

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
from dibekho.core import catalog
from dibekho.core.receipts import NewProduct
from dibekho.core.stock import MAIN, OFFICE, stock_levels
from dibekho.core.text import clean, unaccent
from dibekho.core.workspace import Workspace
from dibekho.excel.issue_note import IssueHead, IssueRow, is_draft_title, write_issue_note

PREFIX = "A"  # made in the app; "W" on the web page
_NUMBERED = re.compile(r"^\s*[AaWw]?\s*0*(\d{1,9})\s*$")  # an order number, maybe with the app's or the web's letter
FILE_PREFIX = "PhieuXuat_"
FOLDER = "phieu-xuat"
DELETED = "da-xoa"
EDITED = "da-sua"
_ISSUE_CODE = re.compile(r"^\s*[AaWw]\d+\s*$")
DRAFTS = "nhap"  # output/phieu-xuat/nhap/
DRAFTS_DONE = "da-chot"
DRAFT_PREFIX = "N"
DRAFT_FILE_PREFIX = "PhieuXuat_NHAP_"
_DRAFT_FILE = re.compile(r"^PhieuXuat_NHAP_N(\d+)", re.IGNORECASE)


@dataclass
class IssueLineInput:
    product_id: int | None
    qty_main: float = 0.0
    qty_office: float = 0.0
    unit_price: float | None = None
    note: str = ""
    new: NewProduct | None = None  # not in the catalog yet: created on save (product_id stays None)

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
    tax_code: str = ""
    email: str = ""
    lines: list[IssueLineInput] = field(default_factory=list)
    # "CNY": the prices are yuan, as typed while the ₫ | ¥ switch shows yuan (user, 21/11/2026); the note is written
    # and recorded in yuan. fx_rate: dong for one yuan the window used, kept on the document (only to show '≈ … ₫').
    currency: str = "VND"
    fx_rate: float | None = None

    def filled(self) -> list[IssueLineInput]:
        return [ln for ln in self.lines if (ln.product_id or ln.new) and ln.qty > 0]


def new_key(n: NewProduct) -> tuple:
    """Two rows with the same new product (another price) make one product, not two."""
    return tuple(unaccent(clean(x)).replace(" ", "") for x in (n.name_vi, n.spec, n.variant))


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
    for ln in data.filled():
        if ln.new and not clean(ln.new.name_vi):
            found.append(("receipt_form.new_needs_name", {}))
        elif (ln.qty_main or 0) < 0 or (ln.qty_office or 0) < 0 or (ln.unit_price or 0) < 0:
            found.append(("issue.negative", {"product": ln.new.label()} if ln.new else {"id": ln.product_id}))
    return found


def same_as_existing(conn, data: IssueInput) -> list[tuple[IssueLineInput, object]]:
    """New products that may already be in the catalog: the user should pick those instead (catalog 9.13), else
    the next Hàng về goes to the existing product and the new one stays below zero."""
    out, seen = [], set()
    for ln in data.filled():
        if ln.new and new_key(ln.new) not in seen:
            seen.add(new_key(ln.new))
            found = catalog.find_possible_duplicates(conn, ln.new.name_vi, ln.new.name_zh, ln.new.spec,
                                                     ln.new.variant)
            if found:
                out.append((ln, found[0]))
    return out


def short_of(conn, data: IssueInput, old: IssueInput | None = None) -> list[tuple[int, int, float, float]]:
    """Products asked for more than a place has now: (product_id, location_id, asked, in stock); the lines of one
    product count together (it may stand on several lines, each with its price). Only a warning: stock may go
    below zero (the app never blocks it, the row turns red). old: the note being replaced, its goods count as free."""
    levels = stock_levels(conn, by_location=True)
    for ln in (old.filled() if old else []):
        for loc, qty in ((MAIN, ln.qty_main), (OFFICE, ln.qty_office)):
            levels[(ln.product_id, loc)] = levels.get((ln.product_id, loc), 0.0) + qty
    asked: dict[tuple[int, int], float] = {}
    for ln in data.filled():
        if not ln.product_id:
            continue  # a new product has nothing in stock: it goes below zero, the user knows
        for loc, qty in ((MAIN, ln.qty_main), (OFFICE, ln.qty_office)):
            if qty:
                asked[(ln.product_id, loc)] = asked.get((ln.product_id, loc), 0.0) + qty
    return [(pid, loc, qty, levels.get((pid, loc), 0.0)) for (pid, loc), qty in asked.items()
            if qty > levels.get((pid, loc), 0.0)]


def last_price(conn, customer_name: str, product_id: int | None, currency: str = "VND",
               vnd_per_cny: float | None = None) -> float | None:
    """The price of this product on the customer's latest order with a price, else on anyone's latest order, in
    `currency`: a price of a note in the other currency is turned at vnd_per_cny (else the note's own rate); yuan
    to two decimals, dong whole. None when it cannot be turned."""
    if not product_id:
        return None
    base = ("SELECT l.unit_price, d.currency, d.fx_rate FROM document_lines l JOIN documents d ON d.id = l.document_id "
            "LEFT JOIN customers c ON c.id = d.customer_id "
            "WHERE d.kind = 'delivery' AND d.status = 'active' AND l.product_id = ? AND l.unit_price IS NOT NULL")
    order = " ORDER BY d.doc_date DESC, d.id DESC, l.line_no LIMIT 1"
    if clean(customer_name):
        row = conn.execute(base + " AND c.name = ?" + order, (product_id, clean(customer_name))).fetchone()
        if row:
            return _in_currency(row, currency, vnd_per_cny)
    row = conn.execute(base + order, (product_id,)).fetchone()
    return _in_currency(row, currency, vnd_per_cny) if row else None


def _in_currency(row, currency: str, vnd_per_cny: float | None) -> float | None:
    price, own = row[0], ("CNY" if row[1] == "CNY" else "VND")
    if own == currency:
        return price
    rate = vnd_per_cny or row[2]
    if not rate:
        return None
    return round(price / rate, 2) if currency == "CNY" else float(round(price * rate))


def note_rows(conn, data: IssueInput) -> list[IssueRow]:
    """The table of the file: one row per line typed, like a delivery note (a product may come twice, at two
    prices); where it is taken from (Kho tổng and/or Văn phòng) goes in the hidden 'Lấy từ kho' column."""
    rows = []
    for ln in data.filled():
        places = [(loc, qty) for loc, qty in ((MAIN, ln.qty_main), (OFFICE, ln.qty_office)) if qty and qty > 0]
        amount = None if ln.unit_price is None else round(ln.qty * ln.unit_price, 2)
        if ln.product_id is None and ln.new:  # only on a draft: a real note creates its new products first
            n = ln.new
            rows.append(IssueRow("", " ".join(x for x in (clean(n.name_vi), clean(n.variant)) if x), clean(n.name_zh),
                                 clean(n.spec), ln.qty, places, ln.unit_price, amount, clean(ln.note)))
            continue
        p = conn.execute("SELECT * FROM products WHERE id = ?", (ln.product_id,)).fetchone()
        name_vi = " ".join(x for x in (p["name_vi"], p["variant"]) if x)
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
    if problems(conn, data):
        raise ValueError("Phiếu xuất kho chưa đủ thông tin.")
    created = _create_new_products(conn, data)
    try:
        return _save(conn, ws, data)
    except BaseException:
        # the note was not recorded: the products made for it go too (they are in no document)
        with db.transaction(conn):
            for pid in created:
                catalog.delete_product(conn, pid)
        raise


def _create_new_products(conn, data: IssueInput) -> list[int]:
    """Create the ★ new products of the note (one per name + packing + type) and put their ids on the lines."""
    made: dict[tuple, int] = {}
    with db.transaction(conn):
        for ln in data.filled():
            if ln.new and not ln.product_id:
                key = new_key(ln.new)
                if key not in made:
                    n = ln.new
                    made[key] = catalog.create_product(conn, n.name_vi, n.name_zh, n.spec, unit=n.unit,
                                                       category=n.category, variant=n.variant)
                ln.product_id = made[key]
    return list(made.values())


def _save(conn, ws: Workspace, data: IssueInput, code: str | None = None) -> tuple[int, Path]:
    from dibekho.core import deliveries

    code = code or new_code(conn)
    cny = data.currency == "CNY"
    head = IssueHead(code, data.doc_date, clean(data.customer_name), clean(data.phone), clean(data.contact),
                     clean(data.address), clean(data.tax_code), clean(data.email), deliveries.letterhead(conn),
                     currency="CNY" if cny else "VND")
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
    if cny and data.fx_rate:  # the rate the user saw, not the one of the moment the file was read
        conn.execute("UPDATE documents SET fx_rate = ? WHERE id = ?", (data.fx_rate, row["document_id"]))
    db.log(conn, "issue_note", f"{code} ({len(data.filled())} mặt hàng)")
    return row["document_id"], user_copy


# ---- draft orders

def drafts_folder(ws: Workspace) -> Path:
    return ws.output / FOLDER / DRAFTS


def new_draft_code(ws: Workspace) -> str:
    """N + 1 + the highest draft number in the drafts folder and its da-chot/ (a number is never reused)."""
    folder = drafts_folder(ws)
    files = list(folder.glob("*.xlsx")) + list((folder / DRAFTS_DONE).glob("*.xlsx"))
    numbers = [int(m.group(1)) for m in (_DRAFT_FILE.match(p.name) for p in files) if m]
    return f"{DRAFT_PREFIX}{max(numbers, default=0) + 1}"


def save_draft(conn, ws: Workspace, data: IssueInput, path: Path | None = None) -> Path:
    """Write the draft file (a new one, or over `path`: the draft opened again keeps its code). Nothing is recorded.
    Raises ValueError on a problem, OSError when the file is open in Excel."""
    from dibekho.core import deliveries

    if problems(conn, data):
        raise ValueError("Đơn nháp chưa đủ thông tin.")
    m = _DRAFT_FILE.match(path.name) if path else None
    code = f"{DRAFT_PREFIX}{m.group(1)}" if m else new_draft_code(ws)
    head = IssueHead(code, data.doc_date, clean(data.customer_name), clean(data.phone), clean(data.contact),
                     clean(data.address), clean(data.tax_code), clean(data.email), deliveries.letterhead(conn),
                     currency="CNY" if data.currency == "CNY" else "VND", draft=True)
    target = path or _free(drafts_folder(ws) / f"{DRAFT_FILE_PREFIX}{code}.xlsx")
    return write_issue_note(target, head, note_rows(conn, data))


def load_draft(conn, path: Path) -> tuple[str, IssueInput]:
    """(draft code, what it holds) read back from a draft file: a product by its code in the catalog, else a ★ new
    product with the name and packing of the file. Raises ValueError when the file is not a draft order."""
    from dibekho.excel.delivery_note import DeliveryNoteError, NotDeliveryNote, read_delivery_note

    try:
        note = read_delivery_note(path)
    except (NotDeliveryNote, DeliveryNoteError, OSError) as exc:
        raise ValueError(str(exc)) from exc
    if not is_draft_title(note.title):
        raise ValueError("File này không phải đơn nháp của DiBeKho.")
    lines = []
    for ln in note.lines:
        main = sum(q for loc, q in ln.places if loc == MAIN) if ln.places else ln.qty
        office = sum(q for loc, q in ln.places if loc == OFFICE) if ln.places else 0.0
        code = clean(ln.product_code)
        p = conn.execute("SELECT id FROM products WHERE code = ?", (code,)).fetchone() if code else None
        if p:
            lines.append(IssueLineInput(p["id"], main, office, ln.unit_price, ln.note))
        else:
            lines.append(IssueLineInput(None, main, office, ln.unit_price, ln.note,
                                        new=NewProduct(clean(ln.name_vi or ln.raw_name), clean(ln.name_zh), clean(ln.spec))))
    return note.code, IssueInput(note.doc_date, note.customer_name, note.phone, note.contact, note.address,
                                 note.tax_code, note.email, lines, currency="CNY" if note.currency == "CNY" else "VND")


def close_draft(ws: Workspace, path: Path) -> Path | None:
    """The draft became a real note: its file goes to da-chot/ (kept, never counted)."""
    if not path.exists():
        return None
    target = _free(drafts_folder(ws) / DRAFTS_DONE / path.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(target))
    return target


def is_issue_code(code) -> bool:
    """A160 (made in the app) or W160 (made on the web): a stock issue note, which may be deleted."""
    return bool(_ISSUE_CODE.match(str(code or "")))


def _check_issue(conn, doc_id: int):
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None or doc["kind"] != "delivery" or not is_issue_code(doc["code"]):
        raise ValueError("Chỉ xoá được phiếu xuất kho (mã A… hoặc W…).")
    return doc


def _remove_rows(conn, doc) -> set[str]:
    """Delete the document, its earlier versions (same code), their lines, movements and scan records.
    Returns the hashes of their files."""
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
    return hashes


def _move_files(ws: Workspace, hashes: set[str], folder: str) -> list[tuple[Path, Path]]:
    """Move the files of these hashes out of the notes folder and output/phieu-xuat/ into output/phieu-xuat/<folder>/,
    otherwise the next scan would record them again. Returns [(from, to)] of what moved."""
    from dibekho.core import deliveries

    moved = []
    for path in deliveries.delivery_files(ws) + sorted((ws.output / FOLDER).glob("*.xlsx")):
        try:
            if deliveries.file_hash(path) not in hashes:
                continue
            target = _free(ws.output / FOLDER / folder / path.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            path.replace(target)
        except OSError:
            continue  # open in Excel: the user is told by the scan (it is read again)
        moved.append((path, target))
    return moved


def delete(conn, ws: Workspace, doc_id: int) -> int:
    """Delete a stock issue note entirely (user's request 14/11/2026: the shop counts its revenue by these numbers, a
    wrong note must leave no hole): the document and its earlier versions (same code, edited in Excel), their lines and
    stock movements, so the stock is as if it never was; its number is free again (new_code). Its files leave the
    notes folder and output/phieu-xuat/ for output/phieu-xuat/da-xoa/, otherwise the next scan would record it
    again; the stored copy in data/phieu-goc/ stays. On shared data the deletes
    go to the cloud like any change. Run inside a transaction. Returns how many files were moved."""
    doc = _check_issue(conn, doc_id)
    hashes = _remove_rows(conn, doc)
    db.log(conn, "issue_deleted", f"{doc['code']} #{doc_id}")
    return len(_move_files(ws, hashes, DELETED))


def can_edit(doc) -> bool:
    """An active stock issue note made by this system (A... in the app, W... on the web): customer's request 19/11/2026.
    The shop's own notes (numbers like 160) stay as their Excel file says; they are read again from the file."""
    return bool(doc["kind"] == "delivery" and doc["status"] == "active" and is_issue_code(doc["code"]))


def load(conn, doc_id: int) -> tuple[str, IssueInput]:
    """A recorded issue note as the form shows it, to edit: (code, data). The split between the two places comes from
    the stock movements (a line taken from both places has no place of its own)."""
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None or not can_edit(doc):
        raise ValueError("Chỉ sửa được phiếu xuất kho còn hiệu lực (mã A… hoặc W…).")
    c = conn.execute("SELECT * FROM customers WHERE id = ?", (doc["customer_id"],)).fetchone() \
        if doc["customer_id"] else None
    pool: dict[tuple[int, int], float] = {}
    for r in conn.execute("SELECT product_id, location_id, SUM(-qty) AS q FROM stock_movements "
                          "WHERE document_id = ? GROUP BY product_id, location_id", (doc_id,)):
        pool[(r["product_id"], r["location_id"])] = r["q"]
    rows = conn.execute("SELECT * FROM document_lines WHERE document_id = ? AND product_id IS NOT NULL ORDER BY line_no",
                        (doc_id,)).fetchall()
    taken: dict[int, dict[int, float]] = {}
    for r in rows:  # lines with a place of their own first: the split ones share what is left
        if r["location_id"] is not None:
            key = (r["product_id"], r["location_id"])
            pool[key] = pool.get(key, 0.0) - r["qty"]
            taken[r["id"]] = {r["location_id"]: r["qty"]}
    out: list[IssueLineInput] = []
    for r in rows:
        if r["id"] not in taken:
            split, left = {}, r["qty"]
            for loc in (MAIN, OFFICE):
                part = min(left, max(pool.get((r["product_id"], loc), 0.0), 0.0))
                if part:
                    split[loc] = part
                    pool[(r["product_id"], loc)] -= part
                    left -= part
            if left > 0:  # no movement to read it from: the document's place
                where = doc["location_id"] or MAIN
                split[where] = split.get(where, 0.0) + left
            taken[r["id"]] = split
        out.append(IssueLineInput(r["product_id"], taken[r["id"]].get(MAIN, 0.0), taken[r["id"]].get(OFFICE, 0.0),
                                  r["unit_price"], r["note"] or ""))
    data = IssueInput(date.fromisoformat(doc["doc_date"]), c["name"] if c else "",
                      phone=(c["phone"] if c else "") or "", contact=(c["contact"] if c else "") or "",
                      address=(c["address"] if c else "") or "", tax_code=(c["tax_code"] if c else "") or "",
                      email=(c["email"] if c else "") or "", lines=out,
                      currency="CNY" if doc["currency"] == "CNY" else "VND", fx_rate=doc["fx_rate"])
    return doc["code"], data


def edit(conn, ws: Workspace, doc_id: int, data: IssueInput) -> tuple[int, Path]:
    """Replace a recorded issue note by the corrected one, with the same code (customer's request 19/11/2026: prices,
    quantities... of a note already issued). The old note goes as in delete() but its files to output/phieu-xuat/da-sua/
    (the old version can still be looked at); the new one is written and recorded as in save(). One transaction: on
    any failure the old note stays as it was, files included. Returns (document id, the user's copy)."""
    doc = _check_issue(conn, doc_id)
    if not can_edit(doc):
        raise ValueError("Chỉ sửa được phiếu xuất kho còn hiệu lực (mã A… hoặc W…).")
    if problems(conn, data):
        raise ValueError("Phiếu xuất kho chưa đủ thông tin.")
    created = _create_new_products(conn, data)
    moved: list[tuple[Path, Path]] = []
    try:
        with db.transaction(conn):
            hashes = _remove_rows(conn, doc)
            moved = _move_files(ws, hashes, EDITED)
            result = _save(conn, ws, data, doc["code"])
            db.log(conn, "issue_edited", f"{doc['code']} #{result[0]}")
    except BaseException:
        for src, target in moved:  # the old note is back as it was
            try:
                src.parent.mkdir(parents=True, exist_ok=True)
                target.replace(src)
            except OSError:
                pass
        with db.transaction(conn):
            for pid in created:
                catalog.delete_product(conn, pid)
        raise
    return result


def customer_choices(conn) -> list:
    return conn.execute("SELECT id, name, phone, contact, address, tax_code, email FROM customers ORDER BY name").fetchall()
