"""Import the product catalog from the customer's monthly stock sheet, with an editable preview."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
)

from dibekho.core import catalog
from dibekho.excel.catalog_sheet import CatalogItem, NotCatalogSheet, read_catalog
from dibekho.i18n import t
from dibekho.ui.common import GREY, error, fill_table, hint_label, info, make_table

# editable columns -> CatalogItem field
FIELDS = ("name_vi", "name_zh", "spec", "variant", "unit", "category")


class CatalogImportDialog(QDialog):
    def __init__(self, ctx, path: Path, items: list[CatalogItem], parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(t("catalog.title", file=path.name))
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(1200, 720)
        lay = QVBoxLayout(self)
        lay.addWidget(hint_label(t("catalog.hint")))

        self.table = make_table([t("catalog.row"), t("col.product"), t("col.name_zh"), t("col.spec"),
                                 t("col.variant"), t("col.unit"), t("col.category"), t("col.status")], stretch=1)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                   | QAbstractItemView.AnyKeyPressed)
        rows, exists = [], []
        for it in items:
            same = catalog.find_same(ctx.conn, it.name_vi, it.spec, it.variant)
            exists.append(same is not None)
            rows.append([str(it.row), it.name_vi, it.name_zh, it.spec, it.variant, it.unit, it.category,
                         t("catalog.exists") if same else t("catalog.new")])
        fill_table(self.table, rows)
        self.table.setSortingEnabled(False)
        for r, already in enumerate(exists):
            first = self.table.item(r, 0)
            first.setFlags((first.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
            first.setCheckState(Qt.Unchecked if already else Qt.Checked)
            status = self.table.item(r, 7)
            status.setFlags(status.flags() & ~Qt.ItemIsEditable)
            if already:
                for c in range(self.table.columnCount()):
                    self.table.item(r, c).setForeground(GREY)
        lay.addWidget(self.table)

        row = QHBoxLayout()
        for text, state in ((t("catalog.check_all"), Qt.Checked), (t("catalog.check_none"), Qt.Unchecked)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, s=state: self._check_all(s))
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

        box = QDialogButtonBox()
        box.addButton(t("catalog.import_do"), QDialogButtonBox.AcceptRole)
        box.addButton(t("btn.cancel"), QDialogButtonBox.RejectRole)
        box.accepted.connect(self.do_import)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def _check_all(self, state):
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setCheckState(state)

    def selected_items(self) -> list[CatalogItem]:
        result = []
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).checkState() != Qt.Checked:
                continue
            values = {f: self.table.item(r, c + 1).text().strip() for c, f in enumerate(FIELDS)}
            if values["name_vi"]:
                result.append(CatalogItem(row=int(self.table.item(r, 0).text()), **values))
        return result

    def do_import(self):
        items = self.selected_items()
        if not items:
            error(self, t("catalog.nothing"))
            return
        created, skipped = catalog.import_catalog(self.ctx.conn, items)
        self.ctx.notify()
        info(self, t("catalog.done", created=created, skipped=skipped))
        self.accept()


def import_catalog_file(ctx, parent, path: Path, items: list[CatalogItem] | None = None) -> bool:
    """Preview and import the catalog sheet at path. Returns True if the user imported it."""
    if items is None:
        try:
            items = read_catalog(path)
        except NotCatalogSheet as exc:
            error(parent, t("catalog.not_sheet", error=str(exc)))
            return False
    if not items:
        error(parent, t("catalog.not_sheet", error="0"))
        return False
    return CatalogImportDialog(ctx, Path(path), items, parent).exec() == QDialog.Accepted


def start_catalog_import(ctx, parent) -> bool:
    """Ask for the Excel file, show the preview, import. Returns True if something was imported."""
    path, _ = QFileDialog.getOpenFileName(parent, t("catalog.pick_file"), str(ctx.ws.root.parent), "Excel (*.xlsx)")
    if not path:
        return False
    return import_catalog_file(ctx, parent, Path(path))

