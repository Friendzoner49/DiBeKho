"""Shared UI helpers: app context, tables, formatting, messages."""

import sqlite3
from datetime import date

from PySide6.QtCore import QDate, QObject, Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from dibekho import db
from dibekho.core.text import fmt_qty
from dibekho.core.workspace import Config, Workspace
from dibekho.i18n import t

RED = QColor("#fde2e1")
YELLOW = QColor("#fff4cc")
GREY = QColor("#888888")


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

    def close(self) -> None:
        self.conn.close()
        self.conn = None

    def reopen(self) -> None:
        if self.conn is not None:
            self.conn.close()
        self.conn = db.connect(self.ws.db_path)
        self.notify()


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


def make_table(headers: list[str], stretch: int | None = 1) -> QTableWidget:
    table = QTableWidget(0, len(headers))
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
    if stretch is not None:
        header.setSectionResizeMode(stretch, QHeaderView.Stretch)
    return table


def fill_table(table: QTableWidget, rows: list[list], ids: list | None = None, colors: list | None = None) -> None:
    """rows: list of cell lists; a cell is a QTableWidgetItem or a plain value."""
    table.setSortingEnabled(False)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            item = value if isinstance(value, QTableWidgetItem) else text_item(value)
            if ids is not None and c == 0:
                item.setData(Qt.UserRole, ids[r])
            if colors and colors[r] is not None:
                item.setBackground(QBrush(colors[r]))
            table.setItem(r, c, item)
    table.setSortingEnabled(True)
    table.resizeColumnsToContents()
    for c in range(table.columnCount()):
        if table.columnWidth(c) > 380:
            table.setColumnWidth(c, 380)


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
    label.setStyleSheet("color: #666;")
    return label


def ask(parent: QWidget, text: str, title: str | None = None) -> bool:
    box = QMessageBox(QMessageBox.Question, title or t("app.name"), text, parent=parent)
    yes = box.addButton(t("btn.yes"), QMessageBox.YesRole)
    box.addButton(t("btn.no"), QMessageBox.NoRole)
    box.exec()
    return box.clickedButton() is yes


def info(parent: QWidget, text: str) -> None:
    QMessageBox.information(parent, t("app.name"), text)


def error(parent: QWidget, text: str) -> None:
    QMessageBox.warning(parent, t("app.name"), text)
