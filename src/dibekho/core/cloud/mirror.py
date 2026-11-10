"""Build the cloud mirror payload from the local database.

The desktop is the single source of truth: each push REPLACES the whole mirror on the cloud
(cloud/supabase/001_init.sql, replace_mirror). Only business data goes up -- scanned_files,
hidden_inputs, app_log and anything with machine paths stay local. Design: docs/cloud/04-thiet-ke-chot.md.
"""

import sqlite3

from dibekho import __version__

# column lists match the mirror_* tables in cloud/supabase/001_init.sql
# (jsonb_populate_recordset matches by name, missing fields become NULL/defaults)
_PRODUCTS = "id, code, name_vi, name_zh, spec, variant, unit, category, stock_note, active"
_CUSTOMERS = "id, name, contact, phone, address"
_DOCUMENTS = ("id, kind, code, doc_date, customer_id, status, note, location_id, to_location_id, "
              "fee_amount, note_total")
_LINES = "id, document_id, line_no, product_id, qty, note, unit_price, amount, location_id"


def build_payload(conn: sqlite3.Connection, device_id: str, device_name: str,
                  based_on_push: int | None = None) -> dict:
    schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
    products = _rows(conn, f"SELECT {_PRODUCTS} FROM products")
    for p in products:
        p["active"] = bool(p["active"])  # Postgres boolean: 0/1 would not cast from JSON
    return {
        "device_id": device_id,
        "device_name": device_name,
        "app_version": __version__,
        "schema_version": schema_version,
        "based_on_push": based_on_push,
        "products": products,
        "customers": _rows(conn, f"SELECT {_CUSTOMERS} FROM customers"),
        "documents": _rows(conn, f"SELECT {_DOCUMENTS} FROM documents"),
        "document_lines": _rows(conn, f"SELECT {_LINES} FROM document_lines"),
        "stock": _rows(conn,
                       "SELECT product_id, COALESCE(location_id, 1) AS location_id, SUM(qty) AS qty "
                       "FROM stock_movements GROUP BY product_id, COALESCE(location_id, 1)"),
    }


def _rows(conn, sql: str) -> list[dict]:
    return [dict(r) for r in conn.execute(sql).fetchall()]
