"""SQLite connection and migrations.

Migrations are plain SQL files in db/migrations named NNN_description.sql.
The applied version is stored in PRAGMA user_version.
"""

import sqlite3
from datetime import datetime
from importlib import resources
from pathlib import Path

from dibekho.core import activity
from dibekho.core.text import unaccent


def _migration_files() -> list[tuple[int, str]]:
    folder = resources.files("dibekho.db") / "migrations"
    items = []
    for entry in folder.iterdir():
        if entry.name.endswith(".sql"):
            items.append((int(entry.name.split("_", 1)[0]), entry.read_text(encoding="utf-8")))
    return sorted(items)


def schema_version() -> int:
    return max(v for v, _ in _migration_files())


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None)  # autocommit; we open transactions explicitly
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_function("unaccent", 1, unaccent, deterministic=True)
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, sql in _migration_files():
        if version <= current:
            continue
        with transaction(conn):
            for statement in _split_sql(sql):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {version}")


def _split_sql(sql: str) -> list[str]:
    # executescript() would commit implicitly; split so each migration stays in one transaction.
    # Comments are stripped first because they may contain ';'. Migrations must not put '--' or ';' in strings.
    lines = [line.split("--", 1)[0] for line in sql.splitlines()]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


class transaction:
    """`with transaction(conn):` -> BEGIN IMMEDIATE ... COMMIT, or ROLLBACK on error."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")
        return False


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def touch(conn: sqlite3.Connection) -> None:
    """Record that local data changed (used to warn before a data package overwrites it)."""
    set_meta(conn, "last_change_at", datetime.now().isoformat(timespec="seconds"))


def log(conn: sqlite3.Connection, action: str, detail: str = "") -> None:
    conn.execute("INSERT INTO app_log(action, detail) VALUES(?, ?)", (action, detail))
    # also in the activity file; written inside the transaction, so an action rolled back may leave its line
    # (the error line follows it)
    activity.log("data", f"{action} {detail}".strip())
