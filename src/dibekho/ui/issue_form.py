"""'Phiếu xuất kho…': goods out to a customer, typed in the app instead of written in Excel.

The customer (picked from the list, or typed), the date, and the lines: each product says how many are taken from
Kho tổng and how many from Văn phòng (both may be filled), with the price (the customer's last one is filled in).
The same product may stand on several lines: another quantity, another price (user, 15/11/2026).
'Lưu phiếu' writes the Excel file (output/phieu-xuat/) and lowers the stock at once (core/issues.py).

While the ₫ | ¥ switch shows yuan, the prices are typed in yuan (user, 15/11/2026) at the rate the window opened
with; the note and the data keep dong: a typed price is turned into whole dong, a suggested price left untouched
keeps its exact dong.

A row may be '★ Mặt hàng mới' (customer, 15/11/2026): a product not in the catalog yet, made on save (core/issues.py),
its stock goes below zero until the goods come in (Hàng về).
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
    QMenu,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
)

from dibekho import i18n
from dibekho.core import activity, catalog, fx, issues
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
        self.new = None  # receipts.NewProduct: not in the catalog yet, made on save
        self.button = QPushButton()
        self.qty_main = _spin(1e7, 100)
        self.qty_office = _spin(1e7, 100)
        self.price = _spin(1e12, 120)
        self.price_typed = False  # typed by the user: the app no longer fills it in
        self.price_vnd: float | None = None  # the price the app filled in, exact in dong (the box may show yuan)
        self.keep_price = False  # a note being edited: the price on it stays until the product changes
        self.note = QLineEdit()
        self.remove = QPushButton("✕")
        self.remove.setToolTip(t("receipt_form.remove_row"))

    def qty(self) -> float:
        return self.qty_main.value() + self.qty_office.value()


class IssueForm(QDialog):
    def __init__(self, ctx, parent=None, edit_doc: int | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.saved_doc: int | None = None
        self.edit_doc = edit_doc  # a recorded note being corrected (same code), else a new one
        self.edit_code, self.old = "", None
        if edit_doc:
            self.edit_code, self.old = issues.load(ctx.conn, edit_doc)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setWindowTitle(t("issue.edit_title", code=self.edit_code) if edit_doc else t("issue.title"))
        fit_window(self, 1250, 760)
        self.products = {p["id"]: p for p in catalog.products(ctx.conn)}
        self.levels = stock_levels(ctx.conn, by_location=True)
        if self.old:  # the note being edited has already taken its goods: they are free again for the new version
            for ln in self.old.filled():
                for loc, qty in ((MAIN, ln.qty_main), (OFFICE, ln.qty_office)):
                    self.levels[(ln.product_id, loc)] = self.levels.get((ln.product_id, loc), 0.0) + qty
                self.products.setdefault(ln.product_id, ctx.conn.execute(
                    "SELECT * FROM products WHERE id = ?", (ln.product_id,)).fetchone())
        self.customers = issues.customer_choices(ctx.conn)
        self.rows: list[_Row] = []
        self.rate = fx.Display.rate if fx.Display.in_cny() else None  # prices typed in yuan at this rate

        lay = QVBoxLayout(self)
        lay.addWidget(title_label(self.windowTitle()))
        lay.addWidget(hint_label(t("issue.edit_hint", code=self.edit_code) if edit_doc else t("issue.hint")))
        if self.rate is not None:
            lay.addWidget(hint_label(t("issue.cny_hint", rate=fmt_money(round(self.rate.vnd_per_cny)))))
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
        customer_row = QHBoxLayout()
        customer_row.addWidget(self.customer, 1)
        self.new_customer_btn = QPushButton(t("issue.new_customer"))
        self.new_customer_btn.setToolTip(t("issue.new_customer_tip"))
        self.new_customer_btn.setAutoDefault(False)
        self.new_customer_btn.clicked.connect(self.new_customer)
        customer_row.addWidget(self.new_customer_btn)
        form.addRow(t("issue.customer") + ":", customer_row)
        self.phone, self.contact, self.address = QLineEdit(), QLineEdit(), QLineEdit()
        self.tax_code, self.email = QLineEdit(), QLineEdit()
        form.addRow(t("issue.phone") + ":", self.phone)
        form.addRow(t("issue.contact") + ":", self.contact)
        form.addRow(t("issue.address") + ":", self.address)
        form.addRow(t("col.tax_code") + ":", self.tax_code)
        form.addRow(t("col.email") + ":", self.email)
        lay.addLayout(form)

        lay.addWidget(QLabel(t("issue.step_lines")))
        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels([
            t("col.product"), t("col.spec"), t("col.unit"), t("issue.have", place=t("loc.main")),
            t("issue.take", place=t("loc.main")), t("issue.have", place=t("loc.office")),
            t("issue.take", place=t("loc.office")), t("issue.price_cny" if self.rate else "issue.price"),
            t("issue.amount_cny" if self.rate else "issue.amount"), t("col.note"), ""])
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
        if self.old:
            self._fill_from(self.old)
        else:
            for _ in range(START_ROWS):
                self.add_row()
        self._update_summary()

    def _fill_from(self, old: IssueInput):
        """Show the note being edited: its date, customer and lines (prices as recorded, not looked up again)."""
        self.date.setDate(to_qdate(old.doc_date))
        self.customer.setCurrentIndex(0)
        self.customer.setEditText(old.customer_name)
        for box, value in ((self.phone, old.phone), (self.contact, old.contact), (self.address, old.address),
                           (self.tax_code, old.tax_code), (self.email, old.email)):
            box.setText(value)
        for ln in old.lines:
            row = self.add_row()
            row.product_id, row.keep_price, row.price_vnd = ln.product_id, True, ln.unit_price
            row.qty_main.setValue(ln.qty_main)
            row.qty_office.setValue(ln.qty_office)
            row.note.setText(ln.note)
            row.price.blockSignals(True)
            row.price.setValue(((round(self.rate.to_cny(ln.unit_price), 2) if self.rate else ln.unit_price)
                                if ln.unit_price else 0))
            row.price.blockSignals(False)
            self._show_row(row)
        self.add_row()

    # ---- state -----------------------------------------------------------------------------------------------

    def data(self) -> IssueInput:
        return IssueInput(
            from_qdate(self.date.date()), self.customer.currentText().split(" · ")[0].strip(),
            phone=self.phone.text(), contact=self.contact.text(), address=self.address.text(),
            tax_code=self.tax_code.text(), email=self.email.text(),
            lines=[IssueLineInput(r.product_id, r.qty_main.value(), r.qty_office.value(),
                                  self._price_vnd(r), r.note.text(), new=r.new) for r in self.rows])

    def _price_vnd(self, row: _Row) -> float | None:
        """The row's price in dong, as it is saved."""
        shown = row.price.value()
        if not shown:
            return None
        if self.rate is None:
            return shown
        if not row.price_typed and row.price_vnd:
            return row.price_vnd
        return float(round(self.rate.to_vnd(shown)))

    def _money(self, vnd: float) -> str:
        """An amount as this window shows it: dong, or yuan at the window's rate."""
        if self.rate is None:
            return fmt_money(vnd)
        return fx.cny_text(self.rate.to_cny(vnd), i18n.language())

    def _customer_picked(self):
        i = self.customer.currentData()
        if i is None or self.customer.itemText(self.customer.currentIndex()) != self.customer.currentText():
            return
        c = self.customers[i]
        self._show_customer(c)
        for row in self.rows:
            self._fill_price(row)

    def _show_customer(self, c):
        for box, key in ((self.phone, "phone"), (self.contact, "contact"), (self.address, "address"),
                         (self.tax_code, "tax_code"), (self.email, "email")):
            box.setText(c[key] or "")

    def new_customer(self):
        """'＋ Khách hàng mới…': every field of a customer not in the list yet; saved with the note (the note is read
        back like any delivery note, which adds the customer). One already in the list is picked instead."""
        from dibekho.ui.customer_form import CustomerInfoDialog

        values: dict = {}
        while True:
            dlg = CustomerInfoDialog(self, t("cust.new_title"), values, t("issue.new_customer_hint"))
            if dlg.exec() != QDialog.Accepted:
                return
            values = dlg.values()
            twin = (catalog.customer_owning_phone(self.ctx.conn, values["phone"])
                    or catalog.customer_named(self.ctx.conn, values["name"]))
            if twin is None:
                break
            if ask(self, t("issue.customer_exists", name=twin["name"])):
                i = next(n for n, c in enumerate(self.customers) if c["id"] == twin["id"])
                self.customer.setCurrentIndex(self.customer.findData(i))
                return
        self.customer.setCurrentIndex(0)
        self.customer.setEditText(values["name"])
        self._show_customer(values)
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
        if row.new:
            return "★ " + row.new.label()
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
        self.table.cellWidget(i, SPEC).setText(row.new.spec if row.new else (p["spec"] if p else ""))
        self.table.cellWidget(i, UNIT).setText(row.new.unit if row.new else (p["unit"] if p else ""))
        price = self._price_vnd(row)
        amount = row.qty() * price if price else None
        self.table.cellWidget(i, AMOUNT).setText(self._money(amount) if amount else "")
        self._show_stock()
        self._update_summary()

    def _show_stock(self):
        """'Đang có' of every row; red when the rows of that product together take more than the place has."""
        asked: dict[tuple, float] = {}
        for r in self.rows:
            if r.product_id:
                for loc, box in ((MAIN, r.qty_main), (OFFICE, r.qty_office)):
                    asked[(r.product_id, loc)] = asked.get((r.product_id, loc), 0.0) + box.value()
        for i, r in enumerate(self.rows):
            for col, loc in ((HAVE_MAIN, MAIN), (HAVE_OFFICE, OFFICE)):
                label = self.table.cellWidget(i, col)
                if label is None:
                    continue
                have = self.levels.get((r.product_id, loc), 0.0) if r.product_id in self.products else None
                if r.new:
                    have = 0.0  # a new product has nothing yet
                label.setText("" if have is None else fmt_qty(have))
                taken = (r.qty_main if loc == MAIN else r.qty_office).value() if r.new else \
                    asked.get((r.product_id, loc), 0.0)
                over = have is not None and taken > have
                label.setStyleSheet(f"color: {RED.name()};" if over else "")

    def _fill_price(self, row: _Row):
        if row.price_typed or row.keep_price or not row.product_id:
            return
        price = issues.last_price(self.ctx.conn, self.data().customer_name, row.product_id)
        row.price_vnd = price or None
        row.price.blockSignals(True)
        row.price.setValue((round(self.rate.to_cny(price), 2) if self.rate else price) if price else 0)
        row.price.blockSignals(False)
        self._show_row(row)

    def _choose(self, row: _Row):
        """Pick a product of the catalog, or describe a new one (as in Hàng về)."""
        menu = QMenu(self)
        pick = menu.addAction(t("receipt_form.pick_existing"))
        new = menu.addAction(t("receipt_form.pick_new"))
        edit_new = menu.addAction(t("receipt_form.edit_new")) if row.new else None
        clear = menu.addAction(t("receipt_form.clear_row")) if (row.product_id or row.new) else None
        chosen = self._open_menu(menu, row)
        if chosen is None:
            return
        if chosen is pick:
            self._pick_existing(row)
        elif chosen in (new, edit_new):
            from dibekho.ui.receipt_form import NewProductDialog

            dlg = NewProductDialog(self.ctx, row.new, self)
            if dlg.exec() == QDialog.Accepted and dlg.result_product:
                self._set_new(row, dlg.result_product)
        elif chosen is clear:
            row.product_id, row.new, row.price_typed, row.keep_price = None, None, False, False
            row.price.setValue(0)
            self._show_row(row)

    def _open_menu(self, menu: QMenu, row: _Row):
        """The menu under the row's button; a method of its own so tests can answer it (patching QMenu.exec does
        not reach PySide once the method was looked up)."""
        return menu.exec(row.button.mapToGlobal(row.button.rect().bottomLeft()))

    def _set_new(self, row: _Row, new):
        row.product_id, row.new = None, new
        row.price_typed = row.keep_price = False
        row.price.setValue(0)
        self._show_row(row)
        self._after_pick(row)

    def _after_pick(self, row: _Row):
        if row is self.rows[-1]:
            self.add_row()
        row.qty_main.setFocus()
        row.qty_main.selectAll()

    def _pick_existing(self, row: _Row):
        from dibekho.ui.pending_page import ProductPicker

        product_id = ProductPicker(self.ctx, self).choose()
        if not product_id:
            return
        if product_id not in self.products:  # a product no longer in use: still allowed, shown like the others
            p = self.ctx.conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if p is None:
                return
            self.products[product_id] = p
        self._set_existing(row, product_id)
        self._after_pick(row)

    def _set_existing(self, row: _Row, product_id: int):
        if product_id != row.product_id or row.new:
            row.price_typed = row.keep_price = False
        row.product_id, row.new = product_id, None
        self._fill_price(row)
        self._show_row(row)

    def _update_summary(self):
        data = self.data()
        lines = data.filled()
        money = sum(ln.qty * ln.unit_price for ln in lines if ln.unit_price)
        self.summary.setText(t("issue.summary", lines=len(lines), qty=fmt_qty(sum(ln.qty for ln in lines)),
                               money=self._money(money)))

    # ---- save ------------------------------------------------------------------------------------------------

    def _confirm_text(self, data: IssueInput) -> str:
        lines = []
        for ln in data.filled():
            if ln.new:
                name, unit = "★ " + ln.new.label(), ln.new.unit
            else:
                p = self.products[ln.product_id]
                name, unit = catalog.long_label(p), p["unit"]
            parts = [f"{location_name(loc)} {fmt_qty(q)}" for loc, q in ((MAIN, ln.qty_main), (OFFICE, ln.qty_office))
                     if q]
            money = f" × {self._both(ln.unit_price)}" if ln.unit_price else ""
            lines.append(f"• {name}: {' + '.join(parts)} {unit}".rstrip() + money)
        total = sum(ln.qty * ln.unit_price for ln in data.filled() if ln.unit_price)
        text = t("issue.confirm_edit" if self.edit_doc else "issue.confirm", code=self.edit_code,
                 date=data.doc_date.strftime("%d/%m/%Y"), customer=data.customer_name,
                 lines="\n".join(lines), money=self._both(total))
        if any(ln.new for ln in data.filled()):
            text += "\n\n" + t("issue.confirm_new")
        return text

    def _both(self, vnd: float) -> str:
        """Before saving the user sees what is written: yuan as typed and the dong the note will carry."""
        return fmt_money(vnd) if self.rate is None else f"{self._money(vnd)} = {fmt_money(vnd)} ₫"

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
        for ln, existing in issues.same_as_existing(self.ctx.conn, data):
            if ask(self, t("receipt_form.already_in_catalog", new=ln.new.label(), code=existing["code"],
                           product=catalog.long_label(existing))):
                self.products.setdefault(existing["id"], existing)
                for row in [r for r in self.rows if r.new is not None and issues.new_key(r.new) == issues.new_key(ln.new)]:
                    self._set_existing(row, existing["id"])
        data = self.data()
        short = issues.short_of(self.ctx.conn, data, self.old)
        if short:
            text = "\n".join(t("issue.short_line", product=catalog.long_label(self.products[pid]),
                               place=location_name(loc), asked=fmt_qty(asked), have=fmt_qty(have))
                             for pid, loc, asked, have in short)
            if not ask(self, t("issue.short", lines=text)):
                return
        if data.doc_date > date.today() and not ask(self, t("receipt_form.future_date")):
            return
        title = t("issue.confirm_edit_title" if self.edit_doc else "issue.confirm_title")
        if not ask(self, self._confirm_text(data), title):
            return
        activity.log("issue_edit" if self.edit_doc else "issue", f"{len(data.filled())} mặt hàng")
        self.ctx.log_action("issue_edit" if self.edit_doc else "issue_note")
        try:
            if self.edit_doc:
                doc, path = issues.edit(self.ctx.conn, self.ctx.ws, self.edit_doc, data)
            else:
                doc, path = issues.save(self.ctx.conn, self.ctx.ws, data)
        except Exception as exc:
            error(self, t("issue.failed", error=str(exc)))
            return
        self.saved_doc = doc
        self.ctx.notify()
        code = self.ctx.conn.execute("SELECT code FROM documents WHERE id = ?", (doc,)).fetchone()[0]
        if ask(self, t("issue.saved_edit" if self.edit_doc else "issue.saved", code=code, path=str(path))):
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


def open_issue_form(ctx, parent, edit_doc: int | None = None) -> int | None:
    form = IssueForm(ctx, parent, edit_doc)
    form.exec()
    return form.saved_doc
