"""The 'Phiếu xuất kho…' window, driven like a user: pick a customer and products, type numbers, save; the same product
on two lines at two prices; a yuan note while the ₫ | ¥ switch shows yuan (user, 21/11/2026)."""

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


@pytest.fixture(autouse=True)
def menu(monkeypatch):
    """The product button opens a menu (catalog / ★ new product): the test says which entry is clicked."""
    import dibekho.ui.issue_form as form_mod

    choice = ["receipt_form.pick_existing"]
    monkeypatch.setattr(form_mod.IssueForm, "_open_menu",
                        lambda self, menu, row: next(x for x in menu.actions() if x.text() == i18n.t(choice[0])))
    return choice


def type_customer(form, text, more=False):
    """Text typed into the customer box (insert: it sends textEdited like a keystroke; QTest.keyClicks
    cannot type a Vietnamese letter). more=True goes on typing after what is there."""
    form.customer.setFocus()
    if not more:
        form.customer.lineEdit().clear()
    form.customer.lineEdit().insert(text)


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


def test_a_note_made_while_the_switch_shows_yuan_is_a_yuan_note(app, ws, monkeypatch):
    """₫ | ¥ on ¥ (user, 21/11/2026): prices typed in yuan stay yuan in the data and in the Excel file (CNY), the rate
    of the window is kept on the document; the next note suggests that yuan price; a dong note stays dong when
    edited while the switch shows yuan."""
    import openpyxl

    import dibekho.ui.issue_form as form_mod
    import dibekho.ui.pending_page as pending_mod
    from dibekho.excel.delivery_note import read_delivery_note

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
    type_in(form.rows[0].price, "100.5")
    assert form.table.cellWidget(0, form_mod.AMOUNT).text() == "¥201"
    form.save_btn.click()
    assert "¥201" in asked[-2] and "773.850" in asked[-2]  # the question shows the yuan and about how many dong
    assert _lines(ctx.conn) == [(2, 100.5, 201)]
    doc = ctx.conn.execute("SELECT * FROM documents WHERE kind = 'delivery'").fetchone()
    assert doc["currency"] == "CNY" and doc["fx_rate"] == 3850.0
    path = next((ws.output / "phieu-xuat").glob("PhieuXuat_A*.xlsx"))
    assert read_delivery_note(path).currency == "CNY"
    sheet = openpyxl.load_workbook(path).active
    texts = [str(c.value) for row in sheet.iter_rows() for c in row if c.value is not None]
    assert any("CNY" in x for x in texts) and any(x.endswith("NHÂN DÂN TỆ") for x in texts)

    # the next note suggests that price, in yuan, and keeps it as it is
    form = IssueForm(ctx)
    form.customer.setCurrentText("Khách mới")
    form._customer_picked()
    form.rows[0].button.click()
    assert form.rows[0].price.value() == 100.5
    type_in(form.rows[0].qty_main, "1")
    assert form.data().filled()[0].unit_price == 100.5 and form.data().currency == "CNY"

    # a dong note edited while the switch shows yuan stays a dong note
    fx.Display.currency = "vnd"
    dong_doc, _ = issues.save(ctx.conn, ctx.ws, issues.IssueInput(
        date(2026, 11, 16), "Công ty A", lines=[issues.IssueLineInput(paint, qty_main=1, unit_price=500000)]))
    fx.Display.currency = "cny"
    form = IssueForm(ctx, edit_doc=dong_doc)
    assert not form.cny and "¥" not in form.table.horizontalHeaderItem(form_mod.PRICE).text()
    assert form.data().filled()[0].unit_price == 500000 and form.data().currency == "VND"
    ctx.close()


def test_a_product_not_in_the_catalog_goes_out_below_zero_and_the_goods_in_balance_it(app, ws, monkeypatch, menu):
    """Customer, 15/11/2026: a note may carry goods not in the catalog yet; the stock goes below zero and the next
    Hàng về of that product brings it back to the right number."""
    import dibekho.ui.issue_form as form_mod
    from dibekho.core import receipts
    from dibekho.core.receipts import NewProduct, ReceiptInput, ReceiptLineInput
    from dibekho.ui.receipt_form import NewProductDialog

    i18n.set_language("vi")
    asked = []
    monkeypatch.setattr(form_mod, "ask", lambda parent, text, *a, **k: asked.append(text) or True)
    monkeypatch.setattr(form_mod, "error", lambda parent, text: pytest.fail(text))
    monkeypatch.setattr(form_mod, "open_path", lambda *a: None)

    def described(self):
        self.result_product = NewProduct("Màng chống thấm mới", "新防水卷材", "1m×10m", unit="cuộn", category="Màng")
        return 1

    monkeypatch.setattr(NewProductDialog, "exec", described)
    from dibekho.ui.issue_form import IssueForm

    ctx, paint = _shop(ws, "vi")
    form = IssueForm(ctx)
    form.customer.setCurrentIndex(1)
    menu[0] = "receipt_form.pick_new"
    form.rows[0].button.click()
    assert form.rows[0].button.text().startswith("★ Màng chống thấm mới")
    assert form.table.cellWidget(0, form_mod.HAVE_MAIN).text() == "0"
    type_in(form.rows[0].qty_main, "4")
    type_in(form.rows[0].price, "300000")
    form.save_btn.click()
    assert form.saved_doc is not None
    assert i18n.t("issue.confirm_new") in asked[-2]
    new = ctx.conn.execute("SELECT * FROM products WHERE name_vi = 'Màng chống thấm mới'").fetchone()
    assert (new["code"], new["unit"], new["spec"]) == ("SP002", "cuộn", "1m×10m")
    assert stock_levels(ctx.conn, by_location=True)[(new["id"], MAIN)] == -4
    assert deliveries.pending_count(ctx.conn) == 0  # read back by its code: nothing waits in Cần xử lý
    assert _lines(ctx.conn) == [(4, 300000, 1200000)]

    receipts.save(ctx.conn, ReceiptInput(date(2026, 11, 16), receipts.SUPPLIER, supplier_name="Công ty mẹ",
                                         lines=[ReceiptLineInput(10, new["id"])]), ws=ctx.ws)
    assert stock_levels(ctx.conn, by_location=True)[(new["id"], MAIN)] == 6
    ctx.close()


def test_a_new_product_that_is_already_in_the_catalog_uses_the_existing_one(app, ws, monkeypatch, menu):
    import dibekho.ui.issue_form as form_mod
    from dibekho.core.receipts import NewProduct
    from dibekho.ui.receipt_form import NewProductDialog

    i18n.set_language("vi")
    monkeypatch.setattr(form_mod, "ask", lambda *a, **k: True)
    monkeypatch.setattr(form_mod, "open_path", lambda *a: None)

    def described(self):
        self.result_product = NewProduct("Sơn chống thấm", "防水涂料", "20KG/thùng", unit="thùng")
        return 1

    monkeypatch.setattr(NewProductDialog, "exec", described)
    from dibekho.ui.issue_form import IssueForm

    ctx, paint = _shop(ws, "vi")
    form = IssueForm(ctx)
    form.customer.setCurrentIndex(1)
    menu[0] = "receipt_form.pick_new"
    form.rows[0].button.click()
    type_in(form.rows[0].qty_main, "5")
    form.save_btn.click()
    assert ctx.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1
    assert stock_levels(ctx.conn, by_location=True)[(paint, MAIN)] == 45
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


def _fill_dialog(monkeypatch, values):
    """CustomerInfoDialog.exec types `values` and clicks Lưu."""
    from PySide6.QtWidgets import QDialog

    import dibekho.ui.customer_form as cf

    def fake_exec(self):
        for key, text in values.items():
            self.boxes[key].setText(text)
        self._check()
        return QDialog.Accepted if self.result() == QDialog.Accepted else QDialog.Rejected

    monkeypatch.setattr(cf.CustomerInfoDialog, "exec", fake_exec)


def test_a_new_customer_with_every_detail_is_saved_with_the_note(app, ws, monkeypatch):
    """Customer's request 18/11/2026: '＋ Khách hàng mới…' takes name, phone, contact, address, MST and email."""
    import dibekho.ui.issue_form as form_mod
    import dibekho.ui.pending_page as pending_mod

    i18n.set_language("vi")
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(form_mod, "ask", lambda *a, **k: True)
    monkeypatch.setattr(form_mod, "error", lambda parent, text: pytest.fail(text))
    monkeypatch.setattr(form_mod, "open_path", lambda *a: None)
    from dibekho.ui.issue_form import IssueForm

    ctx, paint = _shop(ws, "vi")
    monkeypatch.setattr(pending_mod.ProductPicker, "choose", lambda self: paint)
    _fill_dialog(monkeypatch, {"name": "Công ty Mới", "phone": "0900 000 007", "contact": "Chị C",
                               "address": "2 Đường Y", "tax_code": "0101234567", "email": "moi@example.com"})
    form = IssueForm(ctx)
    form.new_customer_btn.click()
    assert (form.customer.currentText(), form.tax_code.text(), form.email.text()) == (
        "Công ty Mới", "0101234567", "moi@example.com")
    form.rows[0].button.click()
    type_in(form.rows[0].qty_main, "2")
    form.save_btn.click()
    assert form.saved_doc is not None
    c = ctx.conn.execute("SELECT c.* FROM customers c JOIN documents d ON d.customer_id = c.id WHERE d.id = ?",
                         (form.saved_doc,)).fetchone()
    assert (c["name"], c["phone"], c["contact"], c["address"], c["tax_code"], c["email"]) == (
        "Công ty Mới", "0900 000 007", "Chị C", "2 Đường Y", "0101234567", "moi@example.com")
    ctx.close()


def test_a_new_customer_already_in_the_list_picks_the_existing_one(app, ws, monkeypatch):
    import dibekho.ui.issue_form as form_mod

    i18n.set_language("vi")
    asked = []
    monkeypatch.setattr(form_mod, "ask", lambda parent, text, *a, **k: asked.append(text) or True)
    from dibekho.ui.issue_form import IssueForm

    ctx, paint = _shop(ws, "vi")
    with db.transaction(ctx.conn):
        cid = ctx.conn.execute("SELECT id FROM customers").fetchone()[0]
        catalog.update_customer(ctx.conn, cid, tax_code="0109", email="a@example.com")
    _fill_dialog(monkeypatch, {"name": "Ai đó", "phone": "0900000001"})
    form = IssueForm(ctx)
    form.new_customer_btn.click()
    assert asked and "Công ty A" in asked[0]
    assert (form.customer.currentText().split(" · ")[0], form.phone.text(), form.tax_code.text(),
            form.email.text()) == ("Công ty A", "0900 000 001", "0109", "a@example.com")
    ctx.close()


def test_editing_a_customer_from_its_detail_window(app, ws, monkeypatch):
    import dibekho.ui.customer_form as cf

    i18n.set_language("vi")
    monkeypatch.setattr(cf, "ask", lambda *a, **k: pytest.fail("no other customer has this phone or name"))
    from dibekho.ui.details import CustomerDialog

    ctx, _ = _shop(ws, "vi")
    cid = ctx.conn.execute("SELECT id FROM customers").fetchone()[0]
    _fill_dialog(monkeypatch, {"name": "Công ty A (mới)", "tax_code": "0101234567", "email": "a@example.com"})
    dlg = CustomerDialog(ctx, cid)
    assert dlg.fields["tax_code"].text() == "—"
    dlg.edit_info()
    assert (dlg.title.text(), dlg.fields["tax_code"].text(), dlg.fields["email"].text()) == (
        "Công ty A (mới)", "0101234567", "a@example.com")
    c = ctx.conn.execute("SELECT * FROM customers WHERE id = ?", (cid,)).fetchone()
    assert (c["name"], c["phone"], c["tax_code"]) == ("Công ty A (mới)", "0900 000 001", "0101234567")
    dlg.close()
    ctx.close()


def test_a_tax_code_typed_the_first_time_is_kept_for_the_customer(app, ws, monkeypatch):
    """User, 18/11/2026: an MST belongs to the customer; typed on the issue note for a customer who has none, it is
    added to that customer (one already there is left alone: change it in Sửa thông tin khách hàng)."""
    import dibekho.ui.issue_form as form_mod
    import dibekho.ui.pending_page as pending_mod

    i18n.set_language("vi")
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(form_mod, "ask", lambda *a, **k: True)
    monkeypatch.setattr(form_mod, "error", lambda parent, text: pytest.fail(text))
    monkeypatch.setattr(form_mod, "open_path", lambda *a: None)
    from dibekho.ui.issue_form import IssueForm

    ctx, paint = _shop(ws, "vi")
    monkeypatch.setattr(pending_mod.ProductPicker, "choose", lambda self: paint)
    form = IssueForm(ctx)
    form.customer.setCurrentIndex(1)
    assert form.tax_code.text() == "" and form.email.text() == ""
    form.tax_code.setText("0101234567")
    form.email.setText("a@example.com")
    form.rows[0].button.click()
    type_in(form.rows[0].qty_main, "1")
    form.save_btn.click()
    assert form.saved_doc is not None
    c = ctx.conn.execute("SELECT * FROM customers").fetchall()
    assert len(c) == 1 and (c[0]["name"], c[0]["tax_code"], c[0]["email"]) == ("Công ty A", "0101234567", "a@example.com")
    ctx.close()


@pytest.mark.parametrize("lang", ["vi", "zh"])
def test_editing_a_note_in_the_window_keeps_code_and_prices_and_recounts(app, ws, monkeypatch, lang):
    """Customer, 19/11/2026: prices and quantities of an issued note can be corrected, only for notes made here."""
    import dibekho.ui.issue_form as form_mod
    from dibekho.ui.issue_form import IssueForm

    i18n.set_language(lang)
    monkeypatch.setattr(form_mod, "ask", lambda parent, text, *a, **k: False if "issue.confirm_close" in text else True)
    monkeypatch.setattr(form_mod, "error", lambda parent, text: pytest.fail(text))
    monkeypatch.setattr(form_mod, "open_path", lambda p: None)
    ctx, paint = _shop(ws, lang)
    doc, _ = issues.save(ctx.conn, ctx.ws, issues.IssueInput(
        date(2026, 11, 14), "Công ty A", phone="0900 000 001",
        lines=[issues.IssueLineInput(paint, qty_main=10, qty_office=2, unit_price=500000, note="sáng")]))
    form = IssueForm(ctx, edit_doc=doc)
    assert "A1" in form.windowTitle()
    assert form.customer.currentText() == "Công ty A" and form.phone.text() == "0900 000 001"
    row = form.rows[0]
    assert (row.qty_main.value(), row.qty_office.value(), row.price.value(), row.note.text()) == (10, 2, 500000, "sáng")
    assert form.table.cellWidget(0, 3).text() == "50"  # what is in Kho tổng counts the 10 this note took
    type_in(row.qty_main, "20")
    type_in(row.price, "400000")
    form.save_btn.click()
    assert form.saved_doc is not None
    assert [tuple(r) for r in ctx.conn.execute("SELECT code, status FROM documents WHERE kind = 'delivery'")] == \
        [("A1", "active")]
    assert _lines(ctx.conn) == [(22, 400000, 8800000)]
    levels = stock_levels(ctx.conn, by_location=True)
    assert (levels[(paint, MAIN)], levels[(paint, OFFICE)]) == (30, 6)
    ctx.close()


def test_a_draft_is_saved_opened_again_and_made_a_real_note(app, ws, monkeypatch):
    """Đơn nháp (customer, 21/11/2026): «Lưu nháp» writes the file only; «Xuất từ phiếu nháp…» opens it in a fresh form
    (title and hint name the draft); «Lưu phiếu» there makes the real note once and moves the draft to da-chot/."""
    import dibekho.ui.issue_form as form_mod
    import dibekho.ui.pending_page as pending_mod
    from dibekho.ui.issue_form import IssueForm, open_issue_form

    i18n.set_language("vi")
    monkeypatch.setattr(form_mod, "ask", lambda *a, **k: True)
    monkeypatch.setattr(form_mod, "open_path", lambda *a: None)
    ctx, paint = _shop(ws, "vi")
    monkeypatch.setattr(pending_mod.ProductPicker, "choose", lambda self: paint)

    form = IssueForm(ctx)
    form.customer.setCurrentText("Công ty A")
    form.rows[0].button.click()
    type_in(form.rows[0].qty_main, "4")
    type_in(form.rows[0].price, "6182.98")
    form.draft_btn.click()
    draft = issues.drafts_folder(ws) / "PhieuXuat_NHAP_N1.xlsx"
    assert draft.exists() and form.result() == form.DialogCode.Accepted
    assert ctx.conn.execute("SELECT COUNT(*) FROM documents WHERE kind = 'delivery'").fetchone()[0] == 0
    assert stock_levels(ctx.conn, by_location=True)[(paint, MAIN)] == 50

    opened = []

    def run(self):  # the first form picks the draft, the second one saves it as a real note
        if self.draft is None:
            monkeypatch.setattr(form_mod.QFileDialog, "getOpenFileName", lambda *a, **k: (str(draft), ""))
            self.pick_draft()
        else:
            opened.append((self.windowTitle(), self.rows[0].qty_main.value(), self.rows[0].price.value()))
            self.save_btn.click()
        return 0

    monkeypatch.setattr(form_mod.IssueForm, "exec", run)
    doc = open_issue_form(ctx, None)
    assert opened == [(i18n.t("issue.draft_title", code="N1"), 4, 6182.98)]
    assert ctx.conn.execute("SELECT code FROM documents WHERE id = ?", (doc,)).fetchone()[0] == "A1"
    assert stock_levels(ctx.conn, by_location=True)[(paint, MAIN)] == 46
    assert not draft.exists() and (issues.drafts_folder(ws) / "da-chot" / draft.name).exists()
    ctx.close()


def close_form(form):
    """The list of names is a window of its own: left open, it outlives the test."""
    form._customer_completer.popup().hide()
    form.close()


def test_typing_a_few_letters_offers_the_customers_that_fit(app, ws, monkeypatch):
    """User's request 24/11/2026: letters typed in the customer box bring up the customers that fit, accents
    and all; picking one fills its details, exactly as picking from the list does."""
    i18n.set_language("vi")
    from dibekho.ui.issue_form import IssueForm

    ctx, _paint = _shop(ws, "vi")
    with db.transaction(ctx.conn):
        catalog.upsert_customer(ctx.conn, "Khách Mẫu", "0900 000 002", "Chị C", "2 Đường Y")
    form = IssueForm(ctx)

    form.customer.lineEdit().setText("khach")
    form._customer_typed("khach")
    assert form._suggestions.stringList() == ["Khách Mẫu · 0900 000 002"]

    form.customer.lineEdit().setText("cong")
    form._customer_typed("cong")
    assert form._suggestions.stringList() == ["Công ty A · 0900 000 001"]

    form._suggestion_picked("Khách Mẫu · 0900 000 002")
    assert (form.customer.currentText(), form.phone.text(), form.contact.text(), form.address.text()) == (
        "Khách Mẫu · 0900 000 002", "0900 000 002", "Chị C", "2 Đường Y")
    close_form(form)
    ctx.close()


def test_the_box_offers_everyone_before_anything_is_typed(app, ws):
    i18n.set_language("vi")
    from dibekho.ui.issue_form import IssueForm

    ctx, _paint = _shop(ws, "vi")
    form = IssueForm(ctx)
    form._customer_typed("")
    assert form._suggestions.stringList() == ["Công ty A · 0900 000 001"]
    close_form(form)
    ctx.close()


def test_typing_an_old_name_in_full_fills_the_details_without_picking_from_the_list(app, ws):
    """Before the suggestions the box's own completion did this; the details must still fill (keystrokes, not calls)."""
    i18n.set_language("vi")
    from dibekho.ui.issue_form import IssueForm

    ctx, _paint = _shop(ws, "vi")
    form = IssueForm(ctx)
    type_customer(form, "Công ty A")
    assert (form.phone.text(), form.contact.text(), form.address.text()) == ("0900 000 001", "Anh B", "1 Đường X")

    form.customer.lineEdit().clear()
    form.phone.clear()
    type_customer(form, "cong ty a")  # the same name typed without accents is not that customer
    assert form.phone.text() == ""

    form.customer.lineEdit().clear()
    type_customer(form, "Công ty A · 0900 000 001")  # the whole label works too
    assert form.phone.text() == "0900 000 001"
    close_form(form)
    ctx.close()


def test_the_list_of_names_opens_while_typing(app, ws):
    i18n.set_language("vi")
    from dibekho.ui.issue_form import IssueForm

    ctx, _paint = _shop(ws, "vi")
    with db.transaction(ctx.conn):
        catalog.upsert_customer(ctx.conn, "Khách Mẫu", "0900 000 002", "Chị C", "2 Đường Y")
    form = IssueForm(ctx)
    form.show()
    type_customer(form, "khach")
    assert form._suggestions.stringList() == ["Khách Mẫu · 0900 000 002"]
    assert form._customer_completer.popup().isVisible()
    form._suggestion_picked(form._suggestions.stringList()[0])
    assert (form.customer.currentText(), form.phone.text()) == ("Khách Mẫu · 0900 000 002", "0900 000 002")
    close_form(form)
    ctx.close()


def test_typing_on_past_an_old_name_clears_what_that_customer_filled(app, ws):
    """Swift learned this on 21/11: 'Công ty A' -> 'Công ty AB' is a new customer, so the old phone must not ride
    along (phones are how customers are recognised). A value the user changed by hand stays."""
    i18n.set_language("vi")
    from dibekho.ui.issue_form import IssueForm

    ctx, _paint = _shop(ws, "vi")
    form = IssueForm(ctx)
    type_customer(form, "Công ty A")
    assert form.phone.text() == "0900 000 001"
    type_customer(form, "B", more=True)
    assert (form.phone.text(), form.contact.text(), form.address.text()) == ("", "", "")

    form.customer.lineEdit().clear()
    type_customer(form, "Công ty A")
    form.phone.setText("0999 999 999")  # the user's own value
    type_customer(form, "B", more=True)
    assert (form.phone.text(), form.address.text()) == ("0999 999 999", "")
    close_form(form)
    ctx.close()
