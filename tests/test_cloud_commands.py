"""Owner commands (core.cloud.commands): fingerprints, each command through the same core call as the app's own window,
who is obeyed, and that a command never runs twice -- not even after an Undo."""

import hashlib
from datetime import date

import pytest

from dibekho import db
from dibekho.core import catalog, receipts, stock
from dibekho.core.cloud import commands, inbox, state
from dibekho.core.cloud.client import CloudError
from tests.conftest import make_note


class Cloud:
    """Fake cloud: records the answers the desktop sends; can be told to fail."""

    def __init__(self, fail=False, files=None):
        self.patches, self.fail, self.files, self.deleted = [], fail, files or {}, []

    def patch(self, path, body, token):
        if self.fail:
            raise CloudError("offline")
        self.patches.append((path.split("eq.")[-1], body))

    def storage_download(self, name, token, bucket="backups"):
        return self.files[name]

    def storage_delete(self, names, token, bucket="backups"):
        self.deleted += names


def _stamp(conn, table, pk):
    return conn.execute(f"SELECT created_at FROM {table} WHERE id = ?", (pk,)).fetchone()[0]


def fp_product(conn, pid):
    row = conn.execute("SELECT code, created_at FROM products WHERE id = ?", (pid,)).fetchone()
    return {"id": pid, "code": row["code"], "created_at": row["created_at"]}


def fp_doc(conn, doc_id):
    row = conn.execute("SELECT kind, code, created_at FROM documents WHERE id = ?", (doc_id,)).fetchone()
    return {"id": doc_id, "kind": row["kind"], "code": row["code"], "created_at": row["created_at"]}


def fp_customer(conn, cid):
    return {"id": cid, "created_at": _stamp(conn, "customers", cid)}


def line(conn, pid, qty, **extra):
    return {"product_id": pid, "code": conn.execute("SELECT code FROM products WHERE id = ?", (pid,)).fetchone()[0],
            "qty": qty, **extra}


def item(kind, payload, item_id="i1", role="desktop", sender="Chủ"):
    return {"id": item_id, "kind": kind, "payload": payload, "sender_role": role, "sender": sender,
            "created_at": "2026-11-10T08:00:00Z"}


@pytest.fixture
def shop(conn):
    """Two products with stock, a customer, a delivery and a receipt."""
    with db.transaction(conn):
        a = catalog.create_product(conn, "Keo A", spec="15kg", unit="thùng", category="Keo")
        b = catalog.create_product(conn, "Màng B", spec="3mm", unit="cuộn", category="Màng")
        cust = catalog.upsert_customer(conn, "Công ty A", phone="0900 000 001")
        rec = stock.insert_document(conn, "receipt", date(2026, 11, 1), [stock.Line(a, 50), stock.Line(b, 20)],
                                    code="HV001", code_norm="HV001")
        conn.execute("UPDATE documents SET receipt_source = 'supplier' WHERE id = ?", (rec,))
        out = stock.insert_document(conn, "delivery", date(2026, 11, 2), [stock.Line(a, 5)], code="7", code_norm="7",
                                    customer_id=cust)
    return {"a": a, "b": b, "cust": cust, "rec": rec, "out": out}


def run(conn, ws, kind, payload):
    return commands.run(conn, ws, item(kind, payload))


def level(conn, pid, place=None):
    levels = stock.stock_levels(conn, by_location=place is not None)
    return levels.get((pid, place), 0) if place else levels.get(pid, 0)


# ---- fingerprints -------------------------------------------------------------------------------------------

def test_a_command_for_a_row_that_changed_is_refused(conn, ws, shop):
    target = fp_doc(conn, shop["out"])
    with db.transaction(conn):  # an Undo/restore later: the same id now holds a different document
        conn.execute("UPDATE documents SET created_at = '2030-01-01 00:00:00' WHERE id = ?", (shop["out"],))
    with pytest.raises(commands.CommandError, match="Hoàn tác"):
        run(conn, ws, "cmd_cancel_doc", {"target": target})
    assert conn.execute("SELECT status FROM documents WHERE id = ?", (shop["out"],)).fetchone()[0] == "active"

    stale = fp_product(conn, shop["a"])
    stale["code"] = "SP999"
    with pytest.raises(commands.CommandError):
        run(conn, ws, "cmd_product_edit", {"target": stale, "fields": {"name_vi": "x"}})
    with pytest.raises(commands.CommandError):  # a line whose id does not match its code
        run(conn, ws, "cmd_transfer", {"date": "2026-11-05", "from": 1, "to": 2,
                                       "lines": [{"product_id": shop["a"], "code": "SP999", "qty": 1}]})
    assert level(conn, shop["a"], stock.OFFICE) == 0


# ---- the commands -------------------------------------------------------------------------------------------

def test_transfer_and_trial_use(conn, ws, shop):
    said = run(conn, ws, "cmd_transfer", {"date": "2026-11-05", "from": 1, "to": 2, "note": "bán tại văn phòng",
                                          "lines": [line(conn, shop["a"], 12)]})
    assert said.startswith("Chuyển hàng CH001")
    assert level(conn, shop["a"], stock.OFFICE) == 12 and level(conn, shop["a"]) == 45  # total unchanged by a transfer
    said = run(conn, ws, "cmd_trial", {"date": "2026-11-06", "location": 2, "lines": [line(conn, shop["a"], 2)]})
    assert said.startswith("Xuất dùng thử DT001") and level(conn, shop["a"], stock.OFFICE) == 10
    for bad in ({"from": 1, "to": 1}, {"from": 1, "to": 9}):
        with pytest.raises(commands.CommandError):
            run(conn, ws, "cmd_transfer", {"date": "2026-11-05", "lines": [line(conn, shop["a"], 1)], **bad})
    with pytest.raises(commands.CommandError, match="lớn hơn 0"):
        run(conn, ws, "cmd_trial", {"date": "2026-11-06", "location": 1, "lines": [line(conn, shop["a"], 0)]})


def test_product_add_runs_the_duplicate_check(conn, ws, shop):
    new = {"name_vi": "Keo C", "name_zh": "", "spec": "20kg", "variant": "", "unit": "thùng", "category": "Keo"}
    assert run(conn, ws, "cmd_product_add", new).startswith("Thêm mặt hàng SP003")
    with pytest.raises(commands.CommandError, match="Có thể trùng với SP003"):
        run(conn, ws, "cmd_product_add", new)
    assert run(conn, ws, "cmd_product_add", {**new, "allow_duplicate": True}).startswith("Thêm mặt hàng SP004")
    with pytest.raises(commands.CommandError, match="tên"):
        run(conn, ws, "cmd_product_add", {**new, "name_vi": " "})


def test_product_edit_and_stop(conn, ws, shop):
    target = fp_product(conn, shop["a"])
    run(conn, ws, "cmd_product_edit", {"target": target, "fields": {"name_vi": "Keo A mới", "stock_note": "2 thùng móp",
                                                                     "active": False}})
    row = conn.execute("SELECT * FROM products WHERE id = ?", (shop["a"],)).fetchone()
    assert (row["name_vi"], row["stock_note"], row["active"]) == ("Keo A mới", "2 thùng móp", 0)
    assert any(r[0] == "stock_note" for r in conn.execute("SELECT action FROM app_log"))
    with pytest.raises(commands.CommandError):
        run(conn, ws, "cmd_product_edit", {"target": target, "fields": {}})


def test_product_merge_keeps_the_smaller_code(conn, ws, shop):
    said = run(conn, ws, "cmd_product_merge", {"a": fp_product(conn, shop["b"]), "b": fp_product(conn, shop["a"])})
    assert said == "Gộp SP002 vào SP001"
    assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1
    assert level(conn, shop["a"]) == 45 + 20  # both stocks now under SP001
    with pytest.raises(commands.CommandError, match="khác nhau"):
        run(conn, ws, "cmd_product_merge", {"a": fp_product(conn, shop["a"]), "b": fp_product(conn, shop["a"])})


def test_customer_merge(conn, ws, shop):
    with db.transaction(conn):
        other = catalog.upsert_customer(conn, "Khách Mẫu", phone="0900 000 002")
    said = run(conn, ws, "cmd_customer_merge", {"targets": [fp_customer(conn, shop["cust"]),
                                                             fp_customer(conn, other)], "name": "Công ty A chung"})
    assert "2 khách hàng" in said
    assert conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 1
    with pytest.raises(commands.CommandError, match="2 khách"):
        run(conn, ws, "cmd_customer_merge", {"targets": [fp_customer(conn, shop["cust"])], "name": "x"})


def test_cancel_document_settles_the_scanned_file_like_the_app(conn, ws, shop):
    with db.transaction(conn):
        conn.execute("INSERT INTO scanned_files(hash, rel_path, document_id, status) VALUES('h', 'a.xlsx', ?, 'missing')",
                     (shop["out"],))
    assert run(conn, ws, "cmd_cancel_doc", {"target": fp_doc(conn, shop["out"])}) == "Huỷ phiếu 7"
    assert conn.execute("SELECT status FROM documents WHERE id = ?", (shop["out"],)).fetchone()[0] == "cancelled"
    assert level(conn, shop["a"]) == 50  # the 5 delivered came back
    assert conn.execute("SELECT status FROM scanned_files").fetchone()[0] == "imported"  # no 'missing file' warning
    with pytest.raises(commands.CommandError, match="đã huỷ"):
        run(conn, ws, "cmd_cancel_doc", {"target": fp_doc(conn, shop["out"])})


def test_set_location(conn, ws, shop):
    run(conn, ws, "cmd_set_location", {"target": fp_doc(conn, shop["out"]), "location": 2})
    assert level(conn, shop["a"], stock.OFFICE) == -5 and level(conn, shop["a"]) == 45
    assert conn.execute("SELECT location_set FROM documents WHERE id = ?", (shop["out"],)).fetchone()[0] == 1
    count = stock.stock_count(conn, date(2026, 11, 3), {(shop["a"], 1): 40})
    with pytest.raises(commands.CommandError, match="loại phiếu"):
        run(conn, ws, "cmd_set_location", {"target": fp_doc(conn, count), "location": 1})


def test_receipt_edit_replaces_the_receipt_and_keeps_its_code(conn, ws, shop):
    said = run(conn, ws, "cmd_receipt_edit", {
        "target": fp_doc(conn, shop["rec"]),
        "receipt": {"doc_date": "2026-11-01", "supplier_name": "Cửa khẩu", "location_id": 1,
                    "lines": [{"product_id": shop["a"], "qty": 60}, {"product_id": shop["b"], "qty": 20}]}})
    assert said == "Sửa phiếu hàng về HV001"
    assert level(conn, shop["a"]) == 60 - 5  # was 50, the edited receipt says 60
    statuses = conn.execute("SELECT status FROM documents WHERE code = 'HV001' ORDER BY id").fetchall()
    assert [r[0] for r in statuses] == ["replaced", "active"]
    with pytest.raises(commands.CommandError):  # the edited-away receipt can no longer be edited
        run(conn, ws, "cmd_receipt_edit", {"target": fp_doc(conn, shop["rec"]), "receipt": {"lines": []}})


def test_a_returned_goods_receipt_can_be_edited_too(conn, ws, shop):
    done = receipts.save(conn, receipts.ReceiptInput(date(2026, 11, 3), receipts.RETURN, customer_id=shop["cust"],
                                                     ref_code="7", lines=[receipts.ReceiptLineInput(2, shop["a"])]))
    run(conn, ws, "cmd_receipt_edit", {
        "target": fp_doc(conn, done),
        "receipt": {"doc_date": "2026-11-03", "source": "return", "customer_id": shop["cust"], "ref_code": "7",
                    "lines": [{"product_id": shop["a"], "qty": 3}]}})
    row = conn.execute("SELECT * FROM documents WHERE status = 'active' AND receipt_source = 'return'").fetchone()
    assert row["customer_id"] == shop["cust"] and row["ref_code"] == "7"


# ---- who is obeyed, and exactly once ------------------------------------------------------------------------

def test_only_the_owner_is_obeyed_and_unknown_roles_are_not_trusted(conn):
    cmd = {"cmd": item("cmd_cancel_doc", {}, "c1")}
    staff_receipt = item("receipt", {}, "r1", role="editor")
    unknown_receipt = item("receipt", {}, "r2", role="")
    unknown_cmd = item("cmd_cancel_doc", {}, "c2", role="")
    staff_cmd = item("cmd_cancel_doc", {}, "c3", role="editor")
    auto, manual = commands.partition([cmd["cmd"], staff_receipt, unknown_receipt, unknown_cmd, staff_cmd])
    assert [i["id"] for i in auto] == ["c1"]
    assert [i["id"] for i in manual] == ["r1", "r2"]  # requests wait for the owner; commands from others vanish


def test_applying_marks_done_and_answers_the_owner(conn, ws, shop):
    cloud = Cloud()
    cmd = item("cmd_cancel_doc", {"target": fp_doc(conn, shop["out"])}, "c1")
    (outcome,) = commands.apply_owner_items(conn, ws, cloud, "tok", [cmd])
    assert outcome.ok and outcome.summary == "Huỷ phiếu 7"
    assert cloud.patches == [("c1", {"status": "applied", "result": {"summary": "Huỷ phiếu 7"},
                                     "applied_at": cloud.patches[0][1]["applied_at"]})]
    assert state.load()["c1"] == {"ok": True, "summary": "Huỷ phiếu 7", "confirmed": True}


def test_a_refused_command_tells_the_owner_why_and_is_not_retried(conn, ws, shop):
    cloud = Cloud()
    cmd = item("cmd_trial", {"date": "2026-11-06", "location": 1, "lines": []}, "c2")
    (outcome,) = commands.apply_owner_items(conn, ws, cloud, "tok", [cmd])
    assert not outcome.ok
    (target, body), = cloud.patches
    assert body["status"] == "rejected" and "dòng hàng" in body["result"]["reason"]
    assert commands.partition([cmd])[0] == []  # not offered again


def test_undo_does_not_make_a_command_run_again(conn, ws, shop):
    """The batch is applied, then the owner presses Hoàn tác and the database goes back. The cloud still lists the
    command as pending only if the answer never arrived; either way it must not be carried out a second time."""
    cloud = Cloud(fail=True)  # the answer could not be sent
    cmd = item("cmd_transfer", {"date": "2026-11-05", "from": 1, "to": 2, "lines": [line(conn, shop["a"], 4)]}, "c3")
    commands.apply_owner_items(conn, ws, cloud, "tok", [cmd])
    assert level(conn, shop["a"], stock.OFFICE) == 4
    assert state.load()["c3"]["confirmed"] is False  # kept for the answer, never for the command

    with db.transaction(conn):  # Undo: the transfer is gone from the database ...
        conn.execute("DELETE FROM stock_movements WHERE kind LIKE 'transfer%'")
        conn.execute("DELETE FROM document_lines WHERE document_id IN (SELECT id FROM documents WHERE kind='transfer')")
        conn.execute("DELETE FROM documents WHERE kind = 'transfer'")
    auto, manual = commands.partition([cmd])  # ... but the command is still pending in the cloud
    assert auto == [] and manual == []
    assert level(conn, shop["a"], stock.OFFICE) == 0  # nothing re-applied

    cloud2 = Cloud()  # the network is back: only the answer is sent
    assert commands.retry_unconfirmed(cloud2, "tok", {"c3"}) == 1
    assert cloud2.patches[0][1]["status"] == "applied" and state.load()["c3"]["confirmed"] is True
    assert commands.retry_unconfirmed(cloud2, "tok", {"c3"}) == 0


def test_a_transient_network_failure_applies_nothing(conn, ws, shop):
    class Down(Cloud):
        def storage_download(self, *a, **k):
            raise CloudError("no route")

    sha = hashlib.sha256(b"x").hexdigest()
    file_item = item("delivery_file", {"file_path": "11111111-2222-3333-4444-555555555555/phieu.xlsx",
                                       "file_name": "p.xlsx", "size": 1, "sha256": sha}, "f1")
    assert commands.apply_owner_items(conn, ws, Down(), "tok", [file_item]) == []
    assert not state.is_done("f1")  # retried on the next poll
    assert not list(ws.deliveries.rglob("*.xlsx"))


def test_the_owners_goods_in_count_and_file_are_applied_too(conn, ws, shop, tmp_path):
    cloud = Cloud()
    note = make_note(tmp_path / "n.xlsx", code="55").read_bytes()
    files = {"11111111-2222-3333-4444-555555555555/phieu.xlsx": note}
    cloud.files = files
    receipt = item("receipt", {"doc_date": "2026-11-10", "supplier_name": "Cửa khẩu", "location_id": 1,
                               "lines": [{"product_id": shop["b"], "qty": 5}]}, "r1")
    count = item("stock_count", {"count_date": "2026-11-10", "location_id": 1,
                                 "lines": [{"product_id": shop["a"], "qty": 40}]}, "k1")
    count["created_at"] = "2030-01-01T00:00:00Z"  # sent after everything the fixture entered (a count sees what the
    # app knew at the moment it was sent: movements created later are not part of its difference)
    file = item("delivery_file", {"file_path": "11111111-2222-3333-4444-555555555555/phieu.xlsx", "file_name": "Phiếu 55.xlsx",
                                  "size": len(note), "sha256": hashlib.sha256(note).hexdigest()}, "f1")
    outcomes = commands.apply_owner_items(conn, ws, cloud, "tok", [receipt, count, file])
    assert [o.ok for o in outcomes] == [True, True, True]
    assert level(conn, shop["b"]) == 25 and level(conn, shop["a"]) == 40
    assert len(list(ws.deliveries.rglob("*.xlsx"))) == 1
    assert set(state.load()) == {"r1", "k1", "f1"}
    assert set(inbox.applied_map(conn)) == {"r1", "k1"}  # confirmed to the cloud after the next push, as for staff
