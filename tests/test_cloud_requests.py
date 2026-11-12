"""Staff requests from the web: Excel delivery notes and stock counts (core.cloud.inbox)."""

import hashlib
from datetime import date, datetime, timedelta, timezone

import pytest

from dibekho import db
from dibekho.core import catalog, deliveries, stock
from dibekho.core.cloud import inbox
from dibekho.core.cloud.client import CloudError
from tests.conftest import make_note

UUID = "11111111-2222-3333-4444-555555555555"


def _product(conn):
    with db.transaction(conn):
        return catalog.create_product(conn, "Keo chống thấm", spec="15kg", unit="thùng")


class PatchClient:
    def __init__(self, applied=()):
        self.applied, self.patches = list(applied), []

    def get(self, path, token):
        assert "status=eq.applied" in path
        return self.applied

    def patch(self, path, body, token):
        self.patches.append((path, body))


# ---- delivery note file -------------------------------------------------------------------------------------

class FileClient:
    """A fake cloud holding one uploaded file, recording what the desktop does with it."""

    def __init__(self, data=b"", fail_confirm=False):
        self.data, self.fail_confirm = data, fail_confirm
        self.patches, self.deleted = [], []

    def storage_download(self, name, token, bucket="backups"):
        assert bucket == "inbox-files"
        return self.data

    def storage_delete(self, names, token, bucket="backups"):
        assert bucket == "inbox-files"
        self.deleted += names

    def patch(self, path, body, token):
        if self.fail_confirm:
            raise CloudError("offline")
        self.patches.append((path, body))


def _note_bytes(tmp_path, code="101"):
    return make_note(tmp_path / f"n{code}.xlsx", code=code).read_bytes()


def _file_item(data, name="Phiếu 101.xlsx"):
    payload = {"file_path": f"{UUID}/{name}", "file_name": name, "size": len(data),
               "sha256": hashlib.sha256(data).hexdigest(), "note": ""}
    return {"id": "file-1", "kind": "delivery_file", "created_at": "2026-11-10T08:00:00Z", "payload": payload}


def test_apply_delivery_places_the_file_for_the_normal_scan(conn, ws, tmp_path):
    data = _note_bytes(tmp_path)
    client = FileClient(data)
    result = inbox.apply_delivery(conn, ws, client, "tok", _file_item(data))
    assert result["placed"].read_bytes() == data and result["placed"].parent == ws.deliveries
    assert client.patches[0][1]["status"] == "applied" and client.patches[0][1]["result"]["file"].endswith(".xlsx")
    assert client.deleted == [f"{UUID}/Phiếu 101.xlsx"]  # the uploaded copy is dropped from the cloud
    deliveries.scan(conn, ws)  # the existing scan reads it like any delivery note
    assert conn.execute("SELECT COUNT(*) FROM scanned_files WHERE hash = ?",
                        (hashlib.sha256(data).hexdigest(),)).fetchone()[0] == 1


def test_apply_delivery_twice_does_not_make_a_second_copy(conn, ws, tmp_path):
    data = _note_bytes(tmp_path)
    inbox.apply_delivery(conn, ws, FileClient(data), "tok", _file_item(data))
    deliveries.scan(conn, ws)
    again = FileClient(data)
    result = inbox.apply_delivery(conn, ws, again, "tok", _file_item(data))
    assert result["placed"] is None and result["status"]  # the app already has this note
    assert again.patches[0][1]["result"]["already"] is True
    assert len(list(ws.deliveries.rglob("*.xlsx"))) == 1


def test_apply_delivery_rejects_bad_files(conn, ws, tmp_path):
    good = _note_bytes(tmp_path)
    with pytest.raises(ValueError, match="mã kiểm tra"):
        inbox.apply_delivery(conn, ws, FileClient(good + b"x"), "tok", _file_item(good))  # corrupted in transit
    junk = b"not an excel file at all"
    with pytest.raises(ValueError, match="Excel"):
        inbox.apply_delivery(conn, ws, FileClient(junk), "tok", _file_item(junk))
    assert inbox.check_delivery(_file_item(good, name="phieu.exe"))
    escape = _file_item(good)
    escape["payload"]["file_path"] = "../../etc/passwd"
    assert inbox.check_delivery(escape)
    assert not list(ws.deliveries.rglob("*.xlsx"))  # nothing was placed by any of these


def test_file_name_is_made_safe():
    assert inbox.safe_file_name("../../x/Phiếu:1?.xlsx") == "Phiếu_1_.xlsx"
    assert inbox.safe_file_name("") == "phieu-web.xlsx"
    assert inbox.safe_file_name("a.XLSX") == "a.xlsx"


def test_confirm_failure_after_placing_is_harmless(conn, ws, tmp_path):
    data = _note_bytes(tmp_path)
    result = inbox.apply_delivery(conn, ws, FileClient(data, fail_confirm=True), "tok", _file_item(data))
    assert result["placed"].exists()  # the file is in the folder even if the cloud could not be told


def test_rejecting_a_delivery_drops_the_uploaded_file():
    client = FileClient()
    item = _file_item(b"x")
    inbox.reject(client, "tok", item, "sai phiếu")
    assert client.patches[0][1]["status"] == "rejected" and client.deleted == [item["payload"]["file_path"]]


# ---- stock count --------------------------------------------------------------------------------------------

def _count_item(lines, item_id="count-1", day="2026-11-10", sent="2026-11-10T08:00:00Z", location=1):
    return {"id": item_id, "kind": "stock_count", "created_at": sent, "sender": "Lan",
            "payload": {"count_date": day, "location_id": location, "note": "", "lines": lines}}


def _stamp(conn, doc_id, moment):
    """Pretend a document was entered at `moment` (a test cannot wait for the clock)."""
    stamp = stock.stamp_of(moment)
    conn.execute("UPDATE documents SET created_at = ? WHERE id = ?", (stamp, doc_id))
    conn.execute("UPDATE stock_movements SET created_at = ? WHERE document_id = ?", (stamp, doc_id))


def _hours(moment, delta):
    from datetime import timedelta
    return moment + timedelta(hours=delta)


def _shop_day(conn, pid):
    """100 in the books since the day before; counted 90 at 09:00; a delivery of 5 entered at 14:00."""
    nine = inbox.sent_at({"created_at": "2026-11-10T09:00:00Z"})
    with db.transaction(conn):
        rec = stock.insert_document(conn, "receipt", date(2026, 11, 9), [stock.Line(pid, 100)], code="HV001",
                                    code_norm="HV001", location_id=stock.MAIN)
        _stamp(conn, rec, _hours(nine, -2))
    return nine


def _late_delivery(conn, pid, nine):
    with db.transaction(conn):
        out = stock.insert_document(conn, "delivery", date(2026, 11, 10), [stock.Line(pid, 5)], code="55",
                                    code_norm="55", location_id=stock.MAIN)
        _stamp(conn, out, _hours(nine, 5))  # entered AFTER the count


def test_count_is_taken_against_stock_at_the_moment_it_was_sent(conn):
    """Counted 90 at 09:00 with 100 in the books; a delivery of 5 is entered at 14:00 the same day and the owner
    approves at 18:00. The difference must be -10 (against what the app knew at 09:00), not -5."""
    pid = _product(conn)
    nine = _shop_day(conn, pid)
    _late_delivery(conn, pid, nine)

    item = _count_item([{"product_id": pid, "qty": 90}], sent="2026-11-10T09:00:00Z")
    (row,) = inbox.count_preview(conn, item)
    assert (row.counted, row.system, row.diff) == (90, 100, -10)
    doc_id = inbox.apply_count(conn, item)

    total = conn.execute("SELECT SUM(qty) FROM stock_movements WHERE product_id = ?", (pid,)).fetchone()[0]
    assert total == 85  # 90 on the shelf at the count, minus the 5 that left afterwards
    count_doc = conn.execute("SELECT created_at, note FROM documents WHERE id = ?", (doc_id,)).fetchone()
    assert count_doc["created_at"] == stock.stamp_of(nine)  # carries the moment of counting
    assert "Lan" in count_doc["note"]
    assert inbox.applied_map(conn) == {"count-1": doc_id}


def test_delivery_entered_after_a_web_count_goes_to_the_owner_as_a_conflict(conn):
    """The existing 'đơn đọc sau kiểm kê' flow picks it up because the count document carries the sending time."""
    pid = _product(conn)
    nine = _shop_day(conn, pid)
    inbox.apply_count(conn, _count_item([{"product_id": pid, "qty": 90}], sent="2026-11-10T09:00:00Z"))
    _late_delivery(conn, pid, nine)
    assert [c["code"] for c in deliveries.count_conflicts(conn)] == ["55"]


def test_check_count_rejects_bad_requests(conn):
    pid = _product(conn)
    ok = _count_item([{"product_id": pid, "qty": 0}])  # a count of zero is a real count
    assert inbox.check_count(conn, ok)[3] == []
    for bad in (
        _count_item([{"product_id": pid, "qty": -1}]),
        _count_item([{"product_id": 999, "qty": 1}]),
        _count_item([{"product_id": pid, "qty": 1}, {"product_id": pid, "qty": 2}]),
        _count_item([{"product_id": pid, "qty": 1}], location=7),
        _count_item([{"product_id": pid, "qty": 1}], day="2026-12-31"),  # after the day it was sent
        _count_item([]),
    ):
        assert inbox.check_count(conn, bad)[3], bad


def test_count_is_per_place(conn):
    pid = _product(conn)
    with db.transaction(conn):
        stock.stock_count(conn, date(2026, 11, 1), {(pid, stock.MAIN): 20, (pid, stock.OFFICE): 4})
    sent = datetime.now(timezone.utc) + timedelta(minutes=5)  # after the count above, whatever the time of day
    item = _count_item([{"product_id": pid, "qty": 6}], location=stock.OFFICE, sent=sent.isoformat(),
                       day=date.today().isoformat())
    (row,) = inbox.count_preview(conn, item)
    assert (row.system, row.diff) == (4, 2)  # only the office is compared
    inbox.apply_count(conn, item)
    levels = stock.stock_levels(conn, by_location=True)
    assert levels[(pid, stock.OFFICE)] == 6 and levels[(pid, stock.MAIN)] == 20


def test_finish_and_reconcile_a_count(conn):
    pid = _product(conn)
    doc_id = inbox.apply_count(conn, _count_item([{"product_id": pid, "qty": 3}]))
    client = PatchClient()
    assert inbox.finish_applied(conn, client, "tok") == 1
    (path, body), = client.patches
    stamp = conn.execute("SELECT created_at FROM documents WHERE id = ?", (doc_id,)).fetchone()[0]
    assert body["result"] == {"doc_id": doc_id, "stamp": stamp}

    still = PatchClient([{"id": "c1", "kind": "stock_count", "result": {"doc_id": doc_id, "stamp": stamp}}])
    assert inbox.reconcile_applied(conn, still, "tok") == 0
    undone = PatchClient([{"id": "c2", "kind": "stock_count", "result": {"doc_id": doc_id + 50, "stamp": stamp}}])
    assert inbox.reconcile_applied(conn, undone, "tok") == 1  # its count document is gone: back to pending
    files = PatchClient([{"id": "f", "kind": "delivery_file", "result": {"file": "a.xlsx", "hash": "h"}}])
    assert inbox.reconcile_applied(conn, files, "tok") == 0 and not files.patches  # files are never reverted
