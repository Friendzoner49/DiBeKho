"""Automatic daily backups into sao-luu/ (keeps the newest 10, nothing older than 30 days) and restore."""

import os
import shutil
import sqlite3
import tempfile
from datetime import date, datetime
from pathlib import Path

from dibekho.core.workspace import Workspace

KEEP = 10
MAX_AGE_DAYS = 30
KEEP_FLOOR = 3  # never pruned by age, even on a machine left idle for over a month
MAINTENANCE_DAYS = 14
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
    """Keep at most the newest KEEP backups of each kind (daily / named), and drop anything older than
    MAX_AGE_DAYS -- except the newest KEEP_FLOOR, so a machine left off for a month still opens with
    more than today's single copy."""
    daily = sorted(ws.backups.glob(f"{DAILY_PREFIX}*.sqlite"), reverse=True)
    others = sorted(set(ws.backups.glob("*.sqlite")) - set(daily), key=lambda p: p.stat().st_mtime, reverse=True)
    cutoff = datetime.now().timestamp() - MAX_AGE_DAYS * 86400
    for group in (daily, others):
        for i, p in enumerate(group):
            if i < KEEP_FLOOR:
                continue
            if i >= KEEP or p.stat().st_mtime < cutoff:
                try:
                    p.unlink()
                except OSError:
                    pass


def maintenance_due(cfg) -> bool:
    if not cfg.last_cleanup:
        return True
    try:
        last = date.fromisoformat(cfg.last_cleanup)
    except ValueError:
        return True
    return (date.today() - last).days >= MAINTENANCE_DAYS


def run_maintenance(conn: sqlite3.Connection, ws: Workspace, cfg) -> None:
    """Every two weeks: prune old backups, shrink the database file, clear the read-only copies left in the
    system temp folder for 'Mở file gốc'. Never touches phieu-goc/, input/, output/ or sao-luu/hoan-tac/."""
    _prune(ws)
    try:
        conn.execute("VACUUM")
    except sqlite3.DatabaseError:
        pass
    _clear_viewing_copies()
    cfg.last_cleanup = date.today().isoformat()
    cfg.save()


def _clear_viewing_copies() -> None:
    folder = Path(tempfile.gettempdir()) / "DiBeKho"
    if not folder.exists():
        return
    for item in folder.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            try:
                item.unlink()
            except OSError:
                pass
