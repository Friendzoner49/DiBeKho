"""The cloud mirror payload: full business data, nothing machine-local (docs/cloud/04)."""

import json
from datetime import date

from dibekho import db
from dibekho.core import catalog, stock
from dibekho.core.cloud import mirror


def _sample_data(conn):
    with db.transaction(conn):
        pid = catalog.create_product(conn, "Vữa chống thấm", name_zh="背水涂", spec="10KG/thùng",
                                     unit="thùng", category="Vữa")
        cid = catalog.upsert_customer(conn, "Công ty A", phone="0900 000 001")
        stock.stock_count(conn, date(2026, 10, 1), {(pid, stock.MAIN): 50})
        stock.insert_document(conn, "delivery", date(2026, 10, 5),
                              [stock.Line(pid, 3, unit_price=100000.0, amount=300000.0)],
                              code="101", code_norm="101", customer_id=cid)
    return pid, cid


def test_payload_contents(conn):
    pid, cid = _sample_data(conn)
    payload = mirror.build_payload(conn, "dev-1", "May Windows", based_on_push=7)

    assert payload["device_id"] == "dev-1"
    assert payload["schema_version"] == conn.execute("PRAGMA user_version").fetchone()[0]
    assert payload["based_on_push"] == 7

    (p,) = payload["products"]
    assert p["id"] == pid and p["code"] == "SP001" and p["active"] is True  # bool, not 0/1
    (c,) = payload["customers"]
    assert c["id"] == cid and c["name"] == "Công ty A"
    kinds = {d["kind"] for d in payload["documents"]}
    assert kinds == {"stock_count", "delivery"}
    assert any(line["unit_price"] == 100000.0 for line in payload["document_lines"])
    # stock mirrors SUM(movements) per place: 50 counted - 3 delivered at Kho tổng
    assert payload["stock"] == [{"product_id": pid, "location_id": stock.MAIN, "qty": 47.0}]


def test_payload_is_json_and_has_no_local_tables(conn):
    _sample_data(conn)
    payload = mirror.build_payload(conn, "dev-1", "May")
    text = json.dumps(payload, ensure_ascii=False)  # must be JSON-serializable as-is
    for key in ("scanned_files", "hidden_inputs", "app_log", "meta"):
        assert key not in payload
        assert key not in text


def test_inactive_products_and_cancelled_documents_still_mirrored(conn):
    pid, _ = _sample_data(conn)
    with db.transaction(conn):
        doc = conn.execute("SELECT id FROM documents WHERE kind = 'delivery'").fetchone()["id"]
        stock.close_document(conn, doc, "cancelled")
        catalog.update_product(conn, pid, active=0)
    payload = mirror.build_payload(conn, "dev-1", "May")
    (p,) = payload["products"]
    assert p["active"] is False
    assert any(d["status"] == "cancelled" for d in payload["documents"])
    # reversal brings Kho tổng back to the counted 50
    assert payload["stock"] == [{"product_id": pid, "location_id": stock.MAIN, "qty": 50.0}]
