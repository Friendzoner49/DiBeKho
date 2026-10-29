"""Version 0.4.0 (24/10/2026): two places (Kho tổng, Văn phòng) with stock counts per place and transfers,
the place each delivery note was taken from, the default alarm level (below 30), a note kept with each
product's stock, and money in the statistics and the Excel exports."""

import os
import sqlite3
from datetime import date

import openpyxl
import pytest

from dibekho import db, i18n
from dibekho.core import catalog, deliveries, queries, receipts, stats, transfer
from dibekho.core.stock import (
    MAIN,
    OFFICE,
    Line,
    close_document,
    is_low,
    low_stock_default,
    record_trial_use,
    set_location,
    stock_count,
    stock_levels,
)
from dibekho.core.stock import transfer as move_goods
from dibekho.core.workspace import Workspace
from dibekho.excel import master_data, report
from tests.conftest import make_note
from tests.test_prices import PAINT, SAND, SHIPPING, doc, known
from tests.test_receipts import PRICE_COLUMNS_DROP

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def vietnamese():
    i18n.set_language("vi")


def places(conn, pid):
    levels = stock_levels(conn, by_location=True)
    return levels.get((pid, MAIN), 0), levels.get((pid, OFFICE), 0)


def no_movement_without_place(conn):
    return conn.execute("SELECT COUNT(*) FROM stock_movements WHERE location_id IS NULL").fetchone()[0] == 0


def two_notes(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="1", day="02-10-2026", lines=[PAINT, SAND], extra_rows=[SHIPPING])
    make_note(ws.deliveries / "b.xlsx", code="2", day="05-10-2026", lines=[PAINT])
    known(conn, ws)
    ids = {r["name_zh"]: r["id"] for r in conn.execute("SELECT id, name_zh FROM products")}
    return ids["背水涂"], ids["固沙剂"]


# ---- upgrade ----------------------------------------------------------------------------------------------

def test_a_0_3_0_database_is_upgraded_everything_in_the_main_warehouse(tmp_path):
    ws = Workspace(tmp_path / "DiBeKho")
    ws.ensure()
    conn = db.connect(ws.db_path)
    a, b = two_notes(conn, ws)
    before = stock_levels(conn)
    conn.close()
    raw = sqlite3.connect(ws.db_path)
    for sql in (*PRICE_COLUMNS_DROP, "PRAGMA user_version = 6"):
        raw.execute(sql)
    raw.commit()
    raw.close()

    conn = db.connect(ws.db_path)  # 6 -> 7 -> 8, documents rebuilt with foreign keys off
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.schema_version()
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert stock_levels(conn) == before and no_movement_without_place(conn)
    assert places(conn, a) == (before[a], 0)
    # recorded earlier = place known (Kho tổng); nothing waits in Cần xử lý
    assert deliveries.unplaced_count(conn) == 0
    deliveries.scan(conn, ws)
    assert doc(conn, "1")["fee_amount"] == 190000  # prices read again after the rebuild
    with db.transaction(conn):  # the kinds added by 008 and 009 are both allowed after the upgrade
        move_goods(conn, date(2026, 10, 6), MAIN, OFFICE, [Line(a, 1)])
        record_trial_use(conn, date(2026, 10, 6), MAIN, [Line(a, 1)])


# ---- delivery notes ---------------------------------------------------------------------------------------

def test_a_new_note_waits_for_its_place_and_keeps_it_when_read_again(conn, ws):
    a, b = two_notes(conn, ws)
    assert stock_levels(conn)[a] == -6  # the total is right from the start
    assert [d["code"] for d in deliveries.unplaced(conn)] == ["1", "2"]
    assert deliveries.scan(conn, ws).pending == 0  # files are done; places are counted apart (sidebar)
    one = doc(conn, "1")["id"]
    with db.transaction(conn):
        set_location(conn, one, OFFICE)
    assert places(conn, a) == (-3, -3) and places(conn, b) == (0, -2)
    assert [d["code"] for d in deliveries.unplaced(conn)] == ["2"]

    deliveries.reread_document(conn, ws, one)  # read again: same place, not asked again
    deliveries.scan(conn, ws)
    again = doc(conn, "1")
    assert again["id"] != one and (again["location_id"], again["location_set"]) == (OFFICE, 1)
    assert places(conn, a) == (-3, -3) and no_movement_without_place(conn)

    with db.transaction(conn):
        close_document(conn, again["id"])
    assert places(conn, a) == (-3, 0) and places(conn, b) == (0, 0)


def test_a_reused_order_code_does_not_take_the_place_of_an_old_order(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="1", day="02-10-2025", lines=[PAINT])
    known(conn, ws)
    old = doc(conn, "1")["id"]
    with db.transaction(conn):
        set_location(conn, old, OFFICE)
    deliveries.reread_document(conn, ws, old)  # old order replaced...
    (ws.deliveries / "a.xlsx").unlink(missing_ok=True)
    for f in ws.deliveries_done.rglob("*.xlsx"):
        f.unlink()
    deliveries.scan(conn, ws)
    make_note(ws.deliveries / "b.xlsx", code="1", day="02-10-2026", lines=[SAND])  # ...a new order, same code
    known(conn, ws)
    assert doc(conn, "1")["location_set"] == 0  # asked again


def test_an_edited_note_keeps_the_place_of_the_version_it_replaces(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="3", lines=[PAINT])
    known(conn, ws)
    with db.transaction(conn):
        set_location(conn, doc(conn, "3")["id"], OFFICE)
    for f in list(ws.deliveries.rglob("*.xlsx")):
        f.unlink()
    make_note(ws.deliveries / "a.xlsx", code="3", lines=[(*PAINT[:2], 5, "")])  # edited: another file
    deliveries.scan(conn, ws)
    [row] = [r for r in deliveries.pending_files(conn) if r["status"] == "changed"]
    deliveries.replace_changed(conn, ws, row["hash"])
    d = doc(conn, "3")
    assert (d["location_id"], d["location_set"]) == (OFFICE, 1)


def test_lines_added_later_go_to_the_place_of_their_order(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="9", lines=[PAINT, SAND])
    deliveries.scan(conn, ws)
    paint, sand = sorted(deliveries.unknown_lines(conn, ws), key=lambda u: u.name_zh != "背水涂")
    deliveries.create_product_for_line(conn, paint)
    deliveries.scan(conn, ws, allow_partial=True)  # sand: 'Để sau'
    with db.transaction(conn):
        set_location(conn, doc(conn, "9")["id"], OFFICE)
    pid = deliveries.create_product_for_line(conn, sand)
    deliveries.scan(conn, ws)
    assert places(conn, pid) == (0, -2) and no_movement_without_place(conn)


def test_opening_stock_of_a_new_product_and_catalog_counts_go_to_the_main_warehouse(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="5", day="05-10-2026", lines=[PAINT])
    deliveries.scan(conn, ws)
    [line] = deliveries.unknown_lines(conn, ws)
    pid = deliveries.create_product_for_line(conn, line, opening=40)
    deliveries.scan(conn, ws)
    assert places(conn, pid) == (37, 0)
    with db.transaction(conn):
        move_goods(conn, date(2026, 10, 6), MAIN, OFFICE, [Line(pid, 5)])
        stock_count(conn, date(2026, 10, 7), {pid: 50})  # a count of the total: Kho tổng takes the difference
    assert places(conn, pid) == (45, 5) and no_movement_without_place(conn)


# ---- counts and transfers ---------------------------------------------------------------------------------

def test_count_per_place_and_transfer(conn):
    with db.transaction(conn):
        p = catalog.create_product(conn, "Sơn A", spec="20KG")
        stock_count(conn, date(2026, 10, 1), {(p, MAIN): 39, (p, OFFICE): 1})
    assert places(conn, p) == (39, 1) and stock_levels(conn)[p] == 40
    with db.transaction(conn):
        t_id = move_goods(conn, date(2026, 10, 2), MAIN, OFFICE, [Line(p, 5)], note="lên văn phòng")
    assert places(conn, p) == (34, 6) and stock_levels(conn)[p] == 40
    head, lines = queries.document(conn, t_id)
    assert head["kind"] == "transfer" and head["code"] == "CH001" and lines[0]["qty"] == 5
    with db.transaction(conn):  # counting only the office leaves Kho tổng as it is
        c_id = stock_count(conn, date(2026, 10, 3), {(p, OFFICE): 4})
    assert places(conn, p) == (34, 4)
    assert queries.count_differences(conn, c_id) == {(p, OFFICE): -2}
    with db.transaction(conn):
        close_document(conn, t_id)
    assert places(conn, p) == (39, -1)
    # transfers are neither in nor out in the statistics
    [row] = stats.summary(conn, date(2026, 10, 1), date(2026, 10, 31))
    assert (row.qty_in, row.qty_out, row.closing) == (0, 0, 38)
    with pytest.raises(ValueError):
        with db.transaction(conn):
            move_goods(conn, date(2026, 10, 4), MAIN, MAIN, [Line(p, 1)])


def test_editing_a_transfer_keeps_its_code_and_the_old_one_is_replaced(conn):
    with db.transaction(conn):
        p = catalog.create_product(conn, "Sơn A", spec="20KG")
        stock_count(conn, date(2026, 10, 1), {(p, MAIN): 50})
    with db.transaction(conn):
        t_id = move_goods(conn, date(2026, 10, 2), MAIN, OFFICE, [Line(p, 10)])
    assert places(conn, p) == (40, 10)
    with db.transaction(conn):
        t2_id = move_goods(conn, date(2026, 10, 2), MAIN, OFFICE, [Line(p, 15)], replaces=t_id)
    assert places(conn, p) == (35, 15)  # the edit replaces the movement, it does not add to it
    old = conn.execute("SELECT status, code FROM documents WHERE id = ?", (t_id,)).fetchone()
    new = conn.execute("SELECT status, code FROM documents WHERE id = ?", (t2_id,)).fetchone()
    assert old["status"] == "replaced" and new["status"] == "active"
    assert old["code"] == new["code"] == "CH001"
    # a replaced document keeping its old number must not make a later transfer skip one
    with db.transaction(conn):
        t3_id = move_goods(conn, date(2026, 10, 3), MAIN, OFFICE, [Line(p, 1)])
    head3, _ = queries.document(conn, t3_id)
    assert head3["code"] == "CH002"


def test_trial_use_deducts_stock_and_is_an_adjustment_not_a_sale(conn):
    """Goods opened/used for trial purposes (28/10/2026): replaces the sham delivery notes staff made to
    self-deduct stock for this. Must not inflate 'xuất' (qty_out) -- that is the whole point of a separate
    document kind -- but closing stock must still balance, so it is counted as an adjustment."""
    with db.transaction(conn):
        p = catalog.create_product(conn, "Sơn A", spec="20KG")
        stock_count(conn, date(2026, 9, 1), {(p, MAIN): 50})
    with db.transaction(conn):
        t_id = record_trial_use(conn, date(2026, 10, 2), MAIN, [Line(p, 5)], note="mở ra thử")
    assert places(conn, p) == (45, 0) and stock_levels(conn)[p] == 45
    head, lines = queries.document(conn, t_id)
    assert head["kind"] == "trial" and head["code"] == "DT001" and head["customer_id"] is None
    assert head["note"] == "mở ra thử" and lines[0]["qty"] == 5
    [row] = stats.summary(conn, date(2026, 10, 1), date(2026, 10, 31))
    assert (row.qty_in, row.qty_out, row.adjust, row.closing) == (0, 0, -5, 45)
    assert stats.top_out(conn, date(2026, 10, 1), date(2026, 10, 31)) == []  # not a sale
    with db.transaction(conn):
        close_document(conn, t_id)  # Huỷ phiếu restores the stock (no separate edit for this kind)
    assert places(conn, p) == (50, 0)
    with pytest.raises(ValueError):
        with db.transaction(conn):
            record_trial_use(conn, date(2026, 10, 3), MAIN, [])


def test_merge_customers_moves_documents_and_deletes_the_others(conn):
    """Tidying up sham delivery notes made under several made-up customer names (28/10/2026): they all move
    onto one customer, named as the user picks, and the others disappear -- but the orders themselves and
    their history stay exactly as they were."""
    a = catalog.upsert_customer(conn, "Khách Mẫu A")
    b = catalog.upsert_customer(conn, "Khách Mẫu B")
    c = catalog.upsert_customer(conn, "Khách Mẫu C")
    p = catalog.create_product(conn, "Sơn A", spec="20KG")
    from dibekho.core.stock import insert_document

    with db.transaction(conn):
        doc_a = insert_document(conn, "delivery", date(2026, 10, 1), [Line(p, 1)], code="1", code_norm="1",
                                customer_id=a)
        doc_b = insert_document(conn, "delivery", date(2026, 10, 2), [Line(p, 1)], code="2", code_norm="2",
                                customer_id=b)
    kept = catalog.merge_customers(conn, [a, b], "Văn phòng DiBeKho")
    assert kept == a  # the smaller id survives when the name is brand new
    assert conn.execute("SELECT name FROM customers WHERE id = ?", (a,)).fetchone()[0] == "Văn phòng DiBeKho"
    assert conn.execute("SELECT id FROM customers WHERE id = ?", (b,)).fetchone() is None
    assert conn.execute("SELECT customer_id FROM documents WHERE id = ?", (doc_a,)).fetchone()[0] == a
    assert conn.execute("SELECT customer_id FROM documents WHERE id = ?", (doc_b,)).fetchone()[0] == a
    # merging into a name that already exists reuses that customer, even if it is not the smallest id
    kept2 = catalog.merge_customers(conn, [a, c], "Khách Mẫu C")
    assert kept2 == c
    with pytest.raises(ValueError):
        catalog.merge_customers(conn, [a], "Một mình")  # fewer than 2 customers


def test_find_possible_duplicates(conn):
    with db.transaction(conn):
        white = catalog.create_product(conn, "Sơn chống thấm FS-101", "FS-101防水涂料", "20KG", variant="Trắng")
        grey = catalog.create_product(conn, "Sơn chống thấm FS-101", "FS-101防水涂料", "20KG", variant="Xám")
    # exact match (same name + packing + colour): only the one with the same colour
    dups = catalog.find_possible_duplicates(conn, "Sơn chống thấm FS-101", "FS-101防水涂料", "20KG", "Trắng")
    assert [p["id"] for p in dups] == [white]
    # no colour given: the fuzzy matcher (same Chinese name + packing) finds both
    dups = catalog.find_possible_duplicates(conn, "Sơn FS101 mới", "FS-101防水涂料", "20KG")
    assert {white, grey} <= {p["id"] for p in dups}
    # a different colour of the same base item is a different product on purpose, not a duplicate
    dups = catalog.find_possible_duplicates(conn, "Sơn chống thấm FS-101", "FS-101防水涂料", "20KG", variant="Xanh")
    assert white not in {p["id"] for p in dups} and grey not in {p["id"] for p in dups}
    # nothing at all close: no candidates
    assert catalog.find_possible_duplicates(conn, "Keo dán gạch", "瓷砖胶", "25KG") == []


def test_find_possible_duplicates_skips_a_different_category_too(conn):
    """The customer also tells variants apart by Nhóm hàng, not only Loại/màu (mục 9.4b) -- two products
    with the same name/packing but a different category on purpose must not be flagged as duplicates."""
    a = catalog.create_product(conn, "Màng PPE 18.5KG", "高分子聚乙烯涤纶防水卷材", "18.5KG", category="瑞德牌")
    b = catalog.create_product(conn, "Màng PPE 18.5KG", "高分子聚乙烯涤纶防水卷材", "18.5KG", category="纯白色")
    dups = catalog.find_possible_duplicates(conn, "Màng PPE mới", "高分子聚乙烯涤纶防水卷材", "18.5KG", category="瑞德牌")
    assert a in {p["id"] for p in dups} and b not in {p["id"] for p in dups}


def test_find_possible_duplicates_tolerates_a_raw_note_spec_but_not_a_real_one(conn):
    """A delivery-note line's raw spec text ("10KG/thùng") is not in the catalog's own format ("10KG") --
    that difference alone must not hide a real duplicate (regression: an earlier, stricter exact-spec check
    broke this exact case, found via Cần xử lý's own duplicate check). A genuinely different packing (3mm vs
    4mm) must still be told apart, even though neither pattern is a plain "20KG" weight the kg/dims features
    would catch on their own."""
    with db.transaction(conn):
        thin = catalog.create_product(conn, "Vữa chống thấm cũ", "背水涂", "10KG", unit="thùng")
        a = catalog.create_product(conn, "Màng SBS", "SBS自粘膜", "3mm")
        catalog.create_product(conn, "Màng SBS", "SBS自粘膜", "4mm")
    dups = catalog.find_possible_duplicates(conn, "Vữa chống thấm mới", "背水涂", "10KG/thùng")
    assert thin in {p["id"] for p in dups}
    dups = catalog.find_possible_duplicates(conn, "Màng SBS mới", "SBS自粘膜", "3mm")
    assert [p["id"] for p in dups] == [a]


def test_a_receipt_goes_where_it_was_put_and_keeps_it_when_edited(conn, ws):
    with db.transaction(conn):
        p = catalog.create_product(conn, "Sơn A")
    data = receipts.ReceiptInput(date(2026, 10, 1), receipts.SUPPLIER, supplier_name="NCC",
                                 lines=[receipts.ReceiptLineInput(10, p)], location_id=OFFICE)
    doc_id = receipts.save(conn, data, ws=ws)
    assert places(conn, p) == (0, 10)
    loaded = receipts.load(conn, doc_id)
    assert loaded.location_id == OFFICE
    loaded.lines[0].qty = 12
    receipts.save(conn, loaded, replaces=doc_id, ws=ws)
    assert places(conn, p) == (0, 12)


# ---- alarm level ------------------------------------------------------------------------------------------

def test_default_alarm_level_is_30_and_shared_by_every_product(conn):
    assert low_stock_default(conn) == 30
    assert is_low(29, 30) and not is_low(30, 30)  # 'below 30'
    assert not is_low(5, 0)  # 0 = off
    with db.transaction(conn):
        db.set_meta(conn, "low_stock_default", "12")
    assert low_stock_default(conn) == 12


def test_alarm_level_and_stock_note_go_with_the_data_package(conn, ws, tmp_path):
    with db.transaction(conn):
        p = catalog.create_product(conn, "Sơn A")
        catalog.update_product(conn, p, stock_note="3 thùng in lệch, 2 thùng hết hạn 12/2026")
        db.set_meta(conn, "low_stock_default", "20")
    from dibekho.core.workspace import Config

    pkg = transfer.export_package(conn, ws, Config(workspace=str(ws.root), device_id="a", device_name="May A"))
    other = Workspace(tmp_path / "B")
    other.ensure()
    db.connect(other.db_path).close()
    transfer.import_package(other, pkg)
    conn_b = db.connect(other.db_path)
    assert conn_b.execute("SELECT stock_note FROM products").fetchone()[0].startswith("3 thùng in lệch")
    assert low_stock_default(conn_b) == 20


def test_stock_note_in_the_master_data_file_both_ways(conn, tmp_path):
    with db.transaction(conn):
        p = catalog.create_product(conn, "Sơn A", spec="20KG")
        catalog.update_product(conn, p, stock_note="2 thùng móp")
        stock_count(conn, date(2026, 10, 1), {(p, MAIN): 9, (p, OFFICE): 1})
    path = master_data.export(tmp_path / "goc.xlsx", conn)
    row = list(openpyxl.load_workbook(path).worksheets[2].iter_rows(min_row=5, values_only=True))[0]
    assert row[4:] == (10, 9, 1, "2 thùng móp")
    wb = openpyxl.load_workbook(path)
    wb.worksheets[2].cell(row=5, column=8, value="hết móp")
    wb.save(path)
    products, customers, stock = master_data.read(path)
    catalog.import_master(conn, products, customers, stock)
    assert conn.execute("SELECT stock_note FROM products WHERE id = ?", (p,)).fetchone()[0] == "hết móp"
    assert stock_levels(conn)[p] == 10  # the total is unchanged


# ---- money in statistics and exports ----------------------------------------------------------------------

def test_period_revenue_matches_the_customer_window(conn, ws):
    a, b = two_notes(conn, ws)
    start, end = date(2026, 10, 1), date(2026, 10, 31)
    m = stats.money(conn, start, end)
    assert (m.orders, m.goods, m.fees, m.total) == (2, 5500000, 190000, 5500000)  # revenue = goods; shipping apart
    cust = doc(conn, "1")["customer_id"]
    cm = queries.customer_money(conn, cust, start, end)
    assert stats.money(conn, start, end, stats.Filters(customer_ids=[cust])).total == cm["total"]
    only_sand = stats.money(conn, start, end, stats.Filters(product_ids=[b]))
    assert (only_sand.goods, only_sand.fees) == (1300000, None)  # fees belong to no product
    rows = {r.product_id: r.revenue for r in stats.summary(conn, start, end)}
    assert rows == {a: 4200000, b: 1300000}
    with db.transaction(conn):
        close_document(conn, doc(conn, "2")["id"])
    assert stats.money(conn, start, end).total == 3400000  # cancelled orders are no revenue


def test_details_sheet_keeps_two_prices_of_one_product_on_one_note(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="7", day="02-10-2026",
              lines=[PAINT, (*PAINT[:4], 650000), (PAINT[0], PAINT[1], 1, "tặng", 0)])
    known(conn, ws)
    rows = [r for r in stats.detail_lines(conn, date(2026, 10, 1), date(2026, 10, 31)) if r["kind"] == "delivery_out"]
    assert sorted((r["qty"], r["unit_price"], r["amount"]) for r in rows) == \
        [(-3, 650000, 1950000), (-3, 700000, 2100000), (-1, 0, 0)]


def test_statistics_file_has_money_places_and_notes(conn, ws, tmp_path):
    a, _ = two_notes(conn, ws)
    with db.transaction(conn):
        catalog.update_product(conn, a, stock_note="1 thùng hết hạn")
    path = report.export(tmp_path / "r.xlsx", conn, date(2026, 10, 1), date(2026, 10, 31), stats.Filters(), "none",
                         set(report.SHEETS), "10/2026", "Tất cả")
    wb = openpyxl.load_workbook(path)
    text = " ".join(str(c.value) for s in wb.worksheets for row in s.iter_rows() for c in row if c.value)
    assert "5.500.000" in text and "190.000" in text and "1 thùng hết hạn" in text and "Kho tổng" in text
    summary = wb.worksheets[0]
    head = [c.value for c in summary[6]]
    revenue = [r[head.index("Doanh thu")] for r in summary.iter_rows(min_row=7, values_only=True)]
    assert sorted(revenue) == [1300000, 4200000]


def test_customer_file_lists_each_order_with_its_prices(conn, ws, tmp_path):
    two_notes(conn, ws)
    cust = doc(conn, "1")["customer_id"]
    path = report.export_customer(tmp_path / "k.xlsx", conn, cust, date(2026, 10, 1), date(2026, 10, 3),
                                  "01/10/2026 – 03/10/2026")
    wb = openpyxl.load_workbook(path)
    orders = [r for r in wb.worksheets[0].iter_rows(min_row=7, values_only=True)]
    assert [(r[1], r[3], r[10]) for r in orders] == [
        ("1", "vữa chống thấm", 2100000), ("1", "chất cố định cát", 1300000), ("1", "Tiền hàng của đơn", 3400000),
        ("1", i18n.t("cust.fees"), 190000)]  # fees apart, after the goods; order 2 is after the period
    products = list(wb.worksheets[1].iter_rows(min_row=7, values_only=True))
    assert len(products) == 2 and {p[7] for p in products} == {2100000, 1300000}


# ---- screens ------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def window(ws):
    from dibekho.core.workspace import Config
    from dibekho.ui.common import AppContext
    from dibekho.ui.main_window import MainWindow

    ctx = AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)
    return ctx, MainWindow(ctx)


def test_screens_places_notes_and_alarm(app, ws, monkeypatch):
    import dibekho.ui.common as common_mod
    import dibekho.ui.count_page as count_mod
    import dibekho.ui.details as details_mod

    for mod in (count_mod, details_mod, common_mod):
        monkeypatch.setattr(mod, "ask", lambda *a, **k: True)
    for mod in (count_mod, common_mod):
        monkeypatch.setattr(mod, "info", lambda *a, **k: None)
    make_note(ws.deliveries / "a.xlsx", code="1", lines=[PAINT, SAND])
    ctx, win = window(ws)
    known(ctx.conn, ws)
    paint = ctx.conn.execute("SELECT id FROM products WHERE name_zh = '背水涂'").fetchone()[0]
    with db.transaction(ctx.conn):
        stock_count(ctx.conn, date(2026, 10, 10), {paint: 23})  # a count of the total, at Kho tổng
    win.show()
    win.rescan()
    app.processEvents()
    assert "(1)" in win.nav.item(1).text()  # one order without its place

    pending = win.pending
    win.nav.setCurrentRow(1)
    app.processEvents()
    assert pending.places_box.isVisible() and pending.places.rowCount() == 1
    pending._place_combos[0].setCurrentIndex(pending._place_combos[0].findData(OFFICE))
    pending.save_places()
    assert places(ctx.conn, paint) == (26, -3) and deliveries.unplaced_count(ctx.conn) == 0

    stock = win.stack.widget(0)
    win.nav.setCurrentRow(0)
    app.processEvents()
    from dibekho.ui.common import ORANGE
    from dibekho.ui.stock_page import NOTE, ZH

    row = next(r for r in range(stock.table.rowCount()) if stock.table.item(r, ZH).text() == "背水涂")
    assert stock.alarm.isVisible() and stock.table.item(row, 0).background().color() == ORANGE  # 23: below 30
    from PySide6.QtWidgets import QAbstractItemDelegate, QLineEdit

    stock.table.editItem(stock.table.item(row, NOTE))  # the way a double-click types into the cell
    editor = stock.table.viewport().findChild(QLineEdit)
    editor.setText("2 thùng in lệch")
    stock.table.commitData(editor)
    stock.table.closeEditor(editor, QAbstractItemDelegate.NoHint)
    app.processEvents()
    assert ctx.conn.execute("SELECT stock_note FROM products WHERE id = ?", (paint,)).fetchone()[0] == "2 thùng in lệch"
    row = next(r for r in range(stock.table.rowCount()) if stock.table.item(r, ZH).text() == "背水涂")
    assert stock.table.item(row, NOTE).text() == "2 thùng in lệch"  # the table was rebuilt after the edit
    assert not stock.table.item(row, 1).flags() & count_mod.Qt.ItemIsEditable

    count = win.stack.widget(4)
    win.nav.setCurrentRow(win.stack.indexOf(count))
    app.processEvents()
    r = next(r for r in range(count.table.rowCount()) if count.table.item(r, 0).data(count_mod.Qt.UserRole) == paint)
    assert count.table.item(r, count_mod.NOTE_COL).text() == "2 thùng in lệch"  # the same note
    count.table.item(r, count_mod.COUNT_MAIN).setText("39")
    count.table.item(r, count_mod.NOTE_COL).setText("1 thùng hết hạn")
    assert count.table.item(r, count_mod.COUNT_MAIN).text() == "39"  # the note did not wipe the counts typed
    count.save()
    assert places(ctx.conn, paint) == (39, -3)

    dlg = count_mod.TransferDialog(ctx, win)
    r = next(r for r in range(dlg.table.rowCount()) if dlg.table.item(r, 0).data(count_mod.Qt.UserRole) == paint)
    dlg.table.item(r, count_mod.TRANS_QTY).setText("4")
    dlg.save()
    assert places(ctx.conn, paint) == (35, 1)

    from dibekho.ui.details import CustomerDialog, DocumentDialog, ProductDialog

    d = DocumentDialog(ctx, doc(ctx.conn, "1")["id"], win)
    d.location.setCurrentIndex(d.location.findData(MAIN))  # changed back in the order window
    assert places(ctx.conn, paint) == (32, 4)
    ProductDialog(ctx, paint, win).close()
    cd = CustomerDialog(ctx, doc(ctx.conn, "1")["customer_id"], win)
    monkeypatch.setattr(details_mod, "open_path", lambda p: None)
    cd.export()
    assert list(ws.output.glob("KhachHang_*.xlsx"))
    win.close()


def test_dragging_a_pinned_column_wider_resizes_the_real_table(app, ws):
    """Dragging a column border on the frozen pane must resize the real (host) column too, not just the
    overlay's own copy of the header -- host.horizontalHeader() must not be blockSignals()-ed in the process,
    or the table stops redrawing/scrolling correctly after the drag."""
    from dibekho.ui.stock_page import NOTE, STOCK

    make_note(ws.deliveries / "a.xlsx", code="1", lines=[PAINT])
    ctx, win = window(ws)
    known(ctx.conn, ws)
    win.show()
    win.resize(1260, 700)
    win.nav.setCurrentRow(0)
    app.processEvents()
    stock = win.stack.widget(0)
    frozen = stock.table._frozen[0]
    before = stock.table.horizontalHeader().sectionPosition(NOTE)
    frozen.horizontalHeader().resizeSection(STOCK, 200)
    app.processEvents()
    assert stock.table.columnWidth(STOCK) == 200
    assert stock.table.horizontalHeader().sectionPosition(NOTE) != before
    win.close()


def _fixed_width_table(app, n, col_width):
    """A bare table (make_table + freeze_columns) with every column forced to the same fixed width, so the
    pinning tests below are not at the mercy of font metrics / DPI, which vary across machines and even
    across test runs in the same process (a real word-based table's width depends on glyph rendering)."""
    from dibekho.ui.common import fill_table, make_table

    table = make_table([str(i) for i in range(n)], stretch=None)
    fill_table(table, [[str(i) for i in range(n)]])
    for c in range(n):
        table.setColumnWidth(c, col_width)
    app.processEvents()
    return table


def test_pinning_stays_visible_when_the_leftover_is_enough(app):
    """Real product names (SP page caps them at 180/150/100/90/110/60 -- see stock_page.py) leave about 200px
    to scroll to at the window size the app actually opens at (measured against a copy of a real exported
    package with fonts loaded, 25/10/2026); this test uses the same 6x100 shape with plenty of room."""
    from PySide6.QtWidgets import QAbstractItemView

    from dibekho.ui.common import FrozenColumns, freeze_columns

    table = _fixed_width_table(app, 6, 100)  # 600px of content, 200px pinned
    table.resize(480, 200)  # content (600) > window: scrolling is needed
    table.show()
    app.processEvents()
    frozen = freeze_columns(table, [0, 1], side="left")
    app.processEvents()
    # per-pixel, not per-column, scrolling: any column can be brought fully into the scrollable strip next
    # to the pinned pane, not just whichever one happens to land at x=0 after a column-sized jump
    assert table.horizontalScrollMode() == QAbstractItemView.ScrollPerPixel
    assert table.horizontalScrollBar().maximum() > 0
    leftover = table.viewport().width() - 200
    assert leftover >= FrozenColumns.MIN_SCROLLABLE, leftover  # plenty of room: comfortably visible
    assert frozen.isVisible()
    table.close()


def test_pinning_hides_itself_when_the_leftover_is_too_small(app):
    """The opposite edge: a window too narrow for the pinned columns plus one more must fall back to plain
    scrolling rather than cover the whole table."""
    from dibekho.ui.common import freeze_columns

    table = _fixed_width_table(app, 6, 100)  # 600px of content, 200px pinned
    table.resize(310, 200)  # content (600) > window, and little is left over once 200px are pinned
    table.show()
    app.processEvents()
    frozen = freeze_columns(table, [0, 1], side="left")
    app.processEvents()
    assert table.horizontalScrollBar().maximum() > 0  # still needs to scroll
    assert not frozen.isVisible()
    table.close()


def test_sticky_pin_only_shows_once_scrolled_past_its_real_column(app):
    """Tồn kho pins only the Tồn column, in the middle of the table -- unlike an edge pin (always drawn at
    the edge whenever scrolling is possible), a sticky pin must stay invisible (the real cell shows through)
    until scrolling would actually carry that column past the edge."""
    from dibekho.ui.common import freeze_columns

    table = _fixed_width_table(app, 6, 100)  # 600px of content; column 2 is the one pinned
    table.resize(310, 200)  # narrow enough that scrolling is needed
    table.show()
    app.processEvents()
    frozen = freeze_columns(table, [2], side="left", sticky=True)
    app.processEvents()
    assert table.horizontalScrollBar().maximum() > 0
    assert not frozen.isVisible()  # column 2 is still in its natural place at scroll 0
    table.horizontalScrollBar().setValue(table.horizontalScrollBar().maximum())
    app.processEvents()
    assert frozen.isVisible()
    assert frozen.geometry().x() == table.viewport().x()  # stuck at the left edge
    table.close()


def test_numeric_cell_delegate_disables_the_input_method(app):
    """On macOS, a Chinese or Vietnamese input source left enabled on a plain text cell editor can still
    treat a typed digit as composing text that only resolves when Enter commits it, landing the keystroke
    twice. numeric_cell_delegate() turns the input method off for that one editor."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLineEdit, QStyleOptionViewItem

    from dibekho.ui.common import fill_table, make_table, numeric_cell_delegate

    table = make_table(["a", "b"], stretch=None)
    fill_table(table, [["1", "2"]])
    table.item(0, 1).setFlags(table.item(0, 1).flags() | Qt.ItemIsEditable)
    numeric_cell_delegate(table, 1)
    delegate = table.itemDelegateForColumn(1)
    editor = delegate.createEditor(table, QStyleOptionViewItem(), table.model().index(0, 1))
    assert isinstance(editor, QLineEdit)
    assert editor.testAttribute(Qt.WA_InputMethodEnabled) is False
    assert bool(editor.inputMethodHints() & Qt.ImhFormattedNumbersOnly)
    editor.deleteLater()


def test_orders_page_fixed_kind_hides_filters_and_offers_to_edit(app, ws, monkeypatch):
    """Opened from Kiểm kê (Phiếu chuyển hàng / Phiếu kiểm kê): the kind and customer filters are pointless
    (there is only one kind, and transfers/counts have no customer) and the money columns are always blank
    for these kinds, so all four are hidden; a transfer list also gets an edit-selected button."""
    import dibekho.ui.orders_page as orders_mod

    ctx, win = window(ws)
    with db.transaction(ctx.conn):
        p = catalog.create_product(ctx.conn, "Sơn A", spec="20KG")
        stock_count(ctx.conn, date(2026, 10, 1), {(p, MAIN): 10})
        move_goods(ctx.conn, date(2026, 10, 2), MAIN, OFFICE, [Line(p, 3)])

    page = orders_mod.OrdersPage(ctx, fixed_kind="transfer")
    page.refresh()
    assert page.kind.currentData() == "transfer"
    for w in (page.kind_label, page.kind, page.customer_label, page.customer):
        assert not w.isVisible()
    assert page.table.isColumnHidden(orders_mod.GOODS_COL) and page.table.isColumnHidden(orders_mod.FEES_COL)
    assert page.table.rowCount() == 1 and page.table.item(0, 1).text() == "CH001"

    # nothing selected: a clear message, not a crash
    errors = []
    monkeypatch.setattr(orders_mod, "error", lambda parent, text: errors.append(text))
    page.edit_transfer_selected()
    assert errors

    page.table.selectRow(0)
    import dibekho.ui.count_page as count_mod
    monkeypatch.setattr(count_mod.TransferDialog, "exec", lambda self: 1)  # Accepted, without a real modal
    page.edit_transfer_selected()  # must not crash, even though the patched exec() never calls save()
    win.close()


def test_count_page_history_buttons_open_cached_windows(app, ws):
    """'Phiếu chuyển hàng…' and 'Phiếu kiểm kê…' open the same list used from Tra cứu, fixed to that one
    kind; re-clicking reuses the same window instead of opening another one."""
    ctx, win = window(ws)
    win.show()
    app.processEvents()
    count = win.stack.widget(4)
    win.nav.setCurrentRow(win.stack.indexOf(count))
    app.processEvents()
    count.open_history("transfer")
    first = count._history_windows["transfer"]
    assert first.page.fixed_kind == "transfer"
    count.open_history("transfer")
    assert count._history_windows["transfer"] is first  # cached, not rebuilt
    count.open_history("stock_count")
    assert count._history_windows["stock_count"].page.fixed_kind == "stock_count"
    for w in count._history_windows.values():
        w.close()
    win.close()


def test_transfer_dialog_prefills_and_saves_an_edit(app, ws, monkeypatch):
    """Opening TransferDialog with doc_id pre-fills the old transfer's fields and quantities, shows the
    source place as if that transfer had not happened yet (so re-saving the same or a larger quantity is
    never blocked by its own prior move), and saving replaces the old document under the same code."""
    import dibekho.ui.count_page as count_mod

    make_note(ws.deliveries / "a.xlsx", code="1", lines=[PAINT])
    ctx, win = window(ws)
    known(ctx.conn, ws)
    paint = ctx.conn.execute("SELECT id FROM products WHERE name_zh = '背水涂'").fetchone()[0]
    with db.transaction(ctx.conn):  # after the note's own date (05-10-2026), so the count absorbs its effect
        stock_count(ctx.conn, date(2026, 10, 6), {(paint, MAIN): 20})
    with db.transaction(ctx.conn):
        t_id = move_goods(ctx.conn, date(2026, 10, 7), MAIN, OFFICE, [Line(paint, 10)], note="ghi chú")
    assert places(ctx.conn, paint) == (10, 10)

    dlg = count_mod.TransferDialog(ctx, win, t_id)
    assert dlg.from_loc.currentData() == MAIN and dlg.to_loc.currentData() == OFFICE
    assert dlg.note.text() == "ghi chú"
    assert dlg._typed().get(paint) == 10
    # as if the 10 already moved were still at Kho tổng: editing up to 18 (8 more than really there) is fine
    assert dlg.levels.get((paint, MAIN)) == 20

    monkeypatch.setattr(count_mod, "ask", lambda *a, **k: True)
    monkeypatch.setattr(count_mod, "info", lambda *a, **k: None)
    r = next(r for r in range(dlg.table.rowCount()) if dlg.table.item(r, 0).data(count_mod.Qt.UserRole) == paint)
    dlg.table.item(r, count_mod.TRANS_QTY).setText("18")
    dlg.save()
    assert places(ctx.conn, paint) == (2, 18)
    old = ctx.conn.execute("SELECT status, code FROM documents WHERE id = ?", (t_id,)).fetchone()
    assert old["status"] == "replaced"
    new = ctx.conn.execute("SELECT id, status, code FROM documents WHERE code = ? AND status = 'active'",
                           (old["code"],)).fetchone()
    assert new["id"] != t_id
    win.close()


def test_transfer_dialog_prefills_the_other_direction_too(app, ws):
    """Office -> Kho tổng (not the combos' own default Kho tổng -> Office): setting from_loc to a value that
    differs from its default fires currentIndexChanged while the dialog is still being built -- must not
    reach _fill() before self.table/self.products exist."""
    import dibekho.ui.count_page as count_mod

    make_note(ws.deliveries / "a.xlsx", code="1", lines=[PAINT])
    ctx, win = window(ws)
    known(ctx.conn, ws)
    paint = ctx.conn.execute("SELECT id FROM products WHERE name_zh = '背水涂'").fetchone()[0]
    with db.transaction(ctx.conn):
        stock_count(ctx.conn, date(2026, 10, 6), {(paint, OFFICE): 20})
    with db.transaction(ctx.conn):
        t_id = move_goods(ctx.conn, date(2026, 10, 7), OFFICE, MAIN, [Line(paint, 10)])
    dlg = count_mod.TransferDialog(ctx, win, t_id)
    assert dlg.from_loc.currentData() == OFFICE and dlg.to_loc.currentData() == MAIN
    assert dlg._typed().get(paint) == 10
    win.close()


def test_the_opened_editor_has_the_input_method_off(app, ws):
    """Qt resets WA_InputMethodEnabled on the VIEW itself back to True as soon as an editable cell becomes
    current -- a one-off setAttribute() call right after building the dialog (as TransferDialog/TrialUseDialog
    used to do) does not survive that. The cell editor numeric_cell_delegate() creates is a separate QLineEdit
    the view-level reset does not touch, so it stays off once opened; see
    test_current_cell_turns_off_input_method_on_the_view_itself for the view-level half of the fix (the
    customer still got doubled digits on a real Mac with only this editor-level half in place -- the view
    itself has IME back on for the first keystroke that selects a numeric cell and types into it at once)."""
    from PySide6.QtWidgets import QAbstractItemDelegate, QLineEdit

    import dibekho.ui.count_page as count_mod

    make_note(ws.deliveries / "a.xlsx", code="1", lines=[PAINT])
    ctx, win = window(ws)
    known(ctx.conn, ws)
    paint = ctx.conn.execute("SELECT id FROM products WHERE name_zh = '背水涂'").fetchone()[0]
    dlg = count_mod.TransferDialog(ctx, win)
    r = next(r for r in range(dlg.table.rowCount()) if dlg.table.item(r, 0).data(count_mod.Qt.UserRole) == paint)
    index = dlg.frozen.model().index(r, count_mod.TRANS_QTY)
    dlg.frozen.setCurrentIndex(index)
    dlg.frozen.edit(index)
    editor = dlg.frozen.viewport().findChild(QLineEdit)
    assert editor is not None
    assert editor.testAttribute(count_mod.Qt.WA_InputMethodEnabled) is False
    assert bool(editor.inputMethodHints() & count_mod.Qt.ImhFormattedNumbersOnly)
    dlg.frozen.closeEditor(editor, QAbstractItemDelegate.NoHint)
    win.close()


def test_current_cell_turns_off_input_method_on_the_view_itself(app, ws):
    """29/10/2026: the customer still got doubled digits on a real Mac (Telex) in Xuất dùng thử, Chuyển hàng
    and Kiểm kê even with the editor-level fix above. Root cause: with the AnyKeyPressed edit trigger, the
    first keystroke that both selects a numeric cell and types into it is read off the VIEW -- no editor
    exists yet at that point -- and Qt had already turned the view's WA_InputMethodEnabled back on as soon
    as the cell became current. Table/FrozenColumns now override currentChanged() to keep it off while the
    current column is one numeric_cell_delegate() was called on, and back on for every other column (Kiểm
    kê's Ghi chú tồn kho, in the same table, still needs Vietnamese/Chinese input)."""
    import dibekho.ui.count_page as count_mod

    make_note(ws.deliveries / "a.xlsx", code="1", lines=[PAINT])
    ctx, win = window(ws)
    known(ctx.conn, ws)
    paint = ctx.conn.execute("SELECT id FROM products WHERE name_zh = '背水涂'").fetchone()[0]
    dlg = count_mod.TransferDialog(ctx, win)
    r = next(r for r in range(dlg.table.rowCount()) if dlg.table.item(r, 0).data(count_mod.Qt.UserRole) == paint)

    dlg.table.setCurrentCell(r, count_mod.TRANS_QTY)
    assert dlg.table.testAttribute(count_mod.Qt.WA_InputMethodEnabled) is False
    dlg.frozen.setCurrentIndex(dlg.frozen.model().index(r, count_mod.TRANS_QTY))
    assert dlg.frozen.testAttribute(count_mod.Qt.WA_InputMethodEnabled) is False

    dlg.table.setCurrentCell(r, count_mod.TRANS_CODE)  # not a numeric column: IME must come back
    assert dlg.table.testAttribute(count_mod.Qt.WA_InputMethodEnabled) is True
    win.close()


def test_count_page_typed_value_survives_moving_to_another_cell(app, ws):
    """29/10/2026: the customer reported a typed count 'jumping' after clicking once and moving to another
    cell in Kiểm kê. Kiểm kê uses AllEditTriggers (unlike Chuyển hàng/Xuất dùng thử's AnyKeyPressed), so
    simply making a cell current already opens its editor, before any key is pressed -- exercise that real
    editor lifecycle (not a direct item.setText(), which every other test here uses) to make sure typing one
    digit and then moving away with setCurrentCell() commits exactly what was typed, not a doubled or empty
    value. This cannot reproduce the Mac IME side of the report (offscreen Qt has no real input method), but
    it does rule out an actual commit-on-move bug in CountPage itself."""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit

    import dibekho.ui.count_page as count_mod

    make_note(ws.deliveries / "a.xlsx", code="1", lines=[PAINT])
    ctx, win = window(ws)
    known(ctx.conn, ws)
    paint = ctx.conn.execute("SELECT id FROM products WHERE name_zh = '背水涂'").fetchone()[0]
    win.show()
    win.rescan()
    app.processEvents()
    count = win.stack.widget(4)
    win.nav.setCurrentRow(win.stack.indexOf(count))
    app.processEvents()
    r = next(r for r in range(count.table.rowCount()) if count.table.item(r, 0).data(count_mod.Qt.UserRole) == paint)

    app_main = count.table.item(r, count_mod.APP_MAIN).key
    count.table.setCurrentCell(r, count_mod.COUNT_MAIN)  # AllEditTriggers: this alone opens the editor
    editor = count.table.viewport().findChild(QLineEdit)
    assert editor is not None
    QTest.keyClicks(editor, "1")
    count.table.setCurrentCell(r, count_mod.NOTE_COL)  # move away without pressing Enter
    app.processEvents()
    assert count.table.item(r, count_mod.COUNT_MAIN).text() == "1"  # not doubled, not wiped
    diff = 1 - app_main
    from dibekho.core.text import fmt_qty

    assert count.table.item(r, count_mod.DIFF_COL).text() == ("+" if diff > 0 else "") + fmt_qty(diff)
    win.close()


def test_transfer_dialog_edits_through_the_frozen_pane(app, ws):
    """Số lượng is pinned on the right (frozen_columns): typing through that pane must land in the real
    cell, not open a second, hidden editor on the cell underneath."""
    from PySide6.QtWidgets import QAbstractItemDelegate, QLineEdit

    import dibekho.ui.count_page as count_mod

    make_note(ws.deliveries / "a.xlsx", code="1", lines=[PAINT])
    ctx, win = window(ws)
    known(ctx.conn, ws)
    paint = ctx.conn.execute("SELECT id FROM products WHERE name_zh = '背水涂'").fetchone()[0]
    dlg = count_mod.TransferDialog(ctx, win)
    dlg.show()
    dlg.resize(700, 320)  # narrow enough that Số lượng would scroll out of view without the frozen pane
    app.processEvents()
    assert dlg.frozen.isVisible()
    r = next(r for r in range(dlg.table.rowCount()) if dlg.table.item(r, 0).data(count_mod.Qt.UserRole) == paint)
    index = dlg.frozen.model().index(r, count_mod.TRANS_QTY)
    dlg.frozen.setCurrentIndex(index)
    dlg.frozen.edit(index)  # the way a double-click on the overlay opens an editor
    app.processEvents()
    editor = dlg.frozen.viewport().findChild(QLineEdit)
    assert editor is not None
    # the cell under the overlay never got its own, invisible editor open at the same time
    assert dlg.table.state() != dlg.table.State.EditingState
    editor.setText("4")
    dlg.frozen.commitData(editor)
    dlg.frozen.closeEditor(editor, QAbstractItemDelegate.NoHint)
    app.processEvents()
    assert dlg._typed().get(paint) == 4
    dlg.close()
    win.close()
