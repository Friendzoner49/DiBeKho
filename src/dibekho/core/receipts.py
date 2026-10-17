"""Goods in (hàng về) entered in the app: where the goods come from, the lines, products that are new.

The user fills one window; saving creates the products that are new, the receipt document and its stock
movements in one transaction, then the receipt is written to an Excel file in output/hang-ve/ (to print or keep).
The file's hash is stored on the document, so dropping that file into input/ later does not count it twice.

A receipt can be edited later: the old document is marked 'replaced' (its movements reversed) and a new one,
with the same code, takes its place. Nothing is deleted.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dibekho import db
from dibekho.core import catalog
from dibekho.core.deliveries import file_hash
from dibekho.core.stock import Line, close_document, insert_document
from dibekho.core.text import clean, unaccent
from dibekho.core.workspace import Workspace

SUPPLIER = "supplier"  # border gate / parent company
RETURN = "return"      # goods a customer sent back
SOURCES = (SUPPLIER, RETURN)
FOLDER = "hang-ve"     # output/hang-ve/
SUGGESTED = 3


@dataclass
class NewProduct:
    name_vi: str
    name_zh: str = ""
    spec: str = ""
    variant: str = ""
    unit: str = ""
    category: str = ""

    def label(self) -> str:
        return " · ".join(x for x in (self.name_vi, self.spec, self.variant) if x)


@dataclass
class ReceiptLineInput:
    qty: float
    product_id: int | None = None
    new: NewProduct | None = None  # a product that is not in the catalog yet, created on save
    note: str = ""


@dataclass
class ReceiptInput:
    doc_date: date
    source: str
    supplier_name: str = ""       # source 'supplier'
    customer_name: str = ""       # source 'return'
    customer_id: int | None = None
    ref_code: str = ""            # source 'return': the order the goods came back from (optional)
    note: str = ""
    lines: list[ReceiptLineInput] = field(default_factory=list)

    def filled(self) -> list[ReceiptLineInput]:
        """Lines that will be recorded: a product (or a new one) and a quantity above 0."""
        return [ln for ln in self.lines if (ln.product_id or ln.new) and ln.qty > 0]


# ---- what the window offers ---------------------------------------------------------------------------------

def supplier_names(conn) -> list[str]:
    """Suppliers used before, the most recent first."""
    return [r[0] for r in conn.execute(
        """
        SELECT s.name FROM suppliers s
        LEFT JOIN documents d ON d.supplier_id = s.id
        GROUP BY s.id ORDER BY MAX(COALESCE(d.created_at, s.created_at)) DESC, s.name
        """)]


def customer_orders(conn, customer_id: int, limit: int = 20) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT code FROM documents WHERE kind = 'delivery' AND status = 'active' AND customer_id = ? "
        "ORDER BY doc_date DESC, id DESC LIMIT ?", (customer_id, limit))]


def suggestions(conn, source: str, supplier_name: str = "", customer_id: int | None = None,
                ref_code: str = "", n: int = SUGGESTED) -> list[int]:
    """Products to put on the first rows (the user changes or clears them).
    Return: the products of that order, else of the customer's last orders.
    Supplier: what usually comes from this supplier, then what usually comes in at all, then what is running out,
    then what went out most lately, so the very first receipt still opens with 3 products."""
    if source == RETURN:
        if not customer_id:
            return []
        sql = ("SELECT l.product_id FROM document_lines l JOIN documents d ON d.id = l.document_id "
               "JOIN products p ON p.id = l.product_id "
               "WHERE d.kind = 'delivery' AND d.status = 'active' AND p.active = 1 AND d.customer_id = ?")
        args: list = [customer_id]
        if ref_code:
            sql += " AND d.code = ?"
            args.append(ref_code)
        rows = conn.execute(sql + " ORDER BY d.doc_date DESC, d.id DESC, l.line_no", args)
        return _first(rows, n)
    base = ("SELECT l.product_id FROM document_lines l JOIN documents d ON d.id = l.document_id "
            "JOIN products p ON p.id = l.product_id "
            "WHERE d.kind = 'receipt' AND d.status = 'active' AND p.active = 1")
    found: list[int] = []
    if supplier_name:
        found = _first(conn.execute(
            base + " AND d.supplier_id IN (SELECT id FROM suppliers WHERE unaccent(name) = ?) "
                   "GROUP BY l.product_id ORDER BY COUNT(*) DESC, MAX(d.doc_date) DESC",
            (unaccent(clean(supplier_name)),)), n)
    for sql in (
        base + " GROUP BY l.product_id ORDER BY COUNT(*) DESC, MAX(d.doc_date) DESC",
        # running out: below 0, or at the 'báo sắp hết' level; the lowest first
        """SELECT p.id FROM products p LEFT JOIN stock_movements m ON m.product_id = p.id WHERE p.active = 1
           GROUP BY p.id
           HAVING COALESCE(SUM(m.qty), 0) < 0 OR (p.min_stock > 0 AND COALESCE(SUM(m.qty), 0) <= p.min_stock)
           ORDER BY COALESCE(SUM(m.qty), 0) - p.min_stock, p.code""",
        # what went out most in the last 90 days
        """SELECT l.product_id FROM document_lines l JOIN documents d ON d.id = l.document_id
           JOIN products p ON p.id = l.product_id
           WHERE d.kind = 'delivery' AND d.status = 'active' AND p.active = 1 AND d.doc_date >= date('now', '-90 days')
           GROUP BY l.product_id ORDER BY SUM(l.qty) DESC""",
    ):
        if len(found) >= n:
            break
        more = _first(conn.execute(sql), n + len(found))
        found += [p for p in more if p not in found][: n - len(found)]
    return found


def _first(rows, n: int) -> list[int]:
    out: list[int] = []
    for r in rows:
        if r[0] not in out:
            out.append(r[0])
        if len(out) == n:
            break
    return out


# ---- checks before saving -----------------------------------------------------------------------------------

def problems(data: ReceiptInput) -> list[str]:
    """Reasons the receipt cannot be saved as it is (keys of i18n texts, with values)."""
    found = []
    if data.source not in SOURCES:
        found.append(("receipt_form.need_source", {}))
    elif data.source == SUPPLIER and not clean(data.supplier_name):
        found.append(("receipt_form.need_supplier", {}))
    elif data.source == RETURN and not (data.customer_id or clean(data.customer_name)):
        found.append(("receipt_form.need_customer", {}))
    lines = data.filled()
    if not lines:
        found.append(("receipt_form.need_lines", {}))
    seen = set()
    for ln in lines:
        if ln.product_id:
            if ln.product_id in seen:
                found.append(("receipt_form.twice", {"id": ln.product_id}))
            seen.add(ln.product_id)
    for ln in lines:
        if ln.new and not clean(ln.new.name_vi):
            found.append(("receipt_form.new_needs_name", {}))
    return found


def same_as_existing(conn, data: ReceiptInput) -> list[tuple[ReceiptLineInput, object]]:
    """New products that are already in the catalog (same name, packing and type): the user should pick those."""
    out = []
    for ln in data.filled():
        if ln.new:
            row = catalog.find_same(conn, ln.new.name_vi, ln.new.spec, ln.new.variant)
            if row is not None:
                out.append((ln, row))
    return out


# ---- saving -------------------------------------------------------------------------------------------------

def next_code(conn, ws: Workspace | None = None) -> str:
    """HV001, HV002… Files already in output/hang-ve/ count too: after an Undo the database forgets a receipt
    but its file stays, and a new receipt must not get the code of that file."""
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(code, 3) AS INTEGER)) FROM documents WHERE kind = 'receipt' AND code GLOB 'HV[0-9]*'"
    ).fetchone()
    highest = row[0] or 0
    if ws is not None and (ws.output / FOLDER).exists():
        for f in (ws.output / FOLDER).glob("HangVe_HV*_*.xlsx"):
            m = re.match(r"HangVe_HV(\d+)_", f.name)
            if m:
                highest = max(highest, int(m.group(1)))
    return f"HV{highest + 1:03d}"


def _supplier_id(conn, name: str) -> int:
    name = clean(name)
    row = conn.execute("SELECT id FROM suppliers WHERE unaccent(name) = ?", (unaccent(name),)).fetchone()
    if row:
        return row[0]
    return conn.execute("INSERT INTO suppliers(name) VALUES(?)", (name,)).lastrowid


def save(conn, data: ReceiptInput, replaces: int | None = None, ws: Workspace | None = None) -> int:
    """Create the new products and the receipt in one transaction. replaces: the receipt being edited
    (marked 'replaced', the new one keeps its code). Returns the new document id."""
    if problems(data):
        raise ValueError("Phiếu hàng về chưa đủ thông tin.")
    with db.transaction(conn):
        code = next_code(conn, ws)
        if replaces:
            old = conn.execute("SELECT code FROM documents WHERE id = ?", (replaces,)).fetchone()
            close_document(conn, replaces, "replaced")
            code = old["code"] or code
        supplier_id, customer_id = None, None
        if data.source == SUPPLIER:
            supplier_id = _supplier_id(conn, data.supplier_name)
        else:
            customer_id = data.customer_id or catalog.upsert_customer(conn, data.customer_name)
        lines = []
        for ln in data.filled():
            product_id = ln.product_id
            if ln.new:
                n = ln.new
                product_id = catalog.create_product(conn, n.name_vi, n.name_zh, n.spec, unit=n.unit,
                                                    category=n.category, variant=n.variant)
            lines.append(Line(product_id, ln.qty, note=clean(ln.note)))
        doc_id = insert_document(conn, "receipt", data.doc_date, lines, code=code, code_norm=code,
                                 customer_id=customer_id, note=clean(data.note))
        conn.execute("UPDATE documents SET receipt_source = ?, supplier_id = ?, ref_code = ? WHERE id = ?",
                     (data.source, supplier_id, clean(data.ref_code) if data.source == RETURN else "", doc_id))
        db.log(conn, "receipt_edited" if replaces else "receipt_entered", f"{code} #{doc_id}")
    return doc_id


def load(conn, doc_id: int) -> ReceiptInput:
    """A saved receipt as the window shows it, to edit."""
    d = conn.execute(
        "SELECT d.*, s.name AS supplier_name, c.name AS customer_name FROM documents d "
        "LEFT JOIN suppliers s ON s.id = d.supplier_id LEFT JOIN customers c ON c.id = d.customer_id WHERE d.id = ?",
        (doc_id,)).fetchone()
    lines = [ReceiptLineInput(r["qty"], r["product_id"], note=r["note"]) for r in conn.execute(
        "SELECT * FROM document_lines WHERE document_id = ? ORDER BY line_no", (doc_id,))]
    return ReceiptInput(date.fromisoformat(d["doc_date"]), d["receipt_source"] or SUPPLIER,
                        supplier_name=d["supplier_name"] or "", customer_name=d["customer_name"] or "",
                        customer_id=d["customer_id"], ref_code=d["ref_code"], note=d["note"], lines=lines)


def export_file(conn, ws: Workspace, doc_id: int) -> Path:
    """Write the receipt to output/hang-ve/ and remember the file on the document."""
    from dibekho.excel.receipt import write_receipt

    head = conn.execute(
        "SELECT d.*, s.name AS supplier_name, c.name AS customer_name FROM documents d "
        "LEFT JOIN suppliers s ON s.id = d.supplier_id LEFT JOIN customers c ON c.id = d.customer_id WHERE d.id = ?",
        (doc_id,)).fetchone()
    lines = conn.execute(
        "SELECT l.qty, l.note, p.code, p.name_vi, p.name_zh, p.spec, p.unit, p.variant FROM document_lines l "
        "JOIN products p ON p.id = l.product_id WHERE l.document_id = ? ORDER BY l.line_no", (doc_id,)).fetchall()
    folder = ws.output / FOLDER
    base = f"HangVe_{head['code']}_{head['doc_date']}"
    path = folder / f"{base}.xlsx"
    n = 2
    while path.exists():
        path = folder / f"{base}_{n}.xlsx"
        n += 1
    write_receipt(path, head, lines)
    with db.transaction(conn):
        conn.execute("UPDATE documents SET source_file = ?, source_hash = ? WHERE id = ?",
                     (path.name, file_hash(path), doc_id))
    return path


def exported_file(ws: Workspace, name: str) -> Path | None:
    p = ws.output / FOLDER / name
    return p if name and p.exists() else None
