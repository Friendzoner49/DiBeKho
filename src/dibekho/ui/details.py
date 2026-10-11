"""Detail windows: order (document), customer, product. They link to each other."""

from datetime import date

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
    QVBoxLayout,
)

from dibekho import db
from dibekho.core import deliveries, queries
from dibekho.core.stock import close_document
from dibekho.core.text import fmt_qty
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
    make_table,
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

        title = t("doc.title_delivery", code=head["code"]) if kind == "delivery" else kind_text(kind)
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
        if head["note"]:
            form.addRow(t("col.note") + ":", _selectable(head["note"]))
        if head["source_file"]:
            form.addRow(t("col.file") + ":", _selectable(head["source_file"]))
        form.addRow(t("doc.read_at") + ":", QLabel(fmt_date(head["created_at"]) + head["created_at"][10:16]))
        self.layout_.addLayout(form)

        if kind == "stock_count":
            diffs = queries.count_differences(ctx.conn, doc_id)
            headers = [t("col.code"), t("col.product"), t("col.spec"), t("col.variant"), t("col.counted"),
                       t("col.difference")]
            rows = [[ln["code"], ln["name_vi"], ln["spec"], ln["variant"], num_item(ln["qty"]),
                     num_item(diffs.get(ln["product_id"], 0))] for ln in lines]
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
        if kind in ("delivery", "receipt"):
            total = sum(ln["qty"] for ln in lines)
            self.layout_.addWidget(hint_label(t("doc.total", lines=len(lines), qty=fmt_qty(total))))
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
        if head["status"] == "active":
            b = QPushButton(t("btn.cancel_doc"))
            b.clicked.connect(self.cancel_doc)
            buttons.addWidget(b)
        buttons.addStretch()
        self.layout_.addLayout(buttons)
        self.add_close()

    def open_customer(self):
        CustomerDialog(self.ctx, self.head["customer_id"], self).exec()

    def open_product(self, product_id):
        if product_id:
            ProductDialog(self.ctx, product_id, self).exec()

    def open_original(self):
        copy = deliveries.original_copy(self.ctx.ws, self.head["source_hash"])
        if copy is None:
            error(self, t("doc.original_missing"))
        else:
            open_path(copy)

    def cancel_doc(self):
        if not ask(self, t("doc.confirm_cancel")):
            return
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

    def reread_doc(self):
        if not ask(self, t("doc.confirm_reread")):
            return
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
        self.layout_.addLayout(form)

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
        self.layout_.addLayout(bar)
        for sig in (self.all_time.toggled, self.date_from.dateChanged, self.date_to.dateChanged):
            sig.connect(self.refresh)

        box1 = QGroupBox(t("cust.products_title"))
        l1 = QVBoxLayout(box1)
        self.products = make_table([t("col.product"), t("col.name_zh"), t("col.spec"), t("col.variant"),
                                    t("col.total_qty"),
                                    t("col.unit"), t("col.times"), t("col.last_date")], stretch=0)
        self.products.doubleClicked.connect(
            lambda idx: ProductDialog(self.ctx, row_id(self.products, idx.row()), self).exec())
        l1.addWidget(self.products)
        box2 = QGroupBox(t("cust.orders_title"))
        l2 = QVBoxLayout(box2)
        self.orders = make_table([t("col.date"), t("col.doc_code"), t("col.lines"), t("col.total_qty"),
                                  t("col.file")], stretch=4)
        self.orders.doubleClicked.connect(self.open_order)
        l2.addWidget(self.orders)
        self.layout_.addWidget(box1, 3)
        self.layout_.addWidget(box2, 2)
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
        prods = queries.customer_products(self.ctx.conn, self.customer_id, start, end)
        fill_table(self.products,
                   [[p["name_vi"], p["name_zh"], p["spec"], p["variant"], num_item(p["total_qty"]), p["unit"], num_item(p["times"]),
                     date_item(p["last_date"])] for p in prods],
                   ids=[p["id"] for p in prods])
        docs = queries.documents(self.ctx.conn, "delivery", start, end, customer_id=self.customer_id)
        fill_table(self.orders,
                   [[date_item(d["doc_date"]), d["code"], num_item(d["line_count"]), num_item(d["total_qty"]),
                     d["source_file"]] for d in docs],
                   ids=[d["id"] for d in docs])

    def open_order(self, idx):
        DocumentDialog(self.ctx, row_id(self.orders, idx.row()), self).exec()
        self.refresh()


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
        self.layout_.addLayout(form)

        box1 = QGroupBox(t("prod.history_title"))
        l1 = QVBoxLayout(box1)
        self.history = make_table([t("col.date"), t("col.kind"), t("col.doc_code"), t("col.customer"),
                                   t("col.qty_change"), t("col.balance")], stretch=3)
        rows, ids, colors = [], [], []
        for m in reversed(queries.product_history(ctx.conn, product_id)):
            rows.append([date_item(m["occurred_on"]), t(f"move.{m['kind']}"), m["code"], m["customer_name"],
                         num_item(m["qty"]), num_item(m["balance"])])
            ids.append(m["document_id"])
            colors.append(RED if m["balance"] < 0 else None)
        fill_table(self.history, rows, ids=ids, colors=colors)
        self.history.doubleClicked.connect(
            lambda idx: DocumentDialog(self.ctx, row_id(self.history, idx.row()), self).exec())
        l1.addWidget(self.history)

        box2 = QGroupBox(t("prod.customers_title"))
        l2 = QVBoxLayout(box2)
        self.customers = make_table([t("col.customer"), t("col.total_qty"), t("col.times"), t("col.last_date")],
                                    stretch=0)
        tops = queries.product_top_customers(ctx.conn, product_id)
        fill_table(self.customers,
                   [[c["name"], num_item(c["total_qty"]), num_item(c["times"]), date_item(c["last_date"])]
                    for c in tops],
                   ids=[c["id"] for c in tops])
        self.customers.doubleClicked.connect(
            lambda idx: CustomerDialog(self.ctx, row_id(self.customers, idx.row()), self).exec())
        l2.addWidget(self.customers)
        self.layout_.addWidget(box1, 3)
        self.layout_.addWidget(box2, 2)
        self.add_close()

