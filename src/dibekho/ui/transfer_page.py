"""Settings tab 'Chuyển dữ liệu và sao lưu': export a package for another machine; backups and restore."""

from dataclasses import replace
from datetime import datetime

from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dibekho import db
from dibekho.core import backup, catalog, deliveries, transfer
from dibekho.excel import master_data
from dibekho.i18n import t
from dibekho.ui.common import (
    YELLOW,
    ask,
    error,
    fill_table,
    fit_window,
    hint_label,
    info,
    make_table,
    num_item,
    open_path,
    selected_id,
)


class StockMatchDialog(QDialog):
    """Which product each row of the 'Tồn kho' sheet goes to, when they are not tied by code (old files
    without the code column). Rows whose name/category/type differ from the product are yellow, and the user
    can choose another product for any row; the 'Problem' column says why a row is yellow.
    result_stock() gives the rows with the user's choices."""

    ROW, STOCK, IN_FILE, ASSIGN, PROBLEM = range(5)

    def __init__(self, parent, products, stock):
        super().__init__(parent)
        self.setWindowTitle(t("master.preview_title"))
        fit_window(self, 1250, 640)
        self.products = {p.row: p for p in products}
        self.stock = stock
        lay = QVBoxLayout(self)
        lay.addWidget(hint_label(t("master.preview_hint")))
        self.summary = QLabel()
        lay.addWidget(self.summary)
        self.table = make_table([t("master.col_stock_row"), t("col.stock"), t("master.col_in_file"),
                                 t("master.col_assign"), t("master.col_problem")], stretch=self.PROBLEM)
        fill_table(self.table, [[num_item(st.row), num_item(st.stock), self._in_file(st), "", ""] for st in stock])
        self.table.setSortingEnabled(False)  # row r must stay stock[r]
        self.combos = []
        for r, st in enumerate(stock):
            combo = QComboBox()
            combo.addItem(t("master.no_assign"), None)
            for p in products:
                combo.addItem(self._product_label(p), p.row)
            combo.setCurrentIndex(max(combo.findData(st.product_row), 0))
            widest = max(combo.fontMetrics().horizontalAdvance(combo.itemText(i)) for i in range(combo.count()))
            combo.view().setMinimumWidth(widest + 40)  # the drop-down list shows every name in full
            combo.currentIndexChanged.connect(self._mark)
            self.table.setCellWidget(r, self.ASSIGN, combo)
            self.combos.append(combo)
        # long texts: fixed widths that fit the window, hover a cell to read it in full
        self.table.setColumnWidth(self.IN_FILE, 360)
        self.table.setColumnWidth(self.ASSIGN, 360)
        self.table.natural = 280
        self.table.fill_spare()
        lay.addWidget(self.table)
        box = QDialogButtonBox()
        box.addButton(t("master.preview_continue"), QDialogButtonBox.AcceptRole)
        box.addButton(t("btn.cancel"), QDialogButtonBox.RejectRole)
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self._mark()

    # what tells the rows apart (category, type/colour, packing) comes first, so it shows in a narrow column
    @staticmethod
    def _in_file(st) -> str:
        return " · ".join(x for x in (st.category, st.variant, st.name.replace("\n", " / ")) if x)

    @staticmethod
    def _product_label(p) -> str:
        return " · ".join(x for x in (p.code or "—", p.spec, p.category, p.variant, p.name_vi) if x)

    def _chosen(self, r):
        return self.combos[r].currentData()

    def _problem(self, r, st) -> str:
        p = self.products.get(self._chosen(r))
        if p is None:
            return t("master.problem_unassigned")
        problems = []
        name_differs, missing = master_data.stock_problems(st, p)
        if name_differs:
            problems.append(t("master.problem_name"))
        if missing:
            has = " · ".join(x for x in (p.category, p.variant) if x) or "—"
            problems.append(t("master.problem_labels", labels=" · ".join(missing), code=p.code or "—", has=has))
        others = [str(o.row) for i, o in enumerate(self.stock) if i != r and self._chosen(i) == p.row]
        if others:
            problems.append(t("master.problem_twice", rows=", ".join(others)))
        return "; ".join(problems)

    def _mark(self):
        differ = 0
        for r, st in enumerate(self.stock):
            problem = self._problem(r, st)
            differ += bool(problem)
            self.combos[r].setToolTip(self.combos[r].currentText())
            cell = self.table.item(r, self.PROBLEM)
            cell.setText(problem)
            cell.setToolTip(problem)
            for c in (self.ROW, self.STOCK, self.IN_FILE, self.PROBLEM):
                self.table.item(r, c).setBackground(QBrush(YELLOW) if problem else QBrush())
        self.summary.setText(t("master.preview_warn", count=differ) if differ else t("master.preview_ok"))

    def _accept(self):
        rows: dict[int, list[int]] = {}
        for r, st in enumerate(self.stock):
            if self._chosen(r) is not None:
                rows.setdefault(self._chosen(r), []).append(st.row)
        twice = [(p, rs) for p, rs in rows.items() if len(rs) > 1]
        if twice:
            p, rs = twice[0]
            error(self, t("master.preview_twice", product=self._product_label(self.products[p]),
                          rows=", ".join(str(x) for x in rs)))
            return
        self.accept()

    def result_stock(self):
        return [replace(st, product_row=self._chosen(r)) for r, st in enumerate(self.stock)]


def import_master_file(ctx, parent, path, data=None) -> bool:
    """Import a master-data workbook: products, customers and the stock of its 'Tồn kho' sheet.
    Returns True when imported. data: the already read (products, customers, stock)."""
    try:
        products, customers, stock = data or master_data.read(path)
    except master_data.NotMasterData as exc:
        error(parent, t("master.not_master_file", error=str(exc)))
        return False
    if stock and master_data.needs_check(stock):
        dlg = StockMatchDialog(parent, products, stock)
        if dlg.exec() != QDialog.Accepted:
            return False
        stock = dlg.result_stock()
    text = t("master.confirm_import", products=len(products), customers=len(customers))
    if stock:
        text = text.replace("\n\n", "\n\n" + t("master.confirm_stock", count=len(stock)) + "\n\n", 1)
    if not ask(parent, text):
        return False
    backup.named_backup(ctx.conn, ctx.ws, "truoc-nhap-du-lieu-goc")
    if stock:  # notes up to today must be in the ledger first, or they would be subtracted from the count
        deliveries.scan(ctx.conn, ctx.ws)
    result = catalog.import_master(ctx.conn, products, customers, stock, note=t("master.stock_note"))
    ctx.notify()
    text = t("master.imported", **{k: v for k, v in result.items() if isinstance(v, int)})
    if result["stock_counted"]:
        text += "\n" + t("master.imported_stock", count=result["stock_counted"])
    if result["renumbered"]:
        lines = [t("master.renumbered_row", row=r, code=old, new=new) for r, old, new in result["renumbered"]]
        text += "\n\n" + t("master.renumbered") + "\n" + "\n".join(lines)
    if result["skipped"]:
        lines = [t("master.skipped_row", row=r, code=code or "—", existing=existing)
                 for r, code, existing in result["skipped"]]
        text += "\n\n" + t("master.skipped") + "\n" + "\n".join(lines)
    if result["stock_skipped"]:
        lines = [t("master.stock_skipped_row", row=r, name=name) for r, name in result["stock_skipped"]]
        text += "\n\n" + t("master.stock_skipped") + "\n" + "\n".join(lines)
    info(parent, text)
    return True


class TransferPanel(QWidget):
    """Refreshed by the settings page that contains it."""

    def __init__(self, ctx, go_pending):
        super().__init__()
        self.ctx = ctx
        self.layout_ = QVBoxLayout(self)
        box = QGroupBox(t("transfer.export_title"))
        lay = QVBoxLayout(box)
        lay.addWidget(hint_label(t("transfer.steps")))
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        export = QPushButton(t("transfer.export"))
        export.clicked.connect(self.export)
        receive = QPushButton(t("transfer.receive"))
        receive.clicked.connect(go_pending)
        row.addWidget(export)
        row.addWidget(receive)
        row.addStretch()
        lay.addLayout(row)
        self.layout_.addWidget(box)

        master = QGroupBox(t("master.title"))
        lay_m = QVBoxLayout(master)
        lay_m.addWidget(hint_label(t("master.hint")))
        row_m = QHBoxLayout()
        export_master = QPushButton(t("master.export"))
        export_master.clicked.connect(self.export_master)
        import_master = QPushButton(t("master.import"))
        import_master.clicked.connect(self.import_master)
        row_m.addWidget(export_master)
        row_m.addWidget(import_master)
        row_m.addStretch()
        lay_m.addLayout(row_m)
        self.layout_.addWidget(master)

        box2 = QGroupBox(t("backup.title"))
        lay2 = QVBoxLayout(box2)
        lay2.addWidget(hint_label(t("backup.hint")))
        self.backups = make_table([t("backup.file"), t("backup.time")], stretch=0)
        lay2.addWidget(self.backups)
        row2 = QHBoxLayout()
        now = QPushButton(t("backup.now"))
        now.clicked.connect(self.backup_now)
        restore = QPushButton(t("backup.restore"))
        restore.clicked.connect(self.restore)
        folder = QPushButton(t("backup.open_folder"))
        folder.clicked.connect(lambda: open_path(self.ctx.ws.backups))
        for b in (now, restore, folder):
            row2.addWidget(b)
        row2.addStretch()
        lay2.addLayout(row2)
        self.layout_.addWidget(box2, 1)

    def refresh(self):
        conn = self.ctx.conn
        last_export = db.get_meta(conn, "last_transfer_at")
        last_import = db.get_meta(conn, "last_import_from")
        lines = [t("transfer.this_device", name=self.ctx.cfg.device_name)]
        if last_export:
            lines.append(t("transfer.last_transfer", at=last_export.replace("T", " ")))
        if last_import:
            lines.append(t("transfer.last_import", source=last_import.replace("T", " ")))
        if transfer.has_unsent_changes(conn):
            lines.append("⚠ " + t("transfer.has_changes"))
        self.status.setText("\n".join(lines))
        files = backup.list_backups(self.ctx.ws)
        self._files = files
        fill_table(self.backups, [[f.name, datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M")]
                                  for f in files], ids=list(range(len(files))))

    def export(self):
        path = transfer.export_package(self.ctx.conn, self.ctx.ws, self.ctx.cfg)
        self.refresh()
        if ask(self, t("transfer.exported", path=str(path))):
            open_path(path.parent)

    def export_master(self):
        path = self.ctx.ws.output / f"DiBeKho_DuLieuGoc_{datetime.now():%Y-%m-%d_%H%M}.xlsx"
        try:
            master_data.export(path, self.ctx.conn)
        except OSError as exc:
            error(self, t("stats.export_locked") + f"\n{exc}")
            return
        if ask(self, t("master.exported", path=str(path))):
            open_path(path)

    def import_master(self):
        path, _ = QFileDialog.getOpenFileName(self, t("master.import"), str(self.ctx.ws.root), "Excel (*.xlsx)")
        if path:
            import_master_file(self.ctx, self, path)

    def backup_now(self):
        backup.named_backup(self.ctx.conn, self.ctx.ws, "thu-cong")
        self.refresh()

    def restore(self):
        idx = selected_id(self.backups)
        if idx is None:
            error(self, t("backup.pick_first"))
            return
        chosen = self._files[idx]
        if not ask(self, t("backup.confirm_restore", name=chosen.name)):
            return
        try:
            backup.named_backup(self.ctx.conn, self.ctx.ws, "truoc-khoi-phuc")
            self.ctx.close()
            backup.restore(self.ctx.ws, chosen)
        finally:
            self.ctx.reopen()
        info(self, t("backup.restored"))
