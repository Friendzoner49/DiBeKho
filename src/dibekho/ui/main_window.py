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
from dibekho.core import deliveries, inbox
from dibekho.i18n import t
from dibekho.ui.common import AppContext, error, open_path
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
        self.resize(1280, 800)

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

        top = QHBoxLayout()
        scan = QPushButton(t("main.rescan"))
        scan.setToolTip("F5")
        scan.clicked.connect(lambda: self.rescan())
        open_notes = QPushButton(t("main.open_deliveries"))
        open_notes.clicked.connect(lambda: open_path(ctx.ws.deliveries))
        self.status = QLabel()
        top.addWidget(scan)
        top.addWidget(open_notes)
        top.addWidget(self.status, 1)

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

    def rescan(self, quiet: bool = False, allow_partial: bool = False):
        """Scan phieu-giao-hang/ and refresh everything. quiet=True: only notify if something changed.
        allow_partial=True after 'Apply': waiting notes are imported with their approved lines."""
        try:
            result = deliveries.scan(self.ctx.conn, self.ctx.ws, allow_partial)
        except Exception as exc:
            error(self, t("main.scan_failed", error=str(exc)))
            return None
        self._last = result
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

    def show_pending(self):
        self.rescan(quiet=True)
        self.nav.setCurrentRow(PENDING)

    def show_search(self):
        self.nav.setCurrentRow(SEARCH)
        self.search.focus()

    def closeEvent(self, event):
        self.ctx.close()
        super().closeEvent(event)
