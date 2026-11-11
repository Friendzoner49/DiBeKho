"""Full off-machine backups in the private Supabase Storage bucket 'backups'.

The mirror tables are a summary for the web (stock is aggregated, many columns are left out), so they cannot
rebuild the database. This is the real backup: a consistent copy of kho.sqlite (backup.snapshot), a few hundred
KB, uploaded after every successful push. The newest KEEP are kept. Restore goes through the same replace path
as a local backup (core.backup.restore), after the checks below.
"""

import re
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from dibekho import db
from dibekho.core import backup
from dibekho.core.cloud.client import CloudClient, CloudError

KEEP = 30
# 2026-11-11T09-30-00Z__FRIENDZONER__s9.sqlite  (UTC time, machine name, schema version)
_NAME = re.compile(r"^(?P<at>\d{4}-\d\d-\d\dT\d\d-\d\d-\d\dZ)__(?P<device>.+)__s(?P<schema>\d+)\.sqlite$")


@dataclass
class CloudBackup:
    name: str
    at: datetime  # local time
    device: str
    schema: int
    size: int


def _safe_device(name: str) -> str:
    return "".join(ch for ch in (name or "") if ch.isalnum() or ch in "-_") or "may"


def make_name(device_name: str, schema_version: int, now: datetime | None = None) -> str:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"{now:%Y-%m-%dT%H-%M-%SZ}__{_safe_device(device_name)}__s{schema_version}.sqlite"


def parse_name(name: str, size: int = 0) -> CloudBackup | None:
    m = _NAME.match(name or "")
    if not m:
        return None
    at = datetime.strptime(m["at"], "%Y-%m-%dT%H-%M-%SZ").replace(tzinfo=timezone.utc).astimezone()
    return CloudBackup(name, at, m["device"], int(m["schema"]), size)


def upload_snapshot(conn, cfg, client: CloudClient, token: str) -> str:
    """Upload a consistent copy of the database, then drop the oldest beyond KEEP. Returns the cloud file name."""
    schema = conn.execute("PRAGMA user_version").fetchone()[0]
    name = make_name(cfg.device_name, schema)
    with tempfile.TemporaryDirectory() as tmp:
        data = backup.snapshot(conn, Path(tmp) / "kho.sqlite").read_bytes()
    client.storage_upload(name, data, token)
    prune(client, token)
    return name


def list_backups(client: CloudClient, token: str) -> list[CloudBackup]:
    """Newest first. Files that are not ours (other names) are ignored."""
    found = []
    for row in client.storage_list(token):
        size = int(((row.get("metadata") or {}).get("size")) or 0)
        item = parse_name(row.get("name", ""), size)
        if item:
            found.append(item)
    return sorted(found, key=lambda b: b.name, reverse=True)  # names start with the UTC time


def prune(client: CloudClient, token: str, keep: int = KEEP) -> int:
    old = [b.name for b in list_backups(client, token)[keep:]]
    if old:
        client.storage_delete(old, token)
    return len(old)


def fetch(client: CloudClient, token: str, name: str, folder: Path) -> Path:
    """Download one backup into `folder` and check it is a usable DiBeKho database of this or an older version.
    Raises CloudError with a plain Vietnamese reason; nothing local is touched."""
    data = client.storage_download(name, token)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "kho.sqlite"
    path.write_bytes(data)
    validate(path)
    return path


def validate(path: Path) -> int:
    """Schema version of the file when it is safe to restore, else CloudError. Same rules as
    transfer._check_database: a real DiBeKho database, healthy, not from a newer app. An older one is upgraded
    on a copy first, so a failing migration cannot leave the working database half-replaced."""
    try:
        check = sqlite3.connect(f"file:{quote(path.resolve().as_posix(), safe='/:')}?mode=ro", uri=True)
        try:
            version = check.execute("PRAGMA user_version").fetchone()[0]
            tables = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            healthy = check.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            check.close()
    except sqlite3.DatabaseError as exc:
        raise CloudError(f"Bản sao lưu trên Cloud bị hỏng: {exc}") from exc
    if version < 1 or not {"products", "documents", "stock_movements"} <= tables or not healthy:
        raise CloudError("Bản sao lưu trên Cloud bị hỏng hoặc không phải dữ liệu DiBeKho. Dữ liệu trên máy "
                         "này không bị thay đổi.")
    if version > db.schema_version():
        raise CloudError("Bản sao lưu này do phiên bản DiBeKho mới hơn tạo ra. Hãy cập nhật app trước.")
    if version < db.schema_version():
        try:
            upgraded = db.connect(path)
            upgraded.close()
        except sqlite3.DatabaseError as exc:
            raise CloudError(f"Không nâng cấp được bản sao lưu cũ: {exc}") from exc
    return version


def after_restore(conn, cfg, chosen: CloudBackup) -> None:
    """Call right after the database file was replaced by `chosen`. A backup made by ANOTHER machine carries that
    machine's file list: its 'imported'/'missing' notes would all show up as lost files here, so they are hidden
    exactly as transfer.after_import does (the next scan re-links any file that exists on this machine)."""
    with db.transaction(conn):
        if chosen.device != _safe_device(cfg.device_name):
            conn.execute("UPDATE scanned_files SET status = 'missing_ignored' WHERE status IN ('imported', 'missing')")
        db.log(conn, "cloud_restore", chosen.name)
