from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from dibekho.core import catalog, inbox, queries
from dibekho.excel.receipt import write_template
from dibekho.i18n import t
from dibekho.ui.catalog_import import import_catalog_file
from dibekho.ui.common import (
    ask,
    date_item,
    error,
    fill_table,
    fit_window,
    fmt_date,
    hint_label,
    info,
    make_table,
    num_item,
    open_path,
    row_id,
    status_text,
)
from dibekho.ui.details import DocumentDialog
from dibekho.ui.page import Page


def review_receipt(ctx, parent, item) -> bool:
    """Show the goods-in lines and record them on confirmation. Returns True if recorded."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(t("inbox.receipt"))
    fit_window(dlg, 820, 520)
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel(t("inbox.receipt_preview", date=fmt_date(item.receipt.doc_date))))
    if item.receipt.note:
        lay.addWidget(QLabel(f"{t('col.note')}: {item.receipt.note}"))
    table = make_table([t("col.code"), t("col.product"), t("col.spec"), t("col.variant"), t("col.qty"),
                        t("col.unit")])
    fill_table(table, [[p["code"], p["name_vi"], p["spec"], p["variant"], num_item(ln.qty), p["unit"]]
                       for ln, p in item.resolved])
    lay.addWidget(table)
    for w in item.receipt.warnings:
        lay.addWidget(hint_label("⚠ " + w))
    box = QDialogButtonBox()
    box.addButton(t("btn.confirm_receipt"), QDialogButtonBox.AcceptRole)
    box.addButton(t("btn.cancel"), QDialogButtonBox.RejectRole)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec() != QDialog.Accepted:
        return False
    ctx.undo_point("receipt")
    try:
        inbox.apply_receipt(ctx.conn, ctx.ws, item)
    except Exception as exc:
        error(parent, str(exc))
        return False
    ctx.notify()
    return True


def import_excel_file(ctx, parent, path: Path) -> bool:
    """A goods-in file or a catalog sheet from anywhere (input/, input/da-xu-ly/, Desktop...)."""
    item = inbox.read_item(ctx.conn, path)
    if item.kind == "receipt":
        return review_receipt(ctx, parent, item)
    if item.kind == "master":
        from dibekho.ui.transfer_page import import_master_file

        if import_master_file(ctx, parent, path, item.master):
            inbox.done(ctx.ws, path)
            return True
        return False
    if item.kind == "catalog":
        if import_catalog_file(ctx, parent, path, item.catalog):
            inbox.done(ctx.ws, path)
            ctx.notify()
            return True
        return False
    error(parent, item.error)
    return False


class ReceiptPage(Page):
    def __init__(self, ctx, go_pending):
        super().__init__(ctx, t("nav.receipts"), t("receipts.steps"))
        self.go_pending = go_pending
        row = QHBoxLayout()
        make = QPushButton(t("receipts.make_template"))
        make.clicked.connect(self.make_template)
        open_input = QPushButton(t("receipts.open_input"))
        open_input.clicked.connect(lambda: open_path(self.ctx.ws.input))
        pick = QPushButton(t("receipts.pick_file"))
        pick.setToolTip(t("receipts.pick_file_tip"))
        pick.clicked.connect(self.pick_file)
        check = QPushButton(t("receipts.check_input"))
        check.clicked.connect(self.go_pending)
        for b in (make, pick, open_input, check):
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

    def pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, t("receipts.pick_file"), str(self.ctx.ws.input), "Excel (*.xlsx)")
        if path and import_excel_file(self.ctx, self, Path(path)):
            info(self, t("receipts.picked_done"))

    def make_template(self):
        # in product-code order, like the other lists the user fills from (SP001, SP002…)
        products = sorted(catalog.products(self.ctx.conn), key=lambda p: (len(p["code"]), p["code"]))
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
