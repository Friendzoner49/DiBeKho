"""Import the product catalog from the customer's monthly stock sheet, with an editable preview."""

from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from dibekho.core import catalog, deliveries
from dibekho.core.text import fmt_qty, parse_number
from dibekho.excel.catalog_sheet import CatalogItem, NotCatalogSheet, read_catalog, sheet_columns
from dibekho.i18n import t
from dibekho.ui.common import (
    GREY,
    error,
    fill_table,
    fit_window,
    from_qdate,
    hint_label,
    info,
    make_table,
    to_qdate,
)

# editable columns -> CatalogItem field
FIELDS = ("name_vi", "name_zh", "spec", "variant", "unit", "category")
STOCK, STATUS = len(FIELDS) + 1, len(FIELDS) + 2


class CatalogImportDialog(QDialog):
    def __init__(self, ctx, path: Path, items: list[CatalogItem], parent=None):
        super().__init__(parent)
        self.ctx, self.path = ctx, path
        self.setWindowTitle(t("catalog.title", file=path.name))
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        fit_window(self, 1200, 720)
        lay = QVBoxLayout(self)
        lay.addWidget(hint_label(t("catalog.hint")))

        self.table = make_table([t("catalog.row"), t("col.product"), t("col.name_zh"), t("col.spec"),
                                 t("col.variant"), t("col.unit"), t("col.category"), t("catalog.col_stock"),
                                 t("col.status")], stretch=1)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                   | QAbstractItemView.AnyKeyPressed)
        rows, exists = [], []
        for it in items:
            same = catalog.find_same(ctx.conn, it.name_vi, it.spec, it.variant)
            exists.append(same is not None)
            rows.append([str(it.row), it.name_vi, it.name_zh, it.spec, it.variant, it.unit, it.category,
                         fmt_qty(it.stock), t("catalog.exists") if same else t("catalog.new")])
        fill_table(self.table, rows)
        self.table.setSortingEnabled(False)
        for r, already in enumerate(exists):
            first = self.table.item(r, 0)
            first.setFlags((first.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
            first.setCheckState(Qt.Unchecked if already else Qt.Checked)
            status = self.table.item(r, STATUS)
            status.setFlags(status.flags() & ~Qt.ItemIsEditable)
            self.table.item(r, STOCK).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if already:
                for c in range(self.table.columnCount()):
                    self.table.item(r, c).setForeground(GREY)
        # long names: narrower name columns so the stock column stays in view (hover or drag to read more)
        for col, width in ((1, 330), (2, 230)):
            self.table.setColumnWidth(col, min(self.table.columnWidth(col), width))
        lay.addWidget(self.table)

        row = QHBoxLayout()
        for text, state in ((t("catalog.check_all"), Qt.Checked), (t("catalog.check_none"), Qt.Unchecked)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, s=state: self._check_all(s))
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

        # the sheet's stock (column F) becomes the app's stock on the chosen date, as a stock count
        has_stock = any(it.stock is not None for it in items)
        stock_row = QHBoxLayout()
        self.use_stock = QCheckBox(t("catalog.use_stock"))
        self.use_stock.setChecked(has_stock)
        self.use_stock.setEnabled(has_stock)
        self.stock_date = QDateEdit(to_qdate(date.today()))
        self.stock_date.setCalendarPopup(True)
        self.stock_date.setDisplayFormat("dd/MM/yyyy")
        self.use_stock.toggled.connect(self.stock_date.setEnabled)
        self.stock_date.setEnabled(has_stock)
        stock_row.addWidget(self.use_stock)
        stock_row.addWidget(self.stock_date)
        stock_row.addStretch()
        lay.addLayout(stock_row)
        lay.addWidget(hint_label(t("catalog.stock_hint")))

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
                result.append(CatalogItem(row=int(self.table.item(r, 0).text()), stock=self._stock(r), **values))
        return result

    def _stock(self, r) -> float | None:
        text = self.table.item(r, STOCK).text().strip()
        try:
            return parse_number(text) if text else None
        except ValueError:
            return None

    def do_import(self):
        items = self.selected_items()
        if not items:
            error(self, t("catalog.nothing"))
            return
        stock_date = from_qdate(self.stock_date.date()) if self.use_stock.isChecked() else None
        if stock_date is not None:
            # notes up to that date must be in the ledger first, or they would be subtracted from the count later
            deliveries.scan(self.ctx.conn, self.ctx.ws)
        created, skipped, counted = catalog.import_catalog(self.ctx.conn, items, stock_date,
                                                           t("catalog.stock_note", file=self.path.name))
        self.ctx.notify()
        text = t("catalog.done", created=created, skipped=skipped)
        if counted:
            text += "\n\n" + t("catalog.stock_done", count=counted, date=self.stock_date.text())
        info(self, text)
        self.accept()


class StockColumnDialog(QDialog):
    """The sheet has no 'remaining stock' column we recognise: let the user point at it."""

    def __init__(self, path: Path, columns, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("catalog.pick_stock_title"))
        fit_window(self, 640, 460)
        lay = QVBoxLayout(self)
        hint = QLabel(t("catalog.pick_stock_hint", file=path.name))
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.list = QListWidget()
        none = QListWidgetItem(t("catalog.pick_stock_none"))
        none.setData(Qt.UserRole, None)
        self.list.addItem(none)
        for c in columns:
            text = t("catalog.pick_stock_column", letter=c.letter, label=c.label or "—")
            samples = ", ".join(s for s in c.samples if s)
            if samples:
                text += "   " + t("catalog.pick_stock_samples", samples=samples)
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, c.col)
            self.list.addItem(item)
        self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        lay.addWidget(self.list, 1)
        box = QDialogButtonBox()
        box.addButton(t("catalog.pick_stock_continue"), QDialogButtonBox.AcceptRole)
        box.addButton(t("btn.cancel"), QDialogButtonBox.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def chosen(self) -> int | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None


def ask_stock_column(parent, path: Path, columns) -> tuple[bool, int | None]:
    """(go on?, chosen column or None = no stock). Separate function so tests can replace it."""
    dlg = StockColumnDialog(path, columns, parent)
    if dlg.exec() != QDialog.Accepted:
        return False, None
    return True, dlg.chosen()


def import_catalog_file(ctx, parent, path: Path, items: list[CatalogItem] | None = None) -> bool:
    """Preview and import the catalog sheet at path. Returns True if the user imported it.
    When the stock column cannot be found by its label, the user picks it first."""
    try:
        found = sheet_columns(path)
        if found.stock_col is None:
            go_on, col = ask_stock_column(parent, Path(path), found.columns)
            if not go_on:
                return False
            items = read_catalog(path, col)
        elif items is None:
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

