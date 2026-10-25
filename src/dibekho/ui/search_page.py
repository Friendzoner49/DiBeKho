from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter, QVBoxLayout

from dibekho.core import queries
from dibekho.i18n import t
from dibekho.ui.common import (
    PageWindow,
    date_item,
    fill_table,
    kind_text,
    make_table,
    num_item,
    row_id,
    status_text,
)
from dibekho.ui.details import CustomerDialog, DocumentDialog, ProductDialog
from dibekho.ui.orders_page import CustomersPage, OrdersPage
from dibekho.ui.page import Page
from dibekho.ui.stats_page import StatsPage

WINDOWS = (("search.orders_btn", OrdersPage), ("search.customers_btn", CustomersPage), ("search.stats_btn", StatsPage))


class SearchPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, t("nav.search"), t("search.hint"))
        self.box = QLineEdit()
        self.box.setPlaceholderText(t("search.placeholder"))
        self.box.setClearButtonEnabled(True)
        font = self.box.font()
        font.setPointSize(font.pointSize() + 3)
        self.box.setFont(font)
        self.layout_.addWidget(self.box)

        more = QHBoxLayout()
        more.addWidget(QLabel(t("search.more")))
        self.windows: dict[str, PageWindow] = {}
        for key, make in WINDOWS:
            b = QPushButton(t(key))
            b.clicked.connect(lambda _=False, k=key, m=make: self.open_window(k, m))
            more.addWidget(b)
        more.addStretch()
        self.layout_.addLayout(more)

        self._timer = QTimer(self, singleShot=True, interval=250)
        self._timer.timeout.connect(self.refresh)
        self.box.textChanged.connect(lambda _: self._timer.start())

        split = QSplitter(Qt.Vertical)
        self.products = make_table([t("col.code"), t("col.product"), t("col.name_zh"), t("col.spec"), t("col.variant"),
                                    t("col.stock"), t("col.unit")], stretch=1)
        self.customers = make_table([t("col.customer"), t("col.contact"), t("col.phone"), t("col.address")],
                                    stretch=3)
        self.documents = make_table([t("col.date"), t("orders.kind"), t("col.doc_code"), t("col.customer"),
                                     t("col.status"), t("col.file")], stretch=3)
        self.boxes = []
        for table, key, dialog in (
            (self.products, "search.products", ProductDialog),
            (self.customers, "search.customers", CustomerDialog),
            (self.documents, "search.documents", DocumentDialog),
        ):
            group = QGroupBox(t(key, count=0))
            QVBoxLayout(group).addWidget(table)
            table.doubleClicked.connect(
                lambda idx, tb=table, dlg=dialog: dlg(self.ctx, row_id(tb, idx.row()), self).exec())
            split.addWidget(group)
            self.boxes.append((group, key))
        self.layout_.addWidget(split)

    def refresh(self):
        res = queries.search(self.ctx.conn, self.box.text())
        fill_table(self.products, [[p["code"], p["name_vi"], p["name_zh"], p["spec"], p["variant"],
                                    num_item(p["stock"]),
                                    p["unit"]] for p in res["products"]],
                   ids=[p["id"] for p in res["products"]])
        fill_table(self.customers, [[c["name"], c["contact"], c["phone"], c["address"]] for c in res["customers"]],
                   ids=[c["id"] for c in res["customers"]])
        fill_table(self.documents, [[date_item(d["doc_date"]), kind_text(d["kind"]), d["code"], d["customer_name"],
                                     status_text(d["status"]), d["source_file"]] for d in res["documents"]],
                   ids=[d["id"] for d in res["documents"]])
        for (group, key), n in zip(self.boxes, (len(res["products"]), len(res["customers"]), len(res["documents"]))):
            group.setTitle(t(key, count=n))

    def open_window(self, key, make) -> PageWindow:
        win = self.windows.get(key)
        if win is None:
            win = self.windows[key] = PageWindow(make(self.ctx), self)
        win.show()
        win.raise_()
        win.activateWindow()
        return win

    def open_all_windows(self) -> None:
        """Used by --self-test."""
        for key, make in WINDOWS:
            self.open_window(key, make).close()

    def focus(self):
        self.box.setFocus()
        self.box.selectAll()
