"""Stock ledger: every change is a stock_movements row, current stock = SUM(qty).

Every movement has a place (location_id): Kho tổng or Văn phòng. Stock of a place = SUM(qty) of its movements;
the total ignores places. A transfer moves goods between the two (net zero per product).

All functions that write expect to be called inside `db.transaction(conn)`.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from dibekho import db

# document kind -> (movement kind, sign applied to line qty)
_FORWARD = {
    "delivery": ("delivery_out", -1),
    "receipt": ("receipt_in", +1),
}
_REVERSE = {
    "delivery": "delivery_reverse",
    "receipt": "receipt_reverse",
    "stock_count": "count_reverse",
    "transfer": "transfer_reverse",
    "trial": "trial_reverse",
}

MAIN, OFFICE = 1, 2  # locations table; names through i18n loc.main / loc.office
LOCATIONS = (MAIN, OFFICE)
LOCATION_CODES = {MAIN: "main", OFFICE: "office"}


@dataclass
class Line:
    product_id: int
    qty: float
    raw_name: str = ""
    raw_spec: str = ""
    note: str = ""
    line_no: int | None = None  # delivery notes: the Excel row, so lines added later can be told apart
    unit_price: float | None = None  # delivery notes only; None = unknown
    amount: float | None = None
    location_id: int | None = None  # this line's own place (a stock issue note); None = the document's
    # a stock issue note line taken from both places: ((location id, qty), ...) adding up to qty; () = one place
    places: tuple = ()


def insert_document(conn, kind, doc_date: date, lines: list[Line], code="", code_norm="",
                    customer_id=None, note="", source_file="", source_hash="", location_id=MAIN,
                    location_set=True) -> int:
    """Create a delivery or receipt document and its stock movements at location_id (delivery: taken from,
    receipt: put in). location_set=False: a delivery note whose place the user still has to choose."""
    if kind not in _FORWARD:
        raise ValueError(kind)
    movement_kind, sign = _FORWARD[kind]
    cur = conn.execute(
        "INSERT INTO documents(kind, code, code_norm, doc_date, customer_id, note, source_file, source_hash, "
        "location_id, location_set) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (kind, code, code_norm, doc_date.isoformat(), customer_id, note, source_file, source_hash, location_id,
         int(location_set)),
    )
    doc_id = cur.lastrowid
    _insert_lines(conn, doc_id, lines, movement_kind, sign, doc_date.isoformat(), location_id)
    return doc_id


def add_lines(conn, doc_id: int, lines: list[Line]) -> None:
    """Add lines to an active delivery/receipt (a partly approved note getting its remaining lines)."""
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None or doc["status"] != "active" or doc["kind"] not in _FORWARD:
        raise ValueError("Phiếu không tồn tại hoặc đã huỷ.")
    movement_kind, sign = _FORWARD[doc["kind"]]
    _insert_lines(conn, doc_id, lines, movement_kind, sign, doc["doc_date"], doc["location_id"])


def _insert_lines(conn, doc_id, lines, movement_kind, sign, occurred_on, location_id) -> None:
    for i, line in enumerate(lines, start=1):
        conn.execute(
            "INSERT INTO document_lines(document_id, line_no, product_id, qty, raw_name, raw_spec, note, unit_price, "
            "amount, location_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (doc_id, line.line_no or i, line.product_id, line.qty, line.raw_name, line.raw_spec, line.note,
             line.unit_price, line.amount, None if len(line.places) > 1 else line.location_id),
        )
        for place, qty in line.places if len(line.places) > 1 else ((line.location_id or location_id, line.qty),):
            _move(conn, line.product_id, sign * qty, doc_id, movement_kind, occurred_on, place)
    db.touch(conn)


def close_document(conn, doc_id: int, new_status: str = "cancelled") -> None:
    """Cancel (or mark replaced) a document by adding reverse movements. Nothing is deleted."""
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None or doc["status"] != "active":
        raise ValueError("Phiếu không tồn tại hoặc đã huỷ.")
    rows = conn.execute(
        "SELECT product_id, location_id, SUM(qty) AS qty FROM stock_movements WHERE document_id = ? "
        "GROUP BY product_id, location_id",
        (doc_id,),
    ).fetchall()
    for r in rows:
        if r["qty"]:
            # Reversal is dated like the original so period reports stay consistent.
            _move(conn, r["product_id"], -r["qty"], doc_id, _REVERSE[doc["kind"]], doc["doc_date"], r["location_id"])
    conn.execute(
        "UPDATE documents SET status = ?, closed_at = datetime('now', 'localtime') WHERE id = ?",
        (new_status, doc_id),
    )
    db.touch(conn)
    db.log(conn, f"document_{new_status}", f"{doc['kind']} {doc['code']} #{doc_id}")


def stamp_of(moment: datetime) -> str:
    """A moment as the database writes created_at (local time)."""
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def stock_count(conn, count_date: date, counted: dict, note="", at: datetime | None = None) -> int:
    """Record a physical count. Movement = counted - stock as of count_date (inclusive).

    counted: {(product_id, location_id): qty} for a count of one place, or {product_id: qty} for a count of
    the total (catalog import, master data, opening stock of a new product): the difference is then made at
    Kho tổng, Văn phòng is left as it is.
    Delivery notes dated on or before count_date must be scanned first,
    otherwise they will be subtracted twice later.

    at: the moment the shelf was really counted, for a count recorded later (a web request approved at the end of
    the day). The difference is then taken against what the app knew at that moment (movements created by then),
    and the count document and its adjustments carry that time: notes that come into the app after it fall into
    deliveries.count_conflicts, where the owner decides, instead of silently shifting the difference.
    """
    stamp = stamp_of(at) if at else None
    cur = conn.execute(
        "INSERT INTO documents(kind, doc_date, note, created_at) "
        "VALUES('stock_count', ?, ?, COALESCE(?, datetime('now', 'localtime')))",
        (count_date.isoformat(), note, stamp),
    )
    doc_id = cur.lastrowid
    total = stock_levels(conn, as_of=count_date, created_until=stamp)
    placed = stock_levels(conn, as_of=count_date, by_location=True, created_until=stamp)
    for i, (key, qty) in enumerate(counted.items(), start=1):
        product_id, location_id = key if isinstance(key, tuple) else (key, None)
        conn.execute(
            "INSERT INTO document_lines(document_id, line_no, product_id, qty, location_id) VALUES(?,?,?,?,?)",
            (doc_id, i, product_id, qty, location_id),
        )
        diff = qty - (total.get(product_id, 0.0) if location_id is None else placed.get(key, 0.0))
        if abs(diff) > 1e-9:
            _move(conn, product_id, diff, doc_id, "count_adjust", count_date.isoformat(), location_id or MAIN,
                  stamp)
    db.touch(conn)
    db.log(conn, "stock_count", f"#{doc_id} {count_date.isoformat()}")
    return doc_id


def stock_levels(conn, as_of: date | None = None, by_location=False, created_until: str | None = None) -> dict:
    """{product_id: stock}, or {(product_id, location_id): stock} with by_location.
    created_until: only movements the app already had at that moment (created_at <= 'YYYY-MM-DD HH:MM:SS')."""
    key = "product_id, location_id" if by_location else "product_id"
    clauses, args = [], []
    if as_of:
        clauses.append("occurred_on <= ?")
        args.append(as_of.isoformat())
    if created_until:
        clauses.append("created_at <= ?")
        args.append(created_until)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(f"SELECT {key}, SUM(qty) FROM stock_movements {where} GROUP BY {key}", args)
    if by_location:
        return {(r[0], r[1]): r[2] or 0.0 for r in rows}
    return {r[0]: r[1] or 0.0 for r in rows}


def next_transfer_code(conn) -> str:
    """CH001, CH002... Based on the highest number in use, not a count: once an edited transfer's old
    document is replaced (same code, new row), counting rows would skip numbers."""
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(code, 3) AS INTEGER)) FROM documents WHERE kind = 'transfer' AND code GLOB 'CH[0-9]*'"
    ).fetchone()
    return f"CH{(row[0] or 0) + 1:03d}"


def transfer(conn, doc_date: date, from_location: int, to_location: int, lines: list[Line], note="",
             replaces: int | None = None) -> int:
    """Goods moved from one place to the other: the total does not change. Code CH001, CH002...
    replaces: the transfer being edited (marked 'replaced', the new one keeps its code)."""
    if from_location == to_location or from_location not in LOCATIONS or to_location not in LOCATIONS:
        raise ValueError("Nơi chuyển đi và nơi nhận phải khác nhau.")
    if not lines:
        raise ValueError("Phiếu chuyển hàng chưa có dòng nào.")
    code = next_transfer_code(conn)
    if replaces:
        old = conn.execute("SELECT code, kind FROM documents WHERE id = ?", (replaces,)).fetchone()
        if old is None or old["kind"] != "transfer":
            raise ValueError("Chỉ sửa được phiếu chuyển hàng.")
        close_document(conn, replaces, "replaced")
        code = old["code"] or code
    cur = conn.execute(
        "INSERT INTO documents(kind, code, code_norm, doc_date, note, location_id, to_location_id) "
        "VALUES('transfer', ?, ?, ?, ?, ?, ?)",
        (code, code, doc_date.isoformat(), note, from_location, to_location),
    )
    doc_id = cur.lastrowid
    for i, line in enumerate(lines, start=1):
        conn.execute("INSERT INTO document_lines(document_id, line_no, product_id, qty, note) VALUES(?,?,?,?,?)",
                     (doc_id, i, line.product_id, line.qty, line.note))
        _move(conn, line.product_id, -line.qty, doc_id, "transfer_out", doc_date.isoformat(), from_location)
        _move(conn, line.product_id, line.qty, doc_id, "transfer_in", doc_date.isoformat(), to_location)
    db.touch(conn)
    db.log(conn, "transfer_edited" if replaces else "transfer",
           f"{code} {LOCATION_CODES[from_location]}->{LOCATION_CODES[to_location]}")
    return doc_id


def next_trial_code(conn) -> str:
    """DT001, DT002... (dùng thử), same numbering rule as transfer codes."""
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(code, 3) AS INTEGER)) FROM documents WHERE kind = 'trial' AND code GLOB 'DT[0-9]*'"
    ).fetchone()
    return f"DT{(row[0] or 0) + 1:03d}"


def record_trial_use(conn, doc_date: date, location_id: int, lines: list[Line], note="") -> int:
    """Goods taken out of stock for internal trial/testing use, with no customer -- replaces the sham
    delivery notes staff used to make for this. Code DT001, DT002... A mistake is fixed with Huỷ phiếu
    (cancel) and a fresh one, like a stock count; there is no separate edit for this kind."""
    if location_id not in LOCATIONS:
        raise ValueError("Nơi xuất dùng thử không hợp lệ.")
    if not lines:
        raise ValueError("Phiếu dùng thử chưa có dòng nào.")
    code = next_trial_code(conn)
    cur = conn.execute(
        "INSERT INTO documents(kind, code, code_norm, doc_date, note, location_id) VALUES('trial', ?, ?, ?, ?, ?)",
        (code, code, doc_date.isoformat(), note, location_id),
    )
    doc_id = cur.lastrowid
    for i, line in enumerate(lines, start=1):
        conn.execute("INSERT INTO document_lines(document_id, line_no, product_id, qty, note) VALUES(?,?,?,?,?)",
                     (doc_id, i, line.product_id, line.qty, line.note))
        _move(conn, line.product_id, -line.qty, doc_id, "trial_out", doc_date.isoformat(), location_id)
    db.touch(conn)
    db.log(conn, "trial_use", f"{code} {LOCATION_CODES[location_id]}")
    return doc_id


def set_location(conn, doc_id: int, location_id: int) -> None:
    """Where the goods of a delivery note were taken from (or a receipt put in). Its movements change place,
    the total does not change."""
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None or doc["kind"] not in _FORWARD or location_id not in LOCATIONS:
        raise ValueError("Không đổi được nơi lấy hàng của phiếu này.")
    if is_mixed(conn, doc_id):
        raise ValueError("Phiếu này lấy hàng ở cả Kho tổng và Văn phòng: không đổi chung một nơi được. "
                         "Muốn đổi, hãy huỷ phiếu rồi tạo lại phiếu xuất kho.")
    conn.execute("UPDATE stock_movements SET location_id = ? WHERE document_id = ?", (location_id, doc_id))
    conn.execute("UPDATE document_lines SET location_id = ? WHERE document_id = ? AND location_id IS NOT NULL",
                 (location_id, doc_id))
    conn.execute("UPDATE documents SET location_id = ?, location_set = 1 WHERE id = ?", (location_id, doc_id))
    db.touch(conn)
    db.log(conn, "document_location", f"{doc['kind']} {doc['code']} #{doc_id} -> {LOCATION_CODES[location_id]}")


def is_mixed(conn, doc_id: int) -> bool:
    """A document whose goods were taken from both places (a stock issue note)."""
    return conn.execute("SELECT COUNT(DISTINCT location_id) FROM stock_movements WHERE document_id = ?",
                        (doc_id,)).fetchone()[0] > 1


def stock_table(conn) -> list[sqlite3.Row]:
    """Active products with current stock (total and per place), for the main screen."""
    return conn.execute(
        f"""
        SELECT p.*, COALESCE(SUM(m.qty), 0) AS stock,
               COALESCE(SUM(CASE WHEN m.location_id = {MAIN} THEN m.qty END), 0) AS stock_main,
               COALESCE(SUM(CASE WHEN m.location_id = {OFFICE} THEN m.qty END), 0) AS stock_office,
               MAX(CASE WHEN m.kind = 'delivery_out' THEN m.occurred_on END) AS last_out
        FROM products p
        LEFT JOIN stock_movements m ON m.product_id = p.id
        WHERE p.active = 1
        GROUP BY p.id
        ORDER BY p.category, p.name_vi, p.spec
        """
    ).fetchall()


def low_stock_default(conn) -> float:
    """Alarm level for every product: stock below it is 'running low'.
    Kept in meta so it travels with the data package."""
    try:
        return float(db.get_meta(conn, "low_stock_default", "30"))
    except ValueError:
        return 30.0


def is_low(stock: float, default: float) -> bool:
    """Below the shared alarm level (0 = off)."""
    return bool(default) and stock < default


def _move(conn, product_id, qty, doc_id, kind, occurred_on, location_id, created_at: str | None = None) -> None:
    conn.execute(
        "INSERT INTO stock_movements(product_id, qty, document_id, kind, occurred_on, location_id, created_at) "
        "VALUES(?,?,?,?,?,?,COALESCE(?, datetime('now', 'localtime')))",
        (product_id, qty, doc_id, kind, occurred_on, location_id, created_at),
    )
