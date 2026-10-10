"""'Kiểm kê': enter physical counts, the app records the differences."""

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDateEdit, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidgetItem

from dibekho import db
from dibekho.core import catalog
from dibekho.core.stock import stock_count, stock_levels
from dibekho.core.text import fmt_qty, parse_number
from dibekho.i18n import t
from dibekho.ui.common import RED, YELLOW, ask, error, fill_table, from_qdate, info, make_table, num_item, to_qdate
from dibekho.ui.page import Page

IN_APP_COL, COUNT_COL, DIFF_COL = 5, 6, 7


class CountPage(Page):
    def __init__(self, ctx, rescan):
        super().__init__(ctx, t("nav.count"), t("count.hint"))
        self.rescan = rescan
        bar = QHBoxLayout()
        bar.addWidget(QLabel(t("count.date")))
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd/MM/yyyy")
        self.date.setDate(to_qdate(date.today()))
        self.date.dateChanged.connect(self.refresh)
        bar.addWidget(self.date)
        bar.addWidget(QLabel(t("col.note")))
        self.note = QLineEdit()
        bar.addWidget(self.note, 1)
        self.layout_.addLayout(bar)

        self.table = make_table([t("col.code"), t("col.product"), t("col.spec"), t("col.variant"), t("col.unit"), t("count.in_app"),
                                 t("count.counted"), t("col.difference")], stretch=1)
        self.table.setEditTriggers(self.table.EditTrigger.AllEditTriggers)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectItems)
        self.table.itemChanged.connect(self._on_edit)
        self.layout_.addWidget(self.table)

        bottom = QHBoxLayout()
        self.summary = QLabel()
        bottom.addWidget(self.summary, 1)
        save = QPushButton(t("count.save"))
        save.clicked.connect(self.save)
        bottom.addWidget(save)
        self.layout_.addLayout(bottom)

    def refresh(self):
        self.rescan(quiet=True)  # notes dated before the count must be in first
        on_hand = stock_levels(self.ctx.conn, as_of=from_qdate(self.date.date()))
        self.products = catalog.products(self.ctx.conn)
        self.table.blockSignals(True)
        rows = []
        for p in self.products:
            rows.append([p["code"], p["name_vi"], p["spec"], p["variant"], p["unit"], num_item(on_hand.get(p["id"], 0)),
                         "", ""])
        fill_table(self.table, rows, ids=[p["id"] for p in self.products])
        for r in range(self.table.rowCount()):
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                if c != COUNT_COL:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                else:
                    item.setBackground(YELLOW)
        self.table.setSortingEnabled(False)
        self.table.blockSignals(False)
        self._update_summary()

    def _parse(self, text: str):
        if not text.strip():
            return None
        return parse_number(text)

    def _on_edit(self, item: QTableWidgetItem):
        if item.column() != COUNT_COL:
            return
        self.table.blockSignals(True)
        diff_item = self.table.item(item.row(), DIFF_COL)
        try:
            counted = self._parse(item.text())
        except ValueError:
            counted = None
            item.setText("")
        if counted is None:
            diff_item.setText("")
            diff_item.setBackground(Qt.transparent)
        else:
            diff = counted - self.table.item(item.row(), IN_APP_COL).key
            diff_item.setText(("+" if diff > 0 else "") + fmt_qty(diff))
            diff_item.setBackground(RED if abs(diff) > 1e-9 else Qt.transparent)
        self.table.blockSignals(False)
        self._update_summary()

    def _counted(self) -> dict[int, float]:
        result = {}
        for r in range(self.table.rowCount()):
            try:
                value = self._parse(self.table.item(r, COUNT_COL).text())
            except ValueError:
                continue
            if value is not None:
                result[self.table.item(r, 0).data(Qt.UserRole)] = value
        return result

    def _update_summary(self):
        counted = self._counted()
        self.summary.setText(t("count.summary", counted=len(counted), total=self.table.rowCount()))

    def save(self):
        counted = self._counted()
        if not counted:
            error(self, t("count.nothing"))
            return
        d = from_qdate(self.date.date())
        if not ask(self, t("count.confirm", count=len(counted), date=d.strftime("%d/%m/%Y"))):
            return
        with db.transaction(self.ctx.conn):
            stock_count(self.ctx.conn, d, counted, self.note.text().strip())
        self.note.clear()
        self.ctx.notify()
        info(self, t("count.saved"))
