"""Push the mirror to the cloud (docs/cloud/04-thiet-ke-chot.md).

The meta keys cloud_last_push_id / cloud_last_push_at live in the SQLite database, so they travel with
data packages and roll back with Undo. A stale value only makes replace_mirror report a conflict, which
asks the user -- never a silent overwrite.
"""

from datetime import datetime

from dibekho import db
from dibekho.core.cloud import mirror
from dibekho.core.cloud.client import CloudClient, CloudError


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
    if result["conflict"]:
        return result
    with db.transaction(conn):
        db.set_meta(conn, "cloud_last_push_id", str(result["push_id"]))
        db.set_meta(conn, "cloud_last_push_at", datetime.now().isoformat(timespec="seconds"))
        db.log(conn, "cloud_push", f"#{result['push_id']}")
    return result
