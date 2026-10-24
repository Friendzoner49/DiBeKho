"""'Kiểm kê': enter physical counts per place (Kho tổng, Văn phòng), the app records the differences.
'Chuyển hàng…' moves goods from one place to the other."""

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
)

from dibekho import db
from dibekho.core import catalog
from dibekho.core.stock import LOCATIONS, MAIN, OFFICE, Line, stock_count, stock_levels, transfer
from dibekho.core.text import fmt_qty, parse_number
from dibekho.i18n import t
from dibekho.ui.common import (
    RED,
    YELLOW,
    ask,
    error,
    fill_table,
    fit_window,
    from_qdate,
    hint_label,
    info,
    location_combo,
    location_name,
    make_table,
    num_item,
    save_stock_note,
    to_qdate,
)
from dibekho.ui.page import Page

# in app: Kho tổng, Văn phòng, total; counted: Kho tổng, Văn phòng; difference; the stock note (as on Tồn kho)
APP_MAIN, APP_OFFICE, APP_TOTAL, COUNT_MAIN, COUNT_OFFICE, DIFF_COL, NOTE_COL = range(5, 12)
COUNT_COLS = {COUNT_MAIN: MAIN, COUNT_OFFICE: OFFICE}
APP_COLS = {MAIN: APP_MAIN, OFFICE: APP_OFFICE}


def _parse(text: str):
    if not text.strip():
        return None
    return parse_number(text)


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
        move = QPushButton(t("transfer.button"))
        move.setToolTip(t("transfer.tip"))
        move.clicked.connect(self.open_transfer)
        bar.addWidget(move)
        self.layout_.addLayout(bar)

        main, office = location_name(MAIN), location_name(OFFICE)
        self.table = make_table([t("col.code"), t("col.product"), t("col.spec"), t("col.variant"), t("col.unit"),
                                 t("count.in_app_at", place=main), t("count.in_app_at", place=office),
                                 t("count.in_app"), t("count.counted_at", place=main),
                                 t("count.counted_at", place=office), t("col.difference"), t("col.stock_note")],
                                stretch=1)
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

    def hideEvent(self, event):
        super().hideEvent(event)
        if getattr(self, "_notes_changed", False):  # the other pages show the notes typed here
            self._notes_changed = False
            self.ctx.notify()

    def refresh(self):
        self.rescan(quiet=True)  # notes dated before the count must be in first
        on_hand = stock_levels(self.ctx.conn, as_of=from_qdate(self.date.date()), by_location=True)
        self.products = catalog.products(self.ctx.conn)
        self.table.blockSignals(True)
        rows = []
        for p in self.products:
            main, office = on_hand.get((p["id"], MAIN), 0), on_hand.get((p["id"], OFFICE), 0)
            rows.append([p["code"], p["name_vi"], p["spec"], p["variant"], p["unit"], num_item(main),
                         num_item(office), num_item(main + office), "", "", "", p["stock_note"]])
        fill_table(self.table, rows, ids=[p["id"] for p in self.products])
        for r in range(self.table.rowCount()):
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                if c in COUNT_COLS:
                    item.setBackground(YELLOW)
                elif c == NOTE_COL:
                    item.setToolTip(t("note.edit_tip"))
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.table.setSortingEnabled(False)
        self.table.blockSignals(False)
        self._update_summary()

    def _on_edit(self, item: QTableWidgetItem):
        if item.column() == NOTE_COL:
            # saved at once, like on Tồn kho; no refresh, so the counts typed so far stay
            save_stock_note(self.ctx, self.table.item(item.row(), 0).data(Qt.UserRole), item.text(), notify=False)
            self._notes_changed = True
            return
        if item.column() not in COUNT_COLS:
            return
        self.table.blockSignals(True)
        try:
            _parse(item.text())
        except ValueError:
            item.setText("")
        r = item.row()
        diff, any_count = 0.0, False
        for col, loc in COUNT_COLS.items():
            counted = _parse(self.table.item(r, col).text())
            if counted is not None:
                diff += counted - self.table.item(r, APP_COLS[loc]).key
                any_count = True
        diff_item = self.table.item(r, DIFF_COL)
        if not any_count:
            diff_item.setText("")
            diff_item.setBackground(Qt.transparent)
        else:
            diff_item.setText(("+" if diff > 0 else "") + fmt_qty(diff))
            diff_item.setBackground(RED if abs(diff) > 1e-9 else Qt.transparent)
        self.table.blockSignals(False)
        self._update_summary()

    def _counted(self) -> dict[tuple[int, int], float]:
        """{(product_id, location_id): counted}; a place left empty is not counted."""
        result = {}
        for r in range(self.table.rowCount()):
            for col, loc in COUNT_COLS.items():
                try:
                    value = _parse(self.table.item(r, col).text())
                except ValueError:
                    continue
                if value is not None:
                    result[(self.table.item(r, 0).data(Qt.UserRole), loc)] = value
        return result

    def _update_summary(self):
        products = {pid for pid, _ in self._counted()}
        self.summary.setText(t("count.summary", counted=len(products), total=self.table.rowCount()))

    def save(self):
        counted = self._counted()
        if not counted:
            error(self, t("count.nothing"))
            return
        d = from_qdate(self.date.date())
        products = {pid for pid, _ in counted}
        if not ask(self, t("count.confirm", count=len(products), date=d.strftime("%d/%m/%Y"))):
            return
        self.ctx.undo_point("stock_count")
        with db.transaction(self.ctx.conn):
            stock_count(self.ctx.conn, d, counted, self.note.text().strip())
        self.note.clear()
        self.ctx.notify()
        info(self, t("count.saved"))

    def open_transfer(self):
        if TransferDialog(self.ctx, self).exec() == QDialog.Accepted:
            self.ctx.notify()


class TransferDialog(QDialog):
    """Goods moved between Kho tổng and Văn phòng: the total stock stays the same."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(t("transfer.title"))
        fit_window(self, 900, 600)
        lay = QVBoxLayout(self)
        lay.addWidget(hint_label(t("transfer.hint")))
        form = QFormLayout()
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd/MM/yyyy")
        self.date.setDate(to_qdate(date.today()))
        form.addRow(t("transfer.date") + ":", self.date)
        self.from_loc = location_combo(MAIN)
        self.to_loc = location_combo(OFFICE)
        self.from_loc.currentIndexChanged.connect(lambda _: self._sync(self.from_loc, self.to_loc))
        self.to_loc.currentIndexChanged.connect(lambda _: self._sync(self.to_loc, self.from_loc))
        form.addRow(t("transfer.from") + ":", self.from_loc)
        form.addRow(t("transfer.to") + ":", self.to_loc)
        self.note = QLineEdit()
        form.addRow(t("col.note") + ":", self.note)
        lay.addLayout(form)

        self.levels = stock_levels(ctx.conn, by_location=True)
        self.products = catalog.products(ctx.conn)
        self.table = make_table([t("col.code"), t("col.product"), t("col.spec"), t("col.variant"), t("col.unit"),
                                 t("transfer.available"), t("transfer.qty")], stretch=1)
        self.table.setEditTriggers(self.table.EditTrigger.AllEditTriggers)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectItems)
        lay.addWidget(self.table)
        self._fill()
        box = QDialogButtonBox()
        box.addButton(t("transfer.save"), QDialogButtonBox.AcceptRole)
        box.addButton(t("btn.cancel"), QDialogButtonBox.RejectRole)
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def _sync(self, changed, other):
        """The two places are always different."""
        if changed.currentData() == other.currentData():
            other.blockSignals(True)
            other.setCurrentIndex(max(other.findData(next(x for x in LOCATIONS if x != changed.currentData())), 0))
            other.blockSignals(False)
        self._fill()

    def _fill(self):
        typed = self._typed() if self.table.rowCount() else {}
        src = self.from_loc.currentData()
        fill_table(self.table, [[p["code"], p["name_vi"], p["spec"], p["variant"], p["unit"],
                                 num_item(self.levels.get((p["id"], src), 0)), fmt_qty(typed[p["id"]])
                                 if p["id"] in typed else ""] for p in self.products],
                   ids=[p["id"] for p in self.products])
        for r in range(self.table.rowCount()):
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                if c == 6:
                    item.setBackground(YELLOW)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.table.setSortingEnabled(False)

    def _typed(self) -> dict[int, float]:
        result = {}
        for r in range(self.table.rowCount()):
            try:
                value = _parse(self.table.item(r, 6).text())
            except ValueError:
                value = None
            if value:
                result[self.table.item(r, 0).data(Qt.UserRole)] = value
        return result

    def save(self):
        typed = self._typed()
        if not typed or any(q < 0 for q in typed.values()):
            error(self, t("transfer.nothing"))
            return
        src, dst = self.from_loc.currentData(), self.to_loc.currentData()
        names = {p["id"]: p for p in self.products}
        lines = "\n".join(f"• {catalog.label(names[pid])}: {fmt_qty(q)} {names[pid]['unit']}".rstrip()
                          for pid, q in typed.items())
        short = [catalog.label(names[pid]) for pid, q in typed.items() if q > self.levels.get((pid, src), 0) + 1e-9]
        text = t("transfer.confirm", src=location_name(src), dst=location_name(dst), lines=lines)
        if short:
            text += "\n\n" + t("transfer.confirm_short", place=location_name(src), names=", ".join(short))
        if not ask(self, text):
            return
        self.ctx.undo_point("transfer")
        with db.transaction(self.ctx.conn):
            transfer(self.ctx.conn, from_qdate(self.date.date()), src, dst,
                     [Line(pid, q) for pid, q in typed.items()], self.note.text().strip())
        info(self, t("transfer.saved"))
        self.accept()
