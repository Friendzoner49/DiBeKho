"""'Cài đặt': language, workspace folder, learned names on notes (the catalog: Tra cứu), data transfer, uninstall."""

import shutil
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dibekho import __version__, db
from dibekho.core import activity, catalog, deliveries, reset, uninstall
from dibekho.core.cloud import approval, replica
from dibekho.core.text import fmt_qty
from dibekho.core.workspace import Config
from dibekho.i18n import LANGUAGES, t
from dibekho.ui.cloud_tab import CloudTab
from dibekho.ui.common import (
    ask,
    error,
    fmt_date,
    hint_label,
    info,
    open_path,
    reread_whole_note,
)
from dibekho.ui.license_dialog import LicenseDialog
from dibekho.ui.shared_admin import replace_shared_data
from dibekho.ui.log_dialog import LogDialog, TripleClickLabel
from dibekho.ui.page import Page
from dibekho.ui.transfer_page import TransferPanel


SCALES = (100, 110, 120, 130, 140, 150)  # interface size choices, in %


class SettingsPage(Page):
    def __init__(self, ctx, go_pending=lambda: None):
        super().__init__(ctx, t("nav.settings"))
        self.go_pending = go_pending
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(lambda i: activity.log("tab", self.tabs.tabText(i)))
        self.layout_.addWidget(self.tabs, 1)
        general_tab, products_tab = QWidget(), QWidget()
        general_lay, products_lay = QVBoxLayout(general_tab), QVBoxLayout(products_tab)
        self.transfer = TransferPanel(ctx, go_pending)
        self.tabs.addTab(general_tab, t("settings.tab_general"))
        self.tabs.addTab(products_tab, t("settings.learned_title"))  # the product list: Tra cứu
        self.tabs.addTab(self.transfer, t("settings.tab_transfer"))
        self.cloud = CloudTab(ctx)
        self.tabs.addTab(self.cloud, t("settings.tab_cloud"))
        company_tab = QWidget()  # a tab of its own: in 'Chung' it pushed the other boxes off the screen
        company_lay = QVBoxLayout(company_tab)
        company_lay.addWidget(self._company_box())
        company_lay.addStretch()
        self.tabs.addTab(company_tab, t("company.title"))

        general = QGroupBox(t("settings.general"))
        form = QFormLayout(general)
        self.language = QComboBox()
        for code, name in LANGUAGES.items():
            self.language.addItem(name, code)
        self.language.setCurrentIndex(self.language.findData(ctx.cfg.language))
        self.language.currentIndexChanged.connect(self.change_language)
        form.addRow(t("settings.language") + ":", self.language)
        self.scale = QComboBox()
        for pct in SCALES:
            self.scale.addItem(f"{pct}%", pct / 100)
        current = self.scale.findData(ctx.cfg.ui_scale)
        if current < 0:
            self.scale.addItem(f"{round(ctx.cfg.ui_scale * 100)}%", ctx.cfg.ui_scale)
            current = self.scale.count() - 1
        self.scale.setCurrentIndex(current)
        self.scale.currentIndexChanged.connect(self.change_scale)
        form.addRow(t("settings.ui_scale") + ":", self.scale)
        # a newer version: looked for when the app opens (per machine), or on demand (ui/updater.py)
        update_row = QHBoxLayout()
        self.check_updates = QCheckBox(t("update.auto"))
        self.check_updates.setChecked(bool(getattr(ctx.cfg, "check_updates", True)))
        self.check_updates.toggled.connect(self.set_check_updates)
        update_now = QPushButton(t("update.check_now"))
        update_now.clicked.connect(self.check_update_now)
        update_row.addWidget(self.check_updates)
        update_row.addWidget(update_now)
        update_row.addStretch()
        form.addRow(t("update.row") + ":", update_row)

        folder_row = QHBoxLayout()
        self.folder = QLabel(str(ctx.ws.root))
        self.folder.setTextInteractionFlags(Qt.TextSelectableByMouse)
        open_btn = QPushButton(t("settings.open_folder"))
        open_btn.clicked.connect(lambda: open_path(ctx.ws.root))
        change_btn = QPushButton(t("settings.change_folder"))
        change_btn.clicked.connect(self.change_folder)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(open_btn)
        folder_row.addWidget(change_btn)
        form.addRow(t("settings.workspace") + ":", folder_row)
        form.addRow(t("settings.device") + ":", QLabel(ctx.cfg.device_name))
        # the activity log is hidden: 3 clicks on the version number show a small button for it
        version_row = QHBoxLayout()
        self.version = TripleClickLabel(__version__)
        self.log_btn = QPushButton(t("log.button"))
        self.log_btn.setFlat(True)
        self.log_btn.setVisible(False)
        self.log_btn.clicked.connect(lambda: LogDialog(self.ctx, self).exec())
        self.version.revealed.connect(lambda: self.log_btn.setVisible(True))
        version_row.addWidget(self.version)
        version_row.addWidget(self.log_btn)
        licenses = QPushButton(t("license.button"))
        licenses.clicked.connect(lambda: LicenseDialog(self).exec())
        version_row.addWidget(licenses)
        version_row.addStretch()
        form.addRow(t("settings.version") + ":", version_row)
        general_lay.addWidget(general)

        learned = QGroupBox(t("settings.learned_title"))
        lay = QVBoxLayout(learned)
        lay.addWidget(hint_label(t("settings.learned_hint")))
        # grouped by order: click an order to see its lines, then forget a wrong choice or keep it
        self.learned = QTreeWidget()
        self.learned.setColumnCount(4)
        self.learned.setHeaderLabels([t("settings.learned_order"), t("col.qty"), t("settings.learned_as"), ""])
        self.learned.setAlternatingRowColors(True)
        self.learned.header().setSectionResizeMode(QHeaderView.Interactive)
        self.learned.header().setStretchLastSection(False)
        self.learned.setContextMenuPolicy(Qt.CustomContextMenu)
        self.learned.customContextMenuRequested.connect(self._learned_context_menu)
        lay.addWidget(self.learned)
        products_lay.addWidget(learned, 1)

        reset_box = QGroupBox(t("reset.title"))
        lay = QVBoxLayout(reset_box)
        lay.addWidget(hint_label(t("reset.hint")))
        row = QHBoxLayout()
        reset_stock = QPushButton(t("reset.stock"))
        reset_stock.clicked.connect(self.reset_stock)
        reset_all = QPushButton(t("reset.all"))
        reset_all.clicked.connect(self.reset_all)
        row.addWidget(reset_stock)
        row.addWidget(reset_all)
        row.addStretch()
        lay.addLayout(row)
        general_lay.addWidget(reset_box)

        danger = QGroupBox(t("settings.uninstall_title"))
        lay = QHBoxLayout(danger)
        lay.addWidget(hint_label(t("settings.uninstall_hint")), 1)
        uninstall = QPushButton(t("settings.uninstall"))
        uninstall.clicked.connect(self.uninstall)
        lay.addWidget(uninstall)
        general_lay.addWidget(danger)
        general_lay.addStretch()

    def _company_box(self) -> QGroupBox:
        """'Thông tin công ty': the lines printed on top of the stock issue notes (user, 27/11/2026). A staff account
        only reads them: they are the shared data of the shop."""
        box = QGroupBox(t("company.title"))
        lay = QVBoxLayout(box)
        lay.addWidget(hint_label(t("company.hint")))
        form = QFormLayout()
        self.company_name, self.company_address = QPlainTextEdit(), QPlainTextEdit()
        staff = approval.is_staff(self.ctx.cfg)
        for field, label in ((self.company_name, "company.name"), (self.company_address, "company.address")):
            field.setTabChangesFocus(True)
            field.setFixedHeight(field.fontMetrics().lineSpacing() * 2 + 16)  # two rows: Chinese above Vietnamese
            field.setReadOnly(staff)
            form.addRow(t(label) + ":", field)
        lay.addLayout(form)
        row = QHBoxLayout()
        self.company_save = QPushButton(t("company.save"))
        self.company_save.clicked.connect(self.save_company)
        self.company_save.setEnabled(not staff)
        row.addWidget(self.company_save)
        row.addStretch()
        lay.addLayout(row)
        return box

    def _fill_company(self):
        lines = (deliveries.letterhead(self.ctx.conn) + ["", ""])[:2]
        for field, text in zip((self.company_name, self.company_address), lines):
            if not field.document().isModified():  # never over what is being typed
                field.setPlainText(text)

    def save_company(self):
        deliveries.set_letterhead(self.ctx.conn, self.company_name.toPlainText(), self.company_address.toPlainText())
        for field in (self.company_name, self.company_address):
            field.document().setModified(False)
        self.ctx.log_action("company")
        self.ctx.notify()
        self._fill_company()
        info(self, t("company.saved"))

    def refresh(self):
        self._fill_company()
        names = {p["id"]: catalog.long_label(p) for p in catalog.products(self.ctx.conn, include_inactive=True)}
        self._fill_learned(names)
        self.transfer.refresh()

    def _fill_learned(self, names):
        expanded = {self.learned.topLevelItem(i).data(0, Qt.UserRole) for i in range(self.learned.topLevelItemCount())
                    if self.learned.topLevelItem(i).isExpanded()}
        self.learned.clear()
        for order in deliveries.learned_by_order(self.ctx.conn, self.ctx.ws):
            if order.doc_id is None:
                title = t("settings.learned_no_order", count=len(order.lines))
            else:
                title = t("settings.learned_order_title", code=order.code, date=fmt_date(order.doc_date),
                          customer=order.customer or "—", count=len(order.lines))
            head = QTreeWidgetItem([title])
            head.setData(0, Qt.UserRole, order.doc_id or 0)
            self.learned.addTopLevelItem(head)
            head.setFirstColumnSpanned(True)
            for ln in order.lines:
                item = QTreeWidgetItem([ln.label, fmt_qty(ln.qty) if ln.qty else "",
                                        names.get(ln.product_id, "") if ln.product_id else t("pending.skip_short")])
                item.setToolTip(0, ln.label)
                item.setToolTip(2, item.text(2))
                head.addChild(item)
                button = QPushButton(t("settings.forget"))
                button.clicked.connect(lambda _=False, line=ln: self.forget(line))
                self.learned.setItemWidget(item, 3, button)
            head.setExpanded(head.data(0, Qt.UserRole) in expanded)  # collapsed: click an order to open it
        for col, width in ((0, 420), (1, 60), (2, 360), (3, 170)):
            self.learned.setColumnWidth(col, width)

    def _learned_context_menu(self, pos):
        item = self.learned.itemAt(pos)
        if item is None or item.parent() is not None:  # a line, not an order heading
            return
        doc_id = item.data(0, Qt.UserRole)
        if not doc_id:  # the 'names learned but no longer in any order' heading
            return
        menu = QMenu(self)
        menu.addAction(t("btn.reread_doc"), lambda: self._reread_order(doc_id))
        menu.exec(self.learned.viewport().mapToGlobal(pos))

    def _reread_order(self, doc_id):
        if reread_whole_note(self.ctx, self, doc_id):
            self.refresh()

    def forget(self, line):
        orders = [r[0] for r in self.ctx.conn.execute(
            f"SELECT code FROM documents WHERE id IN ({','.join('?' * len(line.documents))}) ORDER BY doc_date",
            line.documents)] if line.documents else []
        if not ask(self, t("settings.confirm_forget", name=line.label, docs=len(orders),
                           orders=", ".join(orders) or "—")):
            return
        activity.log("forget", line.label)
        self.ctx.log_action("forget")
        try:
            count = deliveries.forget_name(self.ctx.conn, self.ctx.ws, line.key)
            deliveries.scan(self.ctx.conn, self.ctx.ws)
        except Exception as exc:
            error(self, str(exc))
            return
        self.ctx.notify()
        info(self, t("settings.forgotten", docs=count))

    def change_language(self):
        self.ctx.cfg.language = self.language.currentData()
        self.ctx.cfg.save()
        info(self, t("settings.restart_needed"))

    def reset_stock(self):
        if approval.is_staff(self.ctx.cfg):  # it would rewrite every document of the shared data
            error(self, t("staff.not_for_staff"))
            return
        if not ask(self, t("reset.confirm_stock")):
            return
        self.ctx.log_action("reset")
        try:
            moved = reset.reset_stock(self.ctx.conn, self.ctx.ws)
        except Exception as exc:
            error(self, str(exc))
            return
        self.ctx.notify()
        info(self, t("reset.done_stock", files=moved))
        self.go_pending()  # notes are read again: what is known is recorded, the rest waits here

    def reset_all(self):
        if approval.is_staff(self.ctx.cfg):
            error(self, t("staff.not_for_staff"))
            return
        if not ask(self, t("reset.confirm_all")) or not ask(self, t("reset.confirm_all_again")):
            return
        if replica.enabled(self.ctx.conn):  # shared data: the cloud is emptied first, for every machine and the web
            def build(folder):
                new = folder / "kho.sqlite"
                c = db.connect(new)  # a new, empty database
                c.close()
                return new
            if replace_shared_data(self.ctx, self, build, t("admin.what_delete_all")):
                moved = reset.clear_files(self.ctx.ws)
                info(self, t("reset.done_all", files=moved))
                self.go_pending()
            return
        try:
            moved = reset.reset_all(self.ctx.conn, self.ctx.ws)
            self.ctx.close()
            reset.wipe_database(self.ctx.ws)
        except Exception as exc:
            error(self, str(exc))
            return
        finally:
            self.ctx.reopen()  # a new, empty database
        info(self, t("reset.done_all", files=moved))
        self.go_pending()

    def set_check_updates(self, on: bool):
        self.ctx.cfg.check_updates = bool(on)
        self.ctx.cfg.save()

    def check_update_now(self):
        from dibekho.ui import updater

        updater.check_now(self, self.window())

    def change_scale(self):
        self.ctx.cfg.ui_scale = self.scale.currentData()
        self.ctx.cfg.save()
        info(self, t("settings.restart_needed"))

    def change_folder(self):
        path = QFileDialog.getExistingDirectory(self, t("settings.change_folder"), str(self.ctx.ws.root.parent))
        if not path:
            return
        if ask(self, t("settings.confirm_folder", path=path)):
            self.ctx.cfg.workspace = path
            self.ctx.cfg.save()
            info(self, t("settings.restart_needed"))

    def uninstall(self):
        if not ask(self, t("settings.confirm_uninstall")):
            return
        delete_data = ask(self, t("settings.confirm_delete_data", path=str(self.ctx.ws.root)))
        root = self.ctx.ws.root
        self.ctx.close()
        Config.remove()
        if delete_data:
            shutil.rmtree(root, ignore_errors=True)
        bundle = uninstall.mac_bundle()
        if bundle is not None and uninstall.can_remove(bundle):
            uninstall.schedule_bundle_removal(bundle)  # DiBeKho.app disappears from Applications once we quit
            hint = t("settings.uninstall_done_mac_auto", path=str(bundle))
        elif sys.platform == "darwin":
            hint = t("settings.uninstall_done_mac")
        else:
            hint = t("settings.uninstall_done_win")
        info(self, hint)
        QApplication.quit()
