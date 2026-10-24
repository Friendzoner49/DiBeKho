"""Detail windows: order (document), customer, product. They link to each other."""

from datetime import date, datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from dibekho import db
from dibekho.core import activity, deliveries, queries, receipts
from dibekho.excel import report
from dibekho.core.stock import MAIN, close_document, set_location
from dibekho.core.text import fmt_money, fmt_qty
from dibekho.i18n import t
from dibekho.ui.common import (
    RED,
    AppContext,
    ask,
    date_item,
    error,
    fill_table,
    fit_window,
    fmt_date,
    from_qdate,
    hint_label,
    info,
    kind_text,
    location_combo,
    location_name,
    make_table,
    money_item,
    num_item,
    open_path,
    row_id,
    status_text,
    theme_color,
    title_label,
    to_qdate,
)


def _link(text: str, on_click) -> QLabel:
    label = QLabel(f'<a href="#">{text}</a>')
    label.setTextInteractionFlags(Qt.TextBrowserInteraction)
    label.linkActivated.connect(lambda _: on_click())
    return label


def _selectable(text: str) -> QLabel:
    label = QLabel(text or "—")
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    label.setWordWrap(True)
    return label


class _Base(QDialog):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        fit_window(self, 1100, 700)
        self.layout_ = QVBoxLayout(self)

    def add_close(self) -> None:
        box = QDialogButtonBox()
        box.addButton(t("btn.close"), QDialogButtonBox.RejectRole)
        box.rejected.connect(self.reject)
        self.layout_.addWidget(box)


# ---- order / document ------------------------------------------------------

class DocumentDialog(_Base):
    def __init__(self, ctx: AppContext, doc_id: int, parent=None):
        super().__init__(ctx, parent)
        self.doc_id = doc_id
        head, lines = queries.document(ctx.conn, doc_id)
        self.head = head
        kind = head["kind"]
        self.setWindowTitle(f"{kind_text(kind)} {head['code']}".strip())

        if kind == "delivery":
            title = t("doc.title_delivery", code=head["code"])
        elif kind == "receipt" and head["code"]:
            title = t("doc.title_receipt", code=head["code"])
        else:
            title = kind_text(kind)
        self.layout_.addWidget(title_label(title))

        form = QFormLayout()
        form.addRow(t("col.date") + ":", QLabel(fmt_date(head["doc_date"])))
        status = QLabel(status_text(head["status"]))
        if head["status"] != "active":
            status.setStyleSheet(f"color: {theme_color('alert')}; font-weight: bold;")
        form.addRow(t("col.status") + ":", status)
        if kind == "delivery":
            if head["customer_id"]:
                form.addRow(t("col.customer") + ":", _link(head["customer_name"], self.open_customer))
            form.addRow(t("col.contact") + ":", _selectable(head["contact"]))
            form.addRow(t("col.phone") + ":", _selectable(head["phone"]))
            form.addRow(t("col.address") + ":", _selectable(head["address"]))
        if kind == "delivery":
            self.location = location_combo(head["location_id"])
            self.location.setEnabled(head["status"] == "active")
            self.location.currentIndexChanged.connect(self.change_location)
            place = QHBoxLayout()
            place.addWidget(self.location)
            if not head["location_set"] and head["status"] == "active":
                place.addWidget(hint_label(t("doc.location_unset")))
            else:
                place.addWidget(hint_label(t("doc.location_change_hint")))
            place.addStretch()
            form.addRow(t("loc.taken_from") + ":", place)
        elif kind == "receipt":
            form.addRow(t("loc.put_in") + ":", QLabel(location_name(head["location_id"])))
        elif kind == "transfer":
            form.addRow(t("transfer.from") + ":", QLabel(location_name(head["location_id"])))
            form.addRow(t("transfer.to") + ":", QLabel(location_name(head["to_location_id"])))
        if kind == "receipt" and head["receipt_source"]:
            form.addRow(t("receipt_form.source") + ":",
                        QLabel(t(f"receipt_form.source_short_{head['receipt_source']}")))
            if head["receipt_source"] == "return":
                if head["customer_id"]:
                    form.addRow(t("col.customer") + ":", _link(head["customer_name"], self.open_customer))
                if head["ref_code"]:
                    form.addRow(t("receipt_form.order") + ":", _selectable(head["ref_code"]))
            else:
                form.addRow(t("receipt_form.supplier") + ":", _selectable(head["supplier_name"]))
        if head["note"]:
            form.addRow(t("col.note") + ":", _selectable(head["note"]))
        if head["source_file"]:
            form.addRow(t("col.file") + ":", _selectable(head["source_file"]))
        form.addRow(t("doc.read_at") + ":", QLabel(fmt_date(head["created_at"]) + head["created_at"][10:16]))
        self.layout_.addLayout(form)

        if kind == "stock_count":
            diffs = queries.count_differences(ctx.conn, doc_id)
            headers = [t("col.code"), t("col.product"), t("col.spec"), t("col.variant"), t("col.place"),
                       t("col.counted"), t("col.difference")]
            rows = [[ln["code"], ln["name_vi"], ln["spec"], ln["variant"],
                     location_name(ln["location_id"]) if ln["location_id"] else t("loc.total"),
                     num_item(ln["qty"]), num_item(diffs.get((ln["product_id"], ln["location_id"] or MAIN), 0))]
                    for ln in lines]
        elif kind == "delivery":
            headers = [t("col.code"), t("col.product"), t("col.name_zh"), t("col.spec"), t("col.variant"), t("col.qty"),
                       t("col.unit"), t("col.unit_price"), t("col.amount"), t("col.note")]
            rows = [[ln["code"], ln["name_vi"], ln["name_zh"], ln["spec"], ln["variant"], num_item(ln["qty"]), ln["unit"],
                     money_item(ln["unit_price"]), money_item(ln["amount"]), ln["note"]] for ln in lines]
        else:
            headers = [t("col.code"), t("col.product"), t("col.name_zh"), t("col.spec"), t("col.variant"), t("col.qty"),
                       t("col.unit"),
                       t("col.note")]
            rows = [[ln["code"], ln["name_vi"], ln["name_zh"], ln["spec"], ln["variant"], num_item(ln["qty"]), ln["unit"],
                     ln["note"]] for ln in lines]
        self.table = make_table(headers, stretch=1)
        fill_table(self.table, rows, ids=[ln["product_id"] for ln in lines])
        self.table.doubleClicked.connect(lambda idx: self.open_product(row_id(self.table, idx.row())))
        self.layout_.addWidget(self.table)
        if kind in ("delivery", "receipt", "transfer"):
            total = sum(ln["qty"] for ln in lines)
            self.layout_.addWidget(hint_label(t("doc.total", lines=len(lines), qty=fmt_qty(total))))
        if kind == "delivery" and head["order_total"] is not None:
            self.layout_.addWidget(QLabel(t("doc.money", goods=fmt_money(head["goods_amount"] or 0),
                                            fees=fmt_money(head["fee_amount"] or 0),
                                            total=fmt_money(head["order_total"]))))
            printed = head["note_total"]
            if printed is not None and abs(printed - head["order_total"]) >= 1:
                self.layout_.addWidget(hint_label(t("doc.money_printed", total=fmt_money(printed))))
        if kind == "delivery" and head["unpriced_lines"]:
            self.layout_.addWidget(hint_label(t("doc.unpriced", count=head["unpriced_lines"])))
        self.layout_.addWidget(hint_label(t("doc.hint_open_product")))

        buttons = QHBoxLayout()
        if head["source_hash"] and kind == "delivery":
            b = QPushButton(t("btn.open_original"))
            b.clicked.connect(self.open_original)
            buttons.addWidget(b)
        if head["status"] == "active" and head["source_hash"] and kind == "delivery":
            b = QPushButton(t("btn.reread_doc"))
            b.setToolTip(t("doc.reread_tip"))
            b.clicked.connect(self.reread_doc)
            buttons.addWidget(b)
        if kind == "receipt" and receipts.exported_file(ctx.ws, head["source_file"]):
            b = QPushButton(t("receipt_form.open_file"))
            b.clicked.connect(lambda: open_path(receipts.exported_file(ctx.ws, head["source_file"])))
            buttons.addWidget(b)
        if kind == "receipt" and head["status"] == "active":
            b = QPushButton(t("receipts.edit"))
            b.setToolTip(t("receipts.edit_tip"))
            b.clicked.connect(self.edit_receipt)
            buttons.addWidget(b)
        if head["status"] == "active":
            b = QPushButton(t("btn.cancel_doc"))
            b.clicked.connect(self.cancel_doc)
            buttons.addWidget(b)
        buttons.addStretch()
        self.layout_.addLayout(buttons)
        self.add_close()

    def open_customer(self):
        CustomerDialog(self.ctx, self.head["customer_id"], self).exec()

    def change_location(self):
        self.ctx.undo_point("places")
        with db.transaction(self.ctx.conn):
            set_location(self.ctx.conn, self.doc_id, self.location.currentData())
        self.ctx.notify()

    def open_product(self, product_id):
        if product_id:
            ProductDialog(self.ctx, product_id, self).exec()

    def open_original(self):
        copy = deliveries.viewing_copy(self.ctx.ws, self.head["source_hash"], self.head["source_file"] or "")
        if copy is None:
            error(self, t("doc.original_missing"))
        else:
            open_path(copy)

    def cancel_doc(self):
        if not ask(self, t("doc.confirm_cancel")):
            return
        self.ctx.undo_point("cancel_doc")
        try:
            with db.transaction(self.ctx.conn):
                close_document(self.ctx.conn, self.doc_id, "cancelled")
                if self.head["kind"] == "delivery":
                    # the file stays in the folder; don't warn about it later
                    self.ctx.conn.execute(
                        "UPDATE scanned_files SET status = 'imported' WHERE document_id = ? AND status = 'missing'",
                        (self.doc_id,))
        except ValueError as exc:
            error(self, str(exc))
            return
        self.ctx.notify()
        self.accept()

    def edit_receipt(self):
        from dibekho.ui.receipt_form import open_receipt_form

        if open_receipt_form(self.ctx, self, self.doc_id):
            self.accept()

    def reread_doc(self):
        if not ask(self, t("doc.confirm_reread")):
            return
        self.ctx.undo_point("reread")
        try:
            deliveries.reread_document(self.ctx.conn, self.ctx.ws, self.doc_id)
            result = deliveries.scan(self.ctx.conn, self.ctx.ws)
        except Exception as exc:
            error(self, str(exc))
            return
        self.ctx.notify()
        info(self, t("doc.reread_done") if result.imported else t("doc.reread_pending"))
        self.accept()


# ---- customer --------------------------------------------------------------

class CustomerDialog(_Base):
    def __init__(self, ctx: AppContext, customer_id: int, parent=None):
        super().__init__(ctx, parent)
        self.customer_id = customer_id
        c = queries.customer(ctx.conn, customer_id)
        self.setWindowTitle(c["name"])
        self.layout_.addWidget(title_label(c["name"]))

        form = QFormLayout()
        form.addRow(t("col.contact") + ":", _selectable(c["contact"]))
        form.addRow(t("col.phone") + ":", _selectable(c["phone"]))
        form.addRow(t("col.address") + ":", _selectable(c["address"]))
        form.addRow(t("cust.summary") + ":", QLabel(t("cust.summary_value", count=c["order_count"],
                                                         first=fmt_date(c["first_order"]),
                                                         last=fmt_date(c["last_order"]))))
        self.money = QLabel()
        form.addRow(t("cust.money") + ":", self.money)
        self.unpriced = hint_label("")
        self.layout_.addLayout(form)
        self.layout_.addWidget(self.unpriced)

        bar = QHBoxLayout()
        self.all_time = QCheckBox(t("filter.all_time"))
        self.all_time.setChecked(True)
        self.date_from, self.date_to = QDateEdit(), QDateEdit()
        for w in (self.date_from, self.date_to):
            w.setCalendarPopup(True)
            w.setDisplayFormat("dd/MM/yyyy")
        today = date.today()
        self.date_from.setDate(to_qdate(date(today.year, 1, 1)))
        self.date_to.setDate(to_qdate(today))
        bar.addWidget(self.all_time)
        bar.addWidget(QLabel(t("filter.from")))
        bar.addWidget(self.date_from)
        bar.addWidget(QLabel(t("filter.to")))
        bar.addWidget(self.date_to)
        bar.addStretch()
        export = QPushButton(t("cust.export"))
        export.setToolTip(t("cust.export_tip"))
        export.clicked.connect(self.export)
        bar.addWidget(export)
        self.layout_.addLayout(bar)
        for sig in (self.all_time.toggled, self.date_from.dateChanged, self.date_to.dateChanged):
            sig.connect(self.refresh)

        box1 = QGroupBox(t("cust.products_title"))
        l1 = QVBoxLayout(box1)
        self.products = make_table([t("col.product"), t("col.name_zh"), t("col.spec"), t("col.variant"),
                                    t("col.total_qty"), t("col.unit"), t("col.revenue"), t("col.price_range"),
                                    t("col.times"), t("col.last_date")], stretch=0)
        self.products.doubleClicked.connect(
            lambda idx: ProductDialog(self.ctx, row_id(self.products, idx.row()), self).exec())
        l1.addWidget(self.products)
        box2 = QGroupBox(t("cust.orders_title"))
        l2 = QVBoxLayout(box2)
        self.orders = QTreeWidget()
        self.orders.setHeaderLabels([t("col.order_or_product"), t("col.spec"), t("col.qty"), t("col.unit"),
                                     t("col.unit_price"), t("col.amount"), t("col.note")])
        self.orders.setAlternatingRowColors(True)
        self.orders.itemDoubleClicked.connect(self.open_order)
        l2.addWidget(self.orders)
        self.layout_.addWidget(box1, 2)
        self.layout_.addWidget(box2, 3)
        self.add_close()
        self.refresh()

    def _range(self):
        if self.all_time.isChecked():
            return None, None
        return from_qdate(self.date_from.date()), from_qdate(self.date_to.date())

    def refresh(self):
        self.date_from.setEnabled(not self.all_time.isChecked())
        self.date_to.setEnabled(not self.all_time.isChecked())
        start, end = self._range()
        money = queries.customer_money(self.ctx.conn, self.customer_id, start, end)
        self.money.setText(t("cust.money_value", total=fmt_money(money["total"] or 0), orders=money["orders"],
                             goods=fmt_money(money["goods"] or 0), fees=fmt_money(money["fees"] or 0)))
        self.unpriced.setText(t("cust.unpriced", count=money["unpriced"]) if money["unpriced"] else "")
        self.unpriced.setVisible(bool(money["unpriced"]))
        prods = queries.customer_products(self.ctx.conn, self.customer_id, start, end)
        fill_table(self.products,
                   [[p["name_vi"], p["name_zh"], p["spec"], p["variant"], num_item(p["total_qty"]), p["unit"],
                     money_item(p["revenue"]), _price_range(p["min_price"], p["max_price"]), num_item(p["times"]),
                     date_item(p["last_date"])] for p in prods],
                   ids=[p["id"] for p in prods])
        self._fill_orders(start, end)

    def _fill_orders(self, start, end):
        """Each order (newest first) with its lines and prices underneath, then its other fees."""
        docs = queries.documents(self.ctx.conn, "delivery", start, end, customer_id=self.customer_id)
        lines: dict[int, list] = {}
        for ln in queries.customer_lines(self.ctx.conn, self.customer_id, start, end):
            lines.setdefault(ln["document_id"], []).append(ln)
        right = Qt.AlignRight | Qt.AlignVCenter
        self.orders.clear()
        for d in docs:
            head = QTreeWidgetItem([t("cust.order_head", date=fmt_date(d["doc_date"]), code=d["code"]), "",
                                    t("cust.order_lines", count=d["line_count"]), "", "",
                                    fmt_money(d["order_total"]), ""])
            head.setData(0, Qt.UserRole, d["id"])
            font = head.font(0)
            font.setBold(True)
            for c in (0, 5):
                head.setFont(c, font)
            head.setTextAlignment(5, right)
            for ln in lines.get(d["id"], []):
                name = " · ".join(x for x in (ln["name_vi"], ln["variant"]) if x)
                child = QTreeWidgetItem([name, ln["spec"], fmt_qty(ln["qty"]), ln["unit"],
                                         fmt_money(ln["unit_price"]), fmt_money(ln["amount"]), ln["note"]])
                child.setData(0, Qt.UserRole, d["id"])
                child.setToolTip(0, ln["name_zh"])
                for c in (2, 4, 5):
                    child.setTextAlignment(c, right)
                head.addChild(child)
            if d["fee_amount"]:
                fee = QTreeWidgetItem([t("cust.fees"), "", "", "", "", fmt_money(d["fee_amount"]), ""])
                fee.setData(0, Qt.UserRole, d["id"])
                fee.setTextAlignment(5, right)
                head.addChild(fee)
            self.orders.addTopLevelItem(head)
        self.orders.expandAll()
        for c in range(self.orders.columnCount()):
            self.orders.resizeColumnToContents(c)

    def export(self):
        """The orders and products of this customer in the chosen period, with prices, to output/."""
        start, end = self._range()
        label = t("filter.all_time") if start is None else f"{fmt_date(start)} – {fmt_date(end)}"
        name = queries.customer(self.ctx.conn, self.customer_id)["name"]
        safe = "".join(ch if ch.isalnum() else "-" for ch in f"{name}_{label}").strip("-")[:80]
        path = self.ctx.ws.output / f"KhachHang_{safe}_{datetime.now():%Y%m%d-%H%M%S}.xlsx"
        try:
            report.export_customer(path, self.ctx.conn, self.customer_id, start, end, label)
        except PermissionError:
            error(self, t("stats.export_locked"))
            return
        activity.log("export", path.name)
        if ask(self, t("stats.exported", path=str(path))):
            open_path(path)

    def open_order(self, item, _column=0):
        doc_id = item.data(0, Qt.UserRole)
        if doc_id:
            DocumentDialog(self.ctx, doc_id, self).exec()
            self.refresh()


def _price_range(low, high) -> str:
    """'1.200.000', or '1.100.000 – 1.200.000' when the price changed over the period."""
    if low is None:
        return fmt_money(None)
    return fmt_money(low) if abs(high - low) < 0.5 else f"{fmt_money(low)} – {fmt_money(high)}"


# ---- product ---------------------------------------------------------------

class ProductDialog(_Base):
    def __init__(self, ctx: AppContext, product_id: int, parent=None):
        super().__init__(ctx, parent)
        p = queries.product(ctx.conn, product_id)
        self.setWindowTitle(p["name_vi"])
        self.layout_.addWidget(title_label(" — ".join(x for x in (p['name_vi'], p['spec'], p['variant']) if x)))
        form = QFormLayout()
        form.addRow(t("col.code") + ":", QLabel(p["code"]))
        form.addRow(t("col.name_zh") + ":", _selectable(p["name_zh"]))
        form.addRow(t("col.category") + ":", QLabel(p["category"] or "—"))
        stock = QLabel(f"{fmt_qty(p['stock'])} {p['unit']}")
        font = stock.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 3)
        stock.setFont(font)
        form.addRow(t("col.stock") + ":", stock)
        form.addRow(t("prod.places") + ":", QLabel(t("prod.places_value", main=fmt_qty(p["stock_main"]),
                                                     office=fmt_qty(p["stock_office"]), unit=p["unit"])))
        if p["stock_note"]:
            note = _selectable(p["stock_note"])
            note.setStyleSheet(f"color: {theme_color('warn')}; font-weight: bold;")
            form.addRow(t("col.stock_note") + ":", note)
        self.layout_.addLayout(form)

        box1 = QGroupBox(t("prod.history_title"))
        l1 = QVBoxLayout(box1)
        self.history = make_table([t("col.date"), t("col.kind"), t("col.doc_code"), t("col.customer"),
                                   t("col.place"), t("col.qty_change"), t("col.balance")], stretch=3)
        rows, ids, colors = [], [], []
        for m in reversed(queries.product_history(ctx.conn, product_id)):
            rows.append([date_item(m["occurred_on"]), t(f"move.{m['kind']}"), m["code"], m["customer_name"],
                         location_name(m["location_id"]), num_item(m["qty"]), num_item(m["balance"])])
            ids.append(m["document_id"])
            colors.append(RED if m["balance"] < 0 else None)
        fill_table(self.history, rows, ids=ids, colors=colors)
        self.history.doubleClicked.connect(
            lambda idx: DocumentDialog(self.ctx, row_id(self.history, idx.row()), self).exec())
        l1.addWidget(self.history)

        box2 = QGroupBox(t("prod.customers_title"))
        l2 = QVBoxLayout(box2)
        self.customers = make_table([t("col.customer"), t("col.total_qty"), t("col.revenue"), t("col.times"),
                                     t("col.last_date")], stretch=0)
        tops = queries.product_top_customers(ctx.conn, product_id)
        fill_table(self.customers,
                   [[c["name"], num_item(c["total_qty"]), money_item(c["revenue"]), num_item(c["times"]),
                     date_item(c["last_date"])]
                    for c in tops],
                   ids=[c["id"] for c in tops])
        self.customers.doubleClicked.connect(
            lambda idx: CustomerDialog(self.ctx, row_id(self.customers, idx.row()), self).exec())
        l2.addWidget(self.customers)
        self.layout_.addWidget(box1, 3)
        self.layout_.addWidget(box2, 2)
        self.add_close()

