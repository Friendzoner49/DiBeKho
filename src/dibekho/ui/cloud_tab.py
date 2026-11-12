"""'Cloud' tab in Settings: sign in to Supabase, 'Đồng bộ ngay' (staff requests, a sync round when the data is shared,
the full backup), restore from a cloud backup, and turning shared data on/off (docs/cloud/06-cloud-la-goc.md).
The password is used once to sign in and never stored; later calls reuse the rotating refresh token in config.json.
"""

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dibekho.core import activity, backup
from dibekho.core.cloud import backup as cloud_backup
from dibekho.core.cloud import inbox as cloud_inbox
from dibekho.core.cloud import replica, sync, twoway
from dibekho.core.cloud.client import CloudClient, CloudError
from dibekho.i18n import t
from dibekho.ui.common import ask, blocked_in_cloud_mode, error, fill_table, fit_window, hint_label, info, make_table, selected_id


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
        form = QFormLayout(box)
        form.addRow(hint_label(t("cloud.hint")))
        self.url = QLineEdit(ctx.cfg.cloud_url)
        self.key = QLineEdit(ctx.cfg.cloud_key)
        self.user = QLineEdit(ctx.cfg.cloud_user)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow(t("cloud.url") + ":", self.url)
        form.addRow(t("cloud.key") + ":", self.key)
        form.addRow(t("cloud.user") + ":", self.user)
        form.addRow(t("cloud.password") + ":", self.password)
        form.addRow("", hint_label(t("cloud.password_hint")))
        row = QHBoxLayout()
        self.sync_btn = QPushButton(t("cloud.sync_now"))
        self.sync_btn.clicked.connect(self.sync_now)
        row.addWidget(self.sync_btn)
        self.restore_btn = QPushButton(t("cloud.restore_btn"))
        self.restore_btn.clicked.connect(self.restore_from_cloud)
        row.addWidget(self.restore_btn)
        self.status = QLabel()
        row.addWidget(self.status, 1)
        form.addRow(row)

        # cloud as the source of truth (docs/cloud/06-cloud-la-goc.md)
        shared = QGroupBox(t("sync.mode_title"))
        lay.addWidget(shared)
        shared_lay = QVBoxLayout(shared)
        shared_lay.addWidget(hint_label(t("sync.mode_hint")))
        mode_row = QHBoxLayout()
        self.mode_btn = QPushButton()
        self.mode_btn.clicked.connect(self.toggle_mode)
        self.conflicts_btn = QPushButton(t("sync.show_conflicts"))
        self.conflicts_btn.clicked.connect(self.show_conflicts)
        self.mode_status = QLabel()
        mode_row.addWidget(self.mode_btn)
        mode_row.addWidget(self.conflicts_btn)
        mode_row.addWidget(self.mode_status, 1)
        shared_lay.addLayout(mode_row)
        lay.addStretch()
        ctx.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        at = sync.last_backup(self.ctx.conn)
        when = at.replace("T", " ")[:16] if at else t("cloud.never")
        self.status.setText(t("cloud.last_push", when=when))
        on = replica.enabled(self.ctx.conn)
        self.mode_btn.setText(t("sync.turn_off") if on else t("sync.turn_on"))
        runner = getattr(self.ctx, "sync_runner", None)
        self.mode_status.setText((runner.status_text() if runner else "") if on else t("sync.mode_off"))
        self.conflicts_btn.setVisible(on and bool(twoway.conflicts(self.ctx.conn)))

    # ---------------------------------------------------------------- actions

    def _connect(self):
        """Save the typed settings, then (client, access token); None after telling the user what is missing."""
        cfg = self.ctx.cfg
        url, key, user = self.url.text().strip(), self.key.text().strip(), self.user.text().strip()
        if not url or not key or not user:
            error(self, t("cloud.missing"))
            return None
        if user != cfg.cloud_user:
            cfg.cloud_refresh_token = ""  # a different account: the saved session is not theirs
        cfg.cloud_url, cfg.cloud_key, cfg.cloud_user = url, key, user
        cfg.save()
        client = CloudClient(url, key)
        token = self._access_token(client)
        return None if token is None else (client, token)

    def sync_now(self):
        activity.log("click", "cloud_sync")
        cfg = self.ctx.cfg
        try:
            pair = self._connect()
            if pair is None:
                return
            client, token = pair
            self.ctx.web_inbox = self._busy(lambda: cloud_inbox.fetch_pending(self.ctx.conn, client, token))
            runner = getattr(self.ctx, "sync_runner", None)
            if runner is not None and replica.enabled(self.ctx.conn):
                runner.start()  # the shared data: a round in the background, as every minute
            backup_problem = self._busy(lambda: sync.finish_push(self.ctx.conn, cfg, client, token))
            self.ctx.notify()  # new staff requests land in Cần xử lý
        except CloudError as exc:
            error(self, str(exc))
            return
        self.refresh()
        if backup_problem:
            error(self, t("cloud.backup_failed", reason=backup_problem))
        else:
            info(self, t("cloud.push_ok"))

    def toggle_mode(self):
        ctx = self.ctx
        if replica.enabled(ctx.conn):
            if ask(self, t("sync.confirm_off")):
                activity.log("click", "cloud_mode_off")
                twoway.stop(ctx.conn)
                self.refresh()
            return
        activity.log("click", "cloud_mode_on")
        try:
            pair = self._connect()
            if pair is None:
                return
            client, token = pair
            pulled = self._busy(lambda: twoway.fetch(client, token, 0))
            if twoway.cloud_empty(pulled):
                if not ask(self, t("sync.confirm_upload")):
                    return
                twoway.start_from_this_machine(ctx.conn)
            else:
                if not ask(self, t("sync.confirm_adopt")):
                    return
                backup.named_backup(ctx.conn, ctx.ws, "truoc-dung-du-lieu-cloud")
                twoway.start_from_cloud(ctx.conn)
            result = self._busy(lambda: twoway.sync_round(ctx.conn, client, token, ctx.cfg.device_id))
            for merged in result.merged:
                twoway.export_renamed(ctx.conn, ctx.ws, merged)
        except CloudError as exc:
            error(self, str(exc))
            return
        ctx.notify()
        info(self, t("sync.turned_on"))

    def show_conflicts(self):
        from dibekho.ui.conflict_dialog import ConflictDialog

        ConflictDialog(self.ctx, self).exec()
        self.refresh()

    def restore_from_cloud(self):
        """Replace the local database with a full backup from the cloud: checked first, the current data
        backed up and an undo point taken, exactly like restoring a local backup (transfer_page.restore)."""
        activity.log("click", "cloud_restore")
        if blocked_in_cloud_mode(self, self.ctx.conn):
            return
        ctx = self.ctx
        try:
            pair = self._connect()
            if pair is None:
                return
            client, token = pair
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
            if sync.has_unpushed(ctx.conn) and not ask(self, t("cloud.restore_unpushed")):
                return
            with tempfile.TemporaryDirectory() as tmp:
                path = self._busy(lambda: cloud_backup.fetch(client, token, chosen.name, Path(tmp)))
                backup.named_backup(ctx.conn, ctx.ws, "truoc-khoi-phuc-cloud")
                ctx.undo_point("restore")
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
        info(self, t("cloud.restored"))

    def _access_token(self, client: CloudClient) -> str | None:
        cfg, password = self.ctx.cfg, self.password.text()
        if password:
            tokens = self._busy(lambda: client.sign_in(cfg.cloud_user, password))
        elif cfg.cloud_refresh_token:
            try:
                tokens = self._busy(lambda: sync.rotate(cfg, client))
            except CloudError:
                error(self, t("cloud.need_password"))  # session expired: one more password entry
                return None
        else:
            error(self, t("cloud.need_password"))
            return None
        cfg.cloud_refresh_token = tokens["refresh_token"]  # refresh tokens rotate
        cfg.save()
        self.password.clear()
        return tokens["access_token"]

    def _busy(self, work):
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            return work()
        finally:
            QGuiApplication.restoreOverrideCursor()
