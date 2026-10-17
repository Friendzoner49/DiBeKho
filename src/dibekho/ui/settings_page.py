"""'Cài đặt': language, workspace folder, product catalog, lines that are not goods, data transfer, uninstall."""

import shutil
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dibekho import __version__, db
from dibekho.core import catalog, deliveries, reset, uninstall
from dibekho.core.text import fmt_qty
from dibekho.core.workspace import Config
from dibekho.i18n import LANGUAGES, t
from dibekho.ui.catalog_import import start_catalog_import
from dibekho.ui.common import (
    GREY,
    ask,
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
    selected_id,
)
from dibekho.ui.page import Page
from dibekho.ui.transfer_page import TransferPanel


SCALES = (100, 110, 120, 130, 140, 150)  # interface size choices, in %


class ProductEditor(QDialog):
    def __init__(self, ctx, product=None, parent=None):
        super().__init__(parent)
        self.ctx, self.product = ctx, product
        self.setWindowTitle(t("settings.edit_product") if product else t("settings.add_product"))
        fit_window(self, 760, 360)
        form = QFormLayout(self)
        self.name_vi, self.name_zh, self.spec, self.unit = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.variant = QLineEdit()
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.addItems([""] + catalog.categories(ctx.conn))
        self.min_stock = QDoubleSpinBox()
        self.min_stock.setRange(0, 1e6)
        self.min_stock.setDecimals(0)
        self.active = QCheckBox(t("settings.active"))
        self.active.setChecked(True)
        for box in (self.name_vi, self.name_zh, self.spec, self.variant, self.unit, self.category):
            box.setMinimumWidth(520)  # a long name stays visible while typing
        if product:
            self.name_vi.setText(product["name_vi"])
            self.name_zh.setText(product["name_zh"])
            self.spec.setText(product["spec"])
            self.variant.setText(product["variant"])
            self.unit.setText(product["unit"])
            self.category.setCurrentText(product["category"])
            self.min_stock.setValue(product["min_stock"])
            self.active.setChecked(bool(product["active"]))
            form.addRow(t("col.code") + ":", QLabel(product["code"]))
        form.addRow(t("col.product") + ":", self.name_vi)
        form.addRow(t("col.name_zh") + ":", self.name_zh)
        form.addRow(t("col.spec") + ":", self.spec)
        form.addRow(t("col.variant") + ":", self.variant)
        form.addRow(t("col.unit") + ":", self.unit)
        form.addRow(t("col.category") + ":", self.category)
        form.addRow(t("col.min_stock") + ":", self.min_stock)
        form.addRow("", self.active)
        form.addRow(hint_label(t("settings.min_stock_hint")))
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setText(t("btn.save"))
        box.button(QDialogButtonBox.Cancel).setText(t("btn.cancel"))
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def fields(self) -> dict:
        return dict(name_vi=self.name_vi.text().strip(), name_zh=self.name_zh.text().strip(),
                    spec=self.spec.text().strip(), variant=self.variant.text().strip(), unit=self.unit.text().strip(),
                    category=self.category.currentText().strip(), min_stock=self.min_stock.value())

    def save(self):
        if not self.name_vi.text().strip():
            self.name_vi.setFocus()
            return
        fields = self.fields()
        self.ctx.undo_point("product_edit" if self.product else "product_add")
        with db.transaction(self.ctx.conn):
            if self.product:
                catalog.update_product(self.ctx.conn, self.product["id"], active=int(self.active.isChecked()),
                                       **fields)
            else:
                catalog.create_product(self.ctx.conn, **fields)
        self.accept()


class SettingsPage(Page):
    def __init__(self, ctx, go_pending=lambda: None):
        super().__init__(ctx, t("nav.settings"))
        self.go_pending = go_pending
        self.tabs = QTabWidget()
        self.layout_.addWidget(self.tabs, 1)
        general_tab, products_tab = QWidget(), QWidget()
        general_lay, products_lay = QVBoxLayout(general_tab), QVBoxLayout(products_tab)
        self.transfer = TransferPanel(ctx, go_pending)
        self.tabs.addTab(general_tab, t("settings.tab_general"))
        self.tabs.addTab(products_tab, t("settings.tab_products"))
        self.tabs.addTab(self.transfer, t("settings.tab_transfer"))

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
        form.addRow(t("settings.version") + ":", QLabel(__version__))
        general_lay.addWidget(general)

        products = QGroupBox(t("settings.products"))
        lay = QVBoxLayout(products)
        lay.addWidget(hint_label(t("settings.products_hint")))
        self.table = make_table([t("col.code"), t("col.product"), t("col.name_zh"), t("col.spec"), t("col.variant"),
                                 t("col.unit"), t("col.category"), t("col.min_stock"), t("settings.active")], stretch=1)
        self.table.doubleClicked.connect(lambda idx: self.edit(row_id(self.table, idx.row())))
        lay.addWidget(self.table)
        row = QHBoxLayout()
        add = QPushButton(t("settings.add_product"))
        add.clicked.connect(lambda: self.edit(None))
        row.addWidget(add)
        edit = QPushButton(t("settings.edit_product_btn"))
        edit.clicked.connect(self.edit_selected)
        row.addWidget(edit)
        delete = QPushButton(t("settings.delete_product"))
        delete.clicked.connect(self.delete_selected)
        row.addWidget(delete)
        import_btn = QPushButton(t("catalog.import_btn"))
        import_btn.clicked.connect(lambda: start_catalog_import(self.ctx, self))
        row.addWidget(import_btn)
        row.addStretch()
        lay.addLayout(row)
        products_lay.addWidget(products, 3)

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
        lay.addWidget(self.learned)
        products_lay.addWidget(learned, 2)

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

    def refresh(self):
        rows = catalog.products(self.ctx.conn, include_inactive=True)
        fill_table(self.table, [[p["code"], p["name_vi"], p["name_zh"], p["spec"], p["variant"], p["unit"], p["category"],
                                 num_item(p["min_stock"]), t("btn.yes") if p["active"] else t("btn.no")]
                                for p in rows],
                   ids=[p["id"] for p in rows])
        for r, p in enumerate(rows):
            if not p["active"]:
                for c in range(self.table.columnCount()):
                    self.table.item(r, c).setForeground(GREY)
        self._fill_learned({p["id"]: catalog.long_label(p) for p in rows})
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

    def forget(self, line):
        orders = [r[0] for r in self.ctx.conn.execute(
            f"SELECT code FROM documents WHERE id IN ({','.join('?' * len(line.documents))}) ORDER BY doc_date",
            line.documents)] if line.documents else []
        if not ask(self, t("settings.confirm_forget", name=line.label, docs=len(orders),
                           orders=", ".join(orders) or "—")):
            return
        self.ctx.undo_point("forget")
        try:
            count = deliveries.forget_name(self.ctx.conn, self.ctx.ws, line.key)
            deliveries.scan(self.ctx.conn, self.ctx.ws)
        except Exception as exc:
            error(self, str(exc))
            return
        self.ctx.notify()
        info(self, t("settings.forgotten", docs=count))

    def edit_selected(self):
        product_id = selected_id(self.table)
        if product_id is None:
            error(self, t("settings.pick_first"))
            return
        self.edit(product_id)

    def delete_selected(self):
        product_id = selected_id(self.table)
        if product_id is None:
            error(self, t("settings.pick_first"))
            return
        conn = self.ctx.conn
        p = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        used = catalog.product_documents(conn, product_id)
        if used:  # deleting would break the history and the stock of those documents
            if not p["active"]:
                error(self, t("settings.delete_used_inactive", name=catalog.label(p), docs=used))
            elif ask(self, t("settings.delete_used", name=catalog.label(p), docs=used)):
                self.ctx.undo_point("product_edit")
                with db.transaction(conn):
                    catalog.update_product(conn, product_id, active=0)
                self.ctx.notify()
            return
        if not ask(self, t("settings.confirm_delete_product", name=catalog.label(p))):
            return
        self.ctx.undo_point("product_delete")
        with db.transaction(conn):
            catalog.delete_product(conn, product_id)
            db.log(conn, "product_deleted", catalog.label(p))
        self.ctx.notify()

    def edit(self, product_id):
        product = None
        if product_id:
            product = self.ctx.conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if ProductEditor(self.ctx, product, self).exec() == QDialog.Accepted:
            self.ctx.notify()

    def change_language(self):
        self.ctx.cfg.language = self.language.currentData()
        self.ctx.cfg.save()
        info(self, t("settings.restart_needed"))

    def reset_stock(self):
        if not ask(self, t("reset.confirm_stock")):
            return
        self.ctx.undo_point("reset")
        try:
            moved = reset.reset_stock(self.ctx.conn, self.ctx.ws)
        except Exception as exc:
            error(self, str(exc))
            return
        self.ctx.notify()
        info(self, t("reset.done_stock", files=moved))
        self.go_pending()  # notes are read again: what is known is recorded, the rest waits here

    def reset_all(self):
        if not ask(self, t("reset.confirm_all")) or not ask(self, t("reset.confirm_all_again")):
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
