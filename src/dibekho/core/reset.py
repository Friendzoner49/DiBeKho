"""Reset the app's data. A backup is always taken first (sao-luu/), so a reset can be undone.

- reset_stock: keep the product catalog (with learned names and dropped lines); remove every document,
  movement, customer and read file, so stock is 0 and every delivery note is read again from scratch.
- reset_all: an empty database, as right after installing. The settings (language, size, folder) are kept.

Files the user put in the workspace (delivery notes, input/, output/, backups) are never deleted; notes in
phieu-giao-hang/da-xu-ly/ are moved back into phieu-giao-hang/ so they are read again.
"""

import shutil

from dibekho import db
from dibekho.core import backup, deliveries
from dibekho.core.workspace import Workspace

# children first (foreign keys)
_STOCK_TABLES = ("stock_movements", "document_skipped_lines", "document_lines", "scanned_files", "documents",
                 "customers")


def reset_stock(conn, ws: Workspace) -> int:
    """Returns the number of delivery-note files moved back out of da-xu-ly."""
    backup.named_backup(conn, ws, "truoc-dat-lai-ton")
    with db.transaction(conn):
        for table in _STOCK_TABLES:
            conn.execute(f"DELETE FROM {table}")
        db.touch(conn)
        db.log(conn, "reset_stock", "")
    # data/phieu-goc/ is kept: the notes are read again right away, and a restored backup still finds them
    return deliveries.move_all_out(ws)


def reset_all(conn, ws: Workspace) -> int:
    """Back up, then delete the database. The caller closes `conn` before and reopens it after
    (db.connect creates a new empty database). Returns the number of files moved back out of da-xu-ly."""
    backup.named_backup(conn, ws, "truoc-xoa-toan-bo")
    return deliveries.move_all_out(ws)


def wipe_database(ws: Workspace) -> None:
    """Second half of reset_all, with the connection closed."""
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = ws.db_path.with_name(ws.db_path.name + suffix)
        if path.exists():
            path.unlink()
    shutil.rmtree(ws.originals, ignore_errors=True)
    ws.originals.mkdir(parents=True, exist_ok=True)
