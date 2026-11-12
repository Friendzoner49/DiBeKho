"""Signing in without the password (rotating refresh token) and the housekeeping after syncing: confirming the staff
requests approved here, and the full backup in Storage. The data itself travels through core.cloud.twoway.

The meta key cloud_last_push_at (name kept from the old mirror) now means: the last full backup uploaded to the cloud.
"""

import threading
from datetime import datetime

from dibekho import db
from dibekho.core import activity
from dibekho.core.cloud import backup as cloud_backup
from dibekho.core.cloud import inbox as cloud_inbox
from dibekho.core.cloud import replica, twoway
from dibekho.core.cloud.client import CloudClient, CloudError


def has_unpushed(conn) -> bool:
    """Business data changed after the last full backup uploaded to the cloud (same ISO-string compare as
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
    return client, rotate(cfg, client)["access_token"]


def rotate(cfg, client: CloudClient) -> dict:
    """Swap the saved refresh token for a new one (they rotate: two refreshes with the same token at once would
    leave one of them holding a used token), saved at once. -> {"access_token", "refresh_token"}."""
    with _SESSION_LOCK:
        tokens = client.refresh(cfg.cloud_refresh_token)
        cfg.cloud_refresh_token = tokens["refresh_token"]
        cfg.save()
    return tokens


def finish_push(conn, cfg, client: CloudClient, access_token: str, with_backup: bool = True) -> str | None:
    """After syncing: confirm the staff requests approved here, then upload the full backup.
    Returns the reason the backup could not be made, else None."""
    # on shared data a request is shown as recorded only once its document is on the cloud (nothing left to send)
    if not (replica.enabled(conn) and twoway.queued_count(conn)):
        cloud_inbox.finish_applied(conn, client, access_token)
    cloud_inbox.reconcile_applied(conn, client, access_token)
    if not with_backup:
        return None
    try:
        name = cloud_backup.upload_snapshot(conn, cfg, client, access_token)
    except CloudError as exc:
        activity.log("error", f"cloud backup: {exc}")
        return str(exc)
    with db.transaction(conn):
        db.set_meta(conn, "cloud_last_push_at", datetime.now().isoformat(timespec="seconds"))
        db.log(conn, "cloud_backup", name)
    return None


def last_backup(conn) -> str:
    """When this machine last uploaded a full backup ('' = never)."""
    return db.get_meta(conn, "cloud_last_push_at")
