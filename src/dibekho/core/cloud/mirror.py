"""Build the cloud mirror payload from the local database.

The desktop is the single source of truth: each push REPLACES the whole mirror on the cloud
(cloud/supabase/001_init.sql, replace_mirror). Only business data goes up -- scanned_files,
hidden_inputs, app_log and anything with machine paths stay local. Design: docs/cloud/04-thiet-ke-chot.md.
"""

import sqlite3

from dibekho import __version__
from dibekho.core.stock import low_stock_default

# column lists match the mirror_* tables in cloud/supabase/001_init.sql
# (jsonb_populate_recordset matches by name, missing fields become NULL/defaults)
# created_at of products, customers and documents is the fingerprint owner commands carry: after an Undo or a restore
# an id can point at a different row, and the app must refuse a command meant for the old one.
_PRODUCTS = "id, code, name_vi, name_zh, spec, variant, unit, category, stock_note, active, created_at"
_CUSTOMERS = "id, name, contact, phone, address, created_at"
_DOCUMENTS = ("d.id, d.kind, d.code, d.doc_date, d.customer_id, d.status, d.note, d.location_id, d.to_location_id, "
              "d.fee_amount, d.note_total, d.created_at, d.location_set, d.receipt_source, d.ref_code, "
              "d.source_file, COALESCE(s.name, '') AS supplier_name")
_LINES = "id, document_id, line_no, product_id, qty, note, unit_price, amount, location_id"
# every movement: the web's product history and statistics are computed from them, like the app's own screens
_MOVEMENTS = "id, product_id, qty, document_id, kind, occurred_on, COALESCE(location_id, 1) AS location_id"


def build_payload(conn: sqlite3.Connection, device_id: str, device_name: str,
                  based_on_push: int | None = None) -> dict:
    schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
    products = _rows(conn, f"SELECT {_PRODUCTS} FROM products")
    for p in products:
        p["active"] = bool(p["active"])  # Postgres boolean: 0/1 would not cast from JSON
    documents = _rows(conn, f"SELECT {_DOCUMENTS} FROM documents d LEFT JOIN suppliers s ON s.id = d.supplier_id")
    for d in documents:
        d["location_set"] = bool(d["location_set"])
    return {
        "device_id": device_id,
        "device_name": device_name,
        "app_version": __version__,
        "schema_version": schema_version,
        "based_on_push": based_on_push,
        "low_stock_default": low_stock_default(conn),  # the web colours rows like the app does
        "products": products,
        "customers": _rows(conn, f"SELECT {_CUSTOMERS} FROM customers"),
        "documents": documents,
        "document_lines": _rows(conn, f"SELECT {_LINES} FROM document_lines"),
        "movements": _rows(conn, f"SELECT {_MOVEMENTS} FROM stock_movements"),
        "stock": _rows(conn,
                       "SELECT product_id, COALESCE(location_id, 1) AS location_id, SUM(qty) AS qty "
                       "FROM stock_movements GROUP BY product_id, COALESCE(location_id, 1)"),
    }


def _rows(conn, sql: str) -> list[dict]:
    return [dict(r) for r in conn.execute(sql).fetchall()]
