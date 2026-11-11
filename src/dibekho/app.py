"""Entry point: first-run setup, open the workspace, back up, scan, show the window."""

import os
import platform
import sqlite3
import sys
import traceback
from importlib import resources
from pathlib import Path

from PySide6.QtCore import qVersion
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

from dibekho import APP_NAME, __version__, i18n
from dibekho.core import activity, backup
from dibekho.core.workspace import Config, Workspace, default_workspace, workspace_missing
from dibekho.i18n import LANGUAGES, t
from dibekho.ui.common import apply_rounded_style, theme_color


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
        form.addRow("Ngôn ngữ / Language / 语言:", self.language)
        row = QHBoxLayout()
        self.folder = QLineEdit(str(default_workspace()))
        browse = QPushButton(t("firstrun.browse"))
        browse.clicked.connect(self.browse)
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        form.addRow(t("settings.workspace") + ":", row)
        hint = QLabel(t("firstrun.folder_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme_color('hint')};")
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
    try:
        activity.log("crash", text.strip())
    except Exception:
        pass
    QMessageBox.critical(None, APP_NAME, t("app.unexpected_error", error=f"{exc_type.__name__}: {exc}"))


def self_test() -> int:
    """`DiBeKho --self-test`: check a packaged build can start (data files, Qt plugins, database)."""
    import os
    import tempfile

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from dibekho.core import workspace as workspace_module

    # Never touch the real config.json: closing the test window saves its geometry (and the build runs this).
    config_home = Path(tempfile.mkdtemp(prefix="dibekho-selftest-"))
    workspace_module.config_dir = lambda: config_home
    app = QApplication(sys.argv)
    from dibekho.ui.common import AppContext
    from dibekho.ui.license_dialog import license_text
    from dibekho.ui.main_window import MainWindow

    assert "GNU LESSER GENERAL PUBLIC LICENSE" in license_text()  # shipped with the build (Qt is LGPLv3)
    with tempfile.TemporaryDirectory() as tmp:
        from dibekho.core.deliveries import file_hash

        probe = Path(tmp) / "hash-probe.bin"
        probe.write_bytes(b"x")
        assert file_hash(probe) == "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"
        import ssl  # cloud sync talks HTTPS: TLS must ship in the build (dibekho.spec keeps OpenSSL)

        assert ssl.create_default_context() is not None
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
    saved = Config.load()
    # Text, cells, buttons and icons all grow together. Set before QApplication exists; a value already in the
    # environment wins (handy while developing).
    os.environ.setdefault("QT_SCALE_FACTOR", f"{saved.ui_scale if saved else Config.ui_scale:g}")
    if sys.platform == "win32":  # own taskbar identity, so the taskbar shows our icon instead of python's
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DiBeKho.App")
        except (AttributeError, OSError):
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(resources.files("dibekho.ui") / "icon.png")))
    font = app.font()
    font.setPointSize(max(font.pointSize(), 10))
    # Chinese product names and the Chinese interface: name Simplified Chinese fallbacks explicitly, so Han
    # characters never come from a Japanese font (missing or different glyphs).
    if sys.platform == "win32":
        font.setFamilies([font.family(), "Microsoft YaHei UI", "Microsoft YaHei", "SimSun"])
    elif sys.platform == "darwin":
        font.setFamilies([font.family(), "PingFang SC", "Hiragino Sans GB", "STHeiti"])
    app.setFont(font)
    apply_rounded_style(app)
    sys.excepthook = _excepthook

    cfg = saved
    if cfg is None:
        dlg = FirstRunDialog()
        if dlg.exec() != QDialog.Accepted:
            return 0
        cfg = Config.create(Path(dlg.folder.text().strip()).expanduser())
        cfg.language = dlg.language.currentData()
        cfg.save()
    i18n.set_language(cfg.language)

    ws = Workspace(Path(cfg.workspace))
    if workspace_missing(ws, configured=saved is not None):
        box = QMessageBox(QMessageBox.Warning, APP_NAME, t("app.workspace_missing", path=str(ws.root)))
        create = box.addButton(t("app.workspace_create"), QMessageBox.AcceptRole)
        quit_button = box.addButton(t("app.quit"), QMessageBox.RejectRole)
        box.setDefaultButton(quit_button)  # Enter pressed by reflex must not start on empty data
        box.setEscapeButton(quit_button)
        box.exec()
        if box.clickedButton() is not create:
            return 1
    try:
        ws.ensure()
    except OSError as exc:
        QMessageBox.critical(None, APP_NAME, t("app.folder_error", path=str(ws.root), error=str(exc)))
        if saved is None:  # a folder chosen just now; a configured one may only be unplugged: keep the setting
            Config.remove()
        return 1

    from dibekho.ui.common import ActivityFilter, AppContext
    from dibekho.ui.main_window import MainWindow
    from dibekho.ui.single_instance import acquire

    lock = acquire(ws)  # held until the app exits
    if lock is None:
        QMessageBox.information(None, APP_NAME, t("app.already_running"))
        return 0

    activity.setup(ws.data / activity.FILE_NAME)
    activity.log("start", f"DiBeKho {__version__} · {platform.platform()} · Python {platform.python_version()} · "
                          f"Qt {qVersion()} · {cfg.language} · {cfg.ui_scale:g}x")
    app.installEventFilter(ActivityFilter(app))
    ctx = AppContext(cfg, ws)
    try:
        backup.daily_backup(ctx.conn, ws)
        if backup.maintenance_due(cfg):
            backup.run_maintenance(ctx.conn, ws, cfg)
    except (OSError, sqlite3.DatabaseError):
        pass  # a failed backup/cleanup must not block daily work; it is retried next start

    window = MainWindow(ctx)
    window.show()
    cloud = ws.cloud_sync_warning()
    if cloud:
        QMessageBox.warning(window, APP_NAME, t("app.cloud_warning", service=cloud))
    window.rescan()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
