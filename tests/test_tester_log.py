"""Fixes from a tester's activity log (data package of 2026-11-07, app 0.4.1 on a Mac).

What the log showed: Enter after typing a quantity opened "save?" over and over (63 answers "No" in 11
minutes), the same product put on two rows of a receipt, a half-typed receipt thrown away to go and fix a
product, the product picker not finding a product among many sharing one long name, a supplier typed as "kho
tổng", and Ctrl+click (a right click on a Mac) used to select several customers. Fake names only.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dibekho import db, i18n  # noqa: E402
from dibekho.core import catalog  # noqa: E402
from dibekho.core.workspace import Config  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _ctx(ws):
    from dibekho.ui.common import AppContext

    i18n.set_language("vi")
    return AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)


def _same_name_products(conn):
    """Products sharing one long name, told apart only by model, packing and colour (like the real catalog)."""
    long_name = "Sơn chống thấm gốc nhựa biến tính dạng lỏng dùng trong công nghệ chống thấm, mới 100%"
    with db.transaction(conn):
        return [catalog.create_product(conn, f"{long_name} (MẪU FS-10{m})", f"漆{m}", spec, variant=v)
                for m, spec, v in (("1", "20KG", "Trắng"), ("1", "10KG", "Xám nhạt"), ("2", "20KG", "Trắng"))]


def test_search_matches_words_in_any_order_without_punctuation():
    from dibekho.core.text import matches_words

    hay = "SP003 Sơn mẫu dạng lỏng (MẪU FS-101), mới 100% 10KG Xám nhạt 漆1"
    for needle in ("fs101", "FS-101", "fs-101 xam", "xám 10kg fs101", "mau fs 101", "漆1", ""):
        assert matches_words(needle, hay), needle
    for needle in ("fs102", "fs101 trang", "20kg"):
        assert not matches_words(needle, hay), needle


def test_enter_in_a_quantity_never_saves_the_receipt(app, ws, monkeypatch):
    import dibekho.ui.receipt_form as rf

    asked = []
    monkeypatch.setattr(rf, "ask", lambda *a, **k: asked.append(a[1]) or False)
    monkeypatch.setattr(rf, "error", lambda *a, **k: asked.append(a[1]))
    ctx = _ctx(ws)
    a, b, _ = _same_name_products(ctx.conn)
    form = rf.ReceiptForm(ctx)
    form.supplier.setCurrentText("Nhà cung cấp A")
    form._set_product(form.rows[0], a)
    form._set_product(form.rows[1], b)
    form.show()
    form.rows[0].qty.setFocus()
    QTest.keyClicks(form.rows[0].qty, "5")
    QTest.keyClick(form.rows[0].qty, Qt.Key_Return)
    app.processEvents()
    assert form.focusWidget() in (form.rows[1].qty, form.rows[1].qty.lineEdit())  # on to the next quantity
    form.rows[0].qty.setFocus()  # the key may reach the box itself or the line edit inside it, on any platform
    QTest.keyClick(form.rows[0].qty.lineEdit(), Qt.Key_Enter)
    app.processEvents()
    assert form.focusWidget() in (form.rows[1].qty, form.rows[1].qty.lineEdit())
    QTest.keyClick(form.rows[1].qty, Qt.Key_Return)  # and Enter again, from there
    app.processEvents()
    assert asked == [] and form.saved_doc is None  # no "save?", nothing saved
    assert form.rows[0].qty.value() == 5
    form.saved_doc = 0  # close without keeping a draft
    form.close()


@pytest.mark.parametrize("kind", ["transfer", "trial"])
def test_enter_in_transfer_and_trial_never_saves(app, ws, monkeypatch, kind):
    import dibekho.ui.count_page as cp

    asked = []
    monkeypatch.setattr(cp, "ask", lambda *a, **k: asked.append(a) or False)
    monkeypatch.setattr(cp, "error", lambda *a, **k: asked.append(a))
    ctx = _ctx(ws)
    _same_name_products(ctx.conn)
    dlg, col = (cp.TransferDialog(ctx), cp.TRANS_QTY) if kind == "transfer" else (cp.TrialUseDialog(ctx), cp.TRIAL_QTY)
    dlg.show()
    dlg.table.setFocus()
    dlg.table.setCurrentCell(0, col)
    app.processEvents()
    QTest.keyClicks(dlg.table.viewport(), "5")
    for _ in range(2):
        QTest.keyClick(dlg.focusWidget() or dlg.table, Qt.Key_Return)
        app.processEvents()
    app.processEvents()
    assert asked == [] and dlg.isVisible()
    assert list(dlg._typed().values()) == [5]
    dlg.close()


def test_product_picker_finds_by_any_words_and_shows_packing_and_colour(app, ws):
    from dibekho.ui.pending_page import ProductPicker

    ctx = _ctx(ws)
    a, b, c = _same_name_products(ctx.conn)
    picker = ProductPicker(ctx)
    picker.show()
    headers = [picker.table.horizontalHeaderItem(i).text() for i in range(picker.table.columnCount())]
    assert headers[2:4] == [i18n.t("col.spec"), i18n.t("col.variant")]
    QTest.keyClicks(picker.search, "fs101 xam")  # no dash, words out of order, no accents
    visible = picker._visible()
    assert len(visible) == 1 and picker.table.item(visible[0], 0).data(Qt.UserRole) == b
    picker._enter()  # Enter with one match left takes it
    assert picker.result() == picker.DialogCode.Accepted
    assert picker.table.item(picker.table.currentRow(), 0).data(Qt.UserRole) == b


def test_receipt_same_product_on_two_rows_is_stopped_when_picked(app, ws, monkeypatch):
    import dibekho.ui.receipt_form as rf

    told = []
    monkeypatch.setattr(rf, "info", lambda *a, **k: told.append(a[1]))
    ctx = _ctx(ws)
    a, b, _ = _same_name_products(ctx.conn)
    form = rf.ReceiptForm(ctx)
    first, second = form.rows[0], form.rows[1]
    form._set_product(first, a)
    first.qty.setValue(5)

    form._picked(second, a)
    assert told and "dòng 1" in told[0] and second.product_id != a  # stopped; the row is left as it was
    first.qty.setValue(0)  # an empty row with that product (e.g. one the app suggested) simply gives way
    rows_before = len(form.rows)
    form._picked(second, a)
    assert second.product_id == a and len(form.rows) == rows_before - 1
    form.saved_doc = 0
    form.close()


def test_closed_receipt_is_kept_and_offered_again(app, ws, monkeypatch):
    import dibekho.ui.receipt_form as rf

    told = []
    monkeypatch.setattr(rf, "info", lambda *a, **k: told.append(a[1]))
    monkeypatch.setattr(rf, "ask", lambda *a, **k: True)
    monkeypatch.setattr(rf.ReceiptForm, "exec", lambda self: 0)
    ctx = _ctx(ws)
    a, b, c = _same_name_products(ctx.conn)
    form = rf.ReceiptForm(ctx)
    form.supplier.setCurrentText("Nhà cung cấp A")
    for row, pid, qty in zip(form.rows, (a, b, c), (5, 3, 2)):
        form._set_product(row, pid)
        row.qty.setValue(qty)
    form.reject()  # closed to go and fix a product in Settings
    assert ctx.receipt_draft is not None and "giữ lại" in told[-1]
    with db.transaction(ctx.conn):
        catalog.delete_product(ctx.conn, c)  # deleted meanwhile
    captured = {}
    real_init = rf.ReceiptForm.__init__

    def spy(self, *args, **kw):
        real_init(self, *args, **kw)
        captured["form"] = self

    monkeypatch.setattr(rf.ReceiptForm, "__init__", spy)
    rf.open_receipt_form(ctx, None)
    resumed = captured["form"]
    assert [(r.product_id, r.qty.value()) for r in resumed.rows] == [(a, 5), (b, 3)]
    assert resumed.supplier.currentText() == "Nhà cung cấp A"
    assert any("1 dòng" in m for m in told)  # the deleted product's row dropped, and the user told
    assert ctx.receipt_draft is None


def test_editing_a_saved_receipt_still_asks_before_discarding(app, ws, monkeypatch):
    import dibekho.ui.receipt_form as rf
    from dibekho.core import receipts
    from dibekho.core.receipts import SUPPLIER, ReceiptInput, ReceiptLineInput
    from datetime import date

    ctx = _ctx(ws)
    a, *_ = _same_name_products(ctx.conn)
    doc = receipts.save(ctx.conn, ReceiptInput(date(2026, 10, 1), SUPPLIER, supplier_name="Nhà cung cấp A",
                                               lines=[ReceiptLineInput(5, a)]))
    asked = []
    monkeypatch.setattr(rf, "ask", lambda *args, **kw: asked.append(args[1]) or False)
    form = rf.ReceiptForm(ctx, doc_id=doc)
    form.reject()
    assert asked and ctx.receipt_draft is None  # an edit is never kept as a draft
    form.saved_doc = 0
    form.close()


def test_supplier_typed_as_a_place_is_questioned(app, ws, monkeypatch):
    import dibekho.ui.receipt_form as rf
    from dibekho.core.receipts import looks_like_place

    assert looks_like_place("Kho tổng") and looks_like_place("kho") and looks_like_place("Văn phòng")
    assert not looks_like_place("Cửa khẩu Mẫu") and not looks_like_place("Công ty mẹ")
    asked = []
    monkeypatch.setattr(rf, "ask", lambda *a, **k: asked.append(a[1]) or False)
    ctx = _ctx(ws)
    a, *_ = _same_name_products(ctx.conn)
    form = rf.ReceiptForm(ctx)
    form.supplier.setCurrentText("kho tổng")
    form._set_product(form.rows[0], a)
    form.rows[0].qty.setValue(5)
    form.save()
    assert asked and "Kiểm kê" in asked[0] and form.saved_doc is None
    form.saved_doc = 0
    form.close()


def test_multi_select_hint_names_the_mac_key():
    for lang in ("vi", "en", "zh"):
        i18n.set_language(lang)
        assert "⌘" in i18n.t("cust.merge_select_first") and "⌘" in i18n.t("cust.merge_tip")
    i18n.set_language("vi")


def test_global_search_finds_products_by_any_words(conn):
    from dibekho.core.queries import search

    a, b, c = _same_name_products(conn)
    assert [p["id"] for p in search(conn, "fs101 xam")["products"]] == [b]
    assert {p["id"] for p in search(conn, "FS-101")["products"]} == {a, b}


def test_settings_merge_duplicate_products(app, ws, monkeypatch):
    """Settings -> Merge duplicate products: pick one row, pick the other; the larger code goes into the smaller."""
    from dibekho.ui import pending_page as pp
    from dibekho.ui import settings_page as sp

    ctx = _ctx(ws)
    with db.transaction(ctx.conn):
        a = catalog.create_product(ctx.conn, "Keo mẫu", "胶", "5KG")
        b = catalog.create_product(ctx.conn, "Keo mẫu", "胶", "5KG")
    page = sp.SettingsPage(ctx)
    page.refresh()
    shown = []
    monkeypatch.setattr(sp, "error", lambda *x, **k: shown.append(x[1]))
    page.merge_selected()  # nothing selected
    assert shown and ctx.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 2
    page.table.selectRow([page.table.item(r, 0).data(Qt.UserRole) for r in range(2)].index(b))
    monkeypatch.setattr(pp.ProductPicker, "choose", lambda self: b)  # the same one again
    page.merge_selected()
    assert len(shown) == 2 and ctx.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 2
    monkeypatch.setattr(pp.ProductPicker, "choose", lambda self: a)
    monkeypatch.setattr(sp, "ask", lambda *x, **k: True)
    monkeypatch.setattr(sp, "info", lambda *x, **k: None)
    page.merge_selected()
    rows = ctx.conn.execute("SELECT id FROM products").fetchall()
    assert [r[0] for r in rows] == [a]  # SP002 merged into SP001


def test_a_return_fills_in_the_price_the_customer_paid_and_keeps_a_typed_one(app, ws):
    import dibekho.ui.receipt_form as rf
    from datetime import date

    from dibekho.core.stock import Line, insert_document

    ctx = _ctx(ws)
    a, b, _ = _same_name_products(ctx.conn)
    with db.transaction(ctx.conn):
        cust = catalog.upsert_customer(ctx.conn, "Khách Mẫu", "0900 000 010")
        insert_document(ctx.conn, "delivery", date(2026, 10, 1), [Line(a, 5, unit_price=100, amount=500)], code="50",
                        code_norm="50", customer_id=cust)
        insert_document(ctx.conn, "delivery", date(2026, 10, 9), [Line(a, 5, unit_price=120, amount=600)], code="51",
                        code_norm="51", customer_id=cust)
    form = rf.ReceiptForm(ctx)
    assert form.table.isColumnHidden(rf.PRICE)  # goods from a supplier: no price column
    form.src_return.setChecked(True)
    form.customer.setCurrentIndex(form.customer.findData(cust))
    assert not form.table.isColumnHidden(rf.PRICE)
    row = next(r for r in form.rows if r.product_id == a)  # suggested from what the customer bought
    assert row.price.value() == 120                        # the latest purchase
    form.order.setCurrentText("50")
    row = next(r for r in form.rows if r.product_id == a)
    assert row.price.value() == 100                        # the order the goods came back from
    row.qty.setValue(2)
    row.price.setValue(80)
    row.price_typed = True                                 # what typing in the box does
    form.order.setCurrentText("51")
    assert row.price.value() == 80                         # a typed price stays
    line = next(ln for ln in form.data().filled() if ln.product_id == a)
    assert (line.qty, line.unit_price) == (2, 80)
    assert "× 80 = 160" in form._confirm_text(form.data())
    form._set_product(row, b)                              # another product: its own price (never bought: empty)
    assert row.price.value() == 0 and form.data().lines[form.rows.index(row)].unit_price is None
    form.saved_doc = 0
    form.close()


def test_another_supplier_is_typed_with_three_recent_ones_and_replaced_receipts_are_not_listed(app, ws):
    import dibekho.ui.receipt_form as rf
    from datetime import date

    from dibekho.core import receipts
    from dibekho.core.receipts import OTHER, SUPPLIER, ReceiptInput, ReceiptLineInput
    from dibekho.ui.receipt_page import ReceiptPage

    ctx = _ctx(ws)
    a, b, _ = _same_name_products(ctx.conn)
    for day, name in ((1, "Đại lý Một"), (2, "Đại lý Hai"), (3, "Đại lý Ba"), (4, "Đại lý Bốn"), (5, "Đại lý Một")):
        receipts.save(ctx.conn, ReceiptInput(date(2026, 11, day), OTHER, supplier_name=name,
                                             lines=[ReceiptLineInput(1, a)]))
    receipts.save(ctx.conn, ReceiptInput(date(2026, 11, 6), SUPPLIER, supplier_name="Cửa khẩu Lạng Sơn",
                                         lines=[ReceiptLineInput(1, b)]))
    assert receipts.supplier_names(ctx.conn, OTHER, receipts.RECENT) == ["Đại lý Một", "Đại lý Bốn", "Đại lý Ba"]
    assert receipts.supplier_names(ctx.conn, SUPPLIER) == ["Cửa khẩu Lạng Sơn"]
    assert receipts.problems(ReceiptInput(date(2026, 11, 7), OTHER, lines=[ReceiptLineInput(1, a)])) == [
        ("receipt_form.need_supplier_other", {})]

    form = rf.ReceiptForm(ctx)
    assert form.supplier.currentText() == "Cửa khẩu Lạng Sơn" and form.recent_box.isHidden()
    form.src_other.setChecked(True)
    assert not form.recent_box.isHidden() and form.supplier.currentText() == ""  # typed or clicked, never guessed
    assert [btn.text() for btn in form.recent_buttons] == ["Đại lý Một", "Đại lý Bốn", "Đại lý Ba"]
    form.recent_buttons[1].click()
    form._set_product(form.rows[0], a)
    form.rows[0].qty.setValue(3)
    data = form.data()
    assert (data.source, data.supplier_name) == (OTHER, "Đại lý Bốn")
    assert "Nhà cung cấp khác: Đại lý Bốn" in form._confirm_text(data)
    doc = receipts.save(ctx.conn, data)
    row = ctx.conn.execute("SELECT d.receipt_source, s.name FROM documents d JOIN suppliers s ON s.id = d.supplier_id "
                           "WHERE d.id = ?", (doc,)).fetchone()
    assert tuple(row) == (OTHER, "Đại lý Bốn")
    form.saved_doc = 0
    form.close()
    edited = receipts.load(ctx.conn, doc)
    assert edited.source == OTHER  # editing keeps the source
    form = rf.ReceiptForm(ctx, doc_id=doc)
    assert form.src_other.isChecked() and form.supplier.currentText() == "Đại lý Bốn"
    form.saved_doc = 0
    form.close()
    edited.lines[0].qty = 4
    new_doc = receipts.save(ctx.conn, edited, replaces=doc)  # the old version becomes 'replaced'

    page = ReceiptPage(ctx, lambda: None)
    page.refresh()
    listed = [page.table.item(r, 0).text() for r in range(page.table.rowCount())]
    code = ctx.conn.execute("SELECT code FROM documents WHERE id = ?", (new_doc,)).fetchone()[0]
    assert listed.count(code) == 1 and len(listed) == 7  # 6 receipts + the edit; the replaced one is gone
    assert "Nhà cung cấp khác" in [page.table.item(r, 2).text() for r in range(page.table.rowCount())]
