"""'Hoàn tác': undo the last actions the user may regret.

Just before such an action (Apply in 'Cần xử lý', forget a learned name, edit or delete a product, a stock
count, an import...) the app keeps a copy of the database in sao-luu/hoan-tac/. Undo puts the newest copy
back, so the data is exactly as it was before that action; pressing it again goes one step further back.
Files in phieu-giao-hang/ follow on the next scan (sort_files moves them in or out of da-xu-ly/).
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dibekho.core import backup
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
