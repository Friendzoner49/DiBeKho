import time

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
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
from dibekho.core.cloud import commands as cloud_commands
from dibekho.core.cloud import sync as cloud_sync
from dibekho.core.cloud.client import CloudError, local_time
from dibekho.i18n import t
from dibekho.ui.common import AppContext, ask, error, fit_window, info, open_path
from dibekho.ui.count_page import CountPage
from dibekho.ui.pending_page import PendingPage
from dibekho.ui.receipt_page import ReceiptPage
from dibekho.ui.search_page import SearchPage
from dibekho.ui.settings_page import SettingsPage
from dibekho.ui.stock_page import StockPage

PENDING, SEARCH, COUNT = 1, 2, 4  # rows in the navigation list
# pages where the user types work a refresh would wipe (mapping choices, counted numbers): the owner's web
# commands wait until the user is somewhere else
UNSAFE_PAGES = (PENDING, COUNT)
OWNER_POLL = 30_000  # ms between looks at the owner's waiting items; the cloud is asked every 6th time
CLOSE_TIMEOUT = 8  # s per cloud request while closing the app
CLOSE_SLOW = 12  # s: a push slower than this skips the full backup


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
        QTimer.singleShot(1500, self._cloud_check_on_open)  # after the window is up, not before
        # The shop app is open all day: the owner's commands sent from home must not wait for the next start.
        self._ticks = 0
        self._owner_timer = QTimer(self)
        self._owner_timer.timeout.connect(self._owner_tick)
        self._owner_timer.start(OWNER_POLL)
        ctx.changed.connect(self._maybe_apply_owner)

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
        if not quiet:
            self._cloud_pull_inbox()  # the button also refreshes orders typed on the web
        if result.imported or not quiet:
            self.ctx.notify()
        self._update_badge(result)
        return result

    def _cloud_pull_inbox(self):
        try:
            pair = cloud_sync.session(self.ctx.cfg, timeout=10)
            if pair is not None:
                self._take_inbox(*pair)
        except CloudError as exc:
            activity.log("error", f"cloud pull inbox: {exc}")

    def _take_inbox(self, client, token) -> None:
        """Pull the web inbox: requests for approval go to Cần xử lý, the owner's own items wait for a safe moment."""
        auto, manual = cloud_commands.pull(self.ctx.conn, client, token)
        activity.log("cloud", f"web inbox: {len(manual)} to approve, {len(auto)} from the owner")
        self.ctx.web_inbox, self.ctx.owner_waiting = manual, auto

    def _update_badge(self, result=None):
        pending = (deliveries.pending_count(self.ctx.conn) + deliveries.unplaced_count(self.ctx.conn)
                   + len(deliveries.count_conflicts(self.ctx.conn)) + len(inbox.items(self.ctx.conn, self.ctx.ws))
                   + len(self.ctx.web_inbox))
        label = t("nav.pending") + (f"  ({pending})" if pending else "")
        self.nav.item(PENDING).setText(label)
        self.nav.item(PENDING).setForeground(Qt.red if pending else self.nav.palette().text().color())
        parts = []
        if result is not None:
            parts.append(t("main.scan_result", count=len(result.imported)))
        if pending:
            parts.append(t("main.pending", count=pending))
        if self.ctx.owner_waiting:
            parts.append(t("web.owner_waiting", n=len(self.ctx.owner_waiting)))
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
        self._cloud_push_on_close()
        self.ctx.close()
        super().closeEvent(event)

    # ------------------------------------------------------------ cloud (docs/cloud/04, step 6)

    def _cloud_push_on_close(self):
        """Closing a work session puts it on the cloud, so the other machine (and the web) see it next.
        Offline or expired session: skip silently -- the next open or a manual sync catches up.
        Bounded: each request waits at most CLOSE_TIMEOUT s, and the full backup is skipped when the push
        itself was slow, so the window cannot look frozen for a minute on a poor line."""
        try:
            if not cloud_sync.has_unpushed(self.ctx.conn):
                return
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
            started = time.monotonic()
            pair = cloud_sync.session(self.ctx.cfg, timeout=CLOSE_TIMEOUT)
            if pair is None:
                return
            client, token = pair
            result = cloud_sync.push_mirror(self.ctx.conn, self.ctx.cfg, client, token)
            if result["conflict"]:
                QGuiApplication.restoreOverrideCursor()  # a question for the user: show the normal cursor
                if self._ask_cloud_overwrite(result):
                    QGuiApplication.setOverrideCursor(Qt.WaitCursor)
                    result = cloud_sync.push_mirror(self.ctx.conn, self.ctx.cfg, client, token, force=True)
            if not result["conflict"]:
                slow = time.monotonic() - started > CLOSE_SLOW
                cloud_sync.finish_push(self.ctx.conn, self.ctx.cfg, client, token, with_backup=not slow)
                if slow:
                    activity.log("cloud", "slow line on close: full backup skipped, the next push makes it")
        except CloudError as exc:
            activity.log("error", f"cloud push on close: {exc}")
        finally:
            while QGuiApplication.overrideCursor() is not None:
                QGuiApplication.restoreOverrideCursor()

    def _cloud_check_on_open(self):
        """Pull the web inbox into 'Cần xử lý', and when another machine pushed after our last push AND this
        machine holds unpushed changes, say so now, before more work piles onto both sides. The choice itself
        happens at push time (ask, never silent)."""
        try:
            pair = cloud_sync.session(self.ctx.cfg, timeout=10)
            if pair is None:
                return
            client, token = pair
            if cloud_sync.has_unpushed(self.ctx.conn):
                state = cloud_sync.fetch_state(client, token)
                last_seen, _ = cloud_sync.last_push(self.ctx.conn)
                if state and state["device_id"] != self.ctx.cfg.device_id and state["last_push_id"] != last_seen:
                    when = local_time(state.get("last_push_at"))
                    info(self, t("cloud.open_conflict", device=state.get("device_name", "?"), at=when))
            self._take_inbox(client, token)
            if self.ctx.web_inbox or self.ctx.owner_waiting:
                self.ctx.notify()
        except CloudError as exc:
            activity.log("error", f"cloud check on open: {exc}")

    # ------------------------------------------------------------ the owner's commands from the web

    def _owner_safe(self) -> bool:
        """No dialog open and the user is not in the middle of typing on Cần xử lý or Kiểm kê."""
        return QApplication.activeModalWidget() is None and self.nav.currentRow() not in UNSAFE_PAGES

    def _owner_tick(self) -> None:
        self._ticks += 1
        if self._ticks % 6 == 0 and QApplication.activeModalWidget() is None:  # ask the cloud every ~3 minutes
            try:
                pair = cloud_sync.session(self.ctx.cfg, timeout=10)
                if pair is not None:
                    self._take_inbox(*pair)
                    if self._owner_safe():
                        self.ctx.notify()
                    else:
                        self._update_badge(self._last)
            except CloudError as exc:
                activity.log("error", f"cloud poll: {exc}")
        self._maybe_apply_owner()

    def _maybe_apply_owner(self) -> None:
        if self.ctx.owner_waiting and self._owner_safe():
            QTimer.singleShot(0, self._apply_owner_waiting)  # not inside the signal that got us here

    def _apply_owner_waiting(self) -> None:
        """Carry out the owner's web items now: one undo point for the batch, push so the web shows the result, and say
        plainly what was done and by whom, so nobody presses Hoàn tác blindly."""
        if not self.ctx.owner_waiting or not self._owner_safe():
            return
        items, self.ctx.owner_waiting = self.ctx.owner_waiting, []
        try:
            pair = cloud_sync.session(self.ctx.cfg, timeout=15)
            if pair is None:
                return
            client, token = pair
            self.ctx.undo_point("web_commands")
            outcomes = cloud_commands.apply_owner_items(self.ctx.conn, self.ctx.ws, client, token, items)
            if not outcomes:
                return
            self.ctx.notify()
            self.rescan(quiet=True)  # a delivery note the owner sent is only put in the folder: read it now
            try:
                result = cloud_sync.push_mirror(self.ctx.conn, self.ctx.cfg, client, token)
                if not result["conflict"]:
                    cloud_sync.finish_push(self.ctx.conn, self.ctx.cfg, client, token)
            except CloudError as exc:
                activity.log("error", f"push after web commands: {exc}")  # the next push or close does it
        except CloudError as exc:
            self.ctx.owner_waiting = items + self.ctx.owner_waiting  # nothing was done: try again later
            activity.log("error", f"owner commands: {exc}")
            return
        done = [o for o in outcomes if o.ok]
        lines = [f"• {o.summary}" for o in done] + [t("web.owner_refused", what=o.item.get("kind", ""), why=o.summary)
                                                       for o in outcomes if not o.ok]
        info(self, t("web.owner_done", n=len(done)) + "\n" + "\n".join(lines))

    def _ask_cloud_overwrite(self, result) -> bool:
        other = result.get("last_push") or {}
        when = local_time(other.get("last_push_at"))
        return ask(self, t("cloud.conflict", device=other.get("device_name", "?"), at=when))
