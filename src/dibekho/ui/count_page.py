"""'Kiểm kê': enter physical counts of one place at a time (Kho tổng, Văn phòng Hà Nội or Văn phòng Bắc Ninh, picked
in 'Đếm ở'; user's choice 25/11/2026: each office counts its own goods), the app records the differences.
'Chuyển hàng…' moves goods from one place to another."""

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
from dibekho.core import catalog, queries
from dibekho.core.stock import LOCATIONS, MAIN, OFFICE, Line, record_trial_use, stock_count, stock_levels, transfer
from dibekho.core.text import fmt_qty, parse_number
from dibekho.i18n import t
from dibekho.ui.common import (
    enter_moves_down,
    no_default_buttons,
    PageWindow,
    RED,
    YELLOW,
    ask,
    error,
    fill_table,
    fit_window,
    freeze_columns,
    from_qdate,
    hint_label,
    info,
    location_combo,
    location_name,
    make_table,
    num_item,
    numeric_cell_delegate,
    save_stock_note,
    to_qdate,
)
from dibekho.ui.page import Page

# in app at the place counted; counted there; difference; the stock note (as on Tồn kho)
APP_COL, COUNT_COL, DIFF_COL, NOTE_COL = range(6, 10)


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
        trial = QPushButton(t("trial.button"))
        trial.setToolTip(t("trial.tip"))
        trial.clicked.connect(self.open_trial)
        bar.addWidget(trial)
        self.layout_.addLayout(bar)

        history = QHBoxLayout()
        # the place counted: first on its own row, so the note box keeps its room on a small screen
        history.addWidget(QLabel(t("count.place")))
        self.place = location_combo(MAIN)
        self.place.currentIndexChanged.connect(self._place_changed)
        self._place_shown = MAIN
        history.addWidget(self.place)
        history.addSpacing(16)
        transfers_btn = QPushButton(t("count.transfers_btn"))
        transfers_btn.clicked.connect(lambda: self.open_history("transfer"))
        trials_btn = QPushButton(t("count.trials_btn"))
        trials_btn.clicked.connect(lambda: self.open_history("trial"))
        counts_btn = QPushButton(t("count.counts_btn"))
        counts_btn.clicked.connect(lambda: self.open_history("stock_count"))
        history.addWidget(transfers_btn)
        history.addWidget(trials_btn)
        history.addWidget(counts_btn)
        history.addStretch()
        self.layout_.addLayout(history)
        self._history_windows: dict[str, PageWindow] = {}

        self.table = make_table(self._headers(MAIN), stretch=1)
        self.table.setEditTriggers(self.table.EditTrigger.AllEditTriggers)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectItems)
        self.table.itemChanged.connect(self._on_edit)
        numeric_cell_delegate(self.table, COUNT_COL)
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

    @staticmethod
    def _headers(loc: int) -> list[str]:
        place = location_name(loc)
        return [t("col.code"), t("col.product"), t("col.name_zh"), t("col.spec"), t("col.variant"), t("col.unit"),
                t("count.in_app_at", place=place), t("count.counted_at", place=place), t("col.difference"),
                t("col.stock_note")]

    def _place_changed(self):
        """Another place to count: its stock in the app; the numbers typed for the place before are dropped (asked)."""
        loc = self.place.currentData()
        if loc == self._place_shown:
            return
        if self._counted() and not ask(self, t("count.place_change", place=location_name(self._place_shown))):
            self.place.blockSignals(True)
            self.place.setCurrentIndex(max(self.place.findData(self._place_shown), 0))
            self.place.blockSignals(False)
            return
        self.refresh()

    def refresh(self):
        self.rescan(quiet=True)  # notes dated before the count must be in first
        loc = self.place.currentData()
        self._place_shown = loc
        self.table.setHorizontalHeaderLabels(self._headers(loc))
        on_hand = stock_levels(self.ctx.conn, as_of=from_qdate(self.date.date()), by_location=True)
        self.products = catalog.products(self.ctx.conn)
        self.table.blockSignals(True)
        rows = []
        for p in self.products:
            rows.append([p["code"], p["name_vi"], p["name_zh"], p["spec"], p["variant"], p["unit"],
                         num_item(on_hand.get((p["id"], loc), 0)), "", "", p["stock_note"]])
        fill_table(self.table, rows, ids=[p["id"] for p in self.products])
        for r in range(self.table.rowCount()):
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                if c == COUNT_COL:
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
        if item.column() != COUNT_COL:
            return
        self.table.blockSignals(True)
        try:
            _parse(item.text())
        except ValueError:
            item.setText("")
        r = item.row()
        counted = _parse(self.table.item(r, COUNT_COL).text())
        diff = 0.0 if counted is None else counted - self.table.item(r, APP_COL).key
        diff_item = self.table.item(r, DIFF_COL)
        if counted is None:
            diff_item.setText("")
            diff_item.setBackground(Qt.transparent)
        else:
            diff_item.setText(("+" if diff > 0 else "") + fmt_qty(diff))
            diff_item.setBackground(RED if abs(diff) > 1e-9 else Qt.transparent)
        self.table.blockSignals(False)
        self._update_summary()

    def _counted(self) -> dict[tuple[int, int], float]:
        """{(product_id, location_id): counted} at the place shown; a row left empty is not counted."""
        result = {}
        for r in range(self.table.rowCount()):
            try:
                value = _parse(self.table.item(r, COUNT_COL).text())
            except ValueError:
                continue
            if value is not None:
                result[(self.table.item(r, 0).data(Qt.UserRole), self._place_shown)] = value
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
        if not ask(self, t("count.confirm_at", count=len(products), date=d.strftime("%d/%m/%Y"),
                           place=location_name(self._place_shown))):
            return
        self.ctx.log_action("stock_count")
        with db.transaction(self.ctx.conn):
            stock_count(self.ctx.conn, d, counted, self.note.text().strip())
        self.note.clear()
        self.ctx.notify()
        info(self, t("count.saved"))

    def open_transfer(self):
        open_transfer_dialog(self.ctx, self)

    def open_trial(self):
        open_trial_dialog(self.ctx, self)

    def open_history(self, kind: str) -> None:
        from dibekho.ui.orders_page import OrdersPage

        win = self._history_windows.get(kind)
        if win is None:
            win = self._history_windows[kind] = PageWindow(OrdersPage(self.ctx, fixed_kind=kind), self)
        win.show()
        win.raise_()
        win.activateWindow()


TRANS_CODE, TRANS_NAME, TRANS_ZH, TRANS_SPEC, TRANS_VARIANT, TRANS_UNIT, TRANS_CATEGORY, TRANS_AVAILABLE, \
    TRANS_QTY = range(9)


def open_transfer_dialog(ctx, parent, doc_id: int | None = None) -> bool:
    accepted = TransferDialog(ctx, parent, doc_id).exec() == QDialog.Accepted
    if accepted:
        ctx.notify()
    return accepted


class TransferDialog(QDialog):
    """Goods moved between Kho tổng and Văn phòng: the total stock stays the same.
    doc_id: edit an existing active transfer instead of recording a new one (the old one is marked
    'replaced', the new one keeps its code)."""

    def __init__(self, ctx, parent=None, doc_id: int | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.doc_id = doc_id
        self.setWindowTitle(t("transfer.title_edit") if doc_id else t("transfer.title"))
        fit_window(self, 1000, 600)
        lay = QVBoxLayout(self)
        lay.addWidget(hint_label(t("transfer.hint")))

        self.levels = stock_levels(ctx.conn, by_location=True)
        self._prefill: dict[int, float] = {}
        head = None
        if doc_id:
            head, old_lines = queries.document(ctx.conn, doc_id)
            # as if this transfer had not happened yet, so editing its own quantities never looks short
            for ln in old_lines:
                self.levels[(ln["product_id"], head["location_id"])] = \
                    self.levels.get((ln["product_id"], head["location_id"]), 0) + ln["qty"]
                self.levels[(ln["product_id"], head["to_location_id"])] = \
                    self.levels.get((ln["product_id"], head["to_location_id"]), 0) - ln["qty"]
            self._prefill = {ln["product_id"]: ln["qty"] for ln in old_lines}

        form = QFormLayout()
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd/MM/yyyy")
        self.date.setDate(to_qdate(date.fromisoformat(head["doc_date"])) if head else to_qdate(date.today()))
        form.addRow(t("transfer.date") + ":", self.date)
        # built with the right place already selected (not set afterwards): setCurrentIndex() on a combo
        # whose signal is already connected would fire _sync() -> _fill() before self.table/self.products exist
        self.from_loc = location_combo(head["location_id"] if head else MAIN)
        self.to_loc = location_combo(head["to_location_id"] if head else OFFICE)
        self.from_loc.currentIndexChanged.connect(lambda _: self._sync(self.from_loc, self.to_loc))
        self.to_loc.currentIndexChanged.connect(lambda _: self._sync(self.to_loc, self.from_loc))
        form.addRow(t("transfer.from") + ":", self.from_loc)
        form.addRow(t("transfer.to") + ":", self.to_loc)
        self.note = QLineEdit()
        self.note.setText(head["note"] or "" if head else "")
        form.addRow(t("col.note") + ":", self.note)
        lay.addLayout(form)

        self.products = catalog.products(ctx.conn)
        if doc_id:  # a product the old transfer carried but since set to Ngừng dùng must still show up to edit
            have = {p["id"] for p in self.products}
            self.products += [p for p in catalog.products(ctx.conn, include_inactive=True)
                              if p["id"] in self._prefill and p["id"] not in have]
        self.table = make_table([t("col.code"), t("col.product"), t("col.name_zh"), t("col.spec"),
                                 t("col.variant"), t("col.unit"), t("col.category"), t("transfer.available"),
                                 t("transfer.qty")], stretch=TRANS_NAME)
        self.table.setEditTriggers(self.table.EditTrigger.DoubleClicked | self.table.EditTrigger.EditKeyPressed
                                   | self.table.EditTrigger.AnyKeyPressed)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectItems)
        lay.addWidget(self.table)
        self._fill()
        self.frozen = freeze_columns(self.table, [TRANS_AVAILABLE, TRANS_QTY], side="right", editable=True)
        numeric_cell_delegate(self.table, TRANS_QTY)
        numeric_cell_delegate(self.frozen, TRANS_QTY)
        box = QDialogButtonBox()
        box.addButton(t("transfer.save"), QDialogButtonBox.AcceptRole)
        box.addButton(t("btn.cancel"), QDialogButtonBox.RejectRole)
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        no_default_buttons(self)  # Enter moves down the quantities (keyPressEvent), it never saves

    def keyPressEvent(self, event):
        if not enter_moves_down(self, self.table, event):
            super().keyPressEvent(event)

    def _sync(self, changed, other):
        """The two places are always different."""
        if changed.currentData() == other.currentData():
            other.blockSignals(True)
            other.setCurrentIndex(max(other.findData(next(x for x in LOCATIONS if x != changed.currentData())), 0))
            other.blockSignals(False)
        self._fill()

    def _fill(self):
        typed = self._typed() if self.table.rowCount() else self._prefill
        src = self.from_loc.currentData()
        fill_table(self.table, [[p["code"], p["name_vi"], p["name_zh"], p["spec"], p["variant"], p["unit"],
                                 p["category"], num_item(self.levels.get((p["id"], src), 0)),
                                 fmt_qty(typed[p["id"]]) if p["id"] in typed else ""] for p in self.products],
                   ids=[p["id"] for p in self.products])
        for r in range(self.table.rowCount()):
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                if c == TRANS_QTY:
                    item.setBackground(YELLOW)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        # capped: both are pinned (freeze_columns), and the long header label must not widen them
        for col in (TRANS_AVAILABLE, TRANS_QTY):
            self.table.setColumnWidth(col, min(self.table.columnWidth(col), 110))
        self.table.setSortingEnabled(False)

    def _typed(self) -> dict[int, float]:
        result = {}
        for r in range(self.table.rowCount()):
            try:
                value = _parse(self.table.item(r, TRANS_QTY).text())
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
        lines = "\n".join(f"• {catalog.long_label(names[pid])}: {fmt_qty(q)} {names[pid]['unit']}".rstrip()
                          for pid, q in typed.items())
        short = [catalog.long_label(names[pid]) for pid, q in typed.items() if q > self.levels.get((pid, src), 0) + 1e-9]
        text = t("transfer.confirm", src=location_name(src), dst=location_name(dst), lines=lines)
        if short:
            text += "\n\n" + t("transfer.confirm_short", place=location_name(src), names=", ".join(short))
        if not ask(self, text):
            return
        self.ctx.log_action("transfer_edit" if self.doc_id else "transfer")
        with db.transaction(self.ctx.conn):
            transfer(self.ctx.conn, from_qdate(self.date.date()), src, dst,
                     [Line(pid, q) for pid, q in typed.items()], self.note.text().strip(), replaces=self.doc_id)
        info(self, t("transfer.saved"))
        self.accept()


TRIAL_CODE, TRIAL_NAME, TRIAL_ZH, TRIAL_SPEC, TRIAL_VARIANT, TRIAL_UNIT, TRIAL_CATEGORY, TRIAL_AVAILABLE, \
    TRIAL_QTY = range(9)


def open_trial_dialog(ctx, parent) -> bool:
    accepted = TrialUseDialog(ctx, parent).exec() == QDialog.Accepted
    if accepted:
        ctx.notify()
    return accepted


class TrialUseDialog(QDialog):
    """Goods taken out of stock for internal trial/testing use (no customer): replaces the sham delivery
    notes staff used to make to self-deduct stock for this. A mistake is fixed with Huỷ phiếu + Hoàn tác,
    like a stock count -- there is no edit for this kind."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(t("trial.title"))
        fit_window(self, 1000, 600)
        lay = QVBoxLayout(self)
        lay.addWidget(hint_label(t("trial.hint")))

        self.levels = stock_levels(ctx.conn, by_location=True)

        form = QFormLayout()
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd/MM/yyyy")
        self.date.setDate(to_qdate(date.today()))
        form.addRow(t("trial.date") + ":", self.date)
        self.location = location_combo(MAIN)
        self.location.currentIndexChanged.connect(self._fill)
        form.addRow(t("trial.location") + ":", self.location)
        self.note = QLineEdit()
        form.addRow(t("col.note") + ":", self.note)
        lay.addLayout(form)

        self.products = catalog.products(ctx.conn)
        self.table = make_table([t("col.code"), t("col.product"), t("col.name_zh"), t("col.spec"),
                                 t("col.variant"), t("col.unit"), t("col.category"), t("trial.available"),
                                 t("trial.qty")], stretch=TRIAL_NAME)
        self.table.setEditTriggers(self.table.EditTrigger.DoubleClicked | self.table.EditTrigger.EditKeyPressed
                                   | self.table.EditTrigger.AnyKeyPressed)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectItems)
        lay.addWidget(self.table)
        self._fill()
        self.frozen = freeze_columns(self.table, [TRIAL_AVAILABLE, TRIAL_QTY], side="right", editable=True)
        numeric_cell_delegate(self.table, TRIAL_QTY)
        numeric_cell_delegate(self.frozen, TRIAL_QTY)
        box = QDialogButtonBox()
        box.addButton(t("trial.save"), QDialogButtonBox.AcceptRole)
        box.addButton(t("btn.cancel"), QDialogButtonBox.RejectRole)
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        no_default_buttons(self)  # Enter moves down the quantities (keyPressEvent), it never saves

    def keyPressEvent(self, event):
        if not enter_moves_down(self, self.table, event):
            super().keyPressEvent(event)

    def _fill(self):
        typed = self._typed() if self.table.rowCount() else {}
        loc = self.location.currentData()
        fill_table(self.table, [[p["code"], p["name_vi"], p["name_zh"], p["spec"], p["variant"], p["unit"],
                                 p["category"], num_item(self.levels.get((p["id"], loc), 0)),
                                 fmt_qty(typed[p["id"]]) if p["id"] in typed else ""] for p in self.products],
                   ids=[p["id"] for p in self.products])
        for r in range(self.table.rowCount()):
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                if c == TRIAL_QTY:
                    item.setBackground(YELLOW)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        # capped: both are pinned (freeze_columns), and the long header label must not widen them
        for col in (TRIAL_AVAILABLE, TRIAL_QTY):
            self.table.setColumnWidth(col, min(self.table.columnWidth(col), 110))
        self.table.setSortingEnabled(False)

    def _typed(self) -> dict[int, float]:
        result = {}
        for r in range(self.table.rowCount()):
            try:
                value = _parse(self.table.item(r, TRIAL_QTY).text())
            except ValueError:
                value = None
            if value:
                result[self.table.item(r, 0).data(Qt.UserRole)] = value
        return result

    def save(self):
        typed = self._typed()
        if not typed or any(q < 0 for q in typed.values()):
            error(self, t("trial.nothing"))
            return
        loc = self.location.currentData()
        names = {p["id"]: p for p in self.products}
        lines = "\n".join(f"• {catalog.long_label(names[pid])}: {fmt_qty(q)} {names[pid]['unit']}".rstrip()
                          for pid, q in typed.items())
        short = [catalog.long_label(names[pid]) for pid, q in typed.items() if q > self.levels.get((pid, loc), 0) + 1e-9]
        text = t("trial.confirm", place=location_name(loc), lines=lines)
        if short:
            text += "\n\n" + t("trial.confirm_short", place=location_name(loc), names=", ".join(short))
        if not ask(self, text):
            return
        self.ctx.log_action("trial_use")
        with db.transaction(self.ctx.conn):
            record_trial_use(self.ctx.conn, from_qdate(self.date.date()), loc,
                             [Line(pid, q) for pid, q in typed.items()], self.note.text().strip())
        info(self, t("trial.saved"))
        self.accept()
