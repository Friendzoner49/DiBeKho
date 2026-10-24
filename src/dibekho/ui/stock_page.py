from PySide6.QtWidgets import QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton

from dibekho.core import catalog
from dibekho.core.stock import is_low, low_stock_default, stock_table
from dibekho.core.text import fmt_qty, unaccent
from dibekho.i18n import t
from dibekho.ui.catalog_import import start_catalog_import
from dibekho.ui.common import (
    ORANGE,
    RED,
    date_item,
    fill_table,
    make_table,
    num_item,
    only_editable,
    row_id,
    save_stock_note,
    theme_color,
)
from dibekho.ui.details import ProductDialog
from dibekho.ui.page import Page

ALARM, NOTE = 8, 9  # the stock note column: typed in here or on the Kiểm kê page


class StockPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, t("nav.stock"), t("stock.hint"))
        bar = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(t("stock.filter"))
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self.refresh)
        self.category = QComboBox()
        self.category.currentIndexChanged.connect(self.refresh)
        self.only_low = QCheckBox(t("stock.only_low"))
        self.only_low.toggled.connect(self.refresh)
        bar.addWidget(self.filter, 3)
        bar.addWidget(QLabel(t("col.category") + ":"))
        bar.addWidget(self.category, 1)
        bar.addWidget(self.only_low)
        self.layout_.addLayout(bar)

        # shown only while the catalog is empty (first start)
        self.empty = QFrame()
        self.empty.setStyleSheet(f"QFrame {{ background: {theme_color('banner')}; border-radius: 6px; }}")
        empty_lay = QHBoxLayout(self.empty)
        empty_text = QLabel(t("stock.empty_hint"))
        empty_text.setWordWrap(True)
        empty_lay.addWidget(empty_text, 1)
        empty_btn = QPushButton(t("catalog.import_btn"))
        empty_btn.clicked.connect(lambda: start_catalog_import(self.ctx, self))
        empty_lay.addWidget(empty_btn)
        self.layout_.addWidget(self.empty)

        # products running low: order more
        self.alarm = QLabel()
        self.alarm.setWordWrap(True)
        self.alarm.setStyleSheet(f"QLabel {{ background: {ORANGE.name()}; color: {theme_color('warn')}; "
                                 "font-weight: bold; border-radius: 6px; padding: 6px; }}")
        self.layout_.addWidget(self.alarm)

        self.summary = QLabel()
        self.layout_.addWidget(self.summary)
        self.table = make_table([t("col.code"), t("col.product"), t("col.spec"), t("col.variant"), t("col.stock"),
                                 t("loc.main"), t("loc.office"), t("col.unit"), t("col.alarm"), t("col.stock_note"),
                                 t("col.name_zh"), t("col.min_stock"), t("col.category"), t("col.last_out")],
                                stretch=1)
        self.table.doubleClicked.connect(self._open)
        self.table.itemChanged.connect(self._note_edited)
        self.layout_.addWidget(self.table)

    def refresh(self):
        current = self.category.currentData()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem(t("filter.all"), None)
        for c in catalog.categories(self.ctx.conn):
            self.category.addItem(c, c)
        idx = self.category.findData(current)
        self.category.setCurrentIndex(max(idx, 0))
        self.category.blockSignals(False)

        needle = unaccent(self.filter.text().strip())
        category = self.category.currentData()
        default = low_stock_default(self.ctx.conn)
        rows, ids, colors = [], [], []
        low = negative = 0
        for p in stock_table(self.ctx.conn):
            if category and p["category"] != category:
                continue
            haystack = unaccent(f"{p['code']} {p['name_vi']} {p['name_zh']} {p['spec']} {p['variant']}")
            if needle and needle not in haystack:
                continue
            color, alarm = None, ""
            if p["stock"] < 0:
                color, alarm, negative = RED, t("stock.alarm_negative"), negative + 1
            elif is_low(p["stock"], p["min_stock"], default):
                color, alarm, low = ORANGE, t("stock.alarm_low"), low + 1
            if self.only_low.isChecked() and color is None:
                continue
            rows.append([p["code"], p["name_vi"], p["spec"], p["variant"], num_item(p["stock"]),
                         num_item(p["stock_main"]), num_item(p["stock_office"]), p["unit"], alarm, p["stock_note"],
                         p["name_zh"], num_item(p["min_stock"] or default or None), p["category"],
                         date_item(p["last_out"])])
            ids.append(p["id"])
            colors.append(color)
        self.table.blockSignals(True)
        fill_table(self.table, rows, ids=ids, colors=colors)
        only_editable(self.table, {NOTE})
        self.table.setColumnWidth(NOTE, min(max(self.table.columnWidth(NOTE), 140), 260))  # long notes: hover
        self.table.fill_spare()
        self.table.blockSignals(False)
        self.empty.setVisible(not catalog.products(self.ctx.conn, include_inactive=True))
        self.alarm.setText(t("stock.alarm_banner", count=low, level=fmt_qty(default)))
        self.alarm.setVisible(bool(low))
        self.summary.setText(t("stock.summary", count=len(rows), low=low, negative=negative))

    def _open(self, idx):
        if idx.column() != NOTE:  # the note cell is typed into instead
            ProductDialog(self.ctx, row_id(self.table, idx.row()), self).exec()

    def _note_edited(self, item):
        if item.column() == NOTE:
            save_stock_note(self.ctx, row_id(self.table, item.row()), item.text())
