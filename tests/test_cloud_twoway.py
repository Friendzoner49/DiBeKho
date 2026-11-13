"""Two machines syncing through the cloud's real tables (cloud/supabase/008_sync_rpc.sql on PGlite, core/cloud/twoway.py).

Each scenario ends with both machines and the cloud agreeing, and stock equal everywhere."""

from datetime import date

import pytest

from dibekho import db
from dibekho.core import catalog, receipts, stock
from dibekho.core.cloud import replica, twoway
from tests.pgdb import FakeCloud, Session, needs_pg

pytestmark = needs_pg
OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
VIEWER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


@pytest.fixture(scope="module")
def pg():
    s = Session()
    s.add_account(OWNER)
    s.add_account(VIEWER, "viewer")
    yield s
    s.close()


@pytest.fixture
def cloud(pg):
    for t in ("meta", "document_skipped_lines", "stock_movements", "document_lines", "documents", "ignored_lines",
              "product_aliases", "products", "customers", "suppliers"):
        pg.query(f"delete from public.{t}")
    return FakeCloud(pg)


def _machine(tmp_path, name):
    conn = db.connect(tmp_path / f"{name}.sqlite")
    replica.set_enabled(conn, True)
    return conn


def _sync(conn, cloud, device):
    return twoway.sync_round(conn, cloud, OWNER, device)


def _seed(conn):
    with db.transaction(conn):
        a = catalog.create_product(conn, "Keo A", spec="15kg", unit="thung")
        b = catalog.create_product(conn, "Mang B", spec="3mm", unit="cuon")
        catalog.upsert_customer(conn, "Cong ty A", phone="0900 000 001")
    receipts.save(conn, receipts.ReceiptInput(date(2026, 11, 1), receipts.SUPPLIER, supplier_name="Cua khau",
                                              lines=[receipts.ReceiptLineInput(50, a), receipts.ReceiptLineInput(20, b)]))
    return a, b


def _by_code(conn) -> dict:
    codes = {r["id"]: r["code"] for r in conn.execute("SELECT id, code FROM products")}
    return {(codes[p], loc): q for (p, loc), q in stock.stock_levels(conn, by_location=True).items() if q}


def _codes(conn, kind) -> list[str]:
    return sorted(r[0] for r in conn.execute("SELECT code FROM documents WHERE kind = ? AND status = 'active'", (kind,)))


def _pid(conn, code) -> int:
    return conn.execute("SELECT id FROM products WHERE code = ?", (code,)).fetchone()[0]


def _two(tmp_path, cloud):
    a = _machine(tmp_path, "a")
    _seed(a)
    replica.queue_all(a)  # the first push of a database that already holds data
    assert _sync(a, cloud, "A").pushed > 0
    b = _machine(tmp_path, "b")
    _sync(b, cloud, "B")
    assert _by_code(b) == _by_code(a)
    return a, b


def _settle(a, b, cloud):
    for conn, dev in ((a, "A"), (b, "B"), (a, "A")):
        _sync(conn, cloud, dev)
    assert _by_code(a) == _by_code(b)
    assert replica.pending(a)[0] == replica.pending(b)[0] == {t: [] for t in replica.BY_NAME}


def test_a_new_machine_gets_everything(tmp_path, cloud):
    a, b = _two(tmp_path, cloud)
    assert _codes(b, "receipt") == ["HV001"]
    assert b.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 2


def test_receipts_made_offline_on_both_machines_get_different_codes(tmp_path, cloud):
    a, b = _two(tmp_path, cloud)
    for conn, qty in ((a, 5), (b, 7)):
        receipts.save(conn, receipts.ReceiptInput(date(2026, 11, 2), receipts.SUPPLIER, supplier_name="Cua khau",
                                                  lines=[receipts.ReceiptLineInput(qty, _pid(conn, "SP001"))]))
    assert _codes(a, "receipt") == _codes(b, "receipt") == ["HV001", "HV002"]  # both offline: the same new code
    _sync(a, cloud, "A")
    r = _sync(b, cloud, "B")
    assert ("documents", "HV002", "HV003") in r.merged[0].renamed
    _settle(a, b, cloud)
    assert _codes(a, "receipt") == _codes(b, "receipt") == ["HV001", "HV002", "HV003"]
    assert _by_code(a)[("SP001", stock.MAIN)] == 50 + 5 + 7


def test_products_created_offline_on_both_machines_get_different_codes(tmp_path, cloud):
    a, b = _two(tmp_path, cloud)
    with db.transaction(a):
        catalog.create_product(a, "Keo C")
    with db.transaction(b):
        catalog.create_product(b, "Son D")
    _settle(a, b, cloud)
    names = lambda c: {r[0]: r[1] for r in c.execute("SELECT code, name_vi FROM products")}  # noqa: E731
    assert names(a) == names(b)
    assert {names(a)["SP003"], names(a)["SP004"]} == {"Keo C", "Son D"}


def test_the_same_delivery_note_read_on_two_machines_counts_once(tmp_path, cloud):
    a, b = _two(tmp_path, cloud)
    for conn in (a, b):
        with db.transaction(conn):
            stock.insert_document(conn, "delivery", date(2026, 11, 3), [stock.Line(_pid(conn, "SP001"), 4)], code="7",
                                  code_norm="7", source_hash="h7", source_file="phieu 7.xlsx")
            conn.execute("INSERT INTO scanned_files(hash, rel_path, document_id, status) "
                         "SELECT 'h7', 'phieu 7.xlsx', id, 'imported' FROM documents WHERE source_hash = 'h7'")
    _sync(a, cloud, "A")
    r = _sync(b, cloud, "B")
    assert r.merged[0].duplicates == 1
    _settle(a, b, cloud)
    assert _by_code(a)[("SP001", stock.MAIN)] == 50 - 4
    scan = b.execute("SELECT document_id FROM scanned_files WHERE hash = 'h7'").fetchone()[0]
    assert b.execute("SELECT source_hash FROM documents WHERE id = ?", (scan,)).fetchone()[0] == "h7"


def test_another_note_with_the_same_order_code_becomes_a_separate_order(tmp_path, cloud):
    a, b = _two(tmp_path, cloud)
    for conn, h in ((a, "ha"), (b, "hb")):
        with db.transaction(conn):
            stock.insert_document(conn, "delivery", date(2026, 11, 3), [stock.Line(_pid(conn, "SP001"), 1)], code="9",
                                  code_norm="9", source_hash=h)
    _sync(a, cloud, "A")
    assert _sync(b, cloud, "B").merged[0].separated == ["9"]
    _settle(a, b, cloud)
    assert sorted(r[0] for r in a.execute("SELECT code_norm FROM documents WHERE kind = 'delivery'")) == ["9", "9#2"]
    assert _by_code(a)[("SP001", stock.MAIN)] == 50 - 2


def test_both_machines_editing_one_product_is_a_conflict_that_holds_only_that_product(tmp_path, cloud):
    a, b = _two(tmp_path, cloud)
    a.execute("UPDATE products SET stock_note = 'tu A' WHERE code = 'SP001'")
    _sync(a, cloud, "A")
    b.execute("UPDATE products SET stock_note = 'tu B' WHERE code = 'SP001'")
    with db.transaction(b):
        catalog.create_product(b, "Keo E")  # unrelated work keeps syncing
    r = _sync(b, cloud, "B")
    [c] = r.merged[0].conflicts
    assert (c.local["stock_note"], c.cloud["stock_note"]) == ("tu B", "tu A")
    _sync(a, cloud, "A")
    assert a.execute("SELECT COUNT(*) FROM products WHERE name_vi = 'Keo E'").fetchone()[0] == 1
    assert a.execute("SELECT stock_note FROM products WHERE code = 'SP001'").fetchone()[0] == "tu A"
    twoway.resolve(b, twoway.conflicts(b)[0], keep_mine=True)
    _settle(a, b, cloud)
    assert a.execute("SELECT stock_note FROM products WHERE code = 'SP001'").fetchone()[0] == "tu B"
    assert twoway.conflicts(b) == []


def test_taking_the_clouds_version_ends_the_conflict(tmp_path, cloud):
    a, b = _two(tmp_path, cloud)
    a.execute("UPDATE products SET stock_note = 'tu A' WHERE code = 'SP001'")
    _sync(a, cloud, "A")
    b.execute("UPDATE products SET stock_note = 'tu B' WHERE code = 'SP001'")
    _sync(b, cloud, "B")
    twoway.resolve(b, twoway.conflicts(b)[0], keep_mine=False)
    _settle(a, b, cloud)
    assert b.execute("SELECT stock_note FROM products WHERE code = 'SP001'").fetchone()[0] == "tu A"


def test_a_push_whose_reply_was_lost_is_not_sent_twice_nor_a_conflict(tmp_path, cloud):
    a, b = _two(tmp_path, cloud)
    receipts.save(a, receipts.ReceiptInput(date(2026, 11, 4), receipts.SUPPLIER, supplier_name="Cua khau",
                                           lines=[receipts.ReceiptLineInput(3, _pid(a, "SP002"))]))
    cloud.lose_next_reply = True
    batch, seq, hold = twoway.prepare(a)
    with pytest.raises(Exception, match="timed out"):
        twoway.send(cloud, OWNER, "A", twoway.cursor(a), batch)
    r = _sync(a, cloud, "A")
    assert r.merged[0].conflicts == [] and r.pushed == 0
    _settle(a, b, cloud)
    assert _codes(b, "receipt") == ["HV001", "HV002"]


def test_a_push_after_someone_else_wrote_is_refused_then_retried(tmp_path, cloud):
    a, b = _two(tmp_path, cloud)
    a.execute("UPDATE products SET stock_note = 'x' WHERE code = 'SP002'")
    batch, seq, hold = twoway.prepare(a)
    b.execute("UPDATE customers SET address = 'Ha Noi'")
    _sync(b, cloud, "B")
    answer = twoway.send(cloud, OWNER, "A", twoway.cursor(a), batch)
    assert answer["ok"] is False and answer["reason"] == "behind"
    _settle(a, b, cloud)
    assert a.execute("SELECT address FROM customers").fetchone()[0] == "Ha Noi"


def test_count_decisions_from_both_machines_are_kept(tmp_path, cloud):
    a, b = _two(tmp_path, cloud)
    db.set_meta(a, "count_checked", "ha")
    _sync(a, cloud, "A")
    db.set_meta(b, "count_checked", "hb")
    _settle(a, b, cloud)
    for conn in (a, b):
        assert set(db.get_meta(conn, "count_checked").split(",")) == {"ha", "hb"}


def test_a_reset_on_one_machine_reaches_the_other_without_breaking_its_scans(tmp_path, cloud):
    a, b = _two(tmp_path, cloud)
    hv = b.execute("SELECT id FROM documents WHERE code = 'HV001'").fetchone()[0]
    b.execute("INSERT INTO scanned_files(hash, rel_path, document_id, status) VALUES ('x', 'x.xlsx', ?, 'imported')", (hv,))
    with db.transaction(a):
        for t in ("stock_movements", "document_lines", "documents"):
            a.execute(f"DELETE FROM {t}")
    _settle(a, b, cloud)
    assert b.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    assert b.execute("SELECT COUNT(*) FROM scanned_files").fetchone()[0] == 0


def test_only_the_desktop_account_may_push(tmp_path, cloud):
    a = _machine(tmp_path, "a")
    _seed(a)
    replica.queue_all(a)
    batch, seq, hold = twoway.prepare(a)
    with pytest.raises(Exception, match="not allowed"):
        twoway.send(cloud, VIEWER, "A", 0, batch)


def test_both_machines_pricing_an_old_return_is_no_conflict(tmp_path, cloud):
    """0.5.1 fills in the price of returns saved without one: two main machines doing it before they see each
    other's push write the same values, which is not a conflict (no question for the user)."""
    a, b = _two(tmp_path, cloud)
    with db.transaction(a):
        cust = a.execute("SELECT id FROM customers").fetchone()[0]
        stock.insert_document(a, "delivery", date(2026, 11, 2), [stock.Line(_pid(a, "SP001"), 5, unit_price=100,
                                                                            amount=500)],
                              code="7", code_norm="7", customer_id=cust)
        old = stock.insert_document(a, "receipt", date(2026, 11, 3), [stock.Line(_pid(a, "SP001"), 2)], code="HV002",
                                    code_norm="HV002", customer_id=cust)
        a.execute("UPDATE documents SET receipt_source = 'return', ref_code = '7', prices_read = 0 WHERE id = ?",
                  (old,))
    _settle(a, b, cloud)
    assert receipts.backfill_return_prices(a) == 1 and receipts.backfill_return_prices(b) == 1
    for conn, dev in ((a, "A"), (b, "B"), (a, "A"), (b, "B")):
        assert all(not m.conflicts for m in _sync(conn, cloud, dev).merged)
    assert twoway.conflicts(a) == twoway.conflicts(b) == []
    for conn in (a, b):
        got = conn.execute("SELECT l.unit_price, l.amount FROM document_lines l JOIN documents d ON d.id = l.document_id "
                           "WHERE d.receipt_source = 'return'").fetchone()
        assert tuple(got) == (100, 200)
