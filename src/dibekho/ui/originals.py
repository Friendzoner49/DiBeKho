"""'Tải file gốc từ Cloud' (user, 27/11/2026): the original files of the chosen orders come down to this computer, with a
progress bar that says which order is on the way. Used by the order window ('Mở file gốc' too) and the order list."""

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QProgressDialog

from dibekho.core import activity
from dibekho.core.cloud import approval
from dibekho.core.cloud import backup as cloud_backup
from dibekho.core.cloud import sync as cloud_sync
from dibekho.i18n import t


class _Bridge(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object, object)  # result, error: on the main thread


def allowed(cfg) -> bool:
    """Only the owner's account reads the cloud's files, and only when signed in."""
    return bool(cfg.cloud_user) and not approval.is_staff(cfg)


def download(parent, ctx, orders: list[tuple[str, str]], then):
    """orders: (source hash, order code) of the files this computer lacks. then(result) gets a
    cloud_backup.Download, or None when the cloud could not be reached; it is not called after 'Huỷ'."""
    codes = {f"{h}.xlsx": code for h, code in orders}
    cfg, ws = ctx.cfg, ctx.ws
    dlg = QProgressDialog(t("originals.connecting"), t("btn.cancel"), 0, len(codes), parent)
    dlg.setWindowTitle(t("originals.title"))
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setMinimumWidth(420)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    dlg.setValue(0)
    stop = threading.Event()
    dlg.canceled.connect(stop.set)
    bridge = _Bridge(dlg)

    def show(done, total, name):
        if stop.is_set():
            return
        dlg.setMaximum(total)
        dlg.setValue(done)
        dlg.setLabelText(t("originals.progress", n=done + 1, total=total, code=codes.get(name, "")))

    def finished(result, err):
        if stop.is_set():  # 'Huỷ': the window that asked may be gone by now
            return
        dlg.close()
        if err is not None:
            activity.log("error", f"original download: {type(err).__name__}: {err}")
        else:
            activity.log("cloud", f"originals asked: {len(result.got)} downloaded, {len(result.absent)} not on cloud, "
                                  f"{len(result.failed)} failed")
        then(result)

    def work():
        try:
            pair = cloud_sync.session(cfg, timeout=15)
            if pair is None:
                bridge.finished.emit(None, None)
                return
            bridge.finished.emit(cloud_backup.download_originals(
                ws, *pair, list(codes), progress=bridge.progress.emit, cancelled=stop.is_set), None)
        except Exception as exc:  # offline, signed out: the plain message of the caller
            bridge.finished.emit(None, exc)

    bridge.progress.connect(show)
    bridge.finished.connect(finished)
    dlg.show()
    threading.Thread(target=work, daemon=True).start()
    return dlg


def summary(result, orders: list[tuple[str, str]]) -> str:
    """The plain words about what came down and what did not."""
    codes = {f"{h}.xlsx": code for h, code in orders}
    listed = lambda names: ", ".join(codes.get(n, "") for n in names)  # noqa: E731
    parts = []
    if result.got:
        parts.append(t("originals.got", n=len(result.got)))
    if result.absent:
        parts.append(t("originals.absent", codes=listed(result.absent)))
    if result.failed:
        parts.append(t("originals.failed", codes=listed(result.failed)))
    return "\n\n".join(parts)
