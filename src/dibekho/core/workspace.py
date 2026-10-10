"""Workspace folder layout and the tiny per-machine config file.

Everything the app stores lives inside one visible workspace folder
(default Documents/DiBeKho). Outside it there is only config.json.
"""

import json
import os
import platform
import socket
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from dibekho import APP_NAME

DELIVERIES = "phieu-giao-hang"
INPUT = "input"
PROCESSED = "da-xu-ly"
OUTPUT = "output"
BACKUPS = "sao-luu"
DATA = "data"
ORIGINALS = "phieu-goc"
DB_FILE = "kho.sqlite"


@dataclass(frozen=True)
class Workspace:
    root: Path

    @property
    def deliveries(self) -> Path:
        return self.root / DELIVERIES

    @property
    def input(self) -> Path:
        return self.root / INPUT

    @property
    def processed(self) -> Path:
        return self.root / INPUT / PROCESSED

    @property
    def output(self) -> Path:
        return self.root / OUTPUT

    @property
    def backups(self) -> Path:
        return self.root / BACKUPS

    @property
    def data(self) -> Path:
        return self.root / DATA

    @property
    def originals(self) -> Path:
        return self.root / DATA / ORIGINALS

    @property
    def db_path(self) -> Path:
        return self.root / DATA / DB_FILE

    def ensure(self) -> None:
        for folder in (self.deliveries, self.processed, self.output, self.backups, self.originals):
            folder.mkdir(parents=True, exist_ok=True)

    def cloud_sync_warning(self) -> str | None:
        """Name of a cloud-sync service if the workspace sits inside its folder."""
        text = str(self.root).lower()
        for marker, name in (
            ("onedrive", "OneDrive"),
            ("icloud", "iCloud"),
            ("mobile documents", "iCloud"),
            ("google drive", "Google Drive"),
            ("googledrive", "Google Drive"),
            ("dropbox", "Dropbox"),
        ):
            if marker in text:
                return name
        return None


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME


def default_workspace() -> Path:
    return Path.home() / "Documents" / APP_NAME


@dataclass
class Config:
    workspace: str
    language: str = "vi"
    device_id: str = ""
    device_name: str = ""

    @staticmethod
    def path() -> Path:
        return config_dir() / "config.json"

    @classmethod
    def load(cls) -> "Config | None":
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return None

    @classmethod
    def create(cls, workspace: Path) -> "Config":
        return cls(
            workspace=str(workspace),
            device_id=uuid.uuid4().hex[:12],
            device_name=(socket.gethostname() or platform.node() or "may").split(".")[0],
        )

    def save(self) -> None:
        self.path().parent.mkdir(parents=True, exist_ok=True)
        self.path().write_text(json.dumps(self.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def remove(cls) -> None:
        try:
            cls.path().unlink()
            cls.path().parent.rmdir()
        except OSError:
            pass
