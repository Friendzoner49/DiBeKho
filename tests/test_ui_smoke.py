"""Open every screen and detail window with real data, without showing anything."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from dibekho import i18n  # noqa: E402
from dibekho.core.workspace import Config  # noqa: E402
from tests.test_features import setup_notes  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("lang", ["vi", "en", "zh"])
def test_every_screen_opens(app, ws, monkeypatch, lang):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    i18n.set_language(lang)
    from dibekho.ui.common import AppContext
    from dibekho.ui.details import CustomerDialog, DocumentDialog, ProductDialog
    from dibekho.ui.main_window import MainWindow

    cfg = Config(workspace=str(ws.root), language=lang, device_id="x", device_name="test")
    ctx = AppContext(cfg, ws)
    setup_notes(ctx.conn, ws)
    from datetime import date

    from dibekho import db
    from dibekho.core.stock import MAIN, OFFICE, Line, stock_count, transfer

    prod = ctx.conn.execute("SELECT id FROM products LIMIT 1").fetchone()[0]
    with db.transaction(ctx.conn):  # a count per place and a transfer, so their windows are opened too
        count_doc = stock_count(ctx.conn, date(2026, 10, 5), {(prod, MAIN): 9, (prod, OFFICE): 1, prod + 1: 3})
        transfer_doc = transfer(ctx.conn, date(2026, 10, 6), MAIN, OFFICE, [Line(prod, 2)])
    win = MainWindow(ctx)
    win.show()
    win.rescan()
    for i in range(win.stack.count()):
        win.nav.setCurrentRow(i)
        app.processEvents()

    doc = ctx.conn.execute("SELECT id FROM documents LIMIT 1").fetchone()[0]
    cust = ctx.conn.execute("SELECT id FROM customers LIMIT 1").fetchone()[0]
    from dibekho.ui.count_page import TransferDialog

    for dlg in (DocumentDialog(ctx, doc, win), CustomerDialog(ctx, cust, win), ProductDialog(ctx, prod, win),
                DocumentDialog(ctx, count_doc, win), DocumentDialog(ctx, transfer_doc, win), TransferDialog(ctx, win)):
        dlg.show()
        app.processEvents()
        dlg.close()

    from dibekho.excel.catalog_sheet import CatalogItem
    from dibekho.ui.catalog_import import CatalogImportDialog

    items = [CatalogItem(1, "Sơn mới", "新漆", "5KG", "thùng", "Sơn", "Trắng")]
    imp = CatalogImportDialog(ctx, ws.root / "t7.xlsx", items, win)
    imp.show()
    app.processEvents()
    assert [i.name_vi for i in imp.selected_items()] == ["Sơn mới"]
    imp.close()

    from dibekho.ui.license_dialog import LicenseDialog
    from dibekho.ui.log_dialog import LogDialog
    from dibekho.ui.receipt_form import NewProductDialog, ReceiptForm

    for dlg in (ReceiptForm(ctx, win), NewProductDialog(ctx, None, win), LogDialog(ctx, win),
                LicenseDialog(win)):
        dlg.show()
        app.processEvents()
        dlg.done(0)

    settings = win.stack.widget(win.stack.count() - 1)
    for i in range(settings.tabs.count()):
        settings.tabs.setCurrentIndex(i)
        app.processEvents()

    from dibekho.ui.orders_page import CustomersPage, OrdersPage
    from dibekho.ui.stats_page import StatsPage

    for key, make in (("search.orders_btn", OrdersPage), ("search.customers_btn", CustomersPage)):
        win.search.open_window(key, make)
        app.processEvents()
        page = win.search.windows[key].page
        if key == "search.orders_btn":  # every kind of document, transfers included
            for k in range(page.kind.count()):
                page.kind.setCurrentIndex(k)
                app.processEvents()
            assert page.table.rowCount() == 1  # the transfer
        win.search.windows[key].close()
    stats_win = win.search.open_window("search.stats_btn", StatsPage)
    app.processEvents()
    stats_page = stats_win.page
    for idx in range(stats_page.period.count()):
        stats_page.period.setCurrentIndex(idx)
        for s in range(stats_page.split.count()):
            stats_page.split.setCurrentIndex(s)
    win.close()
    i18n.set_language("vi")


def key_of(page, name):
    return next(k for k, u in page._unknown.items() if u.name_vi == name)


def test_pending_page_groups_lines_by_order(app, ws, monkeypatch):
    """One group per note with all its lines; fee lines are dropped by default; nothing unknown is created
    by itself; the drop-down ignores the mouse wheel; the same name in two orders takes one decision."""
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    i18n.set_language("vi")
    from dibekho.ui.common import AppContext, NoWheelCombo
    from dibekho.ui.main_window import PENDING, MainWindow
    from dibekho.ui.pending_page import LATER, NEW, SKIP
    from tests.conftest import make_note

    make_note(ws.deliveries / "a.xlsx", code="1", lines=[("背水涂\nvữa chống thấm", "10KG/thùng", 3, ""),
                                                         ("运费\nPhí vận chuyển", "", 1, "")])
    make_note(ws.deliveries / "b.xlsx", code="2", day="06-10-2026", lines=[("背水涂\nvữa chống thấm", "10KG/thùng", 2, "")])
    ctx = AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)
    win = MainWindow(ctx)
    win.show()
    win.rescan()
    win.nav.setCurrentRow(PENDING)
    app.processEvents()
    page = win.pending
    assert page.unknown.topLevelItemCount() == 2  # orders 1 and 2
    assert "Đơn 1" in page.unknown.topLevelItem(0).text(0) and page.unknown.topLevelItem(0).childCount() == 2
    fee, goods = key_of(page, "Phí vận chuyển"), key_of(page, "vữa chống thấm")
    assert page.choice(fee) == SKIP and page._rows[fee][0].font(0).strikeOut()
    assert page.choice(goods) == LATER  # no product is close: the user decides
    assert len(page._combos[goods]) == 2  # in both orders

    combo = page._combos[goods][0]
    assert isinstance(combo, NoWheelCombo)
    before = combo.currentIndex()
    combo.wheelEvent(QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120), Qt.NoButton,
                                 Qt.NoModifier, Qt.NoScrollPhase, False))
    assert combo.currentIndex() == before  # scrolling the page never changes a choice

    combo.setCurrentIndex(combo.findData(NEW))
    assert page._combos[goods][1].currentData() == NEW  # the other order follows
    assert page._openings[goods].isEnabled()
    assert not page._openings[fee].isEnabled()  # only a new product takes an opening stock
    page._openings[goods].setText("10")
    page.apply_mapping(confirm=False)
    from dibekho.core.stock import stock_levels

    assert list(stock_levels(ctx.conn).values()) == [10 - 3 - 2]
    assert ctx.conn.execute("SELECT COUNT(*) FROM ignored_lines").fetchone()[0] == 1
    assert page.unknown.topLevelItemCount() == 0
    win.close()


def test_undo_the_last_apply(app, ws, monkeypatch):
    import dibekho.ui.main_window as main_mod

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(main_mod, "ask", lambda *a, **k: True)
    monkeypatch.setattr(main_mod, "info", lambda *a, **k: None)
    i18n.set_language("vi")
    from dibekho.core import catalog
    from dibekho.ui.common import AppContext
    from dibekho.ui.main_window import MainWindow
    from tests.conftest import make_note

    make_note(ws.deliveries / "a.xlsx", code="125", lines=[("管根套 90-110\nBọc ống chân 90-110", "Cái", 20, "")])
    ctx = AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)
    with ctx.conn:
        pipe = catalog.create_product(ctx.conn, "Bọc chống thấm cổ ống nước 90-110", "管根套90-110", "90-110")
        membrane = catalog.create_product(ctx.conn, "Màng PPE", "高分子聚乙烯涤纶防水卷材", "16.5KG")
    win = MainWindow(ctx)
    win.show()
    win.rescan()
    page = win.pending
    page.refresh()
    assert not win.undo_btn.isEnabled()
    [key] = page._unknown
    assert page.choice(key) == pipe  # the right one is suggested first
    page.set_choice(key, membrane)  # the customer's mistake
    page.apply_mapping(confirm=False)
    assert ctx.conn.execute("SELECT product_id FROM document_lines").fetchone()[0] == membrane
    assert win.undo_btn.isEnabled() and "Áp dụng" in win.undo_btn.text()

    win.undo_last()
    assert ctx.conn.execute("SELECT COUNT(*) FROM documents WHERE kind = 'delivery'").fetchone()[0] == 0
    assert ctx.conn.execute("SELECT COUNT(*) FROM product_aliases").fetchone()[0] == 0
    page.refresh()
    assert list(page._unknown) == [key]  # back in 'Cần xử lý', to choose again
    assert not win.undo_btn.isEnabled()
    win.close()


def test_undo_buttons(app, ws, monkeypatch):
    """'Đọc lại cả phiếu' in the order window and 'Quên và đọc lại' in settings (grouped by order)."""
    import dibekho.ui.common as common_mod
    import dibekho.ui.details as details_mod
    import dibekho.ui.settings_page as settings_mod

    for mod in (details_mod, settings_mod, common_mod):
        monkeypatch.setattr(mod, "ask", lambda *a, **k: True)
    for mod in (settings_mod, common_mod):
        monkeypatch.setattr(mod, "info", lambda *a, **k: None)
    i18n.set_language("vi")
    from dibekho.ui.common import AppContext
    from dibekho.ui.details import DocumentDialog
    from dibekho.ui.main_window import MainWindow

    ctx = AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)
    a, b = setup_notes(ctx.conn, ws)
    win = MainWindow(ctx)
    win.show()
    doc = ctx.conn.execute("SELECT id FROM documents WHERE code = '1'").fetchone()[0]
    DocumentDialog(ctx, doc, win).reread_doc()
    # the whole order's names are forgotten: every active note sharing one (orders 2 and 3 too, via A)
    # comes back to Cần xử lý, not just order 1
    assert ctx.conn.execute("SELECT status FROM documents WHERE id = ?", (doc,)).fetchone()[0] == "replaced"
    assert ctx.conn.execute("SELECT COUNT(*) FROM documents WHERE status = 'active'").fetchone()[0] == 0
    assert "Đọc lại cả phiếu" in win.undo_btn.text()

    # choose the same products again, so the rest of this test can exercise the per-line 'Quên và đọc lại'
    from dibekho.core import deliveries

    for u in deliveries.unknown_lines(ctx.conn, ws):
        deliveries.map_line(ctx.conn, u.key, a if "背水涂" in u.name_zh else b, deliveries.line_label(u))
    deliveries.scan(ctx.conn, ws)

    settings = win.stack.widget(win.stack.count() - 1)
    win.nav.setCurrentRow(win.stack.count() - 1)
    app.processEvents()
    tree = settings.learned
    assert tree.topLevelItemCount() == 3  # orders 3, 2, 1 (newest first)
    assert "Đơn 3" in tree.topLevelItem(0).text(0) and not tree.topLevelItem(0).isExpanded()
    assert tree.topLevelItem(0).childCount() == 2
    from dibekho.core import deliveries

    line = next(ln for o in deliveries.learned_by_order(ctx.conn, ws) for ln in o.lines if "cát" in ln.label)
    settings.forget(line)
    app.processEvents()
    assert all(tree.topLevelItem(i).childCount() == 1 for i in range(tree.topLevelItemCount()) if
               tree.topLevelItem(i).childCount())
    # both notes with the forgotten name wait under "Cần xử lý", and the third one for its place
    assert "(3)" in win.nav.item(1).text()
    assert "Quên" in win.undo_btn.text()
    win.close()


def test_master_data_buttons(app, ws, tmp_path, monkeypatch):
    import dibekho.ui.transfer_page as transfer_mod

    seen = []
    monkeypatch.setattr(transfer_mod, "ask", lambda *a, **k: True)
    monkeypatch.setattr(transfer_mod, "open_path", lambda p: seen.append(p))
    monkeypatch.setattr(transfer_mod, "info", lambda parent, text: seen.append(text))
    i18n.set_language("vi")
    from dibekho.ui.common import AppContext
    from dibekho.ui.transfer_page import TransferPanel

    ctx = AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)
    setup_notes(ctx.conn, ws)
    panel = TransferPanel(ctx, lambda: None)
    panel.export_master()
    exported = seen[0]
    assert exported.exists() and exported.parent == ws.output

    other_ws = type(ws)(tmp_path / "other")
    other_ws.ensure()
    other = AppContext(Config(workspace=str(other_ws.root), language="vi", device_id="y", device_name="u"), other_ws)
    monkeypatch.setattr(transfer_mod.QFileDialog, "getOpenFileName", lambda *a, **k: (str(exported), ""))
    TransferPanel(other, lambda: None).import_master()
    assert other.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 2
    assert "2 mới" in seen[-1]


def test_catalog_in_input_and_pick_file(app, ws, monkeypatch):
    """Catalog sheet dropped into input/: shown as a catalog, importable; a file in da-xu-ly can be picked again."""
    import dibekho.ui.catalog_import as catalog_mod
    import dibekho.ui.receipt_page as receipt_mod
    from dibekho.ui.common import AppContext
    from dibekho.ui.main_window import PENDING, MainWindow
    from tests.test_catalog import make_sheet

    i18n.set_language("vi")
    monkeypatch.setattr(catalog_mod.CatalogImportDialog, "exec",
                        lambda self: (self.do_import(), catalog_mod.QDialog.Accepted)[1])
    monkeypatch.setattr(catalog_mod, "info", lambda *a, **k: None)
    monkeypatch.setattr(catalog_mod, "error", lambda *a, **k: None)  # 2nd time: every row exists, nothing ticked
    monkeypatch.setattr(receipt_mod, "info", lambda *a, **k: None)
    make_sheet(ws.input / "danh-muc.xlsx")
    ctx = AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)
    win = MainWindow(ctx)
    win.show()
    win.rescan()
    win.nav.setCurrentRow(PENDING)
    app.processEvents()
    page = win.pending
    assert [it.kind for it in page._items] == ["catalog"]
    page.import_catalog(page._items[0])
    assert ctx.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 6
    [moved] = list(ws.processed.iterdir())

    # picking the same file again from da-xu-ly on the goods-in page works and creates no duplicates
    monkeypatch.setattr(receipt_mod.QFileDialog, "getOpenFileName", lambda *a, **k: (str(moved), ""))
    win.stack.widget(3).pick_file()
    assert ctx.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 6
    assert moved.exists()
    win.close()


def test_apply_imports_approved_lines_and_keeps_the_rest_waiting(app, ws, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    i18n.set_language("vi")
    from dibekho.ui.common import AppContext
    from dibekho.ui.main_window import PENDING, MainWindow
    from dibekho.ui.pending_page import CHOICE, NEW
    from tests.conftest import make_note

    make_note(ws.deliveries / "a.xlsx", code="74", customer="Khách Chờ",
              lines=[("背水涂\nvữa chống thấm", "10KG/thùng", 3, ""), ("新产品\nHàng chưa duyệt", "5KG/thùng", 4, "")])
    ctx = AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)
    win = MainWindow(ctx)
    win.show()
    win.rescan()
    win.nav.setCurrentRow(PENDING)
    app.processEvents()
    page = win.pending
    page.set_choice(key_of(page, "vữa chống thấm"), NEW)  # 'Hàng chưa duyệt' stays 'Để sau'
    page.apply_mapping(confirm=False)
    assert ctx.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    assert ctx.conn.execute("SELECT COUNT(*) FROM document_lines").fetchone()[0] == 1
    assert ctx.conn.execute("SELECT name FROM customers").fetchone()[0] == "Khách Chờ"
    assert [u.name_vi for u in page._unknown.values()] == ["Hàng chưa duyệt"]
    head = page.unknown.topLevelItem(0)
    assert head.childCount() == 2 and head.child(0).text(CHOICE).startswith("✓")  # the approved line, to compare
    win.close()


def test_settings_edit_and_delete_buttons(app, ws, monkeypatch):
    import dibekho.ui.settings_page as settings_mod

    errors = []
    monkeypatch.setattr(settings_mod, "ask", lambda *a, **k: True)
    monkeypatch.setattr(settings_mod, "error", lambda parent, text: errors.append(text))
    monkeypatch.setattr(settings_mod.ProductEditor, "exec", lambda self: (self.name_vi.setText("Tên mới"),
                                                                          self.save(), self.result())[2])
    i18n.set_language("vi")
    from dibekho.core import catalog
    from dibekho.ui.common import AppContext
    from dibekho.ui.main_window import MainWindow

    ctx = AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)
    used, _ = setup_notes(ctx.conn, ws)
    spare = catalog.create_product(ctx.conn, "Sơn thừa")
    win = MainWindow(ctx)
    win.show()
    settings = win.stack.widget(win.stack.count() - 1)
    win.nav.setCurrentRow(win.stack.count() - 1)
    app.processEvents()

    def select(pid):
        row = next(r for r in range(settings.table.rowCount()) if settings.table.item(r, 0).data(Qt.UserRole) == pid)
        settings.table.selectRow(row)

    select(spare)
    settings.edit_selected()
    assert ctx.conn.execute("SELECT name_vi FROM products WHERE id = ?", (spare,)).fetchone()[0] == "Tên mới"
    select(spare)
    settings.delete_selected()
    assert ctx.conn.execute("SELECT COUNT(*) FROM products WHERE id = ?", (spare,)).fetchone()[0] == 0
    select(used)  # in documents: kept, marked inactive instead
    settings.delete_selected()
    assert ctx.conn.execute("SELECT active FROM products WHERE id = ?", (used,)).fetchone()[0] == 0
    select(used)
    settings.delete_selected()
    assert len(errors) == 1
    win.close()


def test_reset_buttons(app, ws, monkeypatch):
    import dibekho.ui.settings_page as settings_mod

    monkeypatch.setattr(settings_mod, "ask", lambda *a, **k: True)
    monkeypatch.setattr(settings_mod, "info", lambda *a, **k: None)
    i18n.set_language("vi")
    from dibekho.ui.common import AppContext
    from dibekho.ui.main_window import MainWindow

    ctx = AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)
    setup_notes(ctx.conn, ws)
    win = MainWindow(ctx)
    win.show()
    settings = win.stack.widget(win.stack.count() - 1)
    settings.reset_stock()
    count = lambda sql: ctx.conn.execute(sql).fetchone()[0]  # noqa: E731
    assert count("SELECT COUNT(*) FROM products") == 2
    assert count("SELECT COUNT(*) FROM documents WHERE status = 'active'") == 3  # read again right away
    settings.reset_all()
    assert count("SELECT COUNT(*) FROM products") == 0
    assert count("SELECT COUNT(*) FROM documents") == 0
    assert win.nav.currentRow() == 1  # 'Cần xử lý': the notes wait for product names again
    win.close()


def test_catalog_import_asks_for_the_stock_column(app, ws, monkeypatch):
    import dibekho.ui.catalog_import as catalog_mod
    from dibekho.core.stock import stock_levels
    from dibekho.ui.common import AppContext
    from tests.test_catalog import make_other_layout

    asked = []
    monkeypatch.setattr(catalog_mod, "ask_stock_column",
                        lambda parent, path, columns: (asked.append([c.letter for c in columns]), (True, 4))[1])
    monkeypatch.setattr(catalog_mod.CatalogImportDialog, "exec",
                        lambda self: (self.do_import(), catalog_mod.QDialog.Accepted)[1])
    monkeypatch.setattr(catalog_mod, "info", lambda *a, **k: None)
    i18n.set_language("vi")
    ctx = AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)
    assert catalog_mod.import_catalog_file(ctx, None, make_other_layout(ws.root / "khac.xlsx"))
    assert asked == [["C", "D"]]
    assert sorted(stock_levels(ctx.conn).values()) == [7.5, 12]

    # the dialog itself: 'no stock' first, then one line per column
    dlg = catalog_mod.StockColumnDialog(ws.root / "khac.xlsx", [], None)
    assert dlg.chosen() is None


def test_master_file_dropped_in_input_is_imported_from_to_do(app, ws, monkeypatch):
    import dibekho.ui.transfer_page as transfer_mod
    from dibekho import db
    from dibekho.core import catalog
    from dibekho.excel import master_data
    from dibekho.ui.common import AppContext
    from dibekho.ui.main_window import PENDING, MainWindow

    monkeypatch.setattr(transfer_mod, "ask", lambda *a, **k: True)
    monkeypatch.setattr(transfer_mod, "info", lambda *a, **k: None)
    i18n.set_language("vi")
    source = db.connect(":memory:")
    with db.transaction(source):
        catalog.create_product(source, "Sơn A", spec="20KG")
    path = master_data.export(ws.input / "goc.xlsx", source)
    import openpyxl

    wb = openpyxl.load_workbook(path)
    wb.worksheets[2]["E5"] = 42  # the customer corrects the stock in the file
    wb.save(path)

    ctx = AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)
    win = MainWindow(ctx)
    win.show()
    win.rescan()
    win.nav.setCurrentRow(PENDING)
    app.processEvents()
    [item] = win.pending._items
    assert item.kind == "master"
    win.pending.import_master(item)
    from dibekho.core.stock import stock_levels

    assert list(stock_levels(ctx.conn).values()) == [42]
    assert not path.exists() and list(ws.processed.iterdir())  # moved to input/da-xu-ly
    win.close()


def test_goods_in_window(app, ws, monkeypatch):
    """3 suggested rows, '+' adds one, the wheel never changes a quantity, a new product on its row; saving
    records the receipt, writes its file and keeps an undo point; editing replaces it under the same code."""
    from datetime import date

    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent

    import dibekho.ui.receipt_form as form_mod
    from dibekho import db
    from dibekho.core import catalog, receipts, undo
    from dibekho.core.receipts import SUPPLIER, NewProduct, ReceiptInput, ReceiptLineInput
    from dibekho.core.stock import stock_levels
    from dibekho.ui.common import AppContext, NoWheelSpin

    i18n.set_language("vi")
    asked = []
    monkeypatch.setattr(form_mod, "ask", lambda parent, text, *a: asked.append(text) or True)
    monkeypatch.setattr(form_mod, "open_path", lambda *a: None)
    ctx = AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)
    with db.transaction(ctx.conn):
        a, b, c, d = (catalog.create_product(ctx.conn, f"Sơn {x}", spec="20KG", unit="thùng") for x in "ABCD")
    receipts.save(ctx.conn, ReceiptInput(date(2026, 9, 1), SUPPLIER, supplier_name="Công ty mẹ",
                                         lines=[ReceiptLineInput(1, c), ReceiptLineInput(1, d), ReceiptLineInput(1, a)]))

    form = form_mod.ReceiptForm(ctx)
    assert form.supplier.currentText() == "Công ty mẹ"  # the last supplier
    assert len(form.rows) == 3 and {r.product_id for r in form.rows} == {a, c, d}
    form.add_row()
    assert len(form.rows) == 4 and form.rows[3].product_id is None

    qty = form.rows[0].qty
    assert isinstance(qty, NoWheelSpin)
    qty.wheelEvent(QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120), Qt.NoButton,
                               Qt.NoModifier, Qt.NoScrollPhase, False))
    assert qty.value() == 0  # scrolling the window never types a quantity
    from PySide6.QtCore import QLocale

    qty.setLocale(QLocale(QLocale.Vietnamese))  # '.' is the thousands separator there: '1.5' became 15
    for typed in ("1.5", "1,5"):
        qty.lineEdit().setText(typed)
        qty.interpretText()
        assert qty.value() == 1.5 and qty.text() == "1,5"
    qty.setValue(0)

    form.rows[0].qty.setValue(12)
    form._set_product(form.rows[3], None, NewProduct("Keo mới", spec="5KG", unit="thùng"))
    form.rows[3].qty.setValue(4)
    first = form.rows[0].product_id
    form.save()
    assert form.saved_doc
    confirm = asked[0]
    assert "★ Keo mới" in confirm and "2 dòng chưa có số lượng" in confirm
    new_id = ctx.conn.execute("SELECT id FROM products WHERE name_vi = 'Keo mới'").fetchone()[0]
    levels = stock_levels(ctx.conn)
    assert levels[first] == 1 + 12 and levels[new_id] == 4
    assert [p.action for p in undo.points(ws)][0] == "receipt"
    assert list((ws.output / "hang-ve").glob("HangVe_HV002_*.xlsx"))

    # edit: 12 was meant to be 2
    doc = form.saved_doc
    edit = form_mod.ReceiptForm(ctx, doc_id=doc)
    assert [r.qty.value() for r in edit.rows] == [12, 4]
    edit.rows[0].qty.setValue(2)
    edit.save()
    assert stock_levels(ctx.conn)[first] == 1 + 2
    assert ctx.conn.execute("SELECT status FROM documents WHERE id = ?", (doc,)).fetchone()[0] == "replaced"
    assert ctx.conn.execute("SELECT code FROM documents WHERE id = ?", (edit.saved_doc,)).fetchone()[0] == "HV002"

    # a customer return: the customer's order is suggested, nothing is saved without a customer
    return_form = form_mod.ReceiptForm(ctx)
    return_form.src_return.setChecked(True)
    assert return_form.customer.isVisibleTo(return_form) and not return_form.supplier.isVisibleTo(return_form)
    errors = []
    monkeypatch.setattr(form_mod, "error", lambda parent, text: errors.append(text))
    return_form.rows[0].qty.setValue(1)
    return_form._set_product(return_form.rows[0], a)
    return_form.save()
    assert return_form.saved_doc is None and "khách hàng" in errors[0]


def test_stock_rows_without_code_are_checked_before_import(app, ws, tmp_path, monkeypatch):
    """Old master file: the preview shows the matching found from the stock sheet; a row given to the wrong
    product turns yellow, one product for two rows is refused, and the import uses the user's choice."""
    import dibekho.ui.transfer_page as transfer_mod
    from dibekho import db
    from dibekho.core.stock import stock_levels
    from dibekho.ui.common import AppContext
    from tests.test_master_data import PPE_NAME, old_file_with_stock, ppe_variants

    i18n.set_language("vi")
    source = db.connect(":memory:")
    ppe_variants(source)
    path = old_file_with_stock(source, tmp_path / "goc.xlsx",
                               [(PPE_NAME, "瑞德牌", "瑞德牌", 79), (PPE_NAME, "瑞德牌", "纯白色", 31)])
    dlg = transfer_mod.StockMatchDialog(None, *[x for i, x in enumerate(transfer_mod.master_data.read(path))
                                               if i != 1])
    assert dlg.summary.text().startswith("✓")
    first, second = (combo.currentData() for combo in dlg.combos)
    assert "SP001" in dlg.table.item(1, dlg.PROBLEM).text()  # SP001 will take the stock sheet's labels
    dlg.combos[1].setCurrentIndex(dlg.combos[1].findData(first))  # the user gives row 6 to SP002 as well
    problems = [dlg.table.item(r, dlg.PROBLEM).text() for r in range(2)]
    assert "dòng 6" in problems[0] and "dòng 5" in problems[1]  # SP002 is now given to both rows
    assert "2 dòng" in dlg.summary.text()
    errors = []
    monkeypatch.setattr(transfer_mod, "error", lambda parent, text: errors.append(text))
    dlg._accept()
    assert errors and dlg.result() != transfer_mod.QDialog.Accepted  # one product given two rows is refused
    dlg.combos[1].setCurrentIndex(dlg.combos[1].findData(second))

    other_ws = type(ws)(tmp_path / "other")
    other_ws.ensure()
    ctx = AppContext(Config(workspace=str(other_ws.root), language="vi", device_id="y", device_name="u"), other_ws)
    monkeypatch.setattr(transfer_mod.StockMatchDialog, "exec", lambda self: transfer_mod.QDialog.Accepted)
    monkeypatch.setattr(transfer_mod, "ask", lambda *a, **k: True)
    monkeypatch.setattr(transfer_mod, "info", lambda *a, **k: None)
    assert transfer_mod.import_master_file(ctx, None, path)
    levels = stock_levels(ctx.conn)
    got = {r["code"]: levels.get(r["id"], 0) for r in ctx.conn.execute("SELECT id, code FROM products")}
    assert got == {"SP001": 31, "SP002": 79}
