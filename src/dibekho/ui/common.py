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
    QMenu,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from dibekho import db
from dibekho.core import activity, undo
from dibekho.core.text import fmt_qty, parse_number
from dibekho.core.workspace import Config, Workspace
from dibekho.i18n import t

# Row highlight colours. Light theme: pale backgrounds; dark theme (e.g. macOS Dark Mode): deep tones,
# so the white text stays readable. sync_theme_colors() updates these objects in place.
_THEMES = {
    "light": {"RED": "#fde2e1", "YELLOW": "#fff4cc", "hint": "#666666", "banner": "#eef5ff", "alert": "#c0392b"},
    "dark": {"RED": "#6e2a2a", "YELLOW": "#5e4c14", "hint": "#a0a0a0", "banner": "#1f3550", "alert": "#ff7b72"},
}
RED = QColor(_THEMES["light"]["RED"])
YELLOW = QColor(_THEMES["light"]["YELLOW"])
GREY = QColor("#888888")


def is_dark() -> bool:
    app = QApplication.instance()
    return app is not None and app.palette().color(QPalette.Window).lightness() < 128


def theme_color(name: str) -> str:
    """'hint', 'banner' or 'alert' for the current light/dark theme."""
    return _THEMES["dark" if is_dark() else "light"][name]


def sync_theme_colors() -> None:
    colors = _THEMES["dark" if is_dark() else "light"]
    RED.setRgb(QColor(colors["RED"]).rgb())
    YELLOW.setRgb(QColor(colors["YELLOW"]).rgb())


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


class Table(QTableWidget):
    """Every column can be dragged wider (or double-click its border to fit its contents).
    The 'stretch' column also takes the spare width when the window is wider than the columns."""

    def __init__(self, rows: int, columns: int, stretch: int | None):
        super().__init__(rows, columns)
        self.stretch = stretch
        self.natural = 0  # width of the stretch column before it took the spare width

    def fill_spare(self) -> None:
        if self.stretch is None or self.stretch >= self.columnCount():
            return
        others = sum(self.columnWidth(c) for c in range(self.columnCount()) if c != self.stretch)
        self.natural = self.natural or self.columnWidth(self.stretch)
        self.setColumnWidth(self.stretch, max(self.natural, self.viewport().width() - others))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fill_spare()


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
