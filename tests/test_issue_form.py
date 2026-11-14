"""The 'Phiếu xuất kho…' window, driven like a user: pick a customer and products, type numbers, save; the same product
on two lines at two prices; prices typed in yuan while the ₫ | ¥ switch shows yuan (user, 15/11/2026)."""

import os
from datetime import date, datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from dibekho import db, i18n  # noqa: E402
from dibekho.core import catalog, deliveries, fx, issues, reset  # noqa: E402
from dibekho.core.stock import MAIN, OFFICE, stock_count, stock_levels  # noqa: E402
from dibekho.core.workspace import Config  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def dong_again():
    yield
    fx.Display.currency, fx.Display.rate = "vnd", None


def type_in(box, text):
    box.setFocus()
    box.lineEdit().selectAll()
    QTest.keyClicks(box.lineEdit(), text)
    box.interpretText()


def _shop(ws, lang):
    from dibekho.ui.common import AppContext

    ctx = AppContext(Config(workspace=str(ws.root), language=lang, device_id="x", device_name="t"), ws)
    with db.transaction(ctx.conn):
        paint = catalog.create_product(ctx.conn, "Sơn chống thấm", "防水涂料", "20KG/thùng", "thùng")
        stock_count(ctx.conn, date(2026, 11, 1), {(paint, MAIN): 50, (paint, OFFICE): 8})
        catalog.upsert_customer(ctx.conn, "Công ty A", "0900 000 001", "Anh B", "1 Đường X")
    return ctx, paint


def _lines(conn):
    return [(r["qty"], r["unit_price"], r["amount"]) for r in conn.execute(
        "SELECT l.qty, l.unit_price, l.amount FROM document_lines l JOIN documents d ON d.id = l.document_id "
        "WHERE d.kind = 'delivery' AND d.status = 'active' ORDER BY l.line_no")]


@pytest.mark.parametrize("lang", ["vi", "zh"])
def test_the_same_product_on_two_lines_at_two_prices(app, ws, monkeypatch, lang):
    import dibekho.ui.issue_form as form_mod
    import dibekho.ui.pending_page as pending_mod

    i18n.set_language(lang)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    asked = []
    monkeypatch.setattr(form_mod, "ask", lambda parent, text, *a, **k: asked.append(text) or True)
    monkeypatch.setattr(form_mod, "error", lambda parent, text: pytest.fail(text))
    opened = []
    monkeypatch.setattr(form_mod, "open_path", opened.append)
    from dibekho.ui.issue_form import IssueForm

    ctx, paint = _shop(ws, lang)
    picks = iter([paint, paint])
    monkeypatch.setattr(pending_mod.ProductPicker, "choose", lambda self: next(picks))

    form = IssueForm(ctx)
    form.customer.setCurrentIndex(1)
    assert form.phone.text() == "0900 000 001" and form.address.text() == "1 Đường X"
    form.rows[0].button.click()
    form.rows[1].button.click()  # the same product again: allowed (another quantity, another price)
    type_in(form.rows[0].qty_main, "10")
    type_in(form.rows[0].price, "500000")
    type_in(form.rows[1].qty_main, "30")
    type_in(form.rows[1].qty_office, "2,5")
    type_in(form.rows[1].price, "450000")
    form.save_btn.click()
    assert form.saved_doc is not None and opened
    levels = stock_levels(ctx.conn, by_location=True)
    assert (levels[(paint, MAIN)], levels[(paint, OFFICE)]) == (10, 5.5)
    assert _lines(ctx.conn) == [(10, 500000, 5000000), (32.5, 450000, 14625000)]

    # read again from the files (Đặt lại tồn kho, a data package): the same two lines, each with its own price
    reset.reset_stock(ctx.conn, ctx.ws)
    deliveries.scan(ctx.conn, ctx.ws)
    assert _lines(ctx.conn) == [(10, 500000, 5000000), (32.5, 450000, 14625000)]
    levels = stock_levels(ctx.conn, by_location=True)  # the reset dropped the count too: only the note is left
    assert (levels[(paint, MAIN)], levels[(paint, OFFICE)]) == (-40, -2.5)

    # a wrong note is deleted, not undone: nothing of it is left
    doc = ctx.conn.execute("SELECT id FROM documents WHERE kind = 'delivery' AND status = 'active'").fetchone()[0]
    with db.transaction(ctx.conn):
        issues.delete(ctx.conn, ctx.ws, doc)
    levels = stock_levels(ctx.conn, by_location=True)
    assert (levels.get((paint, MAIN), 0), levels.get((paint, OFFICE), 0)) == (0, 0)
    ctx.close()


def test_prices_typed_in_yuan_are_saved_in_dong(app, ws, monkeypatch):
    import dibekho.ui.issue_form as form_mod
    import dibekho.ui.pending_page as pending_mod

    i18n.set_language("vi")
    asked = []
    monkeypatch.setattr(form_mod, "ask", lambda parent, text, *a, **k: asked.append(text) or True)
    monkeypatch.setattr(form_mod, "open_path", lambda *a: None)
    from dibekho.ui.issue_form import IssueForm

    ctx, paint = _shop(ws, "vi")
    fx.Display.rate = fx.Rate(3850.0, datetime(2026, 11, 15, 9, 0), datetime(2026, 11, 15, 9, 0))
    fx.Display.currency = "cny"
    picks = iter([paint, paint])
    monkeypatch.setattr(pending_mod.ProductPicker, "choose", lambda self: next(picks))

    form = IssueForm(ctx)
    assert "¥" in form.table.horizontalHeaderItem(form_mod.PRICE).text()
    form.customer.setCurrentText("Khách mới")
    form.rows[0].button.click()
    type_in(form.rows[0].qty_main, "2")
    type_in(form.rows[0].price, "100")  # ¥100 = 385.000 ₫
    assert form.table.cellWidget(0, form_mod.AMOUNT).text() == "¥200"
    form.save_btn.click()
    assert "385.000" in asked[-2] and "¥100" in asked[-2]  # the question shows both
    assert _lines(ctx.conn) == [(2, 385000, 770000)]

    # the next note suggests that price: shown in yuan, saved in its exact dong when left as it is
    form = IssueForm(ctx)
    form.customer.setCurrentText("Khách mới")
    form._customer_picked()
    form.rows[0].button.click()
    assert form.rows[0].price.value() == 100
    type_in(form.rows[0].qty_main, "1")
    assert form.data().filled()[0].unit_price == 385000
    ctx.close()


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
