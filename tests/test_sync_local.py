"""The local half of cloud sync (migration 010 + dibekho.db.sync_schema): changes are queued only in cloud mode,
deletes carry the uuid and free the mapping, and the triggers survive anything that rebuilds a table."""

from datetime import date

from dibekho import db
from dibekho.core import catalog, stock
from dibekho.core.cloud import replica
from dibekho.db.sync_schema import trigger_names


def _triggers(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}


def _outbox(conn) -> list[tuple]:
    return [tuple(r) for r in conn.execute("SELECT tbl, local_id, op FROM sync_outbox ORDER BY seq")]


def test_every_synced_table_has_its_triggers(conn):
    assert trigger_names() <= _triggers(conn)


def test_triggers_come_back_after_a_table_rebuild(tmp_path):
    path = tmp_path / "k.sqlite"
    c = db.connect(path)
    # what a migration that rebuilds a table does (008/009 did this to documents)
    c.execute("DROP TRIGGER sync_documents_ins")
    c.execute("DROP TRIGGER sync_documents_del")
    c.close()
    c = db.connect(path)
    assert trigger_names() <= _triggers(c)
    c.close()


def test_nothing_is_queued_in_local_mode(conn):
    with db.transaction(conn):
        pid = catalog.create_product(conn, "Keo A", spec="15kg", unit="thung")
        stock.insert_document(conn, "receipt", date(2026, 11, 1), [stock.Line(pid, 5)], code="HV001")
        db.set_meta(conn, "low_stock_default", "20")
    assert _outbox(conn) == []


def test_cloud_mode_queues_changes_and_pending_builds_cloud_rows(conn):
    replica.set_enabled(conn, True)
    with db.transaction(conn):
        pid = catalog.create_product(conn, "Keo A", spec="15kg", unit="thung")
        conn.execute("UPDATE products SET stock_note = 'mop' WHERE id = ?", (pid,))
        db.set_meta(conn, "low_stock_default", "20")
        db.set_meta(conn, "cloud_last_push_id", "9")  # this machine's own bookkeeping: never travels
    rows, last = replica.pending(conn)
    assert [r["stock_note"] for r in rows["products"]] == ["mop"]  # changed twice, travels once
    assert rows["products"][0]["active"] is True and len(rows["products"][0]["id"]) == 36
    keys = [r["key"] for r in rows["meta"]]
    assert "low_stock_default" in keys and "cloud_last_push_id" not in keys
    replica.clear_outbox(conn, last)
    assert replica.pending(conn)[0]["products"] == []


def test_a_document_travels_with_its_lines_and_movements_referencing_uuids(conn):
    replica.set_enabled(conn, True)
    with db.transaction(conn):
        pid = catalog.create_product(conn, "Keo A")
        doc = stock.insert_document(conn, "receipt", date(2026, 11, 1), [stock.Line(pid, 5)], code="HV001")
    rows, _ = replica.pending(conn)
    product_uid = replica.uid_for(conn, "products", pid, create=False)
    doc_uid = replica.uid_for(conn, "documents", doc, create=False)
    assert [r["document_id"] for r in rows["document_lines"]] == [doc_uid]
    assert {(r["product_id"], r["qty"]) for r in rows["stock_movements"]} == {(product_uid, 5)}


def test_delete_sends_the_uuid_and_a_reused_id_gets_a_new_one(conn):
    replica.set_enabled(conn, True)
    with db.transaction(conn):
        pid = catalog.create_product(conn, "Keo A")
    rows, last = replica.pending(conn)
    old_uid = rows["products"][0]["id"]
    replica.clear_outbox(conn, last)
    with db.transaction(conn):
        conn.execute("DELETE FROM products WHERE id = ?", (pid,))
        again = catalog.create_product(conn, "Mang B")
    assert again == pid  # SQLite handed the freed id to the new product
    rows, _ = replica.pending(conn)
    assert {"id": old_uid, "deleted": True} in rows["products"]
    new = [r for r in rows["products"] if not r["deleted"]]
    assert [r["name_vi"] for r in new] == ["Mang B"] and new[0]["id"] != old_uid


def test_rows_pulled_from_the_cloud_are_not_queued_again(conn):
    replica.set_enabled(conn, True)
    pid_uid = "11111111-1111-4111-8111-111111111111"
    replica.apply(conn, {"products": [{"id": pid_uid, "code": "SP001", "name_vi": "Keo A", "name_zh": "", "spec": "",
                                       "unit": "", "category": "", "min_stock": 0, "active": True,
                                       "created_at": "2026-11-01T08:00:00", "variant": "", "stock_note": "",
                                       "deleted": False}]})
    assert _outbox(conn) == []
    row = conn.execute("SELECT * FROM products").fetchone()
    assert (row["code"], row["active"], row["created_at"]) == ("SP001", 1, "2026-11-01 08:00:00")
    assert replica.local_for(conn, "products", pid_uid) == row["id"]
