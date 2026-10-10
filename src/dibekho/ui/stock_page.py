from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton

from dibekho.core import catalog
from dibekho.core.stock import stock_table
from dibekho.core.text import unaccent
from dibekho.i18n import t
from dibekho.ui.catalog_import import start_catalog_import
from dibekho.ui.common import RED, YELLOW, date_item, fill_table, make_table, num_item, row_id, theme_color
from dibekho.ui.details import ProductDialog
from dibekho.ui.page import Page


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
        bar.addWidget(self.filter, 3)
        bar.addWidget(QLabel(t("col.category") + ":"))
        bar.addWidget(self.category, 1)
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

        self.summary = QLabel()
        self.layout_.addWidget(self.summary)
        self.table = make_table([t("col.code"), t("col.product"), t("col.name_zh"), t("col.spec"), t("col.variant"),
                                 t("col.stock"),                                 t("col.unit"), t("col.min_stock"), t("col.category"), t("col.last_out")], stretch=1)
        self.table.doubleClicked.connect(
            lambda idx: ProductDialog(self.ctx, row_id(self.table, idx.row()), self).exec())
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
        rows, ids, colors = [], [], []
        low = negative = 0
        for p in stock_table(self.ctx.conn):
            if category and p["category"] != category:
                continue
            haystack = unaccent(f"{p['code']} {p['name_vi']} {p['name_zh']} {p['spec']} {p['variant']}")
            if needle and needle not in haystack:
                continue
            color = None
            if p["stock"] < 0:
                color, negative = RED, negative + 1
            elif p["min_stock"] and p["stock"] <= p["min_stock"]:
                color, low = YELLOW, low + 1
            rows.append([p["code"], p["name_vi"], p["name_zh"], p["spec"], p["variant"], num_item(p["stock"]),
                         p["unit"],                         num_item(p["min_stock"] or None), p["category"], date_item(p["last_out"])])
            ids.append(p["id"])
            colors.append(color)
        fill_table(self.table, rows, ids=ids, colors=colors)
        self.empty.setVisible(not catalog.products(self.ctx.conn, include_inactive=True))
        self.summary.setText(t("stock.summary", count=len(rows), low=low, negative=negative))
