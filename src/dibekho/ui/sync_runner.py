"""Runs two-way sync in the background while the app is open (cloud mode only; docs/cloud/06-cloud-la-goc.md).

A round = pull (network, worker thread) -> merge (database, main thread, only at a safe moment: no dialog open and
not on a page where the user is typing) -> push (network, worker) -> finish (main). The window never waits on the
network. Rounds start: shortly after opening, a few seconds after any change here, and every minute (to see what
other machines and the web wrote). Closing the app sends what is still queued, briefly."""

import sqlite3
import threading
import time
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from dibekho.core import activity, backup
from dibekho.core.cloud import inbox as cloud_inbox
from dibekho.core.cloud import replica, twoway
from dibekho.core.cloud import sync as cloud_sync
from dibekho.core.cloud.client import CloudError, SessionExpired
from dibekho.i18n import t

PERIOD = 60_000  # ms between rounds when nothing happens here
AFTER_CHANGE = 5_000  # ms after a change here before it is sent (several quick edits travel together)
RETRY_UNSAFE = 15_000  # ms: the user was busy on a page, try again soon
CLOSE_TIMEOUT = 8  # s per request while closing


class SyncRunner(QObject):
    _done = Signal(object, object, object)  # callback, result, error: delivered on the main thread
    status_changed = Signal()

    def __init__(self, ctx, is_safe, tell, parent=None):
        """is_safe(): may rows change under the user now? tell(text): show the user a notice (renumbered codes...)."""
        super().__init__(parent)
        self.ctx, self.is_safe, self.tell = ctx, is_safe, tell
        self.busy = False
        self.last_ok: datetime | None = None
        self.last_error = ""
        self.signed_out = False
        self._done.connect(lambda then, result, err: then(result, err))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.start)
        self.timer.start(PERIOD)
        self.soon = QTimer(self)
        self.soon.setSingleShot(True)
        self.soon.timeout.connect(self.start)
        ctx.changed.connect(self._changed_here)

    # ---------------------------------------------------------------- state
    def active(self) -> bool:
        cfg = self.ctx.cfg
        return bool(cfg.cloud_url and cfg.cloud_refresh_token) and replica.enabled(self.ctx.conn)

    def status_text(self) -> str:
        if not replica.enabled(self.ctx.conn):
            return ""
        parts = []
        conflicts = len(twoway.conflicts(self.ctx.conn))
        if conflicts:
            parts.append(t("sync.conflicts", n=conflicts))
        queued = twoway.queued_count(self.ctx.conn)
        if self.signed_out:
            parts.append(t("sync.signed_out", n=queued))
        elif self.last_error:
            parts.append(t("sync.offline", n=queued))
        elif self.last_ok:
            parts.append(t("sync.ok", at=self.last_ok.strftime("%H:%M")) + (f" · {t('sync.queued', n=queued)}" if queued else ""))
        else:
            parts.append(t("sync.waiting"))
        return " · ".join(parts)

    def _changed_here(self) -> None:
        if self.active() and not self.busy and twoway.queued_count(self.ctx.conn):
            self.soon.start(AFTER_CHANGE)

    def _background(self, work, then) -> None:
        def target():
            try:
                self._done.emit(then, work(), None)
            except Exception as exc:  # delivered to `then`
                self._done.emit(then, None, exc)
        threading.Thread(target=target, daemon=True).start()

    def _failed(self, err) -> None:
        self.busy = False
        if str(err) != self.last_error:  # offline for hours (lid closed, another network): one line, not one a minute
            activity.log("error", f"cloud sync: {err}")
        self.last_error = str(err)
        self.signed_out = isinstance(err, SessionExpired)
        self.status_changed.emit()

    # ---------------------------------------------------------------- a round
    def start(self, tries: int = 3) -> None:
        if self.busy or self.ctx.conn is None or not self.active():  # conn is None while the file is being replaced
            return
        self.busy = True
        cfg, after = self.ctx.cfg, twoway.cursor(self.ctx.conn)

        def pull():
            pair = cloud_sync.session(cfg, timeout=15)
            if pair is None:
                return None
            client, token = pair
            return client, token, twoway.fetch(client, token, after)

        self._background(pull, lambda result, err: self._pulled(result, err, tries, after))

    def _pulled(self, result, err, tries, after=None) -> None:
        if err is not None:
            return self._failed(err)
        # the data was replaced meanwhile (restore / package / delete all on shared data): this pull is stale
        if result is None or self.ctx.conn is None or (after is not None and twoway.cursor(self.ctx.conn) != after):
            self.busy = False
            return None
        client, token, pulled = result
        # rows from elsewhere wait until the user is not typing (Kiểm kê, Cần xử lý, an open window); what was saved
        # here still goes at once when nothing came in (a transfer saved from Kiểm kê once waited for ever)
        if not self.is_safe() and not twoway.nothing_new(pulled):
            self.busy = False
            self.soon.start(RETRY_UNSAFE)
            return None
        conn = self.ctx.conn
        merged = twoway.merge(conn, pulled)
        try:
            twoway.export_renamed(conn, self.ctx.ws, merged)
        except OSError as exc:
            activity.log("error", f"receipt file after renumbering: {exc}")
        if merged.applied or merged.renamed:
            self.ctx.notify()
        self._tell_about(merged)
        batch, seq, hold = twoway.prepare(conn)
        if twoway.empty(batch):
            self._confirm_requests(client, token)
            return self._finished()
        expected, device = twoway.cursor(conn), self.ctx.cfg.device_id
        self._background(lambda: twoway.send(client, token, device, expected, batch),
                         lambda answer, e: self._sent(answer, e, seq, hold, tries, client, token))
        return None

    def _sent(self, answer, err, seq, hold, tries, client=None, token=None) -> None:
        if err is not None:
            return self._failed(err)
        if answer.get("ok"):
            twoway.finish(self.ctx.conn, seq, int(answer["max_rev"]), hold)
            self._confirm_requests(client, token)
            return self._finished()
        self.busy = False  # someone wrote in between: pull again
        if tries > 1:
            self.start(tries - 1)
        return None

    def _confirm_requests(self, client, token) -> None:
        """Staff requests approved here are marked done on the web once their documents are on the cloud."""
        conn = self.ctx.conn
        if client is None or not cloud_inbox.applied_map(conn) or twoway.queued_count(conn):
            return
        try:
            cloud_inbox.finish_applied(conn, client, token)
        except CloudError as exc:  # tried again after the next round
            activity.log("error", f"confirming web requests: {exc}")

    def _finished(self) -> None:
        self.busy = False
        self.last_ok, self.last_error, self.signed_out = datetime.now(), "", False
        try:  # once a day, a full copy of the shared data as it now is (also for an app left open for days)
            backup.daily_backup(self.ctx.conn, self.ctx.ws, prefix=backup.SHARED_PREFIX)
        except (OSError, sqlite3.DatabaseError) as exc:
            activity.log("error", f"daily copy of the shared data: {exc}")
        self.status_changed.emit()

    def _tell_about(self, merged) -> None:
        lines = [t("sync.renamed", old=old, new=new) for _, old, new in merged.renamed]
        lines += [t("sync.separated", code=code) for code in merged.separated]
        if merged.duplicates:
            lines.append(t("sync.duplicates", n=merged.duplicates))
        if merged.conflicts:
            lines.append(t("sync.new_conflicts", n=len(merged.conflicts)))
        if lines:
            activity.log("cloud", "; ".join(lines))
            self.tell("\n".join(lines))

    # ---------------------------------------------------------------- closing the app
    def send_before_closing(self) -> None:
        """Bounded: what is still queued goes now if the line allows; otherwise at the next opening."""
        if not self.active() or not twoway.queued_count(self.ctx.conn):
            return
        started = time.monotonic()
        try:
            pair = cloud_sync.session(self.ctx.cfg, timeout=CLOSE_TIMEOUT)
            if pair is None:
                return
            client, token = pair
            result = twoway.sync_round(self.ctx.conn, client, token, self.ctx.cfg.device_id, tries=2)
            for merged in result.merged:
                twoway.export_renamed(self.ctx.conn, self.ctx.ws, merged)
        except (CloudError, OSError) as exc:
            activity.log("error", f"cloud sync on close ({time.monotonic() - started:.0f}s): {exc}")
