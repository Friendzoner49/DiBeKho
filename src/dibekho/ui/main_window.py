import threading
import time

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from dibekho import APP_NAME, __version__
from dibekho.core import activity, deliveries, inbox, undo
from dibekho.core.cloud import inbox as inbox_mod
from dibekho.core.cloud import commands as cloud_commands
from dibekho.core.cloud import sync as cloud_sync
from dibekho.core.cloud import replica, twoway
from dibekho.core.cloud.client import CloudError, local_time
from dibekho.i18n import t
from dibekho.ui.common import AppContext, ask, error, fit_window, info, open_path
from dibekho.ui.conflict_dialog import ConflictDialog
from dibekho.ui.count_page import CountPage
from dibekho.ui.pending_page import PendingPage
from dibekho.ui.receipt_page import ReceiptPage
from dibekho.ui.search_page import SearchPage
from dibekho.ui.settings_page import SettingsPage
from dibekho.ui.stock_page import StockPage
from dibekho.ui.sync_runner import SyncRunner

PENDING, SEARCH, COUNT = 1, 2, 4  # rows in the navigation list
# pages where the user types work a refresh would wipe (mapping choices, counted numbers): the owner's web
# commands wait until the user is somewhere else
UNSAFE_PAGES = (PENDING, COUNT)
OWNER_POLL = 30_000  # ms between looks at the owner's waiting items; the cloud is asked every 6th time
CLOSE_TIMEOUT = 8  # s per cloud request while closing the app
CLOSE_SLOW = 12  # s: a push slower than this skips the full backup


class MainWindow(QMainWindow):
    _bg_done = Signal(object, object, object)  # callback, result, error: always delivered on the main thread

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self._pulling = False
        self._bg_done.connect(self._bg_finished)
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        fit_window(self, 1280, 800)
        self._restore_geometry()

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
            if page is self.pending:
                # its sections stack up (orders without a place, unknown names, counts, web requests, files): on a
                # small screen it scrolls instead of making the whole window taller than the screen
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QFrame.NoFrame)
                scroll.setWidget(page)
                page = scroll
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
        self.sync_btn = QPushButton()  # cloud mode only: sync state; click = conflicts to decide, or sync now
        self.sync_btn.setFlat(True)
        self.sync_btn.clicked.connect(self._sync_clicked)
        top.addWidget(self.sync_btn)
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
        # cloud as the source of truth (docs/cloud/06): two-way sync in the background
        self.sync = SyncRunner(ctx, self._owner_safe, lambda text: info(self, text), self)
        ctx.sync_runner = self.sync
        self.sync.status_changed.connect(self._update_sync)
        ctx.changed.connect(self._update_sync)
        self._update_sync()
        QTimer.singleShot(2500, self.sync.start)
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
            # the button also refreshes requests sent from the web; the user asked: show them when they arrive
            self._pull_async(check_conflict=False, notify=True, explicit=True)
        if result.imported or not quiet:
            self.ctx.notify()
        self._update_badge(result)
        return result

    def _in_background(self, work, then) -> None:
        """Run `work` (network only, never the database connection) off the main thread; `then(result, error)` runs
        back on it. The window stays usable while the cloud answers (a slow line froze it for seconds)."""
        def target():
            try:
                self._bg_done.emit(then, work(), None)
            except Exception as exc:  # delivered to `then`, which decides what a failure means
                self._bg_done.emit(then, None, exc)
        threading.Thread(target=target, daemon=True).start()

    def _bg_finished(self, then, result, err) -> None:
        then(result, err)

    def _pull_async(self, check_conflict: bool, notify: bool, explicit: bool = False) -> None:
        """Ask the cloud for the web inbox without blocking. The database is read here, the network in the thread."""
        if self._pulling:
            return
        cfg, conn = self.ctx.cfg, self.ctx.conn
        seen = inbox_mod.applied_map(conn)
        unpushed = check_conflict and cloud_sync.has_unpushed(conn)
        last_seen = cloud_sync.last_push(conn)[0] if unpushed else None

        def work():
            pair = cloud_sync.session(cfg, timeout=10)
            if pair is None:
                return None
            client, token = pair
            state = cloud_sync.fetch_state(client, token) if unpushed else None
            auto, manual = cloud_commands.pull(None, client, token, seen)
            return state, auto, manual

        def then(result, err):
            self._pulling = False
            if err is not None:
                activity.log("error", f"cloud pull: {err}")
                return
            if result is None:
                return
            state, auto, manual = result
            if state and state["device_id"] != cfg.device_id and state["last_push_id"] != last_seen:
                info(self, t("cloud.open_conflict", device=state.get("device_name", "?"),
                             at=local_time(state.get("last_push_at"))))
            activity.log("cloud", f"web inbox: {len(manual)} to approve, {len(auto)} from the owner")
            self.ctx.web_inbox, self.ctx.owner_waiting = manual, auto
            if notify and (explicit or self._owner_safe()):  # explicit = Quét lại pressed: refresh whatever page
                self.ctx.notify()
            else:
                self._update_badge(self._last)
            self._maybe_apply_owner()

        self._pulling = True
        self._in_background(work, then)

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
        if replica.enabled(self.ctx.conn):
            return self._update_cloud_undo()
        point = undo.latest(self.ctx.ws)
        self.undo_btn.setEnabled(point is not None)
        if point is None:
            self.undo_btn.setText(t("undo.button_none"))
            self.undo_btn.setToolTip(t("undo.none"))
            return
        action = t(f"undo.{point.action}")
        self.undo_btn.setText(t("undo.button", action=action))
        self.undo_btn.setToolTip(t("undo.tip", action=action, at=point.at.strftime("%d/%m/%Y %H:%M")))

    def _update_cloud_undo(self):
        point = undo.cloud_latest(self.ctx.conn)
        self.undo_btn.setEnabled(point is not None)
        if point is None:
            self.undo_btn.setText(t("undo.button_none"))
            self.undo_btn.setToolTip(t("undo.cloud_none"))
            return
        action = t(f"undo.{point.action}")
        self.undo_btn.setText(t("undo.button", action=f"{action} {point.code}".strip()))
        self.undo_btn.setToolTip(t("undo.cloud_tip", code=point.code))

    def undo_cloud(self):
        """On shared data: cancel the document this machine has just saved (like Huỷ phiếu), never an old file."""
        point = undo.cloud_latest(self.ctx.conn)
        if point is None:
            self._update_undo()
            return
        action = t(f"undo.{point.action}")
        if not ask(self, t("undo.cloud_confirm", action=action, code=point.code)):
            return
        activity.log("undo", f"cloud {point.action} #{point.doc_id}")
        try:
            undo.cloud_undo(self.ctx.conn, point)
        except ValueError as exc:  # cancelled elsewhere in the meantime
            error(self, str(exc))
        self.ctx.notify()
        info(self, t("undo.cloud_done", action=action, code=point.code))

    def undo_last(self):
        """Put the data back as it was just before the last action that left an undo point."""
        if replica.enabled(self.ctx.conn):
            return self.undo_cloud()
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

    def _restore_geometry(self) -> None:
        """Open the way the window was left (size, place, maximised), if that still fits a screen."""
        saved = getattr(self.ctx.cfg, "_extras", {}).get("window_geometry")
        if isinstance(saved, str):
            try:
                self.restoreGeometry(QByteArray.fromBase64(saved.encode("ascii")))
            except (ValueError, UnicodeError):
                pass

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_placed", False):
            self._placed = True
            QTimer.singleShot(0, self._keep_on_screen)  # after the title bar exists: its height counts too

    def _keep_on_screen(self) -> None:
        """The whole window, title bar included, inside the screen's free area (not under the taskbar). A size saved
        on a larger screen or at another zoom must not open half off the screen."""
        if self.isMaximized() or self.isFullScreen():
            return
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        frame = self.frameGeometry()
        extra_w, extra_h = frame.width() - self.width(), frame.height() - self.height()
        w = min(self.width(), avail.width() - extra_w)
        h = min(self.height(), avail.height() - extra_h)
        if (w, h) != (self.width(), self.height()):
            self.resize(w, h)
            frame = self.frameGeometry()
        x = min(max(frame.x(), avail.x()), avail.right() - frame.width() + 1)
        y = min(max(frame.y(), avail.y()), avail.bottom() - frame.height() + 1)
        if (x, y) != (frame.x(), frame.y()):
            self.move(x, y)

    def _save_geometry(self) -> None:
        try:
            extras = self.ctx.cfg.__dict__.setdefault("_extras", {})
            extras["window_geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self.ctx.cfg.save()
        except OSError:
            pass

    def _update_sync(self) -> None:
        text = self.sync.status_text()
        self.sync_btn.setText(text)
        self.sync_btn.setVisible(bool(text))

    def _sync_clicked(self) -> None:
        if twoway.conflicts(self.ctx.conn):
            ConflictDialog(self.ctx, self).exec()
            self._update_sync()
        else:
            self.sync.start()

    def closeEvent(self, event):
        self._save_geometry()
        self.sync.timer.stop()
        self.sync.send_before_closing()
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
        if self.ctx.conn is None:  # the window is gone or the file is being replaced
            return
        self._pull_async(check_conflict=True, notify=True)

    # ------------------------------------------------------------ the owner's commands from the web

    def _owner_safe(self) -> bool:
        """No dialog open and the user is not in the middle of typing on Cần xử lý or Kiểm kê."""
        return QApplication.activeModalWidget() is None and self.nav.currentRow() not in UNSAFE_PAGES

    def _owner_tick(self) -> None:
        self._ticks += 1
        if self._ticks % 6 == 0 and QApplication.activeModalWidget() is None:  # ask the cloud every ~3 minutes
            self._pull_async(check_conflict=False, notify=True)
        self._maybe_apply_owner()

    def _maybe_apply_owner(self) -> None:
        if self.ctx.owner_waiting and self._owner_safe():
            QTimer.singleShot(0, self._apply_owner_waiting)  # not inside the signal that got us here

    def _apply_owner_waiting(self) -> None:
        """Carry out the owner's web items now: one undo point for the batch, push so the web shows the result, and say
        plainly what was done and by whom, so nobody presses Hoàn tác blindly."""
        if self.ctx.conn is None or not self.ctx.owner_waiting or not self._owner_safe():
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
