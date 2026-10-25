"""Hand-over of all data to another machine (".dibekho" package).

Model: only one machine works at a time. Importing a package REPLACES local data
(after a backup). There is no two-way merge.
"""

import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dibekho import __version__, db
from dibekho.core import activity, backup
from dibekho.core.workspace import Config, Workspace

EXTENSION = ".dibekho"
FORMAT = 1


@dataclass
class Manifest:
    device_name: str
    device_id: str
    exported_at: str
    schema_version: int
    app_version: str
    deliveries: int
    products: int

    @classmethod
    def from_dict(cls, d: dict) -> "Manifest":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})


class TransferError(Exception):
    pass


def has_unsent_changes(conn) -> bool:
    """Local data changed after the last export/import."""
    changed = db.get_meta(conn, "last_change_at")
    transferred = db.get_meta(conn, "last_transfer_at")
    return bool(changed) and changed > transferred


def export_package(conn, ws: Workspace, cfg: Config) -> Path:
    now = datetime.now()
    db.set_meta(conn, "last_transfer_at", now.isoformat(timespec="seconds"))
    db.log(conn, "export", cfg.device_name)
    manifest = Manifest(
        device_name=cfg.device_name,
        device_id=cfg.device_id,
        exported_at=now.isoformat(timespec="seconds"),
        schema_version=conn.execute("PRAGMA user_version").fetchone()[0],
        app_version=__version__,
        deliveries=conn.execute(
            "SELECT COUNT(*) FROM documents WHERE kind = 'delivery' AND status = 'active'").fetchone()[0],
        products=conn.execute("SELECT COUNT(*) FROM products WHERE active = 1").fetchone()[0],
    )
    ws.output.mkdir(parents=True, exist_ok=True)
    safe_device = "".join(ch for ch in cfg.device_name if ch.isalnum() or ch in "-_") or "may"
    dest = ws.output / f"DiBeKho_{safe_device}_{now:%Y-%m-%d_%H%M}{EXTENSION}"
    with tempfile.TemporaryDirectory() as tmp:
        snap = backup.snapshot(conn, Path(tmp) / "kho.sqlite")
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps({**manifest.__dict__, "format": FORMAT}, ensure_ascii=False))
            z.write(snap, "kho.sqlite")
            for f in original_files(ws):
                z.write(f, f"phieu-goc/{f.name}")
            log_path = ws.data / activity.FILE_NAME
            if log_path.exists():
                z.write(log_path, "data/app.log")
    return dest


# data/phieu-goc/<sha256>.xlsx; anything else there (an Excel lock file '~$<sha256>.xlsx' left while a copy
# is open, a file the user put there) is not part of the data
ORIGINAL_NAME = re.compile(r"[0-9a-f]{64}\.xlsx")


def original_files(ws: Workspace) -> list[Path]:
    return sorted(f for f in ws.originals.glob("*.xlsx") if ORIGINAL_NAME.fullmatch(f.name))


def is_older(manifest: Manifest) -> bool:
    """The package comes from an earlier version (older schema): it is upgraded when imported."""
    return manifest.schema_version is not None and manifest.schema_version < db.schema_version()


def read_manifest(path: Path) -> Manifest:
    try:
        with zipfile.ZipFile(path) as z:
            data = json.loads(z.read("manifest.json").decode("utf-8"))
            if "kho.sqlite" not in z.namelist():
                raise TransferError("Gói dữ liệu thiếu database.")
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise TransferError(f"File gói dữ liệu bị hỏng: {exc}") from exc
    manifest = Manifest.from_dict(data)
    if manifest.schema_version is None or manifest.schema_version > db.schema_version():
        raise TransferError("Gói dữ liệu được tạo bởi phiên bản DiBeKho mới hơn. Hãy cập nhật app trước.")
    return manifest


def import_package(ws: Workspace, path: Path) -> Manifest:
    """Replace local data with the package. Caller: close the connection before, reopen after,
    then call `after_import(conn, manifest)`.
    """
    manifest = read_manifest(path)
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(path) as z:
            z.extract("kho.sqlite", tmp)
        # a package from an older version is brought to this version's schema here, on the extracted copy:
        # if that fails, nothing on this computer has been replaced yet
        upgraded = db.connect(Path(tmp) / "kho.sqlite")
        upgraded.close()
        with zipfile.ZipFile(path) as z:
            originals = [n for n in z.namelist()
                         if n.startswith("phieu-goc/") and ORIGINAL_NAME.fullmatch(Path(n).name)]
            ws.originals.mkdir(parents=True, exist_ok=True)
            for name in originals:
                target = ws.originals / Path(name).name
                if not target.exists():
                    with z.open(name) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        new_db = ws.db_path.with_suffix(".incoming")
        shutil.copy2(Path(tmp) / "kho.sqlite", new_db)
        os.replace(new_db, ws.db_path)
    _save_sender_log(ws, path, manifest)
    return manifest


def _safe_device_name(name: str) -> str:
    return "".join(ch for ch in (name or "") if ch.isalnum() or ch in "-_") or "may"


def _save_sender_log(ws: Workspace, path: Path, manifest: Manifest) -> None:
    """The sending machine's own activity log, if the package carries one, saved apart under its own name
    (data/nhat-ky-<máy gửi>.log) so a mistake made there can be traced -- never this machine's own app.log,
    and replaced (not added to) by a later import from the same machine. Trimmed to the same 7 days."""
    try:
        with zipfile.ZipFile(path) as z:
            if "data/app.log" not in z.namelist():
                return
            text = z.read("data/app.log").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError, OSError):
        return
    dest = ws.data / f"nhat-ky-{_safe_device_name(manifest.device_name)}.log"
    try:
        ws.data.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8", newline="\n")
        activity.trim_old(dest)
    except OSError:
        pass


def after_import(conn, manifest: Manifest) -> None:
    # File paths in the package belong to the other machine. Hide "missing" warnings for them;
    # the next scan re-links any file that exists here with the same content.
    conn.execute("UPDATE scanned_files SET status = 'missing_ignored' WHERE status IN ('imported', 'missing')")
    now = datetime.now().isoformat(timespec="seconds")
    db.set_meta(conn, "last_transfer_at", now)
    db.set_meta(conn, "last_change_at", now)
    db.set_meta(conn, "last_import_from", f"{manifest.device_name} ({manifest.exported_at})")
    db.log(conn, "import", manifest.device_name)


def move_to_processed(ws: Workspace, path: Path) -> Path:
    ws.processed.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = ws.processed / f"{path.stem}__{stamp}{path.suffix}"
    shutil.move(str(path), dest)
    return dest
