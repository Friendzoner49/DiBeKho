"""Prices on delivery notes (24/10/2026): unit price and amount per line, fees, the printed total; revenue per
customer and per product; notes recorded by 0.3.0 and earlier get their prices from their stored copies."""

import shutil
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from dibekho import db
from dibekho.core import deliveries, queries, transfer
from dibekho.core.stock import stock_levels
from dibekho.core.workspace import Workspace
from dibekho.excel.delivery_note import read_delivery_note
from tests.conftest import SAMPLES, make_note
from tests.test_receipts import PRICE_COLUMNS_DROP

PAINT = ("背水涂\nvữa chống thấm", "10KG/thùng", 3, "", 700000)
SAND = ("固沙剂\nchất cố định cát", "10KG/thùng", 2, "", 650000)
SHIPPING = ("", "Phí vận chuyển", None, None, None, 190000, None)


def known(conn, ws):
    """Map every line of the notes now in the folder to a new product, then scan."""
    deliveries.scan(conn, ws)
    for line in deliveries.unknown_lines(conn, ws):
        deliveries.create_product_for_line(conn, line)
    return deliveries.scan(conn, ws)


def doc(conn, code):
    return conn.execute("SELECT * FROM documents WHERE code = ? AND status = 'active'", (code,)).fetchone()


def test_the_reader_takes_prices_fees_and_the_total(tmp_path):
    path = make_note(tmp_path / "a.xlsx", lines=[PAINT, SAND], extra_rows=[SHIPPING], total=3640000)
    note = read_delivery_note(path)
    assert [(ln.unit_price, ln.amount) for ln in note.lines] == [(700000, 2100000), (650000, 1300000)]
    assert note.fees == [("Phí vận chuyển", 190000)] and note.total == 3640000
    assert note.skipped_rows == ["Phí vận chuyển"]  # still not goods


def test_a_price_written_as_text_and_a_bad_price(tmp_path):
    path = make_note(tmp_path / "a.xlsx", lines=[(*PAINT[:4], "1.188.000"), (*SAND[:4], "hỏi lại")])
    note = read_delivery_note(path)  # a price never blocks the note
    assert (note.lines[0].unit_price, note.lines[0].amount) == (1188000, 3564000)
    assert (note.lines[1].unit_price, note.lines[1].amount) == (None, None)
    assert any("không đọc được giá" in w for w in note.warnings) and note.total is None


def test_an_imported_note_keeps_its_prices_and_fees(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="125", lines=[PAINT, SAND], extra_rows=[SHIPPING], total=3590000)
    assert known(conn, ws).pending == 0
    d = doc(conn, "125")
    assert d["fee_amount"] == 190000 and d["note_total"] == 3590000 and d["prices_read"] == 1
    head, lines = queries.document(conn, d["id"])
    assert [(ln["unit_price"], ln["amount"]) for ln in lines] == [(700000, 2100000), (650000, 1300000)]
    assert head["goods_amount"] == 3400000 and head["order_total"] == 3590000 and head["unpriced_lines"] == 0
    [row] = queries.documents(conn, "delivery")
    assert row["order_total"] == 3590000 and row["line_count"] == 2  # fees not multiplied by the lines


def test_revenue_per_customer_products_and_period(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="1", day="05-09-2026", lines=[PAINT, SAND], extra_rows=[SHIPPING])
    make_note(ws.deliveries / "b.xlsx", code="2", day="05-10-2026", lines=[(*PAINT[:4], 750000)])
    make_note(ws.deliveries / "c.xlsx", code="3", day="06-10-2026", customer="Công ty B", phone="0900 000 999",
              lines=[PAINT])
    known(conn, ws)
    cust = doc(conn, "1")["customer_id"]
    money = queries.customer_money(conn, cust)
    assert (money["orders"], money["goods"], money["fees"], money["total"]) == (2, 5650000, 190000, 5650000)  # revenue = goods, fees apart
    paint = {p["name_vi"]: p for p in queries.customer_products(conn, cust)}["vữa chống thấm"]
    assert (paint["total_qty"], paint["revenue"], paint["min_price"], paint["max_price"]) == (6, 4350000, 700000, 750000)
    october = queries.customer_lines(conn, cust, date(2026, 10, 1), date(2026, 10, 31))
    assert [(ln["code"], ln["unit_price"], ln["amount"]) for ln in october] == [("2", 750000, 2250000)]
    assert queries.customer_money(conn, cust, date(2026, 10, 1), date(2026, 10, 31))["total"] == 2250000
    by_name = {c["name"]: c["revenue"] for c in queries.customers(conn)}
    assert by_name == {"Công ty A": 5650000, "Công ty B": 2100000}


def test_cancelled_orders_and_unknown_prices_are_not_revenue(conn, ws):
    from dibekho.core.stock import close_document

    make_note(ws.deliveries / "a.xlsx", code="1", lines=[PAINT])
    make_note(ws.deliveries / "b.xlsx", code="2", lines=[(*SAND[:4], "")])  # no price written on the note
    known(conn, ws)
    cust = doc(conn, "1")["customer_id"]
    with db.transaction(conn):
        close_document(conn, doc(conn, "1")["id"])
    money = queries.customer_money(conn, cust)
    assert money["orders"] == 1 and money["total"] is None and money["unpriced"] == 1
    head, _ = queries.document(conn, doc(conn, "2")["id"])
    assert head["order_total"] is None and head["unpriced_lines"] == 1


def test_a_printed_total_of_0_over_empty_prices_is_no_price(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="000", lines=[(*SAND[:4], "")], total=0)
    known(conn, ws)
    d = doc(conn, "000")
    head, _ = queries.document(conn, d["id"])
    assert d["note_total"] == 0 and d["fee_amount"] is None and head["order_total"] is None


def test_a_line_decided_later_gets_its_price_and_a_dropped_line_is_a_fee(conn, ws):
    fee_line = ("运费\nphí giao hàng tận nơi", "chuyến", 1, "", 300000)
    make_note(ws.deliveries / "a.xlsx", code="9", lines=[PAINT, SAND, fee_line])
    deliveries.scan(conn, ws)
    unknown = {u.name_zh: u for u in deliveries.unknown_lines(conn, ws)}
    deliveries.create_product_for_line(conn, unknown["背水涂"])
    deliveries.ignore_unknown(conn, unknown["运费"])
    deliveries.scan(conn, ws, allow_partial=True)  # 'Apply' with SAND still waiting ('Later')
    d = doc(conn, "9")
    assert d["fee_amount"] == 300000
    deliveries.create_product_for_line(conn, deliveries.unknown_lines(conn, ws)[0])
    deliveries.scan(conn, ws)
    head, lines = queries.document(conn, d["id"])
    assert sorted(ln["amount"] for ln in lines) == [1300000, 2100000] and head["order_total"] == 3700000


def _as_0_3_0(path: Path) -> None:
    """Turn a database into what DiBeKho 0.3.0 left on disk (schema 6, no price columns)."""
    raw = sqlite3.connect(path)
    for sql in (*PRICE_COLUMNS_DROP, "PRAGMA user_version = 6"):
        raw.execute(sql)
    raw.commit()
    raw.close()


def test_notes_recorded_by_0_3_0_get_their_prices_from_the_stored_copies(tmp_path):
    ws = Workspace(tmp_path / "DiBeKho")
    ws.ensure()
    conn = db.connect(ws.db_path)
    make_note(ws.deliveries / "a.xlsx", code="1", lines=[PAINT, SAND], extra_rows=[SHIPPING])
    make_note(ws.deliveries / "b.xlsx", code="2", lines=[PAINT])
    known(conn, ws)
    gone = doc(conn, "2")["source_hash"]
    conn.close()
    _as_0_3_0(ws.db_path)
    (ws.originals / f"{gone}.xlsx").unlink()  # a note whose stored copy is lost

    conn = db.connect(ws.db_path)  # upgraded to schema 7: prices unknown until the next scan
    assert conn.execute("SELECT COUNT(*) FROM document_lines WHERE amount IS NOT NULL").fetchone()[0] == 0
    before = stock_levels(conn)
    deliveries.scan(conn, ws)
    assert stock_levels(conn) == before
    one, two = doc(conn, "1"), doc(conn, "2")
    assert (one["prices_read"], one["fee_amount"]) == (1, 190000)
    assert queries.document(conn, one["id"])[0]["order_total"] == 3590000
    assert two["prices_read"] == -1 and queries.document(conn, two["id"])[0]["order_total"] is None
    deliveries.scan(conn, ws)  # tried once only
    assert doc(conn, "2")["prices_read"] == -1
    conn.close()


@pytest.mark.parametrize("package", sorted(SAMPLES.glob("*.dibekho")) or [None])
def test_real_packages_keep_their_stock_and_get_prices(package, tmp_path):
    """The user's own data packages (samples/, not in git): same stock after the upgrade, every note read,
    goods + fees equal to the total printed on each note."""
    if package is None:
        pytest.skip("no data package in samples/")
    pkg = tmp_path / "pkg.dibekho"
    shutil.copy2(package, pkg)
    import zipfile

    with zipfile.ZipFile(pkg) as z:
        z.extract("kho.sqlite", tmp_path / "raw")
    raw = sqlite3.connect(tmp_path / "raw" / "kho.sqlite")
    before = dict(raw.execute("SELECT product_id, SUM(qty) FROM stock_movements GROUP BY product_id").fetchall())
    raw.close()
    ws = Workspace(tmp_path / "DiBeKho")
    ws.ensure()
    db.connect(ws.db_path).close()
    transfer.import_package(ws, pkg)
    conn = db.connect(ws.db_path)
    deliveries.scan(conn, ws)
    after = stock_levels(conn)
    assert all(abs(before.get(k, 0) - after.get(k, 0)) < 1e-9 for k in set(before) | set(after))
    docs = conn.execute("SELECT * FROM documents WHERE kind = 'delivery'").fetchall()
    assert docs and all(d["prices_read"] != 0 for d in docs)
    for d in docs:
        head = queries.document(conn, d["id"])[0]
        if d["note_total"] is not None and head["unpriced_lines"] == 0:
            assert abs(head["order_total"] - d["note_total"]) < 1
    conn.close()


def test_customer_window_lists_orders_with_their_prices(qtbot_free_app, ws):
    from PySide6.QtCore import QDate

    from dibekho.core.workspace import Config
    from dibekho.ui.common import AppContext
    from dibekho.ui.details import CustomerDialog, DocumentDialog

    make_note(ws.deliveries / "a.xlsx", code="1", day="05-09-2026", lines=[PAINT, SAND], extra_rows=[SHIPPING])
    make_note(ws.deliveries / "b.xlsx", code="2", day="05-10-2026", lines=[(*PAINT[:4], 750000)])
    ctx = AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)
    known(ctx.conn, ws)
    cust = doc(ctx.conn, "1")["customer_id"]
    dlg = CustomerDialog(ctx, cust)
    assert "5.650.000" in dlg.money.text() and "190.000" in dlg.money.text()
    tree = dlg.orders
    assert tree.topLevelItemCount() == 2
    newest = tree.topLevelItem(0)
    assert "2" in newest.text(0) and newest.text(6) == "2.250.000" and newest.child(0).text(5) == "750.000"
    oldest = tree.topLevelItem(1)
    assert oldest.childCount() == 3 and oldest.child(2).text(6) == "190.000"  # 2 lines, then the shipping fee
    dlg.all_time.setChecked(False)
    dlg.date_from.setDate(QDate(2026, 10, 1))
    dlg.date_to.setDate(QDate(2026, 10, 31))
    assert tree.topLevelItemCount() == 1 and "2.250.000" in dlg.money.text()
    dlg.close()
    d = DocumentDialog(ctx, doc(ctx.conn, "1")["id"])
    assert d.table.item(0, 8).text() == "2.100.000"
    d.close()
    ctx.close()


@pytest.fixture
def qtbot_free_app():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from dibekho import i18n

    app = QApplication.instance() or QApplication([])
    i18n.set_language("vi")
    return app
