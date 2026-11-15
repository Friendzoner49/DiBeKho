"""Asking about a newer version and installing it (core/update.py does the network and the files).

When the app opens (Cài đặt → Chung → "Tự kiểm tra bản mới khi mở app", on by default) it looks in the background a few
seconds after start; a newer version is offered only when no other window is open: "Cập nhật ngay" downloads it with a
progress bar and installs it (Windows: the installer runs and opens the new version; Mac: the .dmg opens and the user
drags DiBeKho onto Applications), "Để sau" asks again next time. Cài đặt → Chung → "Kiểm tra bản mới ngay" does the same
on demand and says when this is already the newest version. Nothing happens when running from the source code."""

import sys
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QProgressDialog

from dibekho import __version__
from dibekho.core import activity, update
from dibekho.i18n import t
from dibekho.ui.common import ask, error, info

START_DELAY_MS = 8000
BUSY_RETRY_MS = 30000


class _Bridge(QObject):
    progress = Signal(int, int)
    finished = Signal(object, object)  # result, error: on the main thread


def _run(work, then, progress_cb=None):
    bridge = _Bridge()
    bridge.finished.connect(lambda result, err: (then(result, err), bridge.deleteLater()))
    if progress_cb:
        bridge.progress.connect(progress_cb)

    def target():
        try:
            bridge.finished.emit(work(bridge.progress.emit), None)
        except BaseException as exc:  # delivered to `then`
            bridge.finished.emit(None, exc)
    threading.Thread(target=target, daemon=True).start()
    return bridge


def _testing() -> bool:
    return "pytest" in sys.modules or "--self-test" in sys.argv


def check_on_start(window) -> None:
    """Called once the main window shows."""
    if not getattr(window.ctx.cfg, "check_updates", True) or not update.can_install() or _testing():
        return
    QTimer.singleShot(START_DELAY_MS, lambda: _check(window, explicit=False))


def check_now(parent, window) -> None:
    if not update.can_install():
        info(parent, t("update.source_only"))
        return
    _check(window, explicit=True, parent=parent)


def _check(window, explicit: bool, parent=None) -> None:
    def then(rel, err):
        if err is not None:
            activity.log("update", f"check failed: {type(err).__name__}: {err}")
            if explicit:
                error(parent or window, t("update.check_failed"))
            return
        if rel is None:
            if explicit:
                info(parent or window, t("update.newest", version=__version__))
            return
        activity.log("update", f"offered {rel.version}")
        _offer(window, rel, parent if explicit else None)

    window._update_bridge = _run(lambda _progress: update.latest(), then)


def _offer(window, rel, parent=None) -> None:
    if parent is None and QApplication.activeModalWidget() is not None:
        QTimer.singleShot(BUSY_RETRY_MS, lambda: _offer(window, rel))  # the user is in the middle of something
        return
    text = t("update.ask", new=rel.version, current=__version__)
    if update.running_from_disk_image():
        info(parent or window, text.split("\n\n")[0] + "\n\n" + t("update.mac_from_dmg"))
        return
    if ask(parent or window, text, t("update.title")):
        install(parent or window, window, rel)


def install(parent, window, rel) -> None:
    dlg = QProgressDialog(t("update.downloading", version=rel.version), t("btn.cancel"), 0, 1000, parent)
    dlg.setWindowTitle(t("update.title"))
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    dlg.setValue(0)
    stop = threading.Event()
    dlg.canceled.connect(stop.set)

    def show_progress(done, total):
        dlg.setValue(int(done * 1000 / max(total, 1)))
        dlg.setLabelText(t("update.downloading_mb", version=rel.version, done=f"{done / 1e6:.1f}", total=f"{total / 1e6:.1f}"))

    def work(progress):
        return update.download(rel, progress=progress, cancelled=stop.is_set)

    def then(path, err):
        dlg.close()
        if isinstance(err, InterruptedError):
            return
        if err is not None:
            activity.log("update", f"download failed: {type(err).__name__}: {err}")
            error(parent, t("update.download_failed"))
            return
        activity.log("update", f"downloaded {rel.version}")
        try:
            if sys.platform == "darwin":
                update.open_mac_image(path)
                info(parent, t("update.mac_steps"))
            else:
                update.start_windows_installer(path)
        except OSError as exc:
            activity.log("update", f"install failed: {exc}")
            error(parent, t("update.install_failed"))
            return
        window.close()  # the normal way out: sync stops, the database closes, the installer can replace the files
        QApplication.quit()

    window._update_bridge = _run(work, then, show_progress)
    dlg.show()
