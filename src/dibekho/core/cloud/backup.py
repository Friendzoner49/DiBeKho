"""Full off-machine backups in the private Supabase Storage bucket 'backups'.

The mirror tables are a summary for the web (stock is aggregated, many columns are left out), so they cannot
rebuild the database. This is the real backup: a consistent copy of kho.sqlite (backup.snapshot), a few hundred
KB, gzip-compressed (about a third of the size; the cloud's free space is limited), uploaded when the app closes
after a change and on Đồng bộ ngay. The newest KEEP are kept (older .sqlite files without gzip still restore). Restore goes through the same replace path
as a local backup (core.backup.restore), after the checks below.

The delivery notes kept in data/phieu-goc/<sha256>.xlsx (for Mở file gốc / Khôi phục file) go to the same private
bucket under phieu-goc/, each file once (its name is its content hash, so it never changes), a bounded number of
seconds per push; they are never pruned (old database backups still point at them). A restore downloads the ones
this machine lacks, each checked against its hash before it is written.
"""

import gzip
import hashlib
import re
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from dibekho import db
from dibekho.core import backup, transfer
from dibekho.core.cloud.client import CloudClient, CloudError
from dibekho.core.workspace import Workspace

KEEP = 10  # the machines keep their own daily backups too; the cloud only needs the last days
ORIGINALS = "phieu-goc"  # folder of the kept delivery notes in the bucket
# 2026-11-11T09-30-00Z__FRIENDZONER__s9.sqlite  (UTC time, machine name, schema version)
_NAME = re.compile(r"^(?P<at>\d{4}-\d\d-\d\dT\d\d-\d\d-\d\dZ)__(?P<device>.+)__s(?P<schema>\d+)\.sqlite(\.gz)?$")


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
    return f"{now:%Y-%m-%dT%H-%M-%SZ}__{_safe_device(device_name)}__s{schema_version}.sqlite.gz"


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
        data = gzip.compress(backup.snapshot(conn, Path(tmp) / "kho.sqlite").read_bytes(), compresslevel=6)
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
    if name.endswith(".gz"):
        try:
            data = gzip.decompress(data)
        except (OSError, EOFError) as exc:
            raise CloudError(f"Bản sao lưu trên Cloud bị hỏng: {exc}") from exc
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


# ---- the kept delivery notes (data/phieu-goc) ------------------------------------------------------------------

def cloud_originals(client: CloudClient, token: str) -> set[str]:
    """Names (<sha256>.xlsx) of the delivery notes already in the bucket."""
    found, offset, page = set(), 0, 1000
    while True:
        rows = client.storage_list(token, prefix=ORIGINALS, limit=page, offset=offset)
        if not rows:  # read on until an empty page: the server may hand out fewer than asked per page
            return found
        found.update(r["name"] for r in rows if transfer.ORIGINAL_NAME.fullmatch(r.get("name") or ""))
        offset += len(rows)


def upload_originals(ws: Workspace, client: CloudClient, token: str, max_seconds: float | None = None) -> tuple[int, int]:
    """Upload the kept notes the bucket does not have yet, stopping after max_seconds (the rest go next time).
    -> (uploaded, still to upload)."""
    local = transfer.original_files(ws)
    if not local:
        return 0, 0
    have = cloud_originals(client, token)
    todo = [f for f in local if f.name not in have]
    started, done = time.monotonic(), 0
    for f in todo:
        if max_seconds is not None and time.monotonic() - started > max_seconds:
            break
        client.storage_upload(f"{ORIGINALS}/{f.name}", f.read_bytes(), token)
        done += 1
    return done, len(todo) - done


def fetch_originals(ws: Workspace, client: CloudClient, token: str) -> tuple[int, int]:
    """After a restore: download the kept notes this machine lacks. A file whose content does not match its name
    is not written. Never raises for one file. -> (downloaded, failed)."""
    try:
        names = cloud_originals(client, token)
    except CloudError:
        return 0, 0
    have = {f.name for f in transfer.original_files(ws)}
    ws.originals.mkdir(parents=True, exist_ok=True)
    done = failed = 0
    for name in sorted(names - have):
        try:
            data = client.storage_download(f"{ORIGINALS}/{name}", token)
        except CloudError:
            failed += 1
            continue
        if hashlib.sha256(data).hexdigest() + ".xlsx" != name:
            failed += 1
            continue
        tmp = ws.originals / (name + ".tai-ve")
        tmp.write_bytes(data)
        tmp.replace(ws.originals / name)
        done += 1
    return done, failed
