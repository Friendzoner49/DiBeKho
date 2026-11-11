"""Push the mirror to the cloud (docs/cloud/04-thiet-ke-chot.md).

The meta keys cloud_last_push_id / cloud_last_push_at live in the SQLite database, so they travel with
data packages and roll back with Undo. A stale value only makes replace_mirror report a conflict, which
asks the user -- never a silent overwrite.
"""

import threading
from datetime import datetime

from dibekho import db
from dibekho.core import activity
from dibekho.core.cloud import backup as cloud_backup
from dibekho.core.cloud import inbox as cloud_inbox
from dibekho.core.cloud import mirror
from dibekho.core.cloud.client import CloudClient, CloudError


def has_unpushed(conn) -> bool:
    """Business data changed after the last cloud push (same ISO-string compare as
    transfer.has_unsent_changes uses for data packages)."""
    changed = db.get_meta(conn, "last_change_at")
    return bool(changed) and changed > db.get_meta(conn, "cloud_last_push_at")


_SESSION_LOCK = threading.Lock()  # the refresh token rotates: two refreshes at once would invalidate it


def session(cfg, timeout: float | None = None) -> tuple[CloudClient, str] | None:
    """Client + access token from the saved refresh token, for syncs with no password prompt
    (push on close, check on open). None when the cloud is not set up on this machine.
    Refresh tokens rotate, so the new one is saved at once. Raises CloudError when offline/expired."""
    if not (cfg.cloud_url and cfg.cloud_key and cfg.cloud_user and cfg.cloud_refresh_token):
        return None
    client = CloudClient(cfg.cloud_url, cfg.cloud_key, **({"timeout": timeout} if timeout else {}))
    with _SESSION_LOCK:
        tokens = client.refresh(cfg.cloud_refresh_token)
        cfg.cloud_refresh_token = tokens["refresh_token"]
        cfg.save()
    return client, tokens["access_token"]


def fetch_state(client: CloudClient, access_token: str) -> dict | None:
    """The cloud's single sync_state row: who pushed last and when. None before the first push ever."""
    rows = client.get("/rest/v1/sync_state?select=*", access_token)
    return rows[0] if rows else None


def finish_push(conn, cfg, client: CloudClient, access_token: str, with_backup: bool = True) -> str | None:
    """After a successful push: confirm the web slips recorded here, then upload the full backup.
    Returns the reason the backup could not be made (the push itself stands), else None."""
    cloud_inbox.finish_applied(conn, client, access_token)
    cloud_inbox.reconcile_applied(conn, client, access_token)
    if not with_backup:
        return None
    try:
        cloud_backup.upload_snapshot(conn, cfg, client, access_token)
    except CloudError as exc:
        activity.log("error", f"cloud backup: {exc}")
        return str(exc)
    return None


def last_push(conn) -> tuple[int | None, str]:
    """(push id this machine saw, when it pushed) -- for the status line and conflict checks."""
    raw = db.get_meta(conn, "cloud_last_push_id")
    return (int(raw) if raw else None), db.get_meta(conn, "cloud_last_push_at")


def push_mirror(conn, cfg, client: CloudClient, access_token: str, force: bool = False) -> dict:
    """Replace the whole cloud mirror with this database. Returns the RPC result:
    {"conflict": true, "last_push": {...}} when another machine pushed in between (ask the user,
    then call again with force=True), or {"conflict": false, "push_id": n} on success."""
    based_on, _ = last_push(conn)
    payload = mirror.build_payload(conn, cfg.device_id, cfg.device_name, based_on)
    result = client.rpc("replace_mirror", {"payload": payload, "force": force}, access_token)
    if not isinstance(result, dict) or "conflict" not in result:
        raise CloudError("Cloud trả về dữ liệu không hiểu được.")
    if result["conflict"] and (result.get("last_push") or {}).get("device_id") == cfg.device_id:
        # The newer push is this machine's own (an Undo or a restore rolled the saved push id back): nobody
        # else's work is overwritten, so it is not a conflict worth asking about.
        result = client.rpc("replace_mirror", {"payload": payload, "force": True}, access_token)
        if not isinstance(result, dict) or "conflict" not in result:
            raise CloudError("Cloud trả về dữ liệu không hiểu được.")
    if result["conflict"]:
        return result
    with db.transaction(conn):
        db.set_meta(conn, "cloud_last_push_id", str(result["push_id"]))
        db.set_meta(conn, "cloud_last_push_at", datetime.now().isoformat(timespec="seconds"))
        db.log(conn, "cloud_push", f"#{result['push_id']}")
    return result
