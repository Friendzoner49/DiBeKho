"""'Hoàn tác': undo the last actions the user may regret.

Just before such an action (Apply in 'Cần xử lý', forget a learned name, edit or delete a product, a stock
count, an import...) the app keeps a copy of the database in sao-luu/hoan-tac/. Undo puts the newest copy
back, so the data is exactly as it was before that action; pressing it again goes one step further back.
Files in phieu-giao-hang/ follow on the next scan (sort_files moves them in or out of da-xu-ly/).
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dibekho import db
from dibekho.core import backup
from dibekho.core.stock import close_document
from dibekho.core.workspace import Workspace

FOLDER = "hoan-tac"
KEEP = 20
_STAMP = "%Y-%m-%d_%H%M%S_%f"


@dataclass
class UndoPoint:
    path: Path
    action: str  # key of the action, shown as t(f"undo.{action}")
    at: datetime


def folder(ws: Workspace) -> Path:
    return ws.backups / FOLDER


def mark(conn, ws: Workspace, action: str) -> Path:
    """Keep the database as it is now, before `action`."""
    path = folder(ws) / f"{datetime.now().strftime(_STAMP)}__{action}.sqlite"
    backup.snapshot(conn, path)
    for old in points(ws)[KEEP:]:
        try:
            old.path.unlink()
        except OSError:
            pass
    return path


def points(ws: Workspace) -> list[UndoPoint]:
    """Newest first."""
    result = []
    for path in folder(ws).glob("*__*.sqlite") if folder(ws).exists() else []:
        stamp, _, action = path.stem.partition("__")
        try:
            result.append(UndoPoint(path, action, datetime.strptime(stamp, _STAMP)))
        except ValueError:
            continue
    return sorted(result, key=lambda p: p.at, reverse=True)


def latest(ws: Workspace) -> UndoPoint | None:
    found = points(ws)
    return found[0] if found else None


def undo(ws: Workspace, point: UndoPoint) -> None:
    """Put the database back as it was before point.action. The caller closes its connection first."""
    backup.restore(ws, point.path)
    point.path.unlink()


# ---- on data shared through the cloud ---------------------------------------------------------------------------
# Putting an old copy of the file back would erase other machines' and the staff's work (docs/cloud/06), so there
# Hoàn tác cancels the document this machine has just saved, exactly like Huỷ phiếu: reverse movements, nothing
# deleted, and the cancel travels to the cloud like any other change. Only actions that create one new document
# can be taken back this way; the key is per machine (not in SHARED_META) and every new undo point clears it, so
# "the last action" is exact.
CLOUD_KEY = "cloud_undo_doc"
CLOUD_ACTIONS = ("receipt", "transfer", "trial_use", "stock_count")


@dataclass
class CloudUndo:
    doc_id: int
    action: str
    code: str


def remember_doc(conn, action: str, doc_id: int) -> None:
    """After `action` saved document doc_id (call it right after the save)."""
    if action not in CLOUD_ACTIONS:
        raise ValueError(action)
    conn.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (CLOUD_KEY, f"{action}:{doc_id}"))


def forget_doc(conn) -> None:
    conn.execute("DELETE FROM meta WHERE key = ?", (CLOUD_KEY,))


def cloud_latest(conn) -> CloudUndo | None:
    """The document Hoàn tác would cancel, if it is still active (it may have been cancelled or merged elsewhere)."""
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (CLOUD_KEY,)).fetchone()
    if row is None:
        return None
    action, _, doc_id = str(row[0]).partition(":")
    if action not in CLOUD_ACTIONS or not doc_id.isdigit():
        return None
    doc = conn.execute("SELECT code, status FROM documents WHERE id = ?", (int(doc_id),)).fetchone()
    if doc is None or doc["status"] != "active":
        return None
    return CloudUndo(int(doc_id), action, doc["code"] or "")


def cloud_undo(conn, point: CloudUndo) -> None:
    """Cancel the document (one transaction); the next sync round carries it to the cloud."""
    with db.transaction(conn):
        close_document(conn, point.doc_id, "cancelled")
        forget_doc(conn)
