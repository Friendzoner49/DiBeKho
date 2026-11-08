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
