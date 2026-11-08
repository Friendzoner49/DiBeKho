"""One DiBeKho window per workspace: a second copy (icon double-clicked twice) would work on the same database
while Hoàn tác, restoring a backup or importing a package replaces that file under the first one."""

from PySide6.QtCore import QLockFile

from dibekho.core.workspace import Workspace


def acquire(ws: Workspace) -> QLockFile | None:
    """The lock, kept for as long as the app runs; None if another copy holds it. A lock left by a copy that
    crashed is taken over (its process is gone)."""
    lock = QLockFile(str(ws.data / "dibekho.lock"))
    lock.setStaleLockTime(0)
    return lock if lock.tryLock(200) else None
