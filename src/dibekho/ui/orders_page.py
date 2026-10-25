"""'Đơn hàng' (all documents with filters) and 'Khách hàng' (customer list)."""

from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
)

from dibekho.core import catalog, queries
from dibekho.i18n import t
from dibekho.ui.common import (
    GREY,
    error,
    location_name,
    date_item,
    fill_table,
    from_qdate,
    make_table,
    money_item,
    num_item,
    reread_whole_note,
    row_id,
    status_text,
    to_qdate,
)
from dibekho.ui.details import CustomerDialog, DocumentDialog
from dibekho.ui.page import Page

KINDS = ("delivery", "receipt", "stock_count", "transfer")
GOODS_COL, FEES_COL = 6, 7  # table columns hidden when fixed_kind is set: always blank outside 'delivery'


def _place(d) -> str:
    """Delivery: taken from; receipt: put in; transfer: from → to ('?' while a note waits for its place)."""
    if d["kind"] == "transfer":
        return f"{location_name(d['location_id'])} → {location_name(d['to_location_id'])}"
    if d["kind"] in ("delivery", "receipt"):
        return location_name(d["location_id"]) + ("" if d["location_set"] else " (?)")
    return ""


class OrdersPage(Page):
    def __init__(self, ctx, fixed_kind: str | None = None):
        title = t(f"kind.{fixed_kind}_plural") if fixed_kind else t("nav.orders")
        super().__init__(ctx, title, t("orders.hint"))
        self.fixed_kind = fixed_kind
        grid = QGridLayout()
        self.kind = QComboBox()
        for k in KINDS:
            self.kind.addItem(t(f"kind.{k}_plural"), k)
        self.all_time = QCheckBox(t("filter.all_time"))
        self.all_time.setChecked(bool(fixed_kind))  # a transfer/count is rare; don't hide one past 90 days
        self.date_from, self.date_to = QDateEdit(), QDateEdit()
        for w in (self.date_from, self.date_to):
            w.setCalendarPopup(True)
            w.setDisplayFormat("dd/MM/yyyy")
        today = date.today()
        self.date_from.setDate(to_qdate(today - timedelta(days=90)))
        self.date_to.setDate(to_qdate(today))
        self.customer = QComboBox()
        self.product = QComboBox()
        for combo in (self.customer, self.product):
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.NoInsert)
        self.text = QLineEdit()
        self.text.setPlaceholderText(t("orders.text_filter"))
        self.text.setClearButtonEnabled(True)
        self.closed = QCheckBox(t("orders.include_cancelled"))

        self.kind_label = QLabel(t("orders.kind"))
        grid.addWidget(self.kind_label, 0, 0)
        grid.addWidget(self.kind, 0, 1)
        grid.addWidget(QLabel(t("filter.from")), 0, 2)
        grid.addWidget(self.date_from, 0, 3)
        grid.addWidget(QLabel(t("filter.to")), 0, 4)
        grid.addWidget(self.date_to, 0, 5)
        grid.addWidget(self.all_time, 0, 6)
        self.customer_label = QLabel(t("col.customer"))
        grid.addWidget(self.customer_label, 1, 0)
        grid.addWidget(self.customer, 1, 1, 1, 2)
        grid.addWidget(QLabel(t("col.product")), 1, 3)
        grid.addWidget(self.product, 1, 4, 1, 2)
        grid.addWidget(self.closed, 1, 6)
        grid.addWidget(self.text, 2, 0, 1, 7)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(5, 1)
        self.layout_.addLayout(grid)

        if fixed_kind:
            self.kind.setCurrentIndex(max(self.kind.findData(fixed_kind), 0))
            for w in (self.kind_label, self.kind, self.customer_label, self.customer):
                w.setVisible(False)

        top = QHBoxLayout()
        self.count = QLabel()
        top.addWidget(self.count, 1)
        if fixed_kind == "transfer":
            edit = QPushButton(t("transfer.edit_selected"))
            edit.clicked.connect(self.edit_transfer_selected)
            top.addWidget(edit)
        self.layout_.addLayout(top)
        self.table = make_table([t("col.date"), t("col.doc_code"), t("col.customer"), t("col.place"),
                                 t("col.lines"), t("col.total_qty"), t("col.goods"), t("col.fees"), t("col.status"),
                                 t("col.file")], stretch=2)
        self.table.doubleClicked.connect(self.open_doc)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        if fixed_kind:
            self.table.setColumnHidden(GOODS_COL, True)
            self.table.setColumnHidden(FEES_COL, True)
        self.layout_.addWidget(self.table)

        for sig in (self.kind.currentIndexChanged, self.all_time.toggled, self.date_from.dateChanged,
                    self.date_to.dateChanged, self.customer.currentIndexChanged, self.product.currentIndexChanged,
                    self.text.textChanged, self.closed.toggled):
            sig.connect(self._load)

    def refresh(self):
        conn = self.ctx.conn
        for combo, items in (
            (self.customer, [(c["name"], c["id"]) for c in queries.customers(conn)]),
            (self.product, [(catalog.label(p), p["id"]) for p in catalog.products(conn, True)]),
        ):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(t("filter.all"), None)
            for text, value in items:
                combo.addItem(text, value)
            combo.setCurrentIndex(max(combo.findData(current), 0))
            combo.blockSignals(False)
        self._load()

    def _load(self):
        all_time = self.all_time.isChecked()
        self.date_from.setEnabled(not all_time)
        self.date_to.setEnabled(not all_time)
        start = None if all_time else from_qdate(self.date_from.date())
        end = None if all_time else from_qdate(self.date_to.date())
        docs = queries.documents(
            self.ctx.conn, self.kind.currentData(), start, end,
            customer_id=self.customer.currentData(), product_id=self.product.currentData(),
            include_closed=self.closed.isChecked(), text=self.text.text().strip(),
        )
        rows, colors = [], []
        for d in docs:
            rows.append([date_item(d["doc_date"]), d["code"], d["customer_name"], _place(d),
                         num_item(d["line_count"]),
                         num_item(d["total_qty"]),
                         money_item(d["goods_amount"]) if d["kind"] == "delivery" else "",
                         money_item(d["fee_amount"]) if d["kind"] == "delivery" and d["fee_amount"] else "",
                         status_text(d["status"]), d["source_file"]])
            colors.append(GREY if d["status"] != "active" else None)
        fill_table(self.table, rows, ids=[d["id"] for d in docs])
        for r, color in enumerate(colors):
            if color is not None:
                for c in range(self.table.columnCount()):
                    self.table.item(r, c).setForeground(color)
        self.count.setText(t("orders.count", count=len(docs)))

    def open_doc(self, idx):
        DocumentDialog(self.ctx, row_id(self.table, idx.row()), self).exec()

    def _context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        doc_id = row_id(self.table, idx.row())
        row = self.ctx.conn.execute("SELECT kind, status FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if row is None or row["kind"] != "delivery" or row["status"] != "active":
            return
        menu = QMenu(self)
        menu.addAction(t("btn.reread_doc"), lambda: self._reread(doc_id))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _reread(self, doc_id):
        if reread_whole_note(self.ctx, self, doc_id):
            self._load()

    def edit_transfer_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            error(self, t("orders.select_first"))
            return
        doc_id = row_id(self.table, rows[0].row())
        status = self.ctx.conn.execute("SELECT status FROM documents WHERE id = ?", (doc_id,)).fetchone()[0]
        if status != "active":
            error(self, t("orders.not_active"))
            return
        from dibekho.ui.count_page import open_transfer_dialog

        if open_transfer_dialog(self.ctx, self, doc_id):
            self._load()


class CustomersPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, t("nav.customers"), t("customers.hint"))
        self.text = QLineEdit()
        self.text.setPlaceholderText(t("customers.filter"))
        self.text.setClearButtonEnabled(True)
        self.text.textChanged.connect(self.refresh)
        self.layout_.addWidget(self.text)
        self.table = make_table([t("col.customer"), t("col.contact"), t("col.phone"), t("col.address"),
                                 t("col.orders"), t("col.revenue"), t("col.first_order"), t("col.last_order")],
                                stretch=3)
        self.table.doubleClicked.connect(
            lambda idx: CustomerDialog(self.ctx, row_id(self.table, idx.row()), self).exec())
        self.layout_.addWidget(self.table)

    def refresh(self):
        rows = queries.customers(self.ctx.conn, self.text.text().strip())
        fill_table(self.table,
                   [[c["name"], c["contact"], c["phone"], c["address"], num_item(c["order_count"]),
                     money_item(c["revenue"]),
                     date_item(c["first_order"]), date_item(c["last_order"])] for c in rows],
                   ids=[c["id"] for c in rows])
