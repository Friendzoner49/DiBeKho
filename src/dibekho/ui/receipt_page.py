from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from dibekho.core import inbox, queries
from dibekho.i18n import t
from dibekho.ui.catalog_import import import_catalog_file
from dibekho.ui.common import (
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
from dibekho.ui.receipt_form import open_receipt_form


def source_text(d) -> str:
    """'Cửa khẩu / công ty mẹ' or 'Khách trả lại' for a receipt row ('' for receipts from before 0.3)."""
    return t(f"receipt_form.source_short_{d['receipt_source']}") if d["receipt_source"] else ""


def from_text(d) -> str:
    if d["receipt_source"] == "return":
        return " · ".join(x for x in (d["customer_name"], d["ref_code"] and t("receipt_form.order") + " " + d["ref_code"])
                          if x)
    return d["supplier_name"] or ""


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
        new = QPushButton(t("receipts.new"))
        f = new.font()
        f.setPointSize(f.pointSize() + 2)
        f.setBold(True)
        new.setFont(f)
        new.setMinimumHeight(48)
        new.clicked.connect(self.new_receipt)
        row.addWidget(new)
        row.addStretch()
        self.layout_.addLayout(row)
        row = QHBoxLayout()
        open_input = QPushButton(t("receipts.open_input"))
        open_input.clicked.connect(lambda: open_path(self.ctx.ws.input))
        pick = QPushButton(t("receipts.pick_file"))
        pick.setToolTip(t("receipts.pick_file_tip"))
        pick.clicked.connect(self.pick_file)
        check = QPushButton(t("receipts.check_input"))
        check.clicked.connect(self.go_pending)
        for b in (pick, open_input, check):
            row.addWidget(b)
        row.addStretch()
        self.layout_.addLayout(row)
        head = QHBoxLayout()
        head.addWidget(QLabel(t("receipts.history")))
        head.addStretch()
        edit = QPushButton(t("receipts.edit_selected"))
        edit.clicked.connect(self.edit_selected)
        head.addWidget(edit)
        self.layout_.addLayout(head)
        self.table = make_table([t("col.doc_code"), t("col.date"), t("receipt_form.source"), t("receipt_form.from"),
                                 t("col.lines"), t("col.total_qty"), t("col.note"), t("col.status")], stretch=3)
        self.table.doubleClicked.connect(
            lambda idx: DocumentDialog(self.ctx, row_id(self.table, idx.row()), self).exec())
        self.layout_.addWidget(self.table)

    def refresh(self):
        docs = queries.documents(self.ctx.conn, "receipt", include_closed=True)
        fill_table(self.table, [[d["code"], date_item(d["doc_date"]), source_text(d), from_text(d),
                                 num_item(d["line_count"]), num_item(d["total_qty"]), d["note"],
                                 status_text(d["status"])] for d in docs],
                   ids=[d["id"] for d in docs])

    def new_receipt(self):
        if open_receipt_form(self.ctx, self):
            self.refresh()

    def edit_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            error(self, t("receipts.select_first"))
            return
        doc_id = row_id(self.table, rows[0].row())
        status = self.ctx.conn.execute("SELECT status FROM documents WHERE id = ?", (doc_id,)).fetchone()[0]
        if status != "active":
            error(self, t("receipts.not_active"))
            return
        if open_receipt_form(self.ctx, self, doc_id):
            self.refresh()

    def pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, t("receipts.pick_file"), str(self.ctx.ws.input), "Excel (*.xlsx)")
        if path and import_excel_file(self.ctx, self, Path(path)):
            info(self, t("receipts.picked_done"))
