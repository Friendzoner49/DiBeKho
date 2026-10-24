"""Settings → Chung → 'Giấy phép mã nguồn mở…': DiBeKho's MIT license and the licenses of everything the app
ships with (Qt for Python is LGPLv3), read from dibekho/licenses/LICENSES.txt (scripts/make_licenses.py)."""

from importlib import resources

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout

from dibekho.i18n import t
from dibekho.ui.common import fit_window, hint_label


def license_text() -> str:
    return (resources.files("dibekho") / "licenses" / "LICENSES.txt").read_text(encoding="utf-8")


class LicenseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("license.title"))
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        fit_window(self, 900, 680)
        lay = QVBoxLayout(self)
        lay.addWidget(hint_label(t("license.hint")))
        self.text = QPlainTextEdit(license_text())
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        lay.addWidget(self.text, 1)
        row = QHBoxLayout()
        row.addStretch()
        close = QPushButton(t("btn.close"))
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
