"""Tra cứu → Danh mục mặt hàng: the product list (add, edit, delete, merge, import) and the low-stock alarm level.
It was a box in Cài đặt, where it showed few rows; it fills a tab of Tra cứu since 21/11/2026 (the owner, as the Mac app)."""

from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dibekho import db
from dibekho.core import catalog
from dibekho.core.stock import low_stock_default
from dibekho.core.text import fmt_qty
from dibekho.i18n import t
from dibekho.ui.catalog_import import start_catalog_import
from dibekho.ui.common import (
    GREY,
    NoWheelSpin,
    ask,
    error,
    fill_table,
    fit_window,
    hint_label,
    info,
    make_table,
    row_id,
    selected_id,
)


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
            self.active.setChecked(bool(product["active"]))
            form.addRow(t("col.code") + ":", QLabel(product["code"]))
        form.addRow(t("col.product") + ":", self.name_vi)
        form.addRow(t("col.name_zh") + ":", self.name_zh)
        form.addRow(t("col.spec") + ":", self.spec)
        form.addRow(t("col.variant") + ":", self.variant)
        form.addRow(t("col.unit") + ":", self.unit)
        form.addRow(t("col.category") + ":", self.category)
        form.addRow("", self.active)
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setText(t("btn.save"))
        box.button(QDialogButtonBox.Cancel).setText(t("btn.cancel"))
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def fields(self) -> dict:
        return dict(name_vi=self.name_vi.text().strip(), name_zh=self.name_zh.text().strip(),
                    spec=self.spec.text().strip(), variant=self.variant.text().strip(), unit=self.unit.text().strip(),
                    category=self.category.currentText().strip())

    def save(self):
        if not self.name_vi.text().strip():
            self.name_vi.setFocus()
            return
        fields = self.fields()
        if self.product is None:
            dups = catalog.find_possible_duplicates(self.ctx.conn, fields["name_vi"], fields["name_zh"],
                                                     fields["spec"], fields["variant"])
            if dups and ask(self, t("settings.product_duplicate", code=dups[0]["code"],
                                    product=catalog.long_label(dups[0]))):
                self.accept()
                ProductEditor(self.ctx, dups[0], self.parent()).exec()
                return
        self.ctx.log_action("product_edit" if self.product else "product_add")
        with db.transaction(self.ctx.conn):
            if self.product:
                catalog.update_product(self.ctx.conn, self.product["id"], active=int(self.active.isChecked()),
                                       **fields)
            else:
                catalog.create_product(self.ctx.conn, **fields)
        self.accept()


class CatalogPanel(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        alarm_row = QHBoxLayout()
        alarm_row.addWidget(QLabel(t("settings.low_default") + ":"))
        self.low_default = NoWheelSpin()
        self.low_default.setRange(0, 1e6)
        self.low_default.setDecimals(0)
        self.low_default.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.low_default.setValue(low_stock_default(ctx.conn))
        self.low_default.editingFinished.connect(self.change_low_default)
        alarm_row.addWidget(self.low_default)
        alarm_row.addWidget(hint_label(t("settings.low_default_hint")), 1)
        lay.addLayout(alarm_row)
        self.table = make_table([t("col.code"), t("col.product"), t("col.name_zh"), t("col.spec"), t("col.variant"),
                                 t("col.unit"), t("col.category"), t("settings.active")], stretch=1)
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
        merge = QPushButton(t("settings.merge_button"))
        merge.setToolTip(t("settings.merge_tip"))
        merge.clicked.connect(self.merge_selected)
        row.addWidget(merge)
        import_btn = QPushButton(t("catalog.import_btn"))
        import_btn.clicked.connect(lambda: start_catalog_import(self.ctx, self))
        row.addWidget(import_btn)
        row.addStretch()
        lay.addLayout(row)

    def refresh(self):
        self.low_default.blockSignals(True)
        self.low_default.setValue(low_stock_default(self.ctx.conn))  # may come with a data package
        self.low_default.blockSignals(False)
        rows = catalog.products(self.ctx.conn, include_inactive=True)
        fill_table(self.table, [[p["code"], p["name_vi"], p["name_zh"], p["spec"], p["variant"], p["unit"], p["category"],
                                 t("btn.yes") if p["active"] else t("btn.no")]
                                for p in rows],
                   ids=[p["id"] for p in rows])
        for r, p in enumerate(rows):
            if not p["active"]:
                for c in range(self.table.columnCount()):
                    self.table.item(r, c).setForeground(GREY)

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
                self.ctx.log_action("product_edit")
                with db.transaction(conn):
                    catalog.update_product(conn, product_id, active=0)
                self.ctx.notify()
            return
        if not ask(self, t("settings.confirm_delete_product", name=catalog.label(p))):
            return
        self.ctx.log_action("product_delete")
        with db.transaction(conn):
            catalog.delete_product(conn, product_id)
            db.log(conn, "product_deleted", catalog.label(p))
        self.ctx.notify()

    def merge_selected(self):
        """Two products that are really one (same item typed twice): pick one in the list, then the other."""
        first_id = selected_id(self.table)
        if first_id is None:
            error(self, t("settings.merge_pick_first"))
            return
        from dibekho.ui.pending_page import ProductPicker  # here: pending_page imports this module (circular)

        conn = self.ctx.conn
        picker = ProductPicker(self.ctx, self)
        picker.setWindowTitle(t("settings.merge_pick_other"))
        other_id = picker.choose()
        if other_id is None:
            return
        if other_id == first_id:
            error(self, t("settings.merge_same"))
            return
        a = conn.execute("SELECT * FROM products WHERE id = ?", (first_id,)).fetchone()
        b = conn.execute("SELECT * FROM products WHERE id = ?", (other_id,)).fetchone()
        keep, drop = (a, b) if catalog._code_num(a["code"]) <= catalog._code_num(b["code"]) else (b, a)
        if not ask(self, t("settings.merge_confirm", keep=catalog.long_label(keep), drop=catalog.long_label(drop))):
            return
        self.ctx.log_action("product_merge")
        with db.transaction(conn):
            catalog.merge_products(conn, first_id, other_id)
            db.log(conn, "product_merged", f"{drop['code']} -> {keep['code']}")
        self.ctx.notify()
        info(self, t("settings.merge_done", keep=keep["code"], drop=drop["code"]))

    def edit(self, product_id):
        product = None
        if product_id:
            product = self.ctx.conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if ProductEditor(self.ctx, product, self).exec() == QDialog.Accepted:
            self.ctx.notify()

    def change_low_default(self):
        value = self.low_default.value()
        if abs(value - low_stock_default(self.ctx.conn)) < 1e-9:
            return
        self.ctx.log_action("low_default")
        with db.transaction(self.ctx.conn):
            db.set_meta(self.ctx.conn, "low_stock_default", str(int(value)))
            db.log(self.ctx.conn, "low_stock_default", fmt_qty(value))
        self.ctx.notify()
