"""The owner's writes from the web (cloud/supabase/009_web_rpc.sql) against the app's own core, side by side.

Each test: machine S holds the shop's data in cloud mode; TWIN is a copy of it that stays local. The same operation
runs through the core function on TWIN and through the web function on the cloud; S then pulls with the normal
two-way sync. S and TWIN must end with the same documents, lines, movements, products, customers and stock.
Runs on PGlite (tests/pg); skipped when it is not installed."""

import json
import sqlite3
from datetime import date

import pytest

from dibekho import db
from dibekho.core import catalog, receipts, stock
from dibekho.core.cloud import replica, twoway
from tests.pgdb import WEB_FILES, FakeCloud, PgError, Session, needs_pg

pytestmark = needs_pg
OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
STAFF = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
FILES = WEB_FILES
TABLES = ("meta", "document_skipped_lines", "stock_movements", "document_lines", "documents", "ignored_lines",
          "product_aliases", "products", "customers", "suppliers")


@pytest.fixture(scope="module")
def pg():
    s = Session(FILES)
    s.add_account(OWNER)
    s.add_account(STAFF, "editor")
    yield s
    s.close()


@pytest.fixture
def cloud(pg):
    for t in TABLES:
        pg.query(f"delete from public.{t}")
    return FakeCloud(pg)


def _seed(conn):
    with db.transaction(conn):
        a = catalog.create_product(conn, "Keo A", spec="15kg/Thùng", category="Keo")
        b = catalog.create_product(conn, "Màng B", spec="3mm", unit="cuộn", category="Màng")
        catalog.create_product(conn, "Màng B", spec="3mm", unit="cuộn")  # a duplicate, merged in a test
        catalog.upsert_customer(conn, "Công ty A", phone="0900 000 001")
        catalog.upsert_customer(conn, "Cty A (cũ)", phone="0900 000 002")
        catalog.upsert_customer(conn, "Khách Mẫu", phone="0900 000 003")
        stock.insert_document(conn, "delivery", date(2026, 11, 3), [stock.Line(a, 4), stock.Line(b, 2)], code="76",
                              code_norm="76", customer_id=1, source_hash="h76", location_set=False)
    receipts.save(conn, receipts.ReceiptInput(date(2026, 11, 1), receipts.SUPPLIER, supplier_name="Cửa khẩu Đông",
                                              lines=[receipts.ReceiptLineInput(50, a), receipts.ReceiptLineInput(20, b)]))
    with db.transaction(conn):
        stock.transfer(conn, date(2026, 11, 2), stock.MAIN, stock.OFFICE, [stock.Line(a, 5)])


@pytest.fixture
def shop(tmp_path, cloud):
    """(S in cloud mode, TWIN local copy, call(fn, **args) -> the web function's answer)."""
    s = db.connect(tmp_path / "s.sqlite")
    replica.set_enabled(s, True)
    _seed(s)
    replica.queue_all(s)
    assert twoway.sync_round(s, cloud, OWNER, "S").pushed > 0
    twin = sqlite3.connect(str(tmp_path / "twin.sqlite"))
    s.backup(twin)
    twin.close()
    twin = db.connect(tmp_path / "twin.sqlite")
    replica.set_enabled(twin, False)

    def call(fn, account=OWNER, **args):
        params, parts = [], []
        for i, (key, (value, cast)) in enumerate(args.items(), start=1):
            params.append(json.dumps(value) if cast == "jsonb" else value)
            parts.append(f"{key} => ${i}::{cast}")
        return cloud.session.query(f"select public.{fn}({', '.join(parts)}) as r", params, sub=account)[0]["r"]

    yield s, twin, call, cloud


def _uid(s, table, local_id):
    return replica.uid_for(s, table, local_id, create=False)


def _pid(conn, code):
    return conn.execute("SELECT id FROM products WHERE code = ?", (code,)).fetchone()[0]


def _doc(conn, kind, code):
    return conn.execute("SELECT id FROM documents WHERE kind = ? AND code = ? AND status = 'active'",
                        (kind, code)).fetchone()[0]


def _pull(s, cloud):
    r = twoway.sync_round(s, cloud, OWNER, "S")
    assert all(not m.conflicts for m in r.merged)
    return r


def _picture(conn) -> dict:
    """Everything that matters, by codes and names (ids differ between the two machines)."""
    q = lambda sql: sorted(tuple(r) for r in conn.execute(sql))  # noqa: E731
    doc = ("d.kind, d.code, d.code_norm, d.status, d.doc_date, d.note, d.location_id, d.to_location_id, d.location_set,"
           " d.receipt_source, d.ref_code, COALESCE(c.name, ''), COALESCE(s.name, ''), d.closed_at IS NULL")
    return {
        "documents": q(f"SELECT {doc} FROM documents d LEFT JOIN customers c ON c.id = d.customer_id "
                       "LEFT JOIN suppliers s ON s.id = d.supplier_id"),
        "lines": q("SELECT d.kind, d.code, d.status, l.line_no, p.code, l.qty, l.note, l.location_id FROM document_lines l "
                   "JOIN documents d ON d.id = l.document_id JOIN products p ON p.id = l.product_id"),
        "movements": q("SELECT d.kind, d.code, d.status, p.code, m.qty, m.kind, m.occurred_on, m.location_id "
                       "FROM stock_movements m JOIN documents d ON d.id = m.document_id "
                       "JOIN products p ON p.id = m.product_id"),
        "products": q("SELECT code, name_vi, name_zh, spec, unit, category, variant, stock_note, active, min_stock "
                      "FROM products"),
        "customers": q("SELECT name, phone FROM customers"),
        "suppliers": q("SELECT name FROM suppliers"),
        "meta": q("SELECT key, value FROM meta WHERE key IN ('freed_codes', 'product_code_max')"),
        "stock": sorted(stock.stock_levels(conn, by_location=True).items()),
    }


def _same(s, twin, cloud):
    _pull(s, cloud)
    a, b = _picture(s), _picture(twin)
    # product ids differ: compare stock by code
    for pic, conn in ((a, s), (b, twin)):
        codes = {r[0]: r[1] for r in conn.execute("SELECT id, code FROM products")}
        pic["stock"] = sorted(((codes[p], loc), q) for (p, loc), q in pic["stock"] if q)
    for key in a:
        assert a[key] == b[key], key


def _lines(s, *rows):
    return [{"product_id": _uid(s, "products", _pid(s, code)), "qty": qty, "note": note} for code, qty, note in rows]


# ---------------------------------------------------------------- documents

def test_goods_in_from_a_supplier_typed_differently_reuses_the_supplier(shop):
    s, twin, call, cloud = shop
    receipts.save(twin, receipts.ReceiptInput(date(2026, 11, 5), receipts.SUPPLIER, supplier_name="  CỬA KHẨU  đông ",
                                              note="lô  2", location_id=stock.OFFICE,
                                              lines=[receipts.ReceiptLineInput(12, _pid(twin, "SP001"), note="góc  kho"),
                                                     receipts.ReceiptLineInput(3.5, _pid(twin, "SP002"))]))
    out = call("web_receipt", p=({"doc_date": "2026-11-05", "source": "supplier", "supplier_name": "  CỬA KHẨU  đông ",
                                  "note": "lô  2", "location_id": 2,
                                  "lines": _lines(s, ("SP001", 12, "góc  kho"), ("SP002", 3.5, ""))}, "jsonb"))
    assert out["code"] == "HV002"
    _same(s, twin, cloud)


def test_goods_returned_by_a_customer(shop):
    s, twin, call, cloud = shop
    cust = twin.execute("SELECT id FROM customers WHERE name = 'Khách Mẫu'").fetchone()[0]
    receipts.save(twin, receipts.ReceiptInput(date(2026, 11, 6), receipts.RETURN, customer_id=cust, ref_code="76",
                                              lines=[receipts.ReceiptLineInput(3, _pid(twin, "SP001"), unit_price=12500.5),
                                                     receipts.ReceiptLineInput(1, _pid(twin, "SP002"))]))
    lines = _lines(s, ("SP001", 3, ""), ("SP002", 1, ""))
    lines[0]["unit_price"] = 12500.5  # what the customer gets back per unit; the second line has none
    lines[1]["unit_price"] = None
    call("web_receipt", p=({"doc_date": "2026-11-06", "source": "return", "ref_code": "76",
                            "customer_id": _uid(s, "customers", s.execute(
                                "SELECT id FROM customers WHERE name = 'Khách Mẫu'").fetchone()[0]),
                            "lines": lines}, "jsonb"))
    _same(s, twin, cloud)
    got = s.execute("SELECT l.unit_price, l.amount, d.prices_read FROM document_lines l JOIN documents d "
                    "ON d.id = l.document_id WHERE d.receipt_source = 'return' ORDER BY l.line_no").fetchall()
    assert [tuple(r) for r in got] == [(12500.5, 37501.5, 1), (None, None, 1)]
    # a price on a supplier's receipt is ignored, like receipts.save
    lines = _lines(s, ("SP001", 2, ""))
    lines[0]["unit_price"] = 999
    call("web_receipt", p=({"doc_date": "2026-11-07", "source": "supplier", "supplier_name": "Cửa khẩu Đông",
                            "lines": lines}, "jsonb"))
    twoway.sync_round(s, cloud, OWNER, "S")
    assert s.execute("SELECT COUNT(*) FROM document_lines l JOIN documents d ON d.id = l.document_id WHERE "
                     "d.receipt_source = 'supplier' AND l.unit_price IS NOT NULL").fetchone()[0] == 0


def test_editing_a_receipt_keeps_its_code(shop):
    s, twin, call, cloud = shop
    receipts.save(twin, receipts.ReceiptInput(date(2026, 11, 1), receipts.SUPPLIER, supplier_name="Cửa khẩu Đông",
                                              lines=[receipts.ReceiptLineInput(45, _pid(twin, "SP001"))]),
                  replaces=_doc(twin, "receipt", "HV001"))
    out = call("web_receipt", p=({"doc_date": "2026-11-01", "source": "supplier", "supplier_name": "Cửa khẩu Đông",
                                  "lines": _lines(s, ("SP001", 45, ""))}, "jsonb"),
               p_replaces=(_uid(s, "documents", _doc(s, "receipt", "HV001")), "uuid"))
    assert out["code"] == "HV001"
    _same(s, twin, cloud)


def test_a_receipt_made_on_the_web_gets_its_excel_file_on_the_machine(shop, tmp_path):
    s, twin, call, cloud = shop
    from dibekho.core.workspace import Workspace

    ws = Workspace(tmp_path / "ws")
    call("web_receipt", p=({"doc_date": "2026-11-07", "source": "supplier", "supplier_name": "Công ty mẹ",
                            "lines": _lines(s, ("SP002", 8, ""))}, "jsonb"))
    r = _pull(s, cloud)
    for m in r.merged:
        twoway.export_renamed(s, ws, m)
    assert (ws.output / receipts.FOLDER / "HangVe_HV002_2026-11-07.xlsx").exists()
    assert twoway.queued_count(s) == 0  # writing the file changed nothing to send back


def test_a_receipt_with_new_products_creates_them_like_the_app(shop):
    s, twin, call, cloud = shop
    NP = receipts.NewProduct
    receipts.save(twin, receipts.ReceiptInput(date(2026, 11, 8), receipts.SUPPLIER, supplier_name="Công ty mẹ",
                                              lines=[receipts.ReceiptLineInput(10, new=NP("Sơn  lót", "底漆", "18L/Thùng",
                                                                                          category="Sơn")),
                                                     receipts.ReceiptLineInput(4, _pid(twin, "SP001")),
                                                     receipts.ReceiptLineInput(2, new=NP("Keo A", spec="15kg/Thùng",
                                                                                         variant="Đỏ", unit="xô"))]))
    out = call("web_receipt", p=({"doc_date": "2026-11-08", "source": "supplier", "supplier_name": "Công ty mẹ",
                                  "lines": [{"new": {"name_vi": "Sơn  lót", "name_zh": "底漆", "spec": "18L/Thùng",
                                                     "category": "Sơn"}, "qty": 10, "note": ""},
                                            *_lines(s, ("SP001", 4, "")),
                                            {"new": {"name_vi": "Keo A", "spec": "15kg/Thùng", "variant": "Đỏ",
                                                     "unit": "xô"}, "qty": 2, "note": ""}]}, "jsonb"))
    assert out["code"] == "HV002"
    _same(s, twin, cloud)
    assert {r[0] for r in s.execute("SELECT code FROM products")} >= {"SP004", "SP005"}


def test_a_receipt_that_fails_leaves_no_new_product(shop, pg):
    s, twin, call, cloud = shop
    before = pg.query("select count(*) as n from public.products")[0]["n"]
    for lines in ([{"new": {"name_vi": "Hàng X"}, "qty": 1}, {"new": {"name_vi": "hàng  x"}, "qty": 2}],
                  [{"new": {"name_vi": "Hàng X"}, "qty": 1}, {"product_id": None, "qty": 1}],
                  [{"new": {"name_vi": "Hàng X"}, "qty": 0}],
                  [{"new": {"name_vi": "  "}, "qty": 1}]):
        with pytest.raises(PgError):
            call("web_receipt", p=({"doc_date": "2026-11-08", "source": "supplier", "supplier_name": "Công ty mẹ",
                                    "lines": lines}, "jsonb"))
    assert pg.query("select count(*) as n from public.products")[0]["n"] == before
    # the code a failed receipt would have used is still the next one
    assert call("web_product_add", p=({"name_vi": "Hàng X"}, "jsonb"))["code"] == "SP004"


def test_the_web_can_tell_the_new_receipt_function_is_there(shop):
    s, twin, call, cloud = shop
    assert cloud.session.query("select public.web_api_version() as v", sub=OWNER)[0]["v"] >= 10


def test_transfer_and_editing_it(shop):
    s, twin, call, cloud = shop
    with db.transaction(twin):
        stock.transfer(twin, date(2026, 11, 8), stock.OFFICE, stock.MAIN, [stock.Line(_pid(twin, "SP001"), 2, note="trả")],
                       note="về kho")
    with db.transaction(twin):
        stock.transfer(twin, date(2026, 11, 2), stock.MAIN, stock.OFFICE, [stock.Line(_pid(twin, "SP001"), 6)],
                       replaces=_doc(twin, "transfer", "CH001"))
    out = call("web_transfer", p=({"date": "2026-11-08", "from": 2, "to": 1, "note": "về kho",
                                   "lines": _lines(s, ("SP001", 2, "trả"))}, "jsonb"))
    assert out["code"] == "CH002"
    call("web_transfer", p=({"date": "2026-11-02", "from": 1, "to": 2, "lines": _lines(s, ("SP001", 6, ""))}, "jsonb"),
         p_replaces=(_uid(s, "documents", _doc(s, "transfer", "CH001")), "uuid"))
    _same(s, twin, cloud)


def test_trial_use(shop):
    s, twin, call, cloud = shop
    with db.transaction(twin):
        stock.record_trial_use(twin, date(2026, 11, 9), stock.OFFICE, [stock.Line(_pid(twin, "SP001"), 1)], note="mẫu")
    assert call("web_trial", p=({"date": "2026-11-09", "location": 2, "note": "mẫu",
                                 "lines": _lines(s, ("SP001", 1, ""))}, "jsonb"))["code"] == "DT001"
    _same(s, twin, cloud)


def test_cancelling_and_choosing_where_a_note_was_taken_from(shop):
    s, twin, call, cloud = shop
    with db.transaction(twin):
        stock.set_location(twin, _doc(twin, "delivery", "76"), stock.OFFICE)
        stock.close_document(twin, _doc(twin, "transfer", "CH001"), "cancelled")
    call("web_set_location", p_doc=(_uid(s, "documents", _doc(s, "delivery", "76")), "uuid"), p_location=(2, "integer"))
    call("web_cancel", p_doc=(_uid(s, "documents", _doc(s, "transfer", "CH001")), "uuid"))
    _same(s, twin, cloud)
    with pytest.raises(PgError, match="đã huỷ"):
        call("web_cancel", p_doc=(_uid(s, "documents", s.execute(
            "SELECT id FROM documents WHERE code = 'CH001'").fetchone()[0]), "uuid"))


def test_stock_count_of_one_place_and_of_the_total(shop):
    s, twin, call, cloud = shop
    a, b = _pid(twin, "SP001"), _pid(twin, "SP002")
    with db.transaction(twin):
        stock.stock_count(twin, date(2026, 11, 10), {(a, stock.MAIN): 40, (b, stock.OFFICE): 0}, note="cuối tháng")
    with db.transaction(twin):
        stock.stock_count(twin, date(2026, 11, 10), {b: 17})
    us = lambda code: _uid(s, "products", _pid(s, code))  # noqa: E731
    call("web_stock_count", p=({"count_date": "2026-11-10", "note": "cuối tháng", "lines": [
        {"product_id": us("SP001"), "location_id": 1, "qty": 40},
        {"product_id": us("SP002"), "location_id": 2, "qty": 0}]}, "jsonb"))
    call("web_stock_count", p=({"count_date": "2026-11-10", "lines": [
        {"product_id": us("SP002"), "location_id": None, "qty": 17}]}, "jsonb"))
    _same(s, twin, cloud)


# ---------------------------------------------------------------- products and customers

def test_add_edit_and_merge_products_and_reuse_the_freed_code(shop):
    s, twin, call, cloud = shop
    with db.transaction(twin):
        catalog.create_product(twin, "Sơn chống thấm", spec="20kg/Thùng", category="Sơn", variant="xám")
        catalog.update_product(twin, _pid(twin, "SP002"), stock_note="hạn 2027", active=0)
        catalog.merge_products(twin, _pid(twin, "SP003"), _pid(twin, "SP002"))
        catalog.create_product(twin, "Bột trét")  # takes the code freed by the merge
    out = call("web_product_add", p=({"name_vi": "Sơn chống thấm", "spec": "20kg/Thùng", "category": "Sơn",
                                      "variant": "xám"}, "jsonb"))
    assert out["code"] == "SP004"
    call("web_product_edit", p_id=(_uid(s, "products", _pid(s, "SP002")), "uuid"),
         p=({"stock_note": "hạn 2027", "active": False}, "jsonb"))
    assert call("web_product_merge", p_a=(_uid(s, "products", _pid(s, "SP003")), "uuid"),
                p_b=(_uid(s, "products", _pid(s, "SP002")), "uuid"))["dropped"] == "SP003"
    assert call("web_product_add", p=({"name_vi": "Bột trét"}, "jsonb"))["code"] == "SP003"
    _same(s, twin, cloud)


def test_adding_the_same_product_twice_asks_first(shop):
    s, twin, call, cloud = shop
    with pytest.raises(PgError, match="SP001"):
        call("web_product_add", p=({"name_vi": "KEO a", "spec": "15KG/thùng"}, "jsonb"))
    assert call("web_product_add", p=({"name_vi": "KEO a", "spec": "15KG/thùng", "allow_duplicate": True},
                                      "jsonb"))["code"] == "SP004"


def test_merge_customers(shop):
    s, twin, call, cloud = shop
    ids = lambda conn: [r[0] for r in conn.execute(  # noqa: E731
        "SELECT id FROM customers WHERE name IN ('Công ty A', 'Cty A (cũ)') ORDER BY id")]
    with db.transaction(twin):
        catalog.merge_customers(twin, ids(twin), "Công ty A")
    call("web_customer_merge", p_ids=([_uid(s, "customers", i) for i in ids(s)], "uuid[]"), p_name=("Công ty A", "text"))
    _same(s, twin, cloud)


def test_unit_guess_matches_the_app():
    s = Session(["cloud/supabase/001_init.sql", "cloud/supabase/007_core.sql", "cloud/supabase/008_sync_rpc.sql",
                 "cloud/supabase/009_web_rpc.sql"])
    try:
        for spec in ("10KG/Thùng", "1m*20m/ cuộn", "Gói", "20 kg / Xô", "", "3mm"):
            got = s.query("select public.dbk_guess_unit($1) as u", [spec])[0]["u"]
            assert got == catalog.guess_unit(spec), spec
        for text in ("Đông Hà  Nội", "CỬA KHẨU", "Màng PPE ơ ư"):
            got = s.query("select public.dbk_unaccent($1) as u", [text])[0]["u"]
            from dibekho.core.text import clean, unaccent

            assert got == unaccent(text), text
            assert s.query("select public.dbk_clean($1) as u", [text])[0]["u"] == clean(text)
    finally:
        s.close()


# ---------------------------------------------------------------- who may write

def test_only_the_owner_writes_and_only_once_the_data_is_shared(shop, pg):
    s, twin, call, cloud = shop
    with pytest.raises(PgError, match="chủ"):
        call("web_trial", account=STAFF, p=({"date": "2026-11-09", "location": 1,
                                             "lines": _lines(s, ("SP001", 1, ""))}, "jsonb"))
    with pytest.raises(PgError):
        pg.query("select public.web_cancel(gen_random_uuid())")  # no account at all (not even a role)
    with pytest.raises(PgError):  # helpers are not callable from outside
        pg.query("select public.dbk_set_meta('x', 'y')", sub=OWNER)
    for t in TABLES:
        pg.query(f"delete from public.{t}")
    with pytest.raises(PgError, match="chưa được bật"):
        call("web_product_add", p=({"name_vi": "X"}, "jsonb"))


def test_times_follow_the_shops_clock(shop, pg):
    s, twin, call, cloud = shop
    assert db.get_meta(s, twoway.CLOCK_KEY) == str(twoway.clock_offset())
    call("web_trial", p=({"date": "2026-11-09", "location": 1, "lines": _lines(s, ("SP001", 1, ""))}, "jsonb"))
    _pull(s, cloud)
    made = s.execute("SELECT created_at FROM documents WHERE kind = 'trial'").fetchone()[0]
    here = s.execute("SELECT datetime('now', 'localtime')").fetchone()[0]
    from datetime import datetime

    gap = abs((datetime.fromisoformat(here) - datetime.fromisoformat(made)).total_seconds())
    assert gap < 120, (made, here)


def test_a_receipt_edited_on_the_web_gets_a_new_file_and_the_old_one_stays(shop, tmp_path):
    s, twin, call, cloud = shop
    from dibekho.core.workspace import Workspace

    ws = Workspace(tmp_path / "ws")
    old = receipts.export_file(s, ws, _doc(s, "receipt", "HV001"))  # the file the app made when it was saved
    _pull(s, cloud)  # the file name travels like any change
    before = old.read_bytes()
    call("web_receipt", p=({"doc_date": "2026-11-01", "source": "supplier", "supplier_name": "Cửa khẩu Đông",
                            "lines": _lines(s, ("SP001", 45, ""))}, "jsonb"),
         p_replaces=(_uid(s, "documents", _doc(s, "receipt", "HV001")), "uuid"))
    for m in _pull(s, cloud).merged:
        twoway.export_renamed(s, ws, m)
    new = ws.output / receipts.FOLDER / "HangVe_HV001_2026-11-01_2.xlsx"
    assert new.exists() and old.read_bytes() == before
    assert s.execute("SELECT source_file FROM documents WHERE code = 'HV001' AND status = 'active'").fetchone()[0] == new.name


def test_the_owner_s_stock_issue_note_on_the_web_takes_the_stock_at_once(shop):
    """cloud 015 (user, 14/11/2026): W + the next order number, the customer found by phone, one line per product with
    its price, the stock taken from each place; the staff cannot."""
    s, _, call, cloud = shop
    a, b = _pid(s, "SP001"), _pid(s, "SP002")
    before = stock.stock_levels(s, by_location=True)
    p = {"doc_date": "2026-11-14", "customer": "Cty khác tên", "phone": "+84 900 000 001", "contact": "Anh B",
         "address": "", "lines": [
             {"product_id": _uid(s, "products", a), "qty_main": 3, "qty_office": 2, "unit_price": 100000, "note": "sáng"},
             {"product_id": _uid(s, "products", b), "qty_main": 0, "qty_office": 1, "unit_price": None, "note": ""}]}
    with pytest.raises(PgError, match="chủ"):
        call("web_issue", account=STAFF, p=(p, "jsonb"))
    made = call("web_issue", p=(p, "jsonb"))
    assert made["code"] == "W77"  # the seed's last order is 76
    assert call("web_issue", p=({**p, "lines": p["lines"][1:]}, "jsonb"))["code"] == "W78"
    _pull(s, cloud)
    doc = s.execute("SELECT d.*, c.name AS customer FROM documents d JOIN customers c ON c.id = d.customer_id "
                    "WHERE d.code = 'W77'").fetchone()
    assert (doc["kind"], doc["status"], doc["location_set"], doc["customer"], doc["note_total"]) == (
        "delivery", "active", 1, "Công ty A", 500000)
    lines = s.execute("SELECT line_no, qty, unit_price, amount, location_id, note FROM document_lines "
                      "WHERE document_id = ? ORDER BY line_no", (doc["id"],)).fetchall()
    assert [tuple(r) for r in lines] == [(9, 5, 100000, 500000, None, "sáng"), (10, 1, None, None, 2, "")]
    after = stock.stock_levels(s, by_location=True)
    assert before[(a, stock.MAIN)] - after[(a, stock.MAIN)] == 3
    assert before.get((a, stock.OFFICE), 0) - after[(a, stock.OFFICE)] == 2
    assert before.get((b, stock.OFFICE), 0) - after[(b, stock.OFFICE)] == 2  # W77 and W78 took one each
    from dibekho.core import issues
    assert issues.new_code(s) == "A79"  # the app goes on after the web's numbers
