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


@pytest.mark.parametrize("lang", ["vi", "en"])
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
    win = MainWindow(ctx)
    win.show()
    win.rescan()
    for i in range(win.stack.count()):
        win.nav.setCurrentRow(i)
        app.processEvents()

    doc = ctx.conn.execute("SELECT id FROM documents LIMIT 1").fetchone()[0]
    cust = ctx.conn.execute("SELECT id FROM customers LIMIT 1").fetchone()[0]
    prod = ctx.conn.execute("SELECT id FROM products LIMIT 1").fetchone()[0]
    for dlg in (DocumentDialog(ctx, doc, win), CustomerDialog(ctx, cust, win), ProductDialog(ctx, prod, win)):
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

    settings = win.stack.widget(win.stack.count() - 1)
    for i in range(settings.tabs.count()):
        settings.tabs.setCurrentIndex(i)
        app.processEvents()

    from dibekho.ui.orders_page import CustomersPage, OrdersPage
    from dibekho.ui.stats_page import StatsPage

    for key, make in (("search.orders_btn", OrdersPage), ("search.customers_btn", CustomersPage)):
        win.search.open_window(key, make)
        app.processEvents()
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


def test_pending_page_drops_fee_lines(app, ws, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    i18n.set_language("vi")
    from dibekho.ui.common import AppContext
    from dibekho.ui.main_window import PENDING, MainWindow
    from dibekho.ui.pending_page import CHOICE, NEW, SKIP
    from tests.conftest import make_note

    make_note(ws.deliveries / "a.xlsx", lines=[("背水涂\nvữa chống thấm", "10KG/thùng", 3, ""),
                                               ("运费\nPhí vận chuyển", "", 1, "")])
    ctx = AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)
    win = MainWindow(ctx)
    win.show()
    win.rescan()
    win.nav.setCurrentRow(PENDING)
    app.processEvents()
    page = win.pending
    names = [page.unknown.item(r, 0).text() for r in range(page.unknown.rowCount())]
    fee, goods = names.index("Phí vận chuyển"), names.index("vữa chống thấm")
    assert page._choice(fee) == SKIP and page.unknown.item(fee, 0).font().strikeOut()
    assert page._choice(goods) == NEW
    page._toggle_drop(goods)
    assert page._choice(goods) == SKIP
    page._toggle_drop(goods)
    assert page._choice(goods) == NEW
    combo = page.unknown.cellWidget(goods, CHOICE)
    combo.setEditText("không có mặt hàng này")
    assert page._choice(goods) == "later"
    combo.setCurrentIndex(combo.findData(NEW))
    page.apply_mapping(confirm=False)
    assert ctx.conn.execute("SELECT COUNT(*) FROM document_lines").fetchone()[0] == 1
    assert ctx.conn.execute("SELECT COUNT(*) FROM ignored_lines").fetchone()[0] == 1
    win.close()


def test_undo_buttons(app, ws, monkeypatch):
    """'Đọc lại phiếu' in the order window and 'Quên và đọc lại' in settings."""
    import dibekho.ui.details as details_mod
    import dibekho.ui.settings_page as settings_mod

    for mod in (details_mod, settings_mod):
        monkeypatch.setattr(mod, "ask", lambda *a, **k: True)
        monkeypatch.setattr(mod, "info", lambda *a, **k: None)
    i18n.set_language("vi")
    from dibekho.ui.common import AppContext
    from dibekho.ui.details import DocumentDialog
    from dibekho.ui.main_window import MainWindow

    ctx = AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)
    setup_notes(ctx.conn, ws)
    win = MainWindow(ctx)
    win.show()
    doc = ctx.conn.execute("SELECT id FROM documents WHERE code = '1'").fetchone()[0]
    DocumentDialog(ctx, doc, win).reread_doc()
    assert ctx.conn.execute("SELECT status FROM documents WHERE id = ?", (doc,)).fetchone()[0] == "replaced"
    assert ctx.conn.execute("SELECT COUNT(*) FROM documents WHERE code = '1' AND status = 'active'").fetchone()[0] == 1

    settings = win.stack.widget(win.stack.count() - 1)
    win.nav.setCurrentRow(win.stack.count() - 1)
    app.processEvents()
    assert settings.learned.rowCount() == 2
    settings.learned.selectRow(0)
    settings.forget()
    app.processEvents()
    assert settings.learned.rowCount() == 1
    assert "(2)" in win.nav.item(1).text()  # both notes with the forgotten name wait under "Cần xử lý"
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
    from dibekho.ui.pending_page import CHOICE, LATER
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
    later = [page.unknown.item(r, 0).text() for r in range(page.unknown.rowCount())].index("Hàng chưa duyệt")
    combo = page.unknown.cellWidget(later, CHOICE)
    combo.setCurrentIndex(combo.findData(LATER))
    page.apply_mapping(confirm=False)
    assert ctx.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    assert ctx.conn.execute("SELECT COUNT(*) FROM document_lines").fetchone()[0] == 1
    assert ctx.conn.execute("SELECT name FROM customers").fetchone()[0] == "Khách Chờ"
    assert [page.unknown.item(r, 0).text() for r in range(page.unknown.rowCount())] == ["Hàng chưa duyệt"]
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
