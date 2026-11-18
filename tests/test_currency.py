"""A delivery note priced in yuan (user, 15/11/2026: order 155 was read as 4,800 dong). The reader tells it from the
note itself, the document keeps its currency and the rate of the moment, and no sum ever adds yuan to dong: every
revenue number comes in dong, in yuan, and the yuan as 'about … dong' for the brackets."""

import hashlib
import time
from datetime import date, datetime

import openpyxl
import pytest

from dibekho import db, i18n
from dibekho.core import deliveries, fx, queries, receipts, stats
from dibekho.core.receipts import RETURN, ReceiptInput, ReceiptLineInput
from dibekho.excel import report
from dibekho.excel.delivery_note import read_delivery_note
from tests.conftest import make_note
from tests.test_prices import doc, known

CNY_FORMAT = r'_-* #,##0\ [$CNY]_-;\-* #,##0\ [$CNY]_-;_-* "-"\ [$CNY]_-;_-@_-'
MEMBRANE = ("丙纶PPP\nMàng chống thấm PPP", "1.15m*87m/Cuộn", 10, "", 450)
GLUE = ("胶粉\nBột keo", "500g/袋", 30, "", 10)
PAINT = ("背水涂\nvữa chống thấm", "10KG/thùng", 3, "", 700000)


@pytest.fixture(autouse=True)
def vietnamese():
    i18n.set_language("vi")


def yuan_note(path, how="format", **kw):
    """A note on the shop's usual form (headers still say VND) whose prices are yuan."""
    make_note(path, **kw)
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    for row in ws.iter_rows():
        for cell in row:
            if how == "format" and cell.column in (5, 6) and isinstance(cell.value, (int, float)):
                cell.number_format = CNY_FORMAT
            if how == "words" and cell.value == "MỘT TRIỆU":
                cell.value = "BỐN NGHÌN TÁM TRĂM NHÂN DÂN TỆ"
            if how == "header" and isinstance(cell.value, str) and cell.value.endswith("\nVND"):
                cell.value = cell.value.replace("VND", "CNY")
    wb.save(path)
    return path


def rate(vnd_per_cny=3600.0):
    return fx.Rate(vnd_per_cny, datetime.now(), datetime.now())


@pytest.mark.parametrize("how", ["format", "words", "header"])
def test_the_reader_sees_a_note_in_yuan(tmp_path, how):
    note = read_delivery_note(yuan_note(tmp_path / "a.xlsx", how, code="155", lines=[MEMBRANE, GLUE]))
    assert note.currency == "CNY"
    assert [(ln.unit_price, ln.amount) for ln in note.lines] == [(450, 4500), (10, 300)]  # as printed, never converted


def test_an_ordinary_note_is_in_dong(tmp_path):
    assert read_delivery_note(make_note(tmp_path / "a.xlsx", lines=[PAINT])).currency == "VND"


def shop(conn, ws, monkeypatch):
    """Order 155 in yuan (4,800) and order 156 in dong (2,100,000) of the same customer, read at 3,600 dong a yuan."""
    monkeypatch.setattr(fx.Display, "rate", rate())
    yuan_note(ws.deliveries / "a.xlsx", code="155", day="11-11-2026", lines=[MEMBRANE, GLUE])
    make_note(ws.deliveries / "b.xlsx", code="156", day="12-11-2026", lines=[PAINT])
    assert known(conn, ws).pending == 0
    return doc(conn, "155"), doc(conn, "156")


def test_the_document_keeps_its_currency_and_the_rate_of_the_moment(conn, ws, monkeypatch):
    yuan, dong = shop(conn, ws, monkeypatch)
    assert (yuan["currency"], yuan["fx_rate"]) == ("CNY", 3600)
    assert (dong["currency"], dong["fx_rate"]) == ("VND", None)
    head, lines = queries.document(conn, yuan["id"])
    assert head["goods_amount"] == 4800 and [ln["amount"] for ln in lines] == [4500, 300]
    monkeypatch.setattr(fx.Display, "rate", rate(9999))
    deliveries.scan(conn, ws)
    deliveries.backfill_currency(conn, ws)
    assert doc(conn, "155")["fx_rate"] == 3600  # kept: the bracket does not move with today's rate


def test_no_sum_adds_yuan_to_dong(conn, ws, monkeypatch):
    yuan, dong = shop(conn, ws, monkeypatch)
    customer = yuan["customer_id"]
    [c] = queries.customers(conn)
    assert (c["revenue"], c["revenue_cny"], c["revenue_approx"]) == (2100000, 4800, 4800 * 3600)

    m = queries.customer_money(conn, customer)
    assert (m["orders"], m["goods"], m["total"]) == (2, 2100000, 2100000)
    assert m["cny"]["goods"] == m["cny"]["total"] == 4800 and m["approx"] == 4800 * 3600

    start, end = date(2026, 11, 1), date(2026, 11, 30)
    money = stats.money(conn, start, end)
    assert (money.orders, money.total, money.total_cny, money.approx) == (2, 2100000, 4800, 4800 * 3600)
    rows = {r.name_zh or r.name_vi: r for r in stats.summary(conn, start, end)}
    by_money = sorted(((r.revenue, r.revenue_cny) for r in rows.values()), key=str)
    assert by_money == sorted([(None, 300), (None, 4500), (2100000, None)], key=str)

    prods = queries.customer_products(conn, customer)
    ranges = sorted(((p["min_price"], p["max_price"], p["min_price_cny"], p["max_price_cny"]) for p in prods), key=str)
    assert ranges == sorted([(None, None, 10, 10), (None, None, 450, 450), (700000, 700000, None, None)], key=str)
    lines = queries.customer_lines(conn, customer)
    assert {ln["currency"] for ln in lines if ln["document_id"] == yuan["id"]} == {"CNY"}


def test_the_texts_show_both_and_the_approximation_in_brackets(monkeypatch):
    monkeypatch.setattr(fx.Display, "rate", None)
    assert fx.both_text(2100000, 0) == "2.100.000" and fx.both_text(None, None) == "—"  # no yuan: as before
    assert fx.both_text(2100000, 4800, 4800 * 3600) == "2.100.000 ₫ + ¥4.800 (≈ 19.380.000 ₫)"
    assert fx.both_text(None, 4800, 4800 * 3600) == "¥4.800 (≈ 17.280.000 ₫)"
    assert fx.both_text(2100000, 4800, 0) == "2.100.000 ₫ + ¥4.800"  # no rate known at all: no bracket
    assert fx.both_text(2100000, 4800, 4800 * 3600, brackets=False) == "2.100.000 ₫ + ¥4.800"
    assert fx.native_text(4800, "CNY", 3600) == "¥4.800 (≈ 17.280.000 ₫)"
    assert fx.native_text(450, "CNY", 3600, approx=False) == "¥450" and fx.native_text(4800, "", 3600) == "4.800"
    # a note read without a rate: today's rate fills the bracket
    monkeypatch.setattr(fx.Display, "rate", rate(3500))
    assert fx.native_text(100, "CNY") == "¥100 (≈ 350.000 ₫)" and fx.both_text(0, 100) == "¥100 (≈ 350.000 ₫)"
    # the switch on yuan: everything is yuan, one number, no bracket
    monkeypatch.setattr(fx.Display, "currency", "cny")
    assert fx.native_text(4800, "CNY", 3600) == "¥4.800"
    assert fx.both_text(350000, 4800, 4800 * 3600) == "¥4.900"
    assert fx.sort_value(1000, 2, 7000) == 8000 and fx.sort_value(None, None) is None


def test_notes_recorded_before_get_their_currency_once(conn, ws, monkeypatch):
    """0.5.4 read order 155 as dong: the stored copy of the note says yuan."""
    yuan, dong = shop(conn, ws, monkeypatch)
    with db.transaction(conn):
        conn.execute("UPDATE documents SET currency = '', fx_rate = NULL")
    assert queries.customer_money(conn, yuan["customer_id"])["goods"] == 2104800  # what 0.5.4 showed
    assert deliveries.backfill_currency(conn, ws) == 1
    assert (doc(conn, "155")["currency"], doc(conn, "155")["fx_rate"]) == ("CNY", 3600)
    assert doc(conn, "156")["currency"] == "VND"
    assert deliveries.backfill_currency(conn, ws) == 0  # once


def test_a_note_whose_copy_is_elsewhere_waits_and_a_late_rate_is_filled(conn, ws, monkeypatch):
    yuan, dong = shop(conn, ws, monkeypatch)
    with db.transaction(conn):
        conn.execute("UPDATE documents SET currency = '' WHERE id = ?", (dong["id"],))
        conn.execute("UPDATE documents SET fx_rate = NULL WHERE id = ?", (yuan["id"],))
    deliveries.original_copy(ws, dong["source_hash"]).unlink()  # this computer does not have the file
    monkeypatch.setattr(fx.Display, "rate", None)
    deliveries.backfill_currency(conn, ws)
    assert doc(conn, "156")["currency"] == "" and doc(conn, "155")["fx_rate"] is None  # no rate on this computer
    assert deliveries.needs_rate(conn)
    assert queries.customer_money(conn, dong["customer_id"])["goods"] == 2100000  # undecided counts as dong
    monkeypatch.setattr(fx.Display, "rate", rate(3555))  # the switch got one
    assert deliveries.fill_rates(conn) == 1 and doc(conn, "155")["fx_rate"] == 3555
    assert not deliveries.needs_rate(conn) and deliveries.fill_rates(conn) == 0


def test_reading_notes_never_asks_the_network(conn, ws, monkeypatch):
    """The rate kept with a yuan note is the switch's or the one cached on this computer: no request while scanning."""
    asked = []
    monkeypatch.setattr(fx, "_get", lambda url, timeout: asked.append(url))
    fx.save(fx.Rate(3520, datetime(2026, 11, 1), datetime(2026, 11, 1)))
    yuan_note(ws.deliveries / "a.xlsx", code="155", lines=[MEMBRANE])
    known(conn, ws)
    assert doc(conn, "155")["fx_rate"] == 3520 and asked == []


def test_goods_sent_back_from_an_order_in_yuan_come_off_the_yuan(conn, ws, monkeypatch):
    yuan, dong = shop(conn, ws, monkeypatch)
    customer = yuan["customer_id"]
    glue = conn.execute("SELECT product_id FROM document_lines WHERE document_id = ? AND qty = 30",
                        (yuan["id"],)).fetchone()[0]
    assert receipts.return_currency(conn, customer, "155") == ("CNY", 3600)
    assert receipts.return_currency(conn, customer, "156") == ("VND", None)
    assert receipts.return_currency(conn, customer, "", date(2026, 11, 11)) == ("CNY", 3600)  # the latest order then
    back = receipts.save(conn, ReceiptInput(date(2026, 11, 13), RETURN, customer_id=customer, ref_code="155",
                                            lines=[ReceiptLineInput(5, glue, unit_price=10)]))
    row = conn.execute("SELECT currency, fx_rate FROM documents WHERE id = ?", (back,)).fetchone()
    assert tuple(row) == ("CNY", 3600)
    m = queries.customer_money(conn, customer)
    assert (m["total"], m["returned"]) == (2100000, 0)
    assert (m["cny"]["total"], m["cny"]["returned"], m["approx"]) == (4750, 50, 4750 * 3600)
    money = stats.money(conn, date(2026, 11, 1), date(2026, 11, 30))
    assert (money.total, money.total_cny, money.returned_cny) == (2100000, 4750, 50)
    # a return saved by 0.5.4 gets the currency of its order
    with db.transaction(conn):
        conn.execute("UPDATE documents SET currency = '', fx_rate = NULL WHERE id = ?", (back,))
    deliveries.backfill_currency(conn, ws)
    assert conn.execute("SELECT currency FROM documents WHERE id = ?", (back,)).fetchone()[0] == "CNY"


def test_the_excel_files_keep_the_two_currencies_apart(conn, ws, monkeypatch, tmp_path):
    yuan, dong = shop(conn, ws, monkeypatch)
    start, end = date(2026, 11, 1), date(2026, 11, 30)
    path = report.export(tmp_path / "r.xlsx", conn, start, end, stats.Filters(), "none",
                         {"summary", "details", "customers", "top"}, "11/2026", "Tất cả")
    wb = openpyxl.load_workbook(path)
    summary = wb.worksheets[0]
    assert "2.100.000 ₫ + ¥4.800 (≈ 19.380.000 ₫)" in summary["A3"].value
    head = [c.value for c in summary[6]]
    col = head.index("Doanh thu (¥)") + 1
    assert head[col - 2] == "Doanh thu" and head[col] == "Ghi chú tồn kho"
    values = sorted([(r[col - 2].value, r[col - 1].value) for r in summary.iter_rows(min_row=7)], key=str)
    assert values == sorted([(2100000, None), (None, 4500), (None, 300)], key=str)
    assert all("¥" in r[col - 1].number_format for r in summary.iter_rows(min_row=7) if r[col - 1].value)
    details = wb.worksheets[1]
    marked = [r for r in details.iter_rows(min_row=7) if r[15].value == "CNY"]
    assert len(marked) == 2 and all("¥" in r[13].number_format for r in marked)
    assert details.cell(row=6, column=16).value == "Loại tiền"

    one = report.export_customer(tmp_path / "c.xlsx", conn, yuan["customer_id"], None, None, "Tất cả")
    wb = openpyxl.load_workbook(one)
    orders, products = wb.worksheets
    assert "2.100.000 ₫ + ¥4.800 (≈ 19.380.000 ₫)" in orders["A3"].value
    totals = {r[1].value: r[10] for r in orders.iter_rows(min_row=7) if r[3].value and r[2].value is None}
    assert "¥" in totals["155"].number_format and "¥" not in totals["156"].number_format
    assert [c.value for c in products[6]][-3:] == ["Doanh thu (¥)", "Giá thấp nhất (¥)", "Giá cao nhất (¥)"]


def test_a_period_without_yuan_exports_as_before(conn, ws, monkeypatch, tmp_path):
    make_note(ws.deliveries / "b.xlsx", code="156", day="12-11-2026", lines=[PAINT])
    known(conn, ws)
    path = report.export(tmp_path / "r.xlsx", conn, date(2026, 11, 1), date(2026, 11, 30), stats.Filters(), "none",
                         {"summary", "details"}, "11/2026", "Tất cả")
    wb = openpyxl.load_workbook(path)
    assert "Doanh thu (¥)" not in [c.value for c in wb.worksheets[0][6]] and "¥" not in wb.worksheets[0]["A3"].value
    assert wb.worksheets[1].cell(row=6, column=16).value is None


def test_a_database_of_0_5_4_is_upgraded(tmp_path):
    conn = db.connect(tmp_path / "kho.sqlite")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    assert {"currency", "fx_rate"} <= cols and db.schema_version() >= 11
    conn.close()


# ---- screens ------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_orders_list_tells_yuan_orders_from_dong_orders(app, ws, monkeypatch):
    import dibekho.ui.orders_page as orders_mod
    from dibekho.ui.details import CustomerDialog, DocumentDialog
    from tests.test_locations import window

    ctx, win = window(ws)
    yuan, dong = shop(ctx.conn, ws, monkeypatch)
    page = orders_mod.OrdersPage(ctx)
    page.all_time.setChecked(True)
    page.refresh()
    cell = lambda r, c: page.table.item(r, c).text()  # noqa: E731
    by_code = {cell(r, 1): r for r in range(page.table.rowCount())}
    assert set(by_code) == {"155", "156"}
    assert cell(by_code["155"], orders_mod.GOODS_CNY_COL) == "¥4.800 (≈ 17.280.000 ₫)"
    assert cell(by_code["155"], orders_mod.GOODS_COL) == ""  # never in the dong column
    assert cell(by_code["156"], orders_mod.GOODS_COL) == "2.100.000" and cell(by_code["156"], orders_mod.GOODS_CNY_COL) == ""

    page.currency.setCurrentIndex(page.currency.findData("CNY"))
    assert [cell(r, 1) for r in range(page.table.rowCount())] == ["155"]
    page.currency.setCurrentIndex(page.currency.findData("VND"))
    assert [cell(r, 1) for r in range(page.table.rowCount())] == ["156"]

    customers = orders_mod.CustomersPage(ctx)
    customers.refresh()
    assert customers.table.item(0, 5).text() == "2.100.000 ₫ + ¥4.800 (≈ 19.380.000 ₫)"

    dlg = DocumentDialog(ctx, yuan["id"], win)
    texts = " | ".join(w.text() for w in dlg.findChildren(__import__("PySide6.QtWidgets").QtWidgets.QLabel))
    assert "¥4.800 (≈ 17.280.000 ₫)" in texts and "1 ¥ ≈ 3.600 ₫" in texts
    dlg.deleteLater()
    cust = CustomerDialog(ctx, yuan["customer_id"], win)
    assert "2.100.000 ₫ + ¥4.800 (≈ 19.380.000 ₫)" in cust.money.text()
    cust.deleteLater()
    win.deleteLater()


def test_a_staff_machine_leaves_old_notes_alone(app, ws, monkeypatch):
    """backfill_currency would rewrite documents nobody touched: on a staff login they would all go for approval."""
    from tests.test_locations import window

    ctx, win = window(ws)
    shop(ctx.conn, ws, monkeypatch)
    with db.transaction(ctx.conn):
        ctx.conn.execute("UPDATE documents SET currency = ''")
    ctx.cfg.cloud_role = "editor"
    win.rescan(quiet=True)
    assert {r[0] for r in ctx.conn.execute("SELECT currency FROM documents")} == {""}
    ctx.cfg.cloud_role = "desktop"
    win.rescan(quiet=True)
    assert doc(ctx.conn, "155")["currency"] == "CNY"
    win.deleteLater()


class CopiesOnCloud:
    """The cloud bucket of kept notes (a real client raises CloudError for a file it does not have)."""

    def __init__(self, files):
        self.files, self.asked = files, []

    def storage_download(self, name, token):
        from dibekho.core.cloud.client import CloudError

        self.asked.append(name)
        if name not in self.files:
            raise CloudError("not found")
        return self.files[name]


def test_a_mac_signed_in_fetches_the_notes_it_lacks_and_reads_their_currency(app, ws, monkeypatch):
    """User, 15/11/2026: on a Mac the database came from the cloud, the stored copies did not, so order 155 stayed
    in the dong column. The owner's window downloads the copies of the undecided notes once, then reads them."""
    from dibekho.ui import main_window
    from tests.test_locations import window

    ctx, win = window(ws)
    yuan, dong = shop(ctx.conn, ws, monkeypatch)
    with db.transaction(ctx.conn):
        ctx.conn.execute("UPDATE documents SET currency = '', fx_rate = NULL")
    bucket = {}
    for d in (yuan, dong):
        copy = deliveries.original_copy(ws, d["source_hash"])
        bucket[f"phieu-goc/{copy.name}"] = copy.read_bytes()
        copy.unlink()  # this computer does not have the files
    bucket.pop(f"phieu-goc/{dong['source_hash']}.xlsx")  # one the bucket does not have either
    assert sorted(deliveries.missing_copies(ctx.conn, ws)) == sorted(f"{d['source_hash']}.xlsx" for d in (yuan, dong))
    cloud = CopiesOnCloud(bucket)
    monkeypatch.setattr(main_window.cloud_sync, "session", lambda cfg, timeout=None: (cloud, "tok"))
    win.rescan(quiet=True)
    for _ in range(200):
        app.processEvents()
        if doc(ctx.conn, "155")["currency"]:
            break
        time.sleep(0.02)
    assert doc(ctx.conn, "155")["currency"] == "CNY" and doc(ctx.conn, "155")["fx_rate"] == 3600
    assert doc(ctx.conn, "156")["currency"] == ""  # its copy is nowhere: stays undecided
    asked = len(cloud.asked)
    win.rescan(quiet=True)  # once per run: no second round of downloads
    app.processEvents()
    assert len(cloud.asked) == asked
    win.deleteLater()


def test_fetching_named_notes_skips_a_bad_name_and_a_damaged_file(ws):
    from dibekho.core.cloud import backup as cloud_backup

    good = b"phieu 1"
    name = f"{hashlib.sha256(good).hexdigest()}.xlsx"
    bad = f"{hashlib.sha256(b'other').hexdigest()}.xlsx"
    cloud = CopiesOnCloud({f"phieu-goc/{name}": good, f"phieu-goc/{bad}": b"tampered"})
    assert cloud_backup.fetch_named(ws, cloud, "tok", [name, bad, "../x.xlsx"]) == (1, 2)
    assert (ws.originals / name).read_bytes() == good and not (ws.originals / bad).exists()
    assert "phieu-goc/../x.xlsx" not in cloud.asked
