"""The 'Phiếu xuất kho…' window, driven like a user: pick a customer and products, type numbers, save, undo."""

import os
from datetime import date

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from dibekho import db, i18n  # noqa: E402
from dibekho.core import catalog  # noqa: E402
from dibekho.core.stock import MAIN, OFFICE, stock_count, stock_levels  # noqa: E402
from dibekho.core.workspace import Config  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def type_in(box, text):
    box.setFocus()
    box.lineEdit().selectAll()
    QTest.keyClicks(box.lineEdit(), text)
    box.interpretText()


@pytest.mark.parametrize("lang", ["vi", "zh"])
def test_save_then_undo(app, ws, monkeypatch, lang):
    import dibekho.ui.issue_form as form_mod
    import dibekho.ui.main_window as main_mod
    import dibekho.ui.pending_page as pending_mod

    i18n.set_language(lang)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    asked = []
    for mod in (form_mod, main_mod):
        monkeypatch.setattr(mod, "ask", lambda parent, text, *a, **k: asked.append(text) or True)
    monkeypatch.setattr(main_mod, "info", lambda *a, **k: None)
    opened = []
    monkeypatch.setattr(form_mod, "open_path", opened.append)
    from dibekho.ui.common import AppContext
    from dibekho.ui.issue_form import IssueForm
    from dibekho.ui.main_window import MainWindow

    ctx = AppContext(Config(workspace=str(ws.root), language=lang, device_id="x", device_name="t"), ws)
    with db.transaction(ctx.conn):
        paint = catalog.create_product(ctx.conn, "Sơn chống thấm", "防水涂料", "20KG/thùng", "thùng")
        stock_count(ctx.conn, date(2026, 11, 1), {(paint, MAIN): 50, (paint, OFFICE): 8})
        catalog.upsert_customer(ctx.conn, "Công ty A", "0900 000 001", "Anh B", "1 Đường X")
    win = MainWindow(ctx)
    picks = iter([paint])
    monkeypatch.setattr(pending_mod.ProductPicker, "choose", lambda self: next(picks))

    form = IssueForm(ctx, win)
    form.customer.setCurrentIndex(1)
    assert form.phone.text() == "0900 000 001" and form.address.text() == "1 Đường X"
    form.rows[0].button.click()
    row = form.rows[0]
    type_in(row.qty_main, "10")
    type_in(row.qty_office, "2,5")
    type_in(row.price, "500000")
    assert row.qty() == 12.5
    form.save_btn.click()
    assert form.saved_doc is not None and opened
    levels = stock_levels(ctx.conn, by_location=True)
    assert (levels[(paint, MAIN)], levels[(paint, OFFICE)]) == (40, 5.5)
    assert win.undo_btn.isEnabled()

    win.undo_last()
    levels = stock_levels(ctx.conn, by_location=True)
    assert (levels[(paint, MAIN)], levels[(paint, OFFICE)]) == (50, 8)
    assert ctx.conn.execute("SELECT COUNT(*) FROM documents WHERE kind = 'delivery'").fetchone()[0] == 0
    win.close()


def test_enter_in_a_number_never_saves(app, ws, monkeypatch):
    import dibekho.ui.issue_form as form_mod

    i18n.set_language("vi")
    monkeypatch.setattr(form_mod, "ask", lambda *a, **k: pytest.fail("Enter must not ask to save"))
    from dibekho.ui.common import AppContext
    from dibekho.ui.issue_form import IssueForm

    ctx = AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)
    form = IssueForm(ctx)
    form.show()
    box = form.rows[0].qty_main
    type_in(box, "3")
    QTest.keyClick(box.lineEdit(), Qt.Key_Return)
    assert form.saved_doc is None and form.isVisible()
    form.done(0)
