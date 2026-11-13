"""Each main machine's activity log (data/app.log) kept on the cloud, so a problem on a customer's machine ('the app
is slow', an error) can be read without asking for a data package. Private bucket 'backups' (cloud/supabase/002:
the desktop role only), folder nhat-ky/, one gzip file per machine replaced each time (the bucket has no update
policy: delete, then upload). The log never holds what the user typed (core.activity); it does hold customer and
file names, which is why it stays in the private bucket like the backups."""

import gzip
import time
from pathlib import Path

from dibekho.core import activity
from dibekho.core.cloud.backup import _safe_device
from dibekho.core.cloud.client import CloudClient, CloudError
from dibekho.core.workspace import Workspace

FOLDER = "nhat-ky"
EVERY = 10 * 60  # s: at most one upload per machine in this time (each one is a small gzip, ~100 KB at most)


def name_for(cfg) -> str:
    return f"{FOLDER}/{_safe_device(cfg.device_name)}-{cfg.device_id}.log.gz"


def upload_log(ws: Workspace, cfg, client: CloudClient, token: str) -> bool:
    """Put this machine's app.log on the cloud (replacing its last copy). False when there is no log yet."""
    path = Path(ws.data) / activity.FILE_NAME
    if not path.exists():
        return False
    data = gzip.compress(path.read_bytes())
    name = name_for(cfg)
    try:
        client.storage_delete([name], token)
    except CloudError:
        pass  # not there yet
    client.storage_upload(name, data, token)
    return True


class LogUploader:
    """Uploads at most once every EVERY seconds; called from the sync worker thread (network only, never the
    database). A failure is written to the log and never stops a sync."""

    def __init__(self, every: float = EVERY):
        self.every, self.last = every, None

    def maybe_upload(self, ws: Workspace, cfg, client: CloudClient, token: str) -> None:
        now = time.monotonic()
        if self.last is not None and now - self.last < self.every:
            return
        self.last = now
        try:
            upload_log(ws, cfg, client, token)
        except (CloudError, OSError) as exc:
            activity.log("error", f"uploading the activity log: {exc}")


def fetch_logs(client: CloudClient, token: str, folder: Path) -> list[Path]:
    """Download every machine's log into folder (for the developer: scripts/fetch_cloud_logs.py)."""
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for row in client.storage_list(token, prefix=FOLDER, limit=100):
        name = row.get("name") or ""
        if not name.endswith(".log.gz"):
            continue
        target = folder / name[: -len(".gz")]
        target.write_bytes(gzip.decompress(client.storage_download(f"{FOLDER}/{name}", token)))
        out.append(target)
    return out
