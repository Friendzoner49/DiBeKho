"""Shared UI helpers: app context, tables, formatting, messages."""

import re
import sqlite3
import sys
import unicodedata
from datetime import date

from PySide6.QtCore import QDate, QEvent, QObject, Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QPalette, QValidator
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QStyledItemDelegate,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dibekho import db
from dibekho.core import activity, deliveries, undo
from dibekho.core.text import fmt_money, fmt_qty, parse_number
from dibekho.core.workspace import Config, Workspace
from dibekho.i18n import t

# Row highlight colours. Light theme: pale backgrounds; dark theme (e.g. macOS Dark Mode): deep tones,
# so the white text stays readable. sync_theme_colors() updates these objects in place.
_THEMES = {
    "light": {"RED": "#fde2e1", "YELLOW": "#fff4cc", "ORANGE": "#ffd9a8", "hint": "#666666", "banner": "#eef5ff",
              "alert": "#c0392b", "warn": "#b35900", "border": "#c6c6c6", "hover": "#eef2f7", "pressed": "#dde4ec"},
    "dark": {"RED": "#6e2a2a", "YELLOW": "#5e4c14", "ORANGE": "#6e4210", "hint": "#a0a0a0", "banner": "#1f3550",
             "alert": "#ff7b72", "warn": "#ffb066", "border": "#55585c", "hover": "#363a3f", "pressed": "#2a2d31"},
}
RED = QColor(_THEMES["light"]["RED"])
YELLOW = QColor(_THEMES["light"]["YELLOW"])
ORANGE = QColor(_THEMES["light"]["ORANGE"])  # running low: order more
GREY = QColor("#888888")


def is_dark() -> bool:
    app = QApplication.instance()
    return app is not None and app.palette().color(QPalette.Window).lightness() < 128


def theme_color(name: str) -> str:
    """'hint', 'banner', 'alert' or 'warn' for the current light/dark theme."""
    return _THEMES["dark" if is_dark() else "light"][name]


def sync_theme_colors() -> None:
    colors = _THEMES["dark" if is_dark() else "light"]
    RED.setRgb(QColor(colors["RED"]).rgb())
    YELLOW.setRgb(QColor(colors["YELLOW"]).rgb())
    ORANGE.setRgb(QColor(colors["ORANGE"]).rgb())


def _rounded_qss() -> str:
    border, hover, pressed = theme_color("border"), theme_color("hover"), theme_color("pressed")
    return f"""
        /* Setting any application-wide stylesheet moves Qt to its "styled" background painting path for
        every widget, not only the ones a rule below actually targets -- without these, a plain QWidget
        stops following the live (light or dark) palette and falls back to a flat default. */
        QWidget {{ background-color: palette(window); color: palette(window-text); }}
        QAbstractItemView {{
            background-color: palette(base);
            alternate-background-color: palette(alternate-base);
            color: palette(text);
        }}
        QLineEdit, QComboBox, QDateEdit, QAbstractSpinBox {{
            background-color: palette(base);
            color: palette(text);
        }}
        QPushButton {{
            background-color: palette(button);
            color: palette(button-text);
            border: 1px solid {border};
            border-radius: 6px;
            padding: 5px 14px;
        }}
        QPushButton:hover {{ background: {hover}; }}
        QPushButton:pressed {{ background: {pressed}; }}
        QPushButton:default {{ border: 1px solid palette(highlight); }}
        QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QAbstractSpinBox {{
            border: 1px solid {border};
            border-radius: 6px;
            padding: 3px 6px;
        }}
        QComboBox::drop-down {{ border: none; width: 20px; }}
        QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
            border: 1px solid palette(highlight);
        }}
        QGroupBox {{
            border: 1px solid {border};
            border-radius: 8px;
            margin-top: 12px;
            padding-top: 10px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
        }}
        QTabWidget::pane {{
            border: 1px solid {border};
            border-radius: 8px;
        }}
        QTabBar::tab {{
            border: 1px solid {border};
            border-bottom: none;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            padding: 5px 14px;
            margin-right: 2px;
        }}
        QTabBar::tab:selected {{ background: {hover}; }}
        QTabBar::tab:!selected {{ margin-top: 2px; }}
        QTableView, QTreeView, QListView {{
            border: 1px solid {border};
            border-radius: 6px;
        }}
        QHeaderView::section {{
            border: none;
            border-bottom: 1px solid {border};
            padding: 4px;
        }}
    """


def apply_rounded_style(app: QApplication) -> None:
    """A softer look for buttons, inputs, tabs and panels (the user's own words: 'bo tròn... để trông nó
    mềm mại hơn'), while leaving the OS window frame itself untouched -- it already comes rounded on both
    Windows 11 and macOS, and drawing a frameless window instead would lose the native minimize/maximize/
    move behaviour. Fusion (already forced by app.setStyle) renders QSS the same way on both platforms.
    Colours come from theme_color(), so this stays readable in dark mode; re-applied whenever the OS
    palette changes, the same trigger sync_theme_colors() reacts to via fill_table()."""
    app.setStyleSheet(_rounded_qss())
    if not getattr(app, "_rounded_style_wired", False):
        app.paletteChanged.connect(lambda *_: app.setStyleSheet(_rounded_qss()))
        app._rounded_style_wired = True


class AppContext(QObject):
    """Holds the open database and notifies screens when data changes."""

    changed = Signal()

    def __init__(self, cfg: Config, ws: Workspace):
        super().__init__()
        self.cfg = cfg
        self.ws = ws
        self.conn: sqlite3.Connection = db.connect(ws.db_path)

    def notify(self) -> None:
        self.changed.emit()

    def undo_point(self, action: str) -> None:
        """Call just before an action the user may want to undo ('Hoàn tác'); action names t('undo.<action>')."""
        activity.log("action", action)
        undo.mark(self.conn, self.ws, action)

    def close(self) -> None:
        self.conn.close()
        self.conn = None

    def reopen(self) -> None:
        if self.conn is not None:
            self.conn.close()
        self.conn = db.connect(self.ws.db_path)
        self.notify()


class NoWheelCombo(QComboBox):
    """A drop-down that ignores the mouse wheel: scrolling a long table must never change a choice on the way
    (a customer's '管根套 90-110' ended up as a PPE membrane, 9 wheel notches further down the list)."""

    def wheelEvent(self, event):
        event.ignore()  # the table under it scrolls instead


def location_name(location_id) -> str:
    """Kho tổng / Văn phòng in the interface language."""
    from dibekho.core.stock import LOCATION_CODES, MAIN

    return t(f"loc.{LOCATION_CODES.get(location_id, LOCATION_CODES[MAIN])}")


def location_combo(selected=None) -> "NoWheelCombo":
    from dibekho.core.stock import LOCATIONS, MAIN

    combo = NoWheelCombo()
    for loc in LOCATIONS:
        combo.addItem(location_name(loc), loc)
    combo.setCurrentIndex(max(combo.findData(selected or MAIN), 0))
    return combo


class NoWheelSpin(QDoubleSpinBox):
    """A quantity box that ignores the mouse wheel, for the same reason as NoWheelCombo.
    Shows 20, not 20,00. '.' and ',' are both the decimal point and there is no thousands separator:
    with the Vietnamese locale Qt read '1.5' as 15."""

    def wheelEvent(self, event):
        event.ignore()

    def textFromValue(self, value):
        text = f"{value:.{self.decimals()}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text.replace(".", self.locale().decimalPoint())

    def valueFromText(self, text):
        try:
            return parse_number(text or "0")
        except ValueError:
            return 0.0

    def validate(self, text, pos):
        s = unicodedata.normalize("NFKC", text).strip().replace("。", ".")
        if re.fullmatch(rf"\d*([.,]\d{{0,{self.decimals()}}})?", s) is None:
            return QValidator.Invalid, text, pos
        if s in ("", ".", ","):
            return QValidator.Intermediate, text, pos
        return (QValidator.Acceptable if parse_number(s) <= self.maximum() else QValidator.Invalid), text, pos

    def fixup(self, text):
        return text


class NoWheelDate(QDateEdit):
    def wheelEvent(self, event):
        event.ignore()


class ActivityFilter(QObject):
    """Installed on the QApplication: writes each button click, menu choice and window opened to the activity
    log (core.activity). Typed text is never logged. Every event passes through here, so it returns at once
    for the other event types and never stops an event."""

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind not in (QEvent.MouseButtonRelease, QEvent.Show):
            return False
        try:
            if kind == QEvent.Show:
                if isinstance(obj, QDialog) and not isinstance(obj, QMessageBox):
                    activity.log("window", obj.windowTitle())
            elif event.button() == Qt.LeftButton:
                if isinstance(obj, QMenu):
                    action = obj.activeAction()
                    if action is not None and action.text():
                        activity.log("menu", action.text().replace("&", ""))
                elif isinstance(obj, QAbstractButton) and obj.isEnabled() and obj.rect().contains(event.position().toPoint()):
                    label = obj.text().replace("&", "") or obj.toolTip()
                    if obj.isCheckable():
                        label += " ☑" if not obj.isChecked() else " ☐"  # the state after this click
                    window = obj.window().windowTitle() if obj.window() else ""
                    activity.log("click", f"{label} · {window}" if window else label)
        except Exception:
            pass
        return False


# ---- formatting ------------------------------------------------------------

def fmt_date(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return value.strftime("%d/%m/%Y")


def to_qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def from_qdate(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


def status_text(status: str) -> str:
    return t(f"status.{status}")


def kind_text(kind: str) -> str:
    return t(f"kind.{kind}")


# ---- tables ----------------------------------------------------------------

class SortItem(QTableWidgetItem):
    """Item that sorts by a hidden key (numbers, ISO dates) but shows formatted text."""

    def __init__(self, text: str, key):
        super().__init__(text)
        self.key = key

    def __lt__(self, other):
        if isinstance(other, SortItem):
            a, b = self.key, other.key
            if a is None:
                return b is not None
            if b is None:
                return False
            return a < b
        return super().__lt__(other)


def num_item(value) -> SortItem:
    item = SortItem(fmt_qty(value) if value is not None else "", value)
    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return item


def money_item(value) -> SortItem:
    """Amount in VND; an unknown price shows '—' and sorts first."""
    item = SortItem(fmt_money(value), value)
    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return item


def money_text(m) -> str:
    """'Doanh thu 12.000.000 = tiền hàng … + phí khác …' for a stats.Money (fees unknown when products are
    filtered: fees belong to no product)."""
    if m.fees is None:
        text = t("stats.money_goods", goods=fmt_money(m.goods), orders=m.orders)
    else:
        text = t("stats.money", total=fmt_money(m.total), goods=fmt_money(m.goods), fees=fmt_money(m.fees),
                 orders=m.orders)
    if m.unpriced:
        text += " · " + t("stats.unpriced", count=m.unpriced)
    return text


def date_item(iso: str | None) -> SortItem:
    return SortItem(fmt_date(iso), iso or "")


def text_item(value) -> QTableWidgetItem:
    return QTableWidgetItem("" if value is None else str(value))


MAX_COLUMN_WIDTH = 520  # long product names: wider columns; the user can still drag any column wider


def fit_window(widget: QWidget, width: int, height: int) -> None:
    """resize() that never makes a window larger than the screen (the UI may be scaled up, e.g. 120%)."""
    screen = widget.screen() or QApplication.primaryScreen()
    if screen is not None:
        avail = screen.availableGeometry()
        width, height = min(width, int(avail.width() * 0.96)), min(height, int(avail.height() * 0.92))
    widget.resize(width, height)


class PageWindow(QDialog):
    """A screen shown in its own (non-modal) window instead of the navigation list."""

    def __init__(self, page, parent):
        super().__init__(parent)
        self.page = page
        self.setWindowTitle(page.title_text)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        fit_window(self, 1200, 760)
        QVBoxLayout(self).addWidget(page)


class _NumericCellDelegate(QStyledItemDelegate):
    """A cell editor restricted to digits/decimals, with the system input method switched off.

    On macOS a Vietnamese or Chinese input source can still treat a typed digit as composing text that
    is only resolved when Enter commits the cell, landing the same keystroke twice in a plain QLineEdit
    editor. There is no `active`/digits-only input method hint applied to a default item-view editor, so
    the OS has no reason to skip composition for it -- this delegate gives it one."""

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit):
            editor.setAttribute(Qt.WA_InputMethodEnabled, False)
            editor.setInputMethodHints(Qt.ImhFormattedNumbersOnly)
        return editor


def numeric_cell_delegate(table: QAbstractItemView, column: int) -> None:
    """Make one column's cell editor digits/decimal-only on `table` (a QTableWidget or a FrozenColumns
    pinned overlay -- apply to every view that can open its own editor for that column, they don't share
    delegates even when they share a model).

    Also marks the column so the view's own currentChanged() override (Table/FrozenColumns below) keeps
    WA_InputMethodEnabled off at the VIEW level whenever this column is the current cell -- not just on
    the cell editor. Qt turns the view's input-method attribute back on by itself whenever an editable
    cell becomes current, before any editor exists, so the first keystroke that both selects a numeric
    cell and types into it (the normal one-click-then-type flow, via the AnyKeyPressed edit trigger)
    still reaches a view with IME on and gets composed/doubled by macOS Telex -- the editor-level fix
    alone (createEditor() in _NumericCellDelegate) only protects keystrokes typed AFTER that first one."""
    table.setItemDelegateForColumn(column, _NumericCellDelegate(table))
    table.numeric_cols.add(column)


class Table(QTableWidget):
    """Every column can be dragged wider (or double-click its border to fit its contents).
    The 'stretch' column also takes the spare width when the window is wider than the columns."""

    def __init__(self, rows: int, columns: int, stretch: int | None):
        super().__init__(rows, columns)
        self.stretch = stretch
        self.natural = 0  # width of the stretch column before it took the spare width
        self._frozen: list["FrozenColumns"] = []  # populated by freeze_columns()
        self.numeric_cols: set[int] = set()  # populated by numeric_cell_delegate()

    def currentChanged(self, current, previous):
        super().currentChanged(current, previous)
        self.setAttribute(Qt.WA_InputMethodEnabled, current.column() not in self.numeric_cols)

    def fill_spare(self) -> None:
        if self.stretch is None or self.stretch >= self.columnCount():
            return
        others = sum(self.columnWidth(c) for c in range(self.columnCount()) if c != self.stretch)
        self.natural = self.natural or self.columnWidth(self.stretch)
        self.setColumnWidth(self.stretch, max(self.natural, self.viewport().width() - others))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fill_spare()
        for frozen in self._frozen:
            frozen.place()


class FrozenColumns(QTableView):
    """Pins `columns` of `table` to its left or right edge, so they stay in view while the rest of `table`
    scrolls sideways. Hidden automatically whenever `table` is wide enough that nothing needs to scroll.

    This view shares `table`'s own model and selection model -- it shows the very same QTableWidgetItems,
    it never copies them -- so anything already wired to `table` (itemChanged, doubleClicked, fill_table,
    only_editable, row_id, sorting...) keeps working unchanged on both the pinned and the scrolling columns.

    `table`'s edit triggers must already exclude CurrentChanged (make_table()'s default does) before this
    is created: with it included, a click on a shared cell would open an editor on each view at once.

    `sticky=True` is for a pinned column that does NOT touch the table's own edge (e.g. a single column
    in the middle, like Tồn kho's Tồn): drawing it flush against the edge the whole time, as the plain
    (non-sticky) mode does, would permanently cover the real columns in front of it. Sticky mode instead
    behaves like a "position: sticky" table column -- invisible (the real cell shows through normally)
    until scrolling would carry it past the edge, then it snaps to the edge and stays there."""

    MIN_SCROLLABLE = 120  # below this much leftover width, not even one narrow scrolling column (Kho tổng,
    # Văn phòng: ~70-80px each on real data) would be readable

    def __init__(self, table: Table, columns: list[int], side: str = "left", editable: bool = False,
                 sticky: bool = False):
        super().__init__(table)
        self.host, self.columns, self.side, self.sticky = table, columns, side, sticky
        self._guard = False
        self.numeric_cols: set[int] = set()  # populated by numeric_cell_delegate()
        self.setModel(table.model())
        self.setSelectionModel(table.selectionModel())
        self.setSelectionBehavior(table.selectionBehavior())
        self.setSelectionMode(table.selectionMode())
        self.setAlternatingRowColors(table.alternatingRowColors())
        self.setWordWrap(table.wordWrap())
        self.setEditTriggers(table.editTriggers())
        self.setFocusPolicy(Qt.StrongFocus if editable else Qt.NoFocus)
        self.verticalHeader().hide()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QTableView { border: none; }")
        for c in range(table.columnCount()):
            self.setColumnHidden(c, c not in columns)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.horizontalHeader().setSectionsClickable(True)
        self.horizontalHeader().setHighlightSections(False)
        table.verticalScrollBar().valueChanged.connect(self.verticalScrollBar().setValue)
        self.verticalScrollBar().valueChanged.connect(table.verticalScrollBar().setValue)
        table.horizontalHeader().sectionResized.connect(self._host_resized)
        self.horizontalHeader().sectionResized.connect(self._own_resized)
        self.horizontalHeader().sortIndicatorChanged.connect(self._sort_from_here)
        table.horizontalHeader().sortIndicatorChanged.connect(self._sort_from_host)
        table.horizontalScrollBar().rangeChanged.connect(lambda *_: self.place())
        if sticky:  # visibility depends on the current scroll position, not just whether scrolling is possible
            table.horizontalScrollBar().valueChanged.connect(lambda *_: self.place())
        self.doubleClicked.connect(table.doubleClicked)
        if editable:  # arrowing onto a pinned cell from the host must not leave its (hidden) editor open there
            self.selectionModel().currentChanged.connect(self._follow_focus)
        table.viewport().stackUnder(self)
        self.place()

    def _host_resized(self, col, _old, new) -> None:
        if col in self.columns and self.columnWidth(col) != new:
            self.setColumnWidth(col, new)
        self.place()

    def _own_resized(self, col, _old, new) -> None:
        if self.host.columnWidth(col) != new:
            self.host.setColumnWidth(col, new)  # _host_resized sees the same value already set: no loop
        self.place()

    def _sort_from_here(self, col, order) -> None:
        if self._guard or not self.host.isSortingEnabled():
            return
        self._guard = True
        try:
            self.host.sortByColumn(col, order)
        finally:
            self._guard = False

    def _sort_from_host(self, col, order) -> None:
        if self._guard:
            return
        self._guard = True
        try:
            self.horizontalHeader().setSortIndicator(col, order)
        finally:
            self._guard = False

    def _follow_focus(self, current, _previous) -> None:
        if self.isVisible() and current.column() in self.columns:
            self.setFocus(Qt.OtherFocusReason)

    def currentChanged(self, current, previous):
        super().currentChanged(current, previous)
        self.setAttribute(Qt.WA_InputMethodEnabled, current.column() not in self.numeric_cols)

    def keyPressEvent(self, event):
        """29/10/2026 (mục 9.13): the real bug behind the "digit doubles" report, found with a key/IME
        logger in the real packaged app, not with any Qt-level probe. On an AnyKeyPressed-triggered edit,
        QAbstractItemView.keyPressEvent() opens an editor, forwards the key into it, and then calls
        event.ignore() -- so Qt propagates that same key event to the parent widget. This view's parent IS
        the host `table` (see __init__, super().__init__(table)), which shares the same current index and
        edit triggers, so the host opens a SECOND, independent editor and processes the identical keystroke
        again -- landing "1" in each, which then merge into "11" once the first one commits. Accepting the
        event once an editor is open here stops it from reaching the host table at all."""
        super().keyPressEvent(event)
        if self.state() == QAbstractItemView.State.EditingState:
            event.accept()

    def place(self) -> None:
        """Hidden unless `table` actually needs to scroll sideways, or the pinned columns alone would leave
        less than MIN_SCROLLABLE for the rest of the table (long real names on a very narrow window: at that
        point even one scrolling column could no longer be seen, so plain scrolling serves better). In sticky
        mode, also hidden until the real column has actually scrolled past the edge it sticks to -- otherwise
        visible and positioned over its pinned columns, using the viewport's own geometry (not `table`'s
        outer size, which ignores its frame and scrollbars)."""
        vp = self.host.viewport()
        width = sum(self.host.columnWidth(c) for c in self.columns)
        if self.sticky:
            if self.side == "left":
                past_edge = self.host.columnViewportPosition(min(self.columns)) < 0
            else:
                last = max(self.columns)
                past_edge = self.host.columnViewportPosition(last) + self.host.columnWidth(last) > vp.width()
            visible = past_edge and vp.width() - width >= self.MIN_SCROLLABLE
        else:
            visible = self.host.horizontalScrollBar().maximum() > 0 and vp.width() - width >= self.MIN_SCROLLABLE
        if not visible:
            self.setVisible(False)
            return
        self.setVisible(True)
        height = vp.height() + self.host.horizontalHeader().height()
        x = vp.x() if self.side == "left" else vp.x() + vp.width() - width
        self.setGeometry(x, 0, width, height)


def freeze_columns(table: Table, columns: list[int], side: str = "left", editable: bool = False,
                    sticky: bool = False) -> FrozenColumns:
    """Pin `columns` of `table` (built by make_table()) to its left or right edge. Call once, right after
    the table is built and its edit triggers set. Visibility is left to place() (called in __init__ and on
    every resize/scroll-range change) -- never force .show() here, or a table too narrow to pin anything
    would have its overlay forced visible again, covering the columns it was supposed to leave scrollable.
    `sticky`: see FrozenColumns -- use it when `columns` does not include the table's own edge column."""
    # per-column scrolling (the default on Windows) would only ever line a column's left edge up at x=0,
    # under the overlay -- which column ends up inside the scrollable strip next to it would be down to
    # luck. Per-pixel scrolling lets any column be brought fully into view.
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    frozen = FrozenColumns(table, columns, side, editable, sticky)
    table._frozen.append(frozen)
    return frozen


def make_table(headers: list[str], stretch: int | None = 1) -> QTableWidget:
    table = Table(0, len(headers), stretch)
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.setWordWrap(False)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setHighlightSections(False)
    # Keep the order the query returns until the user clicks a column header.
    header.setSortIndicator(-1, Qt.AscendingOrder)
    return table


def fill_table(table: QTableWidget, rows: list[list], ids: list | None = None, colors: list | None = None) -> None:
    """rows: list of cell lists; a cell is a QTableWidgetItem or a plain value."""
    sync_theme_colors()  # the user may switch light/dark while the app runs
    table.setSortingEnabled(False)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            item = value if isinstance(value, QTableWidgetItem) else text_item(value)
            if ids is not None and c == 0:
                item.setData(Qt.UserRole, ids[r])
            if colors and colors[r] is not None:
                item.setBackground(QBrush(colors[r]))
            if len(item.text()) > 20:
                item.setToolTip(item.text())  # hover shows the whole name even in a narrow column
            table.setItem(r, c, item)
    table.setSortingEnabled(True)
    table.resizeColumnsToContents()
    for c in range(table.columnCount()):
        if table.columnWidth(c) > MAX_COLUMN_WIDTH:
            table.setColumnWidth(c, MAX_COLUMN_WIDTH)
    if isinstance(table, Table):
        table.natural = 0  # the width that fits the new contents
        table.fill_spare()


def only_editable(table: QTableWidget, columns) -> None:
    """After fill_table: cells of these columns can be typed into (double-click, or start typing), the
    others stay read-only."""
    table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                          | QAbstractItemView.AnyKeyPressed)
    for r in range(table.rowCount()):
        for c in range(table.columnCount()):
            item = table.item(r, c)
            if item is None:
                continue
            if c in columns:
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                item.setToolTip(t("note.edit_tip") + ("\n" + item.text() if item.text() else ""))
            else:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)


def save_stock_note(ctx: "AppContext", product_id: int, text: str, notify=True) -> bool:
    """The note kept with a product's stock (damaged, misprinted, expired boxes...). Shared by the Tồn kho and
    Kiểm kê pages; it is in the database, so it goes with the data package. Returns True when it changed."""
    from dibekho.core import catalog
    from dibekho.core.text import clean

    text = clean(text)
    row = ctx.conn.execute("SELECT code, stock_note FROM products WHERE id = ?", (product_id,)).fetchone()
    if row is None or row["stock_note"] == text:
        return False
    ctx.undo_point("stock_note")
    with db.transaction(ctx.conn):
        catalog.update_product(ctx.conn, product_id, stock_note=text)
        db.log(ctx.conn, "stock_note", row["code"])
    if notify:
        ctx.notify()
    return True


def reread_whole_note(ctx: "AppContext", parent: QWidget, doc_id: int) -> bool:
    """Forget every learned name used by this delivery note and read it (and any other active note sharing
    those names) again from scratch. Shared by the order detail window, Settings → 'Tên trên phiếu đã học'
    and the Đơn hàng list, so a wrong choice can be fixed from wherever the user happens to see the order."""
    others = deliveries.documents_sharing_names(ctx.conn, doc_id)
    if others:
        codes = [r[0] for r in ctx.conn.execute(
            f"SELECT code FROM documents WHERE id IN ({','.join('?' * len(others))}) ORDER BY doc_date",
            others)]
        text = t("doc.confirm_reread_others", orders=", ".join(codes))
    else:
        text = t("doc.confirm_reread")
    if not ask(parent, text):
        return False
    ctx.undo_point("reread")
    try:
        deliveries.forget_order(ctx.conn, ctx.ws, doc_id)
        result = deliveries.scan(ctx.conn, ctx.ws)
    except Exception as exc:
        error(parent, str(exc))
        return False
    ctx.notify()
    info(parent, t("doc.reread_done") if result.imported else t("doc.reread_pending"))
    return True


def selected_id(table: QTableWidget):
    row = table.currentRow()
    if row < 0:
        return None
    item = table.item(row, 0)
    return item.data(Qt.UserRole) if item else None


def row_id(table: QTableWidget, row: int):
    item = table.item(row, 0)
    return item.data(Qt.UserRole) if item else None


# ---- misc ------------------------------------------------------------------

def open_path(path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def title_label(text: str) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setPointSize(font.pointSize() + 5)
    font.setBold(True)
    label.setFont(font)
    return label


def hint_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {theme_color('hint')};")
    return label


def ask(parent: QWidget, text: str, title: str | None = None) -> bool:
    box = QMessageBox(QMessageBox.Question, title or t("app.name"), text, parent=parent)
    yes = box.addButton(t("btn.yes"), QMessageBox.YesRole)
    box.addButton(t("btn.no"), QMessageBox.NoRole)
    box.exec()
    answer = box.clickedButton() is yes
    activity.log("ask", f"{text} → {'yes' if answer else 'no'}")
    return answer


def info(parent: QWidget, text: str) -> None:
    activity.log("info", text)
    QMessageBox.information(parent, t("app.name"), text)


def error(parent: QWidget, text: str) -> None:
    # called from except blocks all over the app: keep the traceback, the message box only shows str(exc)
    if sys.exc_info()[0] is not None:
        activity.log_exception("error", text)
    else:
        activity.log("error", text)
    QMessageBox.warning(parent, t("app.name"), text)
