"""Web inbox on the desktop: parse, apply through core.receipts, confirm after a push."""

from datetime import date

from dibekho import db
from dibekho.core import catalog
from dibekho.core.cloud import inbox


class FakeClient:
    def __init__(self, pending=()):
        self.pending = list(pending)
        self.patches = []

    def get(self, path, token):
        assert "web_inbox" in path and "status=eq.pending" in path
        return self.pending

    def patch(self, path, body, token):
        self.patches.append((path, body))


def _product(conn):
    with db.transaction(conn):
        return catalog.create_product(conn, "Keo chống thấm", spec="15kg", unit="thùng")


def _item(pid, qty=5, item_id="aaa-1", **extra):
    payload = {"doc_date": "2026-11-10", "supplier_name": "Cửa khẩu", "location_id": 2,
               "note": "từ web", "lines": [{"product_id": pid, "qty": qty, "note": ""}], **extra}
    return {"id": item_id, "kind": "receipt", "created_at": "2026-11-10T08:00:00Z", "payload": payload}


def test_check_good_payload(conn):
    pid = _product(conn)
    data, errors = inbox.check(conn, _item(pid))
    assert errors == []
    assert data.doc_date == date(2026, 11, 10) and data.location_id == 2
    assert data.supplier_name == "Cửa khẩu" and data.lines[0].product_id == pid


def test_check_rejects_unknown_product_and_bad_qty(conn):
    pid = _product(conn)
    _, errors = inbox.check(conn, _item(999))
    assert any("#999" in e for e in errors)
    _, errors = inbox.check(conn, _item(pid, qty=0))
    assert errors  # qty must be > 0


def test_apply_creates_receipt_and_remembers_link(conn, ws):
    pid = _product(conn)
    doc_id = inbox.apply_item(conn, ws, _item(pid))
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    assert doc["kind"] == "receipt" and doc["status"] == "active" and doc["location_id"] == 2
    stock = conn.execute("SELECT SUM(qty) FROM stock_movements WHERE product_id = ?", (pid,)).fetchone()[0]
    assert stock == 5
    assert inbox.applied_map(conn) == {"aaa-1": doc_id}


def test_fetch_pending_skips_applied_and_foreign_kinds(conn, ws):
    pid = _product(conn)
    inbox.apply_item(conn, ws, _item(pid, item_id="done-1"))
    client = FakeClient(pending=[_item(pid, item_id="done-1"), _item(pid, item_id="new-2"),
                                 {"id": "x", "kind": "future_kind", "payload": {}}])
    got = inbox.fetch_pending(conn, client, "tok")
    assert [i["id"] for i in got] == ["new-2"]


def test_finish_applied_confirms_existing_and_drops_undone(conn, ws):
    pid = _product(conn)
    doc_id = inbox.apply_item(conn, ws, _item(pid, item_id="keep-1"))
    with db.transaction(conn):  # fake an Undo that removed a second applied item's document
        m = inbox.applied_map(conn)
        m["gone-2"] = doc_id + 999
        import json
        db.set_meta(conn, inbox.META_KEY, json.dumps(m))
    client = FakeClient()
    assert inbox.finish_applied(conn, client, "tok") == 1
    assert inbox.applied_map(conn) == {}  # both links consumed
    (path, body), = client.patches  # only the surviving document was confirmed
    assert "id=eq.keep-1" in path and body["status"] == "applied" and body["result"]["doc_id"] == doc_id


def test_reject_patches_cloud(conn):
    client = FakeClient()
    inbox.reject(client, "tok", "bbb-2", "trùng phiếu")
    (path, body), = client.patches
    assert "id=eq.bbb-2" in path and body["status"] == "rejected"


class ReconcileClient:
    def __init__(self, applied):
        self.applied, self.patches = applied, []

    def get(self, path, token):
        assert "status=eq.applied" in path
        return self.applied

    def patch(self, path, body, token):
        self.patches.append((path, body))


def test_reconcile_returns_undone_slips_to_pending(conn, ws):
    pid = _product(conn)
    doc_id = inbox.apply_item(conn, ws, _item(pid, item_id="kept"))
    kept_code = conn.execute("SELECT code FROM documents WHERE id = ?", (doc_id,)).fetchone()[0]
    client = ReconcileClient([
        {"id": "kept", "result": {"code": kept_code}},         # its receipt exists: stays recorded
        {"id": "undone", "result": {"code": "HV099"}},         # no such receipt any more (Undo/restore)
        {"id": "no-code", "result": {}},                       # nothing to check
    ])
    assert inbox.reconcile_applied(conn, client, "tok") == 1
    (path, body), = client.patches
    assert "id=eq.undone" in path and body == {"status": "pending", "result": None, "applied_at": None}


def test_reconcile_keeps_slips_whose_receipt_was_only_cancelled(conn, ws):
    from dibekho.core import stock

    pid = _product(conn)
    doc_id = inbox.apply_item(conn, ws, _item(pid, item_id="cancelled-later"))
    code = conn.execute("SELECT code FROM documents WHERE id = ?", (doc_id,)).fetchone()[0]
    with db.transaction(conn):
        stock.close_document(conn, doc_id, "cancelled")  # the row stays, only its status changes
    client = ReconcileClient([{"id": "cancelled-later", "result": {"code": code}}])
    assert inbox.reconcile_applied(conn, client, "tok") == 0 and not client.patches
