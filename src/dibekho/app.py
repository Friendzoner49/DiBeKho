"""Entry point: first-run setup, open the workspace, back up, scan, show the window."""

import sys
import traceback
from importlib import resources
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
)

from dibekho import APP_NAME, i18n
from dibekho.core import backup
from dibekho.core.workspace import Config, Workspace, default_workspace
from dibekho.i18n import LANGUAGES, t


class FirstRunDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(640, 260)
        form = QFormLayout(self)
        welcome = QLabel(t("firstrun.welcome"))
        welcome.setWordWrap(True)
        form.addRow(welcome)
        self.language = QComboBox()
        for code, name in LANGUAGES.items():
            self.language.addItem(name, code)
        form.addRow("Ngôn ngữ / Language:", self.language)
        row = QHBoxLayout()
        self.folder = QLineEdit(str(default_workspace()))
        browse = QPushButton(t("firstrun.browse"))
        browse.clicked.connect(self.browse)
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        form.addRow(t("settings.workspace") + ":", row)
        hint = QLabel(t("firstrun.folder_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666;")
        form.addRow(hint)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText(t("firstrun.start"))
        box.button(QDialogButtonBox.Cancel).setText(t("btn.cancel"))
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, t("firstrun.browse"), str(Path.home()))
        if path:
            self.folder.setText(str(Path(path) / APP_NAME))


def _excepthook(exc_type, exc, tb):
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    sys.__stderr__ and sys.__stderr__.write(text)
    QMessageBox.critical(None, APP_NAME, t("app.unexpected_error", error=f"{exc_type.__name__}: {exc}"))


def self_test() -> int:
    """`DiBeKho --self-test`: check a packaged build can start (data files, Qt plugins, database)."""
    import os
    import tempfile

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    from dibekho.ui.common import AppContext
    from dibekho.ui.main_window import MainWindow

    with tempfile.TemporaryDirectory() as tmp:
        ws = Workspace(Path(tmp) / APP_NAME)
        ws.ensure()
        for lang in LANGUAGES:
            i18n.set_language(lang)
            ctx = AppContext(Config(str(ws.root), lang, "selftest", "selftest"), ws)
            window = MainWindow(ctx)
            for i in range(window.stack.count()):
                window.nav.setCurrentRow(i)
                app.processEvents()
            window.search.open_all_windows()
            app.processEvents()
            window.close()
    print("DiBeKho self-test OK")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(resources.files("dibekho.ui") / "icon.png")))
    font = app.font()
    font.setPointSize(max(font.pointSize(), 10))
    # Chinese product names and input: name a CJK fallback explicitly (macOS falls back to PingFang by itself).
    if sys.platform == "win32":
        font.setFamilies([font.family(), "Microsoft YaHei UI", "Microsoft YaHei", "SimSun"])
    app.setFont(font)
    sys.excepthook = _excepthook

    cfg = Config.load()
    if cfg is None:
        dlg = FirstRunDialog()
        if dlg.exec() != QDialog.Accepted:
            return 0
        cfg = Config.create(Path(dlg.folder.text().strip()).expanduser())
        cfg.language = dlg.language.currentData()
        cfg.save()
    i18n.set_language(cfg.language)

    ws = Workspace(Path(cfg.workspace))
    try:
        ws.ensure()
    except OSError as exc:
        QMessageBox.critical(None, APP_NAME, t("app.folder_error", path=str(ws.root), error=str(exc)))
        Config.remove()
        return 1

    from dibekho.ui.common import AppContext
    from dibekho.ui.main_window import MainWindow

    ctx = AppContext(cfg, ws)
    try:
        backup.daily_backup(ctx.conn, ws)
    except OSError:
        pass  # a failed backup must not block daily work; it is retried next start

    window = MainWindow(ctx)
    window.show()
    cloud = ws.cloud_sync_warning()
    if cloud:
        QMessageBox.warning(window, APP_NAME, t("app.cloud_warning", service=cloud))
    window.rescan()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
