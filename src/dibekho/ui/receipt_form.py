"""'Nhập hàng về…': one window to record goods in, instead of filling an Excel template.

Where the goods come from (border gate / parent company, or a customer sending goods back), the date, and the
lines: 3 products are suggested (changed or cleared freely), '＋ Thêm dòng' adds more, a product that is not in
the catalog yet can be entered on its row. Nothing is written until 'Lưu'; then the receipt is recorded, an
undo point is kept, and the receipt is written to an Excel file in output/hang-ve/.

The same window edits a saved receipt (the old one is marked replaced).
"""

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QVBoxLayout,
)

from dibekho.core import activity, catalog, receipts
from dibekho.core.receipts import RETURN, SUPPLIER, NewProduct, ReceiptInput, ReceiptLineInput
from dibekho.core.text import fmt_qty
from dibekho.i18n import t
from dibekho.ui.common import (
    NoWheelCombo,
    NoWheelDate,
    NoWheelSpin,
    ask,
    error,
    fit_window,
    from_qdate,
    hint_label,
    info,
    location_combo,
    location_name,
    open_path,
    theme_color,
    title_label,
    to_qdate,
)
from dibekho.ui.settings_page import ProductEditor

PRODUCT, SPEC, UNIT, QTY, NOTE, REMOVE = range(6)


class NewProductDialog(ProductEditor):
    """The product editor of the settings, without saving: the product is created with the receipt."""

    def __init__(self, ctx, draft: NewProduct | None = None, parent=None):
        super().__init__(ctx, None, parent)
        self.setWindowTitle(t("receipt_form.new_product_title"))
        form = self.layout()
        form.setRowVisible(self.active, False)
        if draft:
            self.name_vi.setText(draft.name_vi)
            self.name_zh.setText(draft.name_zh)
            self.spec.setText(draft.spec)
            self.variant.setText(draft.variant)
            self.unit.setText(draft.unit)
            self.category.setCurrentText(draft.category)
        self.result_product: NewProduct | None = None

    def save(self):
        if not self.name_vi.text().strip():
            self.name_vi.setFocus()
            return
        self.result_product = NewProduct(**self.fields())
        self.accept()


class _Row:
    def __init__(self):
        self.product_id: int | None = None
        self.new: NewProduct | None = None
        self.suggested = False  # put there by the app; replaced when the supplier/customer changes
        self.button = QPushButton()
        self.qty = NoWheelSpin()
        self.qty.setRange(0, 1e7)
        self.qty.setDecimals(2)
        self.qty.setSpecialValueText(" ")  # 0 shows empty: nothing typed yet
        self.qty.setMinimumWidth(110)
        self.note = QLineEdit()
        self.remove = QPushButton("✕")
        self.remove.setToolTip(t("receipt_form.remove_row"))

    def touched(self) -> bool:
        return self.qty.value() > 0 or bool(self.note.text().strip()) or not self.suggested


class ReceiptForm(QDialog):
    def __init__(self, ctx, parent=None, doc_id: int | None = None):
        super().__init__(parent)
        self.ctx, self.doc_id = ctx, doc_id
        self.saved_doc: int | None = None
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setWindowTitle(t("receipt_form.title_edit") if doc_id else t("receipt_form.title"))
        fit_window(self, 1150, 760)
        self.products = {p["id"]: p for p in catalog.products(ctx.conn, include_inactive=True)}
        self.rows: list[_Row] = []
        self._loading = True

        lay = QVBoxLayout(self)
        lay.addWidget(title_label(self.windowTitle()))

        # 1. where from
        lay.addWidget(QLabel(t("receipt_form.step_source")))
        src_row = QHBoxLayout()
        self.src_supplier = QRadioButton(t("receipt_form.source_supplier"))
        self.src_return = QRadioButton(t("receipt_form.source_return"))
        self.sources = QButtonGroup(self)
        for b in (self.src_supplier, self.src_return):
            f = b.font()
            f.setPointSize(f.pointSize() + 2)
            f.setBold(True)
            b.setFont(f)
            self.sources.addButton(b)
            src_row.addWidget(b)
        src_row.addStretch()
        lay.addLayout(src_row)

        form = QFormLayout()
        self.date = NoWheelDate()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd/MM/yyyy")
        self.date.setDate(to_qdate(date.today()))
        form.addRow(t("receipt_form.date") + ":", self.date)
        self.location = location_combo()
        form.addRow(t("loc.put_in") + ":", self.location)

        self.supplier = NoWheelCombo()
        self.supplier.setEditable(True)
        self.supplier.addItems(receipts.supplier_names(ctx.conn))
        self.supplier.lineEdit().setPlaceholderText(t("receipt_form.supplier_placeholder"))
        self.supplier.setMinimumWidth(520)
        self.supplier_label = QLabel(t("receipt_form.supplier") + ":")
        form.addRow(self.supplier_label, self.supplier)

        self.customer = NoWheelCombo()
        self.customer.setEditable(True)
        self.customer.addItem("", None)
        for c in ctx.conn.execute("SELECT id, name, phone FROM customers ORDER BY name"):
            self.customer.addItem(" · ".join(x for x in (c["name"], c["phone"]) if x), c["id"])
        self.customer.lineEdit().setPlaceholderText(t("receipt_form.customer_placeholder"))
        self.customer.setMinimumWidth(520)
        self.customer_label = QLabel(t("receipt_form.customer") + ":")
        form.addRow(self.customer_label, self.customer)

        self.order = NoWheelCombo()
        self.order.setEditable(True)
        self.order.lineEdit().setPlaceholderText(t("receipt_form.order_placeholder"))
        self.order_label = QLabel(t("receipt_form.order") + ":")
        form.addRow(self.order_label, self.order)

        self.note = QLineEdit()
        form.addRow(t("col.note") + ":", self.note)
        lay.addLayout(form)

        # 2. lines
        lay.addWidget(QLabel(t("receipt_form.step_lines")))
        lay.addWidget(hint_label(t("receipt_form.lines_hint")))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([t("col.product"), t("col.spec"), t("col.unit"), t("col.qty"),
                                              t("col.note"), ""])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(PRODUCT, QHeaderView.Stretch)
        for col, width in ((SPEC, 120), (UNIT, 80), (QTY, 130), (NOTE, 200), (REMOVE, 50)):
            header.setSectionResizeMode(col, QHeaderView.Interactive)
            self.table.setColumnWidth(col, width)
        self.table.verticalHeader().setDefaultSectionSize(40)
        lay.addWidget(self.table)
        add = QPushButton(t("receipt_form.add_row"))
        add.clicked.connect(lambda: self.add_row())
        add_row = QHBoxLayout()
        add_row.addWidget(add)
        add_row.addStretch()
        self.summary = QLabel()
        add_row.addWidget(self.summary)
        lay.addLayout(add_row)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton(t("btn.cancel"))
        cancel.clicked.connect(self.reject)
        self.save_btn = QPushButton(t("receipt_form.save"))
        self.save_btn.setDefault(True)
        f = self.save_btn.font()
        f.setBold(True)
        self.save_btn.setFont(f)
        self.save_btn.clicked.connect(self.save)
        buttons.addWidget(cancel)
        buttons.addWidget(self.save_btn)
        lay.addLayout(buttons)

        if doc_id:
            self._load(receipts.load(ctx.conn, doc_id))
        else:
            self.src_supplier.setChecked(True)
            names = receipts.supplier_names(ctx.conn)
            self.supplier.setCurrentText(names[0] if names else "")
            for _ in range(receipts.SUGGESTED):
                self.add_row(suggested=True)
        self._loading = False
        self.sources.buttonToggled.connect(lambda *_: self._context_changed())
        self.supplier.currentTextChanged.connect(lambda _: self._context_changed())
        self.customer.currentIndexChanged.connect(lambda _: self._customer_changed())
        self.order.currentTextChanged.connect(lambda _: self._context_changed())
        self._show_source()
        if not doc_id:
            self._suggest()
        self._update_summary()

    # ---- state -----------------------------------------------------------------------------------------------

    def source(self) -> str:
        return RETURN if self.src_return.isChecked() else SUPPLIER

    def customer_id(self) -> int | None:
        i = self.customer.currentIndex()
        if i > 0 and self.customer.itemText(i) == self.customer.currentText():
            return self.customer.itemData(i)
        return None

    def data(self) -> ReceiptInput:
        return ReceiptInput(
            from_qdate(self.date.date()), self.source(),
            supplier_name=self.supplier.currentText().strip(),
            customer_name=self.customer.currentText().split(" · ")[0].strip(), customer_id=self.customer_id(),
            ref_code=self.order.currentText().strip(), note=self.note.text().strip(),
            lines=[ReceiptLineInput(r.qty.value(), r.product_id, r.new, r.note.text()) for r in self.rows],
            location_id=self.location.currentData())

    def dirty(self) -> bool:
        return any(r.qty.value() > 0 for r in self.rows) or self.doc_id is not None

    def _load(self, data: ReceiptInput):
        (self.src_return if data.source == RETURN else self.src_supplier).setChecked(True)
        self.date.setDate(to_qdate(data.doc_date))
        self.location.setCurrentIndex(max(self.location.findData(data.location_id), 0))
        self.supplier.setCurrentText(data.supplier_name)
        if data.customer_id:
            i = self.customer.findData(data.customer_id)
            if i >= 0:
                self.customer.setCurrentIndex(i)
        self._fill_orders()
        self.order.setCurrentText(data.ref_code)
        self.note.setText(data.note)
        for ln in data.lines:
            row = self.add_row()
            self._set_product(row, ln.product_id)
            row.qty.setValue(ln.qty)
            row.note.setText(ln.note)

    # ---- rows ------------------------------------------------------------------------------------------------

    def add_row(self, suggested=False) -> _Row:
        row = _Row()
        row.suggested = suggested
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setCellWidget(r, PRODUCT, row.button)
        self.table.setCellWidget(r, QTY, row.qty)
        self.table.setCellWidget(r, NOTE, row.note)
        self.table.setCellWidget(r, REMOVE, row.remove)
        for col in (SPEC, UNIT):
            self.table.setCellWidget(r, col, QLabel())
        row.button.clicked.connect(lambda: self._choose(row))
        row.remove.clicked.connect(lambda: self._remove(row))
        row.qty.valueChanged.connect(lambda _: self._update_summary())
        self.rows.append(row)
        self._show_row(row)
        if not self._loading and not suggested:
            self.table.scrollToBottom()
        return row

    def _remove(self, row: _Row):
        if row.qty.value() > 0 and not ask(self, t("receipt_form.confirm_remove", product=self._label(row))):
            return
        i = self.rows.index(row)
        self.rows.pop(i)
        self.table.removeRow(i)
        self._update_summary()

    def _label(self, row: _Row) -> str:
        if row.new:
            return "★ " + row.new.label()
        if row.product_id and row.product_id in self.products:
            return catalog.label(self.products[row.product_id])
        return ""

    def _show_row(self, row: _Row):
        i = self.rows.index(row)
        text = self._label(row)
        row.button.setText(text or t("receipt_form.pick"))
        row.button.setToolTip(text)
        row.button.setStyleSheet("text-align: left; padding-left: 6px;" +
                                 (f"color: {theme_color('hint')};" if not text else ""))
        p = self.products.get(row.product_id) if row.product_id else None
        spec = row.new.spec if row.new else (p["spec"] if p else "")
        unit = row.new.unit if row.new else (p["unit"] if p else "")
        self.table.cellWidget(i, SPEC).setText(spec)
        self.table.cellWidget(i, UNIT).setText(unit)

    def _set_product(self, row: _Row, product_id: int | None, new: NewProduct | None = None):
        row.product_id, row.new = product_id, new
        self._show_row(row)
        self._update_summary()

    def _choose(self, row: _Row):
        menu = QMenu(self)
        pick = menu.addAction(t("receipt_form.pick_existing"))
        new = menu.addAction(t("receipt_form.pick_new"))
        edit_new = menu.addAction(t("receipt_form.edit_new")) if row.new else None
        clear = menu.addAction(t("receipt_form.clear_row")) if (row.product_id or row.new) else None
        chosen = menu.exec(row.button.mapToGlobal(row.button.rect().bottomLeft()))
        if chosen is None:
            return
        if chosen is pick:
            from dibekho.ui.pending_page import ProductPicker

            product_id = ProductPicker(self.ctx, self).choose()
            if product_id:
                row.suggested = False
                self._set_product(row, product_id)
        elif chosen in (new, edit_new):
            dlg = NewProductDialog(self.ctx, row.new, self)
            if dlg.exec() == QDialog.Accepted and dlg.result_product:
                row.suggested = False
                self._set_product(row, None, dlg.result_product)
        elif chosen is clear:
            row.suggested = False
            self._set_product(row, None)

    def _update_summary(self):
        lines = self.data().filled()
        total = sum(ln.qty for ln in lines)
        self.summary.setText(t("receipt_form.summary", lines=len(lines), qty=fmt_qty(total)))

    # ---- supplier / customer ---------------------------------------------------------------------------------

    def _show_source(self):
        ret = self.source() == RETURN
        for w in (self.supplier, self.supplier_label):
            w.setVisible(not ret)
        for w in (self.customer, self.customer_label, self.order, self.order_label):
            w.setVisible(ret)

    def _fill_orders(self):
        text = self.order.currentText()
        self.order.blockSignals(True)
        self.order.clear()
        self.order.addItem("")
        cid = self.customer_id()
        if cid:
            self.order.addItems(receipts.customer_orders(self.ctx.conn, cid))
        self.order.setCurrentText(text if self.order.findText(text) >= 0 else "")
        self.order.blockSignals(False)

    def _customer_changed(self):
        self._fill_orders()
        self._context_changed()

    def _context_changed(self):
        if self._loading:
            return
        self._show_source()
        if not self.doc_id:
            self._suggest()

    def _suggest(self):
        """Put suggested products on the rows the user has not touched."""
        free = [r for r in self.rows if not r.touched()]
        ids = receipts.suggestions(self.ctx.conn, self.source(), self.supplier.currentText(), self.customer_id(),
                                   self.order.currentText().strip())
        used = {r.product_id for r in self.rows if r.touched()}
        ids = [p for p in ids if p not in used and p in self.products]
        for row in free:
            row.suggested = True
            self._set_product(row, ids.pop(0) if ids else None)

    # ---- save / close ----------------------------------------------------------------------------------------

    def save(self):
        data = self.data()
        found = receipts.problems(data)
        if found:
            texts = []
            for key, values in found:
                if "id" in values:
                    values = {"product": catalog.label(self.products[values["id"]])}
                texts.append("• " + t(key, **values))
            error(self, t("receipt_form.cannot_save") + "\n\n" + "\n".join(dict.fromkeys(texts)))
            return
        for ln, existing in receipts.same_as_existing(self.ctx.conn, data):
            if ask(self, t("receipt_form.already_in_catalog", new=ln.new.label(), code=existing["code"],
                           product=catalog.label(existing))):
                row = next(r for r in self.rows if r.new is ln.new)
                self._set_product(row, existing["id"])
                self.products.setdefault(existing["id"], existing)
        data = self.data()
        if data.doc_date > date.today() and not ask(self, t("receipt_form.future_date")):
            return
        if not ask(self, self._confirm_text(data), t("receipt_form.confirm_title")):
            return
        activity.log("receipt", self._confirm_text(data).split("\n\n" + t("receipt_form.confirm_new"))[0])
        self.ctx.undo_point("receipt_edit" if self.doc_id else "receipt")
        try:
            doc = receipts.save(self.ctx.conn, data, replaces=self.doc_id, ws=self.ctx.ws)
        except Exception as exc:
            error(self, str(exc))
            return
        self.saved_doc = doc
        self.ctx.notify()
        code = self.ctx.conn.execute("SELECT code FROM documents WHERE id = ?", (doc,)).fetchone()[0]
        try:
            path = receipts.export_file(self.ctx.conn, self.ctx.ws, doc)
        except Exception as exc:  # e.g. a file of the same name open in Excel: the receipt is recorded anyway
            info(self, t("receipt_form.saved_no_file", code=code, error=str(exc)))
            self.accept()
            return
        if ask(self, t("receipt_form.saved", code=code, path=str(path))):
            open_path(path)
        self.accept()

    def _confirm_text(self, data: ReceiptInput) -> str:
        if data.source == SUPPLIER:
            who = t("receipt_form.source_supplier") + ": " + data.supplier_name
        else:
            who = t("receipt_form.source_return") + ": " + data.customer_name
            if data.ref_code:
                who += " · " + t("receipt_form.order") + " " + data.ref_code
        who += "\n" + t("loc.put_in") + ": " + location_name(data.location_id)
        lines = []
        for ln in data.filled():
            name = ("★ " + ln.new.label()) if ln.new else catalog.label(self.products[ln.product_id])
            unit = ln.new.unit if ln.new else self.products[ln.product_id]["unit"]
            lines.append(f"• {name}: {fmt_qty(ln.qty)} {unit}".rstrip())
        skipped = sum(1 for r in self.rows if (r.product_id or r.new) and r.qty.value() <= 0)
        text = t("receipt_form.confirm", date=data.doc_date.strftime("%d/%m/%Y"), who=who,
                 lines="\n".join(lines), total=fmt_qty(sum(ln.qty for ln in data.filled())))
        if any(ln.new for ln in data.filled()):
            text += "\n\n" + t("receipt_form.confirm_new")
        if skipped:
            text += "\n\n" + t("receipt_form.confirm_skipped", count=skipped)
        if self.doc_id:
            text += "\n\n" + t("receipt_form.confirm_edit")
        return text

    def reject(self):
        if self.saved_doc is None and self.dirty() and not ask(self, t("receipt_form.confirm_close")):
            return
        super().reject()


def open_receipt_form(ctx, parent, doc_id: int | None = None) -> int | None:
    """Returns the id of the saved receipt, or None if the user closed the window."""
    form = ReceiptForm(ctx, parent, doc_id)
    form.exec()
    return form.saved_doc

