"""One DiBeKho window per workspace: a second copy (icon double-clicked twice) would work on the same database
while Hoàn tác, restoring a backup or importing a package replaces that file under the first one."""

from PySide6.QtCore import QLockFile, QSysInfo

from dibekho.core.workspace import Workspace


def acquire(ws: Workspace) -> QLockFile | None:
    """The lock, kept for as long as the app runs; None if another copy holds it. A lock left by a copy that
    crashed is taken over (its process is gone), and so is one written on another computer: the workspace
    was copied there (USB, another machine) with the lock file in it, and no copy here holds it."""
    lock = QLockFile(str(ws.data / "dibekho.lock"))
    lock.setStaleLockTime(0)
    if lock.tryLock(200):
        return lock
    info = lock.getLockInfo()  # (pid, hostname, app name); empty when the file cannot be read
    if info and info[1] != QSysInfo.machineHostName():
        lock.removeStaleLockFile()
        if lock.tryLock(200):
            return lock
    return None
