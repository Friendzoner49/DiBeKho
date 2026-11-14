"""'Phiếu xuất kho…': goods out to a customer, typed in the app instead of written in Excel.

The customer (picked from the list, or typed), the date, and the lines: each product says how many are taken from
Kho tổng and how many from Văn phòng (both may be filled), with the price (the customer's last one is filled in).
'Lưu phiếu' writes the Excel file (output/phieu-xuat/) and lowers the stock at once (core/issues.py).
"""

from datetime import date

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
)

from dibekho.core import activity, catalog, issues, undo
from dibekho.core.issues import IssueInput, IssueLineInput
from dibekho.core.stock import MAIN, OFFICE, stock_levels
from dibekho.core.text import fmt_money, fmt_qty
from dibekho.i18n import t
from dibekho.ui.common import (
    RED,
    NoWheelCombo,
    NoWheelDate,
    NoWheelSpin,
    ask,
    error,
    fit_window,
    from_qdate,
    hint_label,
    location_name,
    open_path,
    theme_color,
    title_label,
    to_qdate,
)

PRODUCT, SPEC, UNIT, HAVE_MAIN, QTY_MAIN, HAVE_OFFICE, QTY_OFFICE, PRICE, AMOUNT, NOTE, REMOVE = range(11)
START_ROWS = 3


def _spin(maximum: float, width: int) -> NoWheelSpin:
    box = NoWheelSpin()
    box.setRange(0, maximum)
    box.setDecimals(2)
    box.setSpecialValueText(" ")  # 0 shows empty: nothing typed yet
    box.setMinimumWidth(width)
    return box


class _Row:
    def __init__(self):
        self.product_id: int | None = None
        self.button = QPushButton()
        self.qty_main = _spin(1e7, 100)
        self.qty_office = _spin(1e7, 100)
        self.price = _spin(1e12, 120)
        self.price_typed = False  # typed by the user: the app no longer fills it in
        self.note = QLineEdit()
        self.remove = QPushButton("✕")
        self.remove.setToolTip(t("receipt_form.remove_row"))

    def qty(self) -> float:
        return self.qty_main.value() + self.qty_office.value()


class IssueForm(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.saved_doc: int | None = None
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setWindowTitle(t("issue.title"))
        fit_window(self, 1250, 760)
        self.products = {p["id"]: p for p in catalog.products(ctx.conn)}
        self.levels = stock_levels(ctx.conn, by_location=True)
        self.customers = issues.customer_choices(ctx.conn)
        self.rows: list[_Row] = []

        lay = QVBoxLayout(self)
        lay.addWidget(title_label(self.windowTitle()))
        lay.addWidget(hint_label(t("issue.hint")))
        form = QFormLayout()
        self.date = NoWheelDate()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd/MM/yyyy")
        self.date.setDate(to_qdate(date.today()))
        form.addRow(t("issue.date") + ":", self.date)
        self.customer = NoWheelCombo()
        self.customer.setEditable(True)
        self.customer.addItem("", None)
        for i, c in enumerate(self.customers):
            self.customer.addItem(" · ".join(x for x in (c["name"], c["phone"]) if x), i)
        self.customer.lineEdit().setPlaceholderText(t("issue.customer_placeholder"))
        self.customer.setMinimumWidth(520)
        self.customer.currentIndexChanged.connect(lambda _: self._customer_picked())
        form.addRow(t("issue.customer") + ":", self.customer)
        self.phone, self.contact, self.address = QLineEdit(), QLineEdit(), QLineEdit()
        form.addRow(t("issue.phone") + ":", self.phone)
        form.addRow(t("issue.contact") + ":", self.contact)
        form.addRow(t("issue.address") + ":", self.address)
        lay.addLayout(form)

        lay.addWidget(QLabel(t("issue.step_lines")))
        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels([
            t("col.product"), t("col.spec"), t("col.unit"), t("issue.have", place=t("loc.main")),
            t("issue.take", place=t("loc.main")), t("issue.have", place=t("loc.office")),
            t("issue.take", place=t("loc.office")), t("issue.price"), t("issue.amount"), t("col.note"), ""])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(PRODUCT, QHeaderView.Stretch)
        for col, width in ((SPEC, 100), (UNIT, 60), (HAVE_MAIN, 80), (QTY_MAIN, 100), (HAVE_OFFICE, 80),
                           (QTY_OFFICE, 100), (PRICE, 120), (AMOUNT, 110), (NOTE, 130), (REMOVE, 44)):
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
        self.save_btn = QPushButton(t("issue.save"))
        for b in (cancel, self.save_btn):  # Enter never saves (see keyPressEvent)
            b.setAutoDefault(False)
            b.setDefault(False)
        f = self.save_btn.font()
        f.setBold(True)
        self.save_btn.setFont(f)
        self.save_btn.clicked.connect(self.save)
        buttons.addWidget(cancel)
        buttons.addWidget(self.save_btn)
        lay.addLayout(buttons)
        for _ in range(START_ROWS):
            self.add_row()
        self._update_summary()

    # ---- state -----------------------------------------------------------------------------------------------

    def data(self) -> IssueInput:
        return IssueInput(
            from_qdate(self.date.date()), self.customer.currentText().split(" · ")[0].strip(),
            phone=self.phone.text(), contact=self.contact.text(), address=self.address.text(),
            lines=[IssueLineInput(r.product_id, r.qty_main.value(), r.qty_office.value(),
                                  r.price.value() or None, r.note.text()) for r in self.rows])

    def _customer_picked(self):
        i = self.customer.currentData()
        if i is None or self.customer.itemText(self.customer.currentIndex()) != self.customer.currentText():
            return
        c = self.customers[i]
        self.phone.setText(c["phone"] or "")
        self.contact.setText(c["contact"] or "")
        self.address.setText(c["address"] or "")
        for row in self.rows:
            self._fill_price(row)

    # ---- rows ------------------------------------------------------------------------------------------------

    def add_row(self) -> _Row:
        row = _Row()
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setCellWidget(r, PRODUCT, row.button)
        self.table.setCellWidget(r, QTY_MAIN, row.qty_main)
        self.table.setCellWidget(r, QTY_OFFICE, row.qty_office)
        self.table.setCellWidget(r, PRICE, row.price)
        self.table.setCellWidget(r, NOTE, row.note)
        self.table.setCellWidget(r, REMOVE, row.remove)
        for col in (SPEC, UNIT, HAVE_MAIN, HAVE_OFFICE, AMOUNT):
            self.table.setCellWidget(r, col, QLabel())
        row.button.clicked.connect(lambda: self._choose(row))
        row.remove.clicked.connect(lambda: self._remove(row))
        row.price.lineEdit().textEdited.connect(lambda _: setattr(row, "price_typed", True))
        for box in (row.qty_main, row.qty_office, row.price):
            box.valueChanged.connect(lambda _: self._show_row(row))
            box.installEventFilter(self)
            box.lineEdit().installEventFilter(self)
        self.rows.append(row)
        self._show_row(row)
        return row

    def _remove(self, row: _Row):
        if row.qty() > 0 and not ask(self, t("receipt_form.confirm_remove", product=self._label(row))):
            return
        i = self.rows.index(row)
        self.rows.pop(i)
        self.table.removeRow(i)
        self._update_summary()

    def _label(self, row: _Row) -> str:
        p = self.products.get(row.product_id) if row.product_id else None
        return catalog.long_label(p) if p else ""

    def _show_row(self, row: _Row):
        i = self.rows.index(row)
        text = self._label(row)
        row.button.setText(text or t("receipt_form.pick"))
        row.button.setToolTip(text)
        row.button.setStyleSheet("text-align: left; padding-left: 6px;" +
                                 (f"color: {theme_color('hint')};" if not text else ""))
        p = self.products.get(row.product_id) if row.product_id else None
        self.table.cellWidget(i, SPEC).setText(p["spec"] if p else "")
        self.table.cellWidget(i, UNIT).setText(p["unit"] if p else "")
        for col, loc, box in ((HAVE_MAIN, MAIN, row.qty_main), (HAVE_OFFICE, OFFICE, row.qty_office)):
            have = self.levels.get((row.product_id, loc), 0.0) if p else None
            label = self.table.cellWidget(i, col)
            label.setText("" if have is None else fmt_qty(have))
            label.setStyleSheet(f"color: {RED.name()};" if have is not None and box.value() > have else "")
        amount = row.qty() * row.price.value() if row.price.value() else None
        self.table.cellWidget(i, AMOUNT).setText(fmt_money(amount) if amount else "")
        self._update_summary()

    def _fill_price(self, row: _Row):
        if row.price_typed or not row.product_id:
            return
        price = issues.last_price(self.ctx.conn, self.data().customer_name, row.product_id)
        row.price.blockSignals(True)
        row.price.setValue(price or 0)
        row.price.blockSignals(False)
        self._show_row(row)

    def _choose(self, row: _Row):
        from dibekho.ui.pending_page import ProductPicker

        product_id = ProductPicker(self.ctx, self).choose()
        if not product_id:
            return
        if product_id not in self.products:  # a product no longer in use: still allowed, shown like the others
            p = self.ctx.conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if p is None:
                return
            self.products[product_id] = p
        other = next((r for r in self.rows if r is not row and r.product_id == product_id), None)
        if other is not None:
            error(self, t("issue.already_on_row", product=self._label(other), row=self.rows.index(other) + 1))
            other.qty_main.setFocus()
            return
        if product_id != row.product_id:
            row.price_typed = False
        row.product_id = product_id
        self._fill_price(row)
        self._show_row(row)
        if row is self.rows[-1]:
            self.add_row()
        row.qty_main.setFocus()
        row.qty_main.selectAll()

    def _update_summary(self):
        data = self.data()
        lines = data.filled()
        money = sum(ln.qty * ln.unit_price for ln in lines if ln.unit_price)
        self.summary.setText(t("issue.summary", lines=len(lines), qty=fmt_qty(sum(ln.qty for ln in lines)),
                               money=fmt_money(money)))

    # ---- save ------------------------------------------------------------------------------------------------

    def _confirm_text(self, data: IssueInput) -> str:
        lines = []
        for ln in data.filled():
            p = self.products[ln.product_id]
            parts = [f"{location_name(loc)} {fmt_qty(q)}" for loc, q in ((MAIN, ln.qty_main), (OFFICE, ln.qty_office))
                     if q]
            money = f" × {fmt_money(ln.unit_price)}" if ln.unit_price else ""
            lines.append(f"• {catalog.long_label(p)}: {' + '.join(parts)} {p['unit']}".rstrip() + money)
        total = sum(ln.qty * ln.unit_price for ln in data.filled() if ln.unit_price)
        return t("issue.confirm", date=data.doc_date.strftime("%d/%m/%Y"), customer=data.customer_name,
                 lines="\n".join(lines), money=fmt_money(total))

    def save(self):
        data = self.data()
        found = issues.problems(self.ctx.conn, data)
        if found:
            texts = []
            for key, values in found:
                if "id" in values:
                    values = {"product": catalog.long_label(self.products[values["id"]])}
                texts.append("• " + t(key, **values))
            error(self, t("issue.cannot_save") + "\n\n" + "\n".join(dict.fromkeys(texts)))
            return
        short = issues.short_of(self.ctx.conn, data)
        if short:
            text = "\n".join(t("issue.short_line", product=catalog.long_label(self.products[pid]),
                               place=location_name(loc), asked=fmt_qty(asked), have=fmt_qty(have))
                             for pid, loc, asked, have in short)
            if not ask(self, t("issue.short", lines=text)):
                return
        if data.doc_date > date.today() and not ask(self, t("receipt_form.future_date")):
            return
        if not ask(self, self._confirm_text(data), t("issue.confirm_title")):
            return
        activity.log("issue", f"{len(data.filled())} mặt hàng")
        self.ctx.undo_point("issue_note")
        try:
            doc, path = issues.save(self.ctx.conn, self.ctx.ws, data)
        except Exception as exc:
            error(self, t("issue.failed", error=str(exc)))
            return
        self.saved_doc = doc
        undo.remember_doc(self.ctx.conn, "issue_note", doc)
        self.ctx.notify()
        code = self.ctx.conn.execute("SELECT code FROM documents WHERE id = ?", (doc,)).fetchone()[0]
        if ask(self, t("issue.saved", code=code, path=str(path))):
            open_path(path)
        self.accept()

    def eventFilter(self, obj, event):
        """Enter in a number box takes the number and goes on; it never reaches the buttons."""
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            box = obj if isinstance(obj, NoWheelSpin) else obj.parent()
            if isinstance(box, NoWheelSpin):
                box.interpretText()
                box.focusNextChild()
            return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def reject(self):
        if self.saved_doc is None and any(r.qty() > 0 for r in self.rows) and not ask(self, t("issue.confirm_close")):
            return
        super().reject()


def open_issue_form(ctx, parent) -> int | None:
    form = IssueForm(ctx, parent)
    form.exec()
    return form.saved_doc
