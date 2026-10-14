"""Settings tab 'Chuyển dữ liệu và sao lưu': export a package for another machine; backups and restore."""

from datetime import datetime

from PySide6.QtWidgets import QFileDialog, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from dibekho import db
from dibekho.core import backup, catalog, deliveries, transfer
from dibekho.excel import master_data
from dibekho.i18n import t
from dibekho.ui.common import ask, error, fill_table, hint_label, info, make_table, open_path, selected_id


def import_master_file(ctx, parent, path, data=None) -> bool:
    """Import a master-data workbook: products, customers and the stock of its 'Tồn kho' sheet.
    Returns True when imported. data: the already read (products, customers, stock)."""
    try:
        products, customers, stock = data or master_data.read(path)
    except master_data.NotMasterData as exc:
        error(parent, t("master.not_master_file", error=str(exc)))
        return False
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
