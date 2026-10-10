"""Stock ledger: every change is a stock_movements row, current stock = SUM(qty).

All functions that write expect to be called inside `db.transaction(conn)`.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date

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
}


@dataclass
class Line:
    product_id: int
    qty: float
    raw_name: str = ""
    raw_spec: str = ""
    note: str = ""


def insert_document(conn, kind, doc_date: date, lines: list[Line], code="", code_norm="",
                    customer_id=None, note="", source_file="", source_hash="") -> int:
    """Create a delivery or receipt document and its stock movements."""
    if kind not in _FORWARD:
        raise ValueError(kind)
    movement_kind, sign = _FORWARD[kind]
    cur = conn.execute(
        "INSERT INTO documents(kind, code, code_norm, doc_date, customer_id, note, source_file, source_hash) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (kind, code, code_norm, doc_date.isoformat(), customer_id, note, source_file, source_hash),
    )
    doc_id = cur.lastrowid
    for i, line in enumerate(lines, start=1):
        conn.execute(
            "INSERT INTO document_lines(document_id, line_no, product_id, qty, raw_name, raw_spec, note) "
            "VALUES(?,?,?,?,?,?,?)",
            (doc_id, i, line.product_id, line.qty, line.raw_name, line.raw_spec, line.note),
        )
        _move(conn, line.product_id, sign * line.qty, doc_id, movement_kind, doc_date.isoformat())
    db.touch(conn)
    return doc_id


def close_document(conn, doc_id: int, new_status: str = "cancelled") -> None:
    """Cancel (or mark replaced) a document by adding reverse movements. Nothing is deleted."""
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None or doc["status"] != "active":
        raise ValueError("Phiếu không tồn tại hoặc đã huỷ.")
    rows = conn.execute(
        "SELECT product_id, SUM(qty) AS qty FROM stock_movements WHERE document_id = ? GROUP BY product_id",
        (doc_id,),
    ).fetchall()
    for r in rows:
        if r["qty"]:
            # Reversal is dated like the original so period reports stay consistent.
            _move(conn, r["product_id"], -r["qty"], doc_id, _REVERSE[doc["kind"]], doc["doc_date"])
    conn.execute(
        "UPDATE documents SET status = ?, closed_at = datetime('now', 'localtime') WHERE id = ?",
        (new_status, doc_id),
    )
    db.touch(conn)
    db.log(conn, f"document_{new_status}", f"{doc['kind']} {doc['code']} #{doc_id}")


def stock_count(conn, count_date: date, counted: dict[int, float], note="") -> int:
    """Record a physical count. Movement = counted - stock as of count_date (inclusive).

    Delivery notes dated on or before count_date must be scanned first,
    otherwise they will be subtracted twice later.
    """
    cur = conn.execute(
        "INSERT INTO documents(kind, doc_date, note) VALUES('stock_count', ?, ?)",
        (count_date.isoformat(), note),
    )
    doc_id = cur.lastrowid
    on_hand = stock_levels(conn, as_of=count_date)
    for i, (product_id, qty) in enumerate(counted.items(), start=1):
        conn.execute(
            "INSERT INTO document_lines(document_id, line_no, product_id, qty) VALUES(?,?,?,?)",
            (doc_id, i, product_id, qty),
        )
        diff = qty - on_hand.get(product_id, 0.0)
        if abs(diff) > 1e-9:
            _move(conn, product_id, diff, doc_id, "count_adjust", count_date.isoformat())
    db.touch(conn)
    db.log(conn, "stock_count", f"#{doc_id} {count_date.isoformat()}")
    return doc_id


def stock_levels(conn, as_of: date | None = None) -> dict[int, float]:
    if as_of is None:
        rows = conn.execute("SELECT product_id, SUM(qty) FROM stock_movements GROUP BY product_id")
    else:
        rows = conn.execute(
            "SELECT product_id, SUM(qty) FROM stock_movements WHERE occurred_on <= ? GROUP BY product_id",
            (as_of.isoformat(),),
        )
    return {r[0]: r[1] or 0.0 for r in rows}


def stock_table(conn) -> list[sqlite3.Row]:
    """Active products with current stock, for the main screen."""
    return conn.execute(
        """
        SELECT p.*, COALESCE(SUM(m.qty), 0) AS stock,
               MAX(CASE WHEN m.kind = 'delivery_out' THEN m.occurred_on END) AS last_out
        FROM products p
        LEFT JOIN stock_movements m ON m.product_id = p.id
        WHERE p.active = 1
        GROUP BY p.id
        ORDER BY p.category, p.name_vi, p.spec
        """
    ).fetchall()


def _move(conn, product_id, qty, doc_id, kind, occurred_on) -> None:
    conn.execute(
        "INSERT INTO stock_movements(product_id, qty, document_id, kind, occurred_on) VALUES(?,?,?,?,?)",
        (product_id, qty, doc_id, kind, occurred_on),
    )
