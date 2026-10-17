from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from dibekho import APP_NAME, __version__
from dibekho.core import activity, deliveries, inbox, undo
from dibekho.i18n import t
from dibekho.ui.common import AppContext, ask, error, fit_window, info, open_path
from dibekho.ui.count_page import CountPage
from dibekho.ui.pending_page import PendingPage
from dibekho.ui.receipt_page import ReceiptPage
from dibekho.ui.search_page import SearchPage
from dibekho.ui.settings_page import SettingsPage
from dibekho.ui.stock_page import StockPage

PENDING, SEARCH = 1, 2  # rows in the navigation list


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        fit_window(self, 1280, 800)

        self.nav = QListWidget()
        self.nav.setFixedWidth(200)
        self.nav.setIconSize(QSize(20, 20))
        font = self.nav.font()
        font.setPointSize(font.pointSize() + 1)
        self.nav.setFont(font)
        self.nav.setSpacing(2)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.stack = QStackedWidget()

        self.pending = PendingPage(ctx, self.rescan)
        self.search = SearchPage(ctx)
        # Orders, customers and statistics are opened from buttons on the search screen (used less often);
        # data transfer and backups live in a tab of the settings screen.
        pages = [
            ("nav.stock", StockPage(ctx)),
            ("nav.pending", self.pending),
            ("nav.search", self.search),
            ("nav.receipts", ReceiptPage(ctx, self.show_pending)),
            ("nav.count", CountPage(ctx, self.rescan)),
            ("nav.settings", SettingsPage(ctx, self.show_pending)),
        ]
        for key, page in pages:
            self.nav.addItem(QListWidgetItem(t(key)))
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.currentRowChanged.connect(
            lambda r: r >= 0 and activity.log("page", self.nav.item(r).text().split("  (")[0]))

        top = QHBoxLayout()
        scan = QPushButton(t("main.rescan"))
        scan.setToolTip("F5")
        scan.clicked.connect(lambda: self.rescan())
        open_notes = QPushButton(t("main.open_deliveries"))
        open_notes.clicked.connect(lambda: open_path(ctx.ws.deliveries))
        self.undo_btn = QPushButton()
        self.undo_btn.clicked.connect(self.undo_last)
        self.status = QLabel()
        top.addWidget(scan)
        top.addWidget(open_notes)
        top.addWidget(self.status, 1)
        top.addWidget(self.undo_btn)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.addLayout(top)
        right_lay.addWidget(self.stack)
        body = QWidget()
        lay = QHBoxLayout(body)
        lay.addWidget(self.nav)
        lay.addWidget(right, 1)
        self.setCentralWidget(body)

        refresh = QAction(self)
        refresh.setShortcut(QKeySequence(Qt.Key_F5))
        refresh.triggered.connect(lambda: self.rescan())
        self.addAction(refresh)
        find = QAction(self)
        find.setShortcut(QKeySequence.Find)
        find.triggered.connect(self.show_search)
        self.addAction(find)

        self.nav.setCurrentRow(0)
        self._last = None
        self._update_badge()
        # e.g. a note read again from its detail window: keep the 'Cần xử lý' counter current
        ctx.changed.connect(lambda: self._update_badge(self._last))
        ctx.changed.connect(self._update_undo)
        self._update_undo()

    def rescan(self, quiet: bool = False, allow_partial: bool = False):
        """Scan phieu-giao-hang/ and refresh everything. quiet=True: only notify if something changed.
        allow_partial=True after 'Apply': waiting notes are imported with their approved lines."""
        try:
            result = deliveries.scan(self.ctx.conn, self.ctx.ws, allow_partial)
        except Exception as exc:
            error(self, t("main.scan_failed", error=str(exc)))
            return None
        self._last = result
        if result.imported or result.pending:
            activity.log("scan", f"read {len(result.imported)}: {', '.join(result.imported)} · waiting {result.pending}"
                         if result.imported else f"waiting {result.pending}")
        if result.imported or not quiet:
            self.ctx.notify()
        self._update_badge(result)
        return result

    def _update_badge(self, result=None):
        pending = deliveries.pending_count(self.ctx.conn) + len(inbox.items(self.ctx.conn, self.ctx.ws))
        label = t("nav.pending") + (f"  ({pending})" if pending else "")
        self.nav.item(PENDING).setText(label)
        self.nav.item(PENDING).setForeground(Qt.red if pending else self.nav.palette().text().color())
        parts = []
        if result is not None:
            parts.append(t("main.scan_result", count=len(result.imported)))
        if pending:
            parts.append(t("main.pending", count=pending))
        self.status.setText(" · ".join(parts))

    def _update_undo(self):
        point = undo.latest(self.ctx.ws)
        self.undo_btn.setEnabled(point is not None)
        if point is None:
            self.undo_btn.setText(t("undo.button_none"))
            self.undo_btn.setToolTip(t("undo.none"))
            return
        action = t(f"undo.{point.action}")
        self.undo_btn.setText(t("undo.button", action=action))
        self.undo_btn.setToolTip(t("undo.tip", action=action, at=point.at.strftime("%d/%m/%Y %H:%M")))

    def undo_last(self):
        """Put the data back as it was just before the last action that left an undo point."""
        point = undo.latest(self.ctx.ws)
        if point is None:
            return
        action = t(f"undo.{point.action}")
        if not ask(self, t("undo.confirm", action=action, at=point.at.strftime("%d/%m/%Y %H:%M"))):
            return
        activity.log("undo", f"{point.action} ({point.at:%d/%m/%Y %H:%M})")
        try:
            self.ctx.close()
            undo.undo(self.ctx.ws, point)
        except Exception as exc:
            error(self, str(exc))
        finally:
            self.ctx.reopen()
        self.rescan(quiet=True)  # notes go back in or out of da-xu-ly/ as the restored data says
        self.ctx.notify()
        info(self, t("undo.done", action=action))

    def show_pending(self):
        self.rescan(quiet=True)
        self.nav.setCurrentRow(PENDING)

    def show_search(self):
        self.nav.setCurrentRow(SEARCH)
        self.search.focus()

    def closeEvent(self, event):
        self.ctx.close()
        super().closeEvent(event)
