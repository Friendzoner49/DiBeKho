from datetime import date

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton

from dibekho.core import catalog, queries
from dibekho.excel.receipt import write_template
from dibekho.i18n import t
from dibekho.ui.common import (
    ask,
    date_item,
    error,
    fill_table,
    make_table,
    num_item,
    open_path,
    row_id,
    status_text,
)
from dibekho.ui.details import DocumentDialog
from dibekho.ui.page import Page


class ReceiptPage(Page):
    def __init__(self, ctx, go_pending):
        super().__init__(ctx, t("nav.receipts"), t("receipts.steps"))
        self.go_pending = go_pending
        row = QHBoxLayout()
        make = QPushButton(t("receipts.make_template"))
        make.clicked.connect(self.make_template)
        open_input = QPushButton(t("receipts.open_input"))
        open_input.clicked.connect(lambda: open_path(self.ctx.ws.input))
        check = QPushButton(t("receipts.check_input"))
        check.clicked.connect(self.go_pending)
        for b in (make, open_input, check):
            row.addWidget(b)
        row.addStretch()
        self.layout_.addLayout(row)
        self.layout_.addWidget(QLabel(t("receipts.history")))
        self.table = make_table([t("col.date"), t("col.lines"), t("col.total_qty"), t("col.note"), t("col.status"),
                                 t("col.file")], stretch=3)
        self.table.doubleClicked.connect(
            lambda idx: DocumentDialog(self.ctx, row_id(self.table, idx.row()), self).exec())
        self.layout_.addWidget(self.table)

    def refresh(self):
        docs = queries.documents(self.ctx.conn, "receipt", include_closed=True)
        fill_table(self.table, [[date_item(d["doc_date"]), num_item(d["line_count"]), num_item(d["total_qty"]),
                                 d["note"], status_text(d["status"]), d["source_file"]] for d in docs],
                   ids=[d["id"] for d in docs])

    def make_template(self):
        products = catalog.products(self.ctx.conn)
        if not products:
            error(self, t("receipts.no_products"))
            return
        today = date.today()
        path = self.ctx.ws.output / f"HangVe_{today:%Y-%m-%d}.xlsx"
        n = 2
        while path.exists():
            path = self.ctx.ws.output / f"HangVe_{today:%Y-%m-%d}_{n}.xlsx"
            n += 1
        write_template(path, products, today)
        if ask(self, t("receipts.template_done", path=str(path))):
            open_path(path)
