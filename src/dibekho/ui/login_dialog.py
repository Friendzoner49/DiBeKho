"""The first window of the app (user's request 15/11/2026): the account and the password. Signing in checks who is
working and connects the machine to the shared data (core/cloud/account.py).

A build that carries the Cloud address (core/cloud/builtin.py) shows two boxes only; one that does not (built from
the public source) also shows the address and the connection key, as Cài đặt → Cloud did before."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from dibekho import APP_NAME
from dibekho.core import activity
from dibekho.core.cloud import account
from dibekho.core.cloud.client import CloudError
from dibekho.i18n import t
from dibekho.ui.common import RED, hint_label, title_label


class LoginDialog(QDialog):
    def __init__(self, cfg, message: str = "", parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.session: account.Session | None = None
        self.setWindowTitle(APP_NAME)
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.addWidget(title_label(t("login.title")))
        lay.addWidget(hint_label(t("login.hint")))
        form = QFormLayout()
        self.url = self.key = None
        if not account.has_builtin():
            self.url, self.key = QLineEdit(cfg.cloud_url), QLineEdit(cfg.cloud_key)
            form.addRow(t("cloud.url") + ":", self.url)
            form.addRow(t("cloud.key") + ":", self.key)
        self.user = QLineEdit(cfg.cloud_user)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow(t("cloud.user") + ":", self.user)
        form.addRow(t("cloud.password") + ":", self.password)
        lay.addLayout(form)
        self.problem = QLabel(message)
        self.problem.setWordWrap(True)
        self.problem.setStyleSheet(f"color: {RED.name()};")
        self.problem.setVisible(bool(message))
        lay.addWidget(self.problem)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.quit_btn = QPushButton(t("btn.cancel") if parent is not None else t("app.quit"))
        self.quit_btn.setAutoDefault(False)
        self.quit_btn.clicked.connect(self.reject)
        self.ok_btn = QPushButton(t("login.sign_in"))
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self.sign_in)
        buttons.addWidget(self.quit_btn)
        buttons.addWidget(self.ok_btn)
        lay.addLayout(buttons)
        (self.password if cfg.cloud_user else self.user).setFocus()

    def sign_in(self):
        activity.log("click", "sign_in")
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.session = account.sign_in(self.cfg, self.user.text(), self.password.text(),
                                           self.url.text() if self.url else "", self.key.text() if self.key else "")
        except CloudError as exc:
            self.password.clear()
            self.problem.setText(str(exc))
            self.problem.setVisible(True)
            self.password.setFocus()
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        self.password.clear()
        self.accept()


def sign_in_again(cfg, parent, message: str = "") -> account.Session | None:
    """The saved session ended (signed out on the web, password changed): ask once more, inside the running app."""
    dlg = LoginDialog(cfg, message or t("login.again"), parent)
    return dlg.session if dlg.exec() == QDialog.Accepted else None
