"""'Cloud' tab in Settings (user's request 15/11/2026: the app signs in when it opens and always works on the shared
data, docs/cloud/06-cloud-la-goc.md): who is signed in, Đăng xuất, Đồng bộ ngay (a sync round now; on the owner's
machine also the full backup in Storage), restore from a cloud backup (owner), the conflicts to decide, and on a
staff machine 'Bỏ thay đổi chưa duyệt…'. The password is never stored; the rotating refresh token is in config.json.
"""

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dibekho import db
from dibekho.core import activity, backup
from dibekho.core.cloud import account, approval, replica, sync, twoway
from dibekho.core.cloud import backup as cloud_backup
from dibekho.core.cloud.client import CloudError
from dibekho.i18n import t
from dibekho.ui.common import ask, error, fill_table, fit_window, hint_label, info, make_table, selected_id
from dibekho.ui.shared_admin import replace_shared_data

ORIGINALS_SECONDS = 90  # s of kept delivery notes uploaded per Đồng bộ ngay (the first time can be many)


class CloudRestoreDialog(QDialog):
    """Pick one of the full backups kept on the cloud (newest first)."""

    def __init__(self, backups, parent=None):
        super().__init__(parent)
        self.backups = backups
        self.setWindowTitle(t("cloud.restore_title"))
        fit_window(self, 760, 460)
        lay = QVBoxLayout(self)
        lay.addWidget(hint_label(t("cloud.restore_hint")))
        self.table = make_table([t("cloud.col_at"), t("cloud.col_device"), t("cloud.col_size")], stretch=1)
        fill_table(self.table, [[b.at.strftime("%d/%m/%Y %H:%M"), b.device, f"{max(1, round(b.size / 1024))} KB"]
                                for b in backups], ids=list(range(len(backups))))
        self.table.doubleClicked.connect(lambda *_: self.accept())
        lay.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(t("cloud.restore_go"))
        buttons.button(QDialogButtonBox.Ok).setAutoDefault(False)
        buttons.button(QDialogButtonBox.Cancel).setAutoDefault(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def selected(self):
        idx = selected_id(self.table)
        return None if idx is None else self.backups[idx]


class CloudTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        box = QGroupBox(t("cloud.title"))
        lay.addWidget(box)
        inner = QVBoxLayout(box)
        inner.addWidget(hint_label(t("sync.mode_hint")))
        who = QHBoxLayout()
        self.who = QLabel()
        self.sign_out_btn = QPushButton(t("login.sign_out"))
        self.sign_out_btn.clicked.connect(self.sign_out)
        who.addWidget(self.who, 1)
        who.addWidget(self.sign_out_btn)
        inner.addLayout(who)
        row = QHBoxLayout()
        self.sync_btn = QPushButton(t("cloud.sync_now"))
        self.sync_btn.clicked.connect(self.sync_now)
        row.addWidget(self.sync_btn)
        self.restore_btn = QPushButton(t("cloud.restore_btn"))
        self.restore_btn.clicked.connect(self.restore_from_cloud)
        row.addWidget(self.restore_btn)
        self.conflicts_btn = QPushButton(t("sync.show_conflicts"))
        self.conflicts_btn.clicked.connect(self.show_conflicts)
        row.addWidget(self.conflicts_btn)
        self.discard_btn = QPushButton(t("staff.discard"))
        self.discard_btn.clicked.connect(self.discard)
        row.addWidget(self.discard_btn)
        row.addStretch()
        inner.addLayout(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        inner.addWidget(self.status)
        lay.addStretch()
        ctx.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        cfg, conn = self.ctx.cfg, self.ctx.conn
        if conn is None:
            return
        role = getattr(cfg, "cloud_role", "")
        self.who.setText(t("login.who", user=cfg.cloud_user or "—", role=t(f"login.role_{role}")) if role else "")
        self.sign_out_btn.setVisible(bool(role))
        staff = approval.is_staff(cfg)
        self.restore_btn.setVisible(not staff)
        self.discard_btn.setVisible(staff and twoway.queued_count(conn) > 0)
        self.conflicts_btn.setVisible(replica.enabled(conn) and bool(twoway.conflicts(conn)))
        runner = getattr(self.ctx, "sync_runner", None)
        parts = [runner.status_text() if runner else ""]
        if not staff:
            at = sync.last_backup(conn)
            parts.append(t("cloud.last_push", when=at.replace("T", " ")[:16] if at else t("cloud.never")))
        self.status.setText("\n".join(p for p in parts if p))

    # ---------------------------------------------------------------- actions

    def _connect(self):
        """(client, access token) from the saved session; None after telling the user."""
        try:
            pair = self._busy(lambda: sync.session(self.ctx.cfg, timeout=30))
        except CloudError as exc:
            error(self, str(exc))
            return None
        if pair is None:
            error(self, t("admin.need_cloud"))
        return pair

    def sync_now(self):
        activity.log("click", "cloud_sync")
        runner = getattr(self.ctx, "sync_runner", None)
        if runner is not None:
            runner.start()  # the shared data: a round in the background, as every minute
        if approval.is_staff(self.ctx.cfg):
            info(self, t("cloud.sync_started"))
            return
        pair = self._connect()
        if pair is None:
            return
        client, token = pair
        try:
            backup_problem = self._busy(lambda: sync.finish_push(self.ctx.conn, self.ctx.cfg, client, token,
                                                                 ws=self.ctx.ws, originals_seconds=ORIGINALS_SECONDS))
        except CloudError as exc:
            error(self, str(exc))
            return
        self.refresh()
        if backup_problem:
            error(self, t("cloud.backup_failed", reason=backup_problem))
        else:
            info(self, t("cloud.push_ok"))

    def sign_out(self):
        queued = twoway.queued_count(self.ctx.conn)
        extra = t("login.queued_warning", n=queued) if queued else ""
        if not ask(self, t("login.confirm_sign_out", queued=extra)):
            return
        activity.log("click", "sign_out")
        account.sign_out(self.ctx.cfg)
        info(self, t("login.signed_out"))
        QApplication.instance().closeAllWindows()

    def discard(self):
        """A staff machine gives its unapproved changes up and takes the shared data again."""
        n = twoway.queued_count(self.ctx.conn)
        if not n or not ask(self, t("staff.confirm_discard", n=n)):
            return
        activity.log("click", "staff_discard")
        runner = getattr(self.ctx, "sync_runner", None)
        if runner is not None and runner.busy:
            error(self, t("admin.busy"))
            return
        backup.named_backup(self.ctx.conn, self.ctx.ws, "truoc-bo-thay-doi-chua-duyet")
        approval.discard(self.ctx.conn)
        try:
            pair = sync.session(self.ctx.cfg, timeout=15)
            if pair is not None:
                approval.cancel(pair[0], pair[1], self.ctx.cfg.device_id)
        except CloudError as exc:  # the owner may still see it; refusing it changes nothing here
            activity.log("error", f"cancel staff request: {exc}")
        if runner is not None:
            runner.start()
        self.ctx.notify()

    def show_conflicts(self):
        from dibekho.ui.conflict_dialog import ConflictDialog

        ConflictDialog(self.ctx, self).exec()
        self.refresh()

    def restore_from_cloud(self):
        """Replace the local database with a full backup from the cloud: checked first, the current data
        backed up, exactly like restoring a local backup (transfer_page.restore)."""
        activity.log("click", "cloud_restore")
        ctx = self.ctx
        if approval.is_staff(ctx.cfg):
            error(self, t("staff.not_for_staff"))
            return
        pair = self._connect()
        if pair is None:
            return
        client, token = pair
        try:
            backups = self._busy(lambda: cloud_backup.list_backups(client, token))
            if not backups:
                info(self, t("cloud.restore_none"))
                return
            dlg = CloudRestoreDialog(backups, self)
            if dlg.exec() != QDialog.Accepted:
                return
            chosen = dlg.selected()
            if chosen is None:
                error(self, t("cloud.restore_pick"))
                return
            if not ask(self, t("cloud.restore_confirm", device=chosen.device,
                               at=chosen.at.strftime("%d/%m/%Y %H:%M"))):
                return
            if replica.enabled(ctx.conn):  # shared data: the cloud takes the backup first
                def build(folder):
                    path = self._busy(lambda: cloud_backup.fetch(client, token, chosen.name, folder))
                    new = db.connect(path)
                    try:
                        cloud_backup.after_restore(new, ctx.cfg, chosen)
                    finally:
                        new.close()
                    return path
                if replace_shared_data(ctx, self, build, t("admin.what_restore")):
                    self.refresh()
                    self._restored_message(client, token)
                return
            if sync.has_unpushed(ctx.conn) and not ask(self, t("cloud.restore_unpushed")):
                return
            with tempfile.TemporaryDirectory() as tmp:
                path = self._busy(lambda: cloud_backup.fetch(client, token, chosen.name, Path(tmp)))
                backup.named_backup(ctx.conn, ctx.ws, "truoc-khoi-phuc-cloud")
                ctx.log_action("restore")
                ctx.close()
                try:
                    backup.restore(ctx.ws, path)
                finally:
                    ctx.reopen()
            cloud_backup.after_restore(ctx.conn, ctx.cfg, chosen)
        except (CloudError, OSError) as exc:
            error(self, str(exc))
            return
        self.refresh()
        self._restored_message(client, token)

    def _restored_message(self, client, token):
        """The kept delivery notes come back too (Mở file gốc / Khôi phục file); one that fails is only reported."""
        got, failed = self._busy(lambda: cloud_backup.fetch_originals(self.ctx.ws, client, token))
        if got:
            activity.log("cloud", f"originals downloaded after restore: {got}")
        info(self, t("cloud.restored") + ("\n\n" + t("cloud.originals_failed", n=failed) if failed else ""))

    def _busy(self, work):
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            return work()
        finally:
            QGuiApplication.restoreOverrideCursor()
