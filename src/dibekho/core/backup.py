"""Automatic daily backups into sao-luu/ (keeps the newest 14) and restore."""

import os
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

from dibekho.core.workspace import Workspace

KEEP = 14
DAILY_PREFIX = "DiBeKho_"


def snapshot(conn: sqlite3.Connection, dest: Path) -> Path:
    """Consistent copy of the open database (safe while the app is running)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    target = sqlite3.connect(str(tmp))
    try:
        conn.backup(target)
    finally:
        target.close()
    os.replace(tmp, dest)
    return dest


def daily_backup(conn, ws: Workspace, today: date | None = None) -> Path | None:
    today = today or date.today()
    dest = ws.backups / f"{DAILY_PREFIX}{today.isoformat()}.sqlite"
    if dest.exists():
        return None
    snapshot(conn, dest)
    _prune(ws)
    return dest


def named_backup(conn, ws: Workspace, label: str) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return snapshot(conn, ws.backups / f"{label}_{stamp}.sqlite")


def list_backups(ws: Workspace) -> list[Path]:
    if not ws.backups.exists():
        return []
    return sorted(ws.backups.glob("*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)


def restore(ws: Workspace, backup: Path) -> None:
    """Replace the database file. The caller must close its connection first."""
    tmp = ws.db_path.with_suffix(".restore")
    shutil.copy2(backup, tmp)
    os.replace(tmp, ws.db_path)


def _prune(ws: Workspace) -> None:
    daily = sorted(ws.backups.glob(f"{DAILY_PREFIX}*.sqlite"), reverse=True)
    others = sorted(set(ws.backups.glob("*.sqlite")) - set(daily), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in daily[KEEP:] + others[KEEP:]:
        try:
            old.unlink()
        except OSError:
            pass
