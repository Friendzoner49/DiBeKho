"""'Cloud' tab in Settings: sign in to Supabase and push the mirror ('Đồng bộ ngay').

The desktop stays the single source of truth; a push REPLACES the whole cloud mirror
(docs/cloud/04-thiet-ke-chot.md). The password is used once to sign in and never stored;
later pushes reuse the rotating refresh token kept in config.json.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from dibekho.core import activity
from dibekho.core.cloud import inbox as cloud_inbox
from dibekho.core.cloud import sync
from dibekho.core.cloud.client import CloudClient, CloudError
from dibekho.i18n import t
from dibekho.ui.common import ask, error, hint_label, info


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
        self.status = QLabel()
        row.addWidget(self.status, 1)
        form.addRow(row)
        lay.addStretch()
        self.refresh()

    def refresh(self):
        _, at = sync.last_push(self.ctx.conn)
        when = at.replace("T", " ")[:16] if at else t("cloud.never")
        self.status.setText(t("cloud.last_push", when=when))

    # ---------------------------------------------------------------- actions

    def sync_now(self):
        activity.log("click", "cloud_sync")
        cfg = self.ctx.cfg
        url, key, user = self.url.text().strip(), self.key.text().strip(), self.user.text().strip()
        if not url or not key or not user:
            error(self, t("cloud.missing"))
            return
        if user != cfg.cloud_user:
            cfg.cloud_refresh_token = ""  # a different account: the saved session is not theirs
        cfg.cloud_url, cfg.cloud_key, cfg.cloud_user = url, key, user
        cfg.save()
        client = CloudClient(url, key)
        try:
            token = self._access_token(client)
            if token is None:
                return
            result = self._busy(lambda: sync.push_mirror(self.ctx.conn, cfg, client, token))
            if result["conflict"]:
                other = result.get("last_push") or {}
                when = str(other.get("last_push_at", ""))[:16].replace("T", " ")
                if not ask(self, t("cloud.conflict", device=other.get("device_name", "?"), at=when)):
                    return
                result = self._busy(lambda: sync.push_mirror(self.ctx.conn, cfg, client, token, force=True))
            if not result["conflict"]:
                self._busy(lambda: cloud_inbox.finish_applied(self.ctx.conn, client, token))
                self.ctx.web_inbox = self._busy(lambda: cloud_inbox.fetch_pending(self.ctx.conn, client, token))
                self.ctx.notify()  # new web orders land in Cần xử lý
        except CloudError as exc:
            error(self, str(exc))
            return
        self.refresh()
        info(self, t("cloud.push_ok"))

    def _access_token(self, client: CloudClient) -> str | None:
        cfg, password = self.ctx.cfg, self.password.text()
        if password:
            tokens = self._busy(lambda: client.sign_in(cfg.cloud_user, password))
        elif cfg.cloud_refresh_token:
            try:
                tokens = self._busy(lambda: client.refresh(cfg.cloud_refresh_token))
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
