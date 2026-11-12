"""Replacing the whole shared data while it lives on the cloud: restoring a backup, importing a data package, deleting
everything (docs/cloud/06-cloud-la-goc.md, step 5). On data of one machine these swap kho.sqlite; on shared data the
cloud must end up holding exactly the new database, or the next sync would bring the old rows back.

The caller builds the new database as a separate file (the live one untouched), then calls replace_shared. One push
(sync_push, cloud/supabase/008) marks every live cloud row deleted and writes every row of the new database, in a
single transaction under the sync lock: a failure or a dropped line leaves the cloud as it was. Rows keep their uuid
when the new database knows it (a backup taken in cloud mode), so other machines see an edit, not a delete + insert.
Only once the cloud has it does the caller put the new file in place of the old one."""

from pathlib import Path

from dibekho import db
from dibekho.core import undo
from dibekho.core.cloud import replica, twoway
from dibekho.core.cloud.client import CloudError
from dibekho.db.sync_schema import SYNCED


class NotReady(Exception):
    """Shown to the user as-is."""


def check_ready(conn) -> None:
    """Changes of this machine still waiting, or unresolved conflicts, would be lost: send/resolve them first."""
    if twoway.conflicts(conn):
        raise NotReady("Còn thay đổi bị trùng chưa giải quyết (Cài đặt → Cloud → Xem các thay đổi trùng). "
                       "Giải quyết xong rồi làm lại.")
    if twoway.queued_count(conn):
        raise NotReady("Máy này còn thay đổi chưa gửi lên Cloud. Hãy đợi dòng Cloud báo đã đồng bộ "
                       "(cần có mạng) rồi làm lại.")


def _key(t) -> str:
    return t.key if t.natural else "id"


def build_batch(new_conn, live: dict[str, set]) -> dict[str, list[dict]]:
    """Every live cloud row marked deleted, then every row of the new database (sync_push applies the deletes first,
    so codes and keys are free again before the rows that take them are written)."""
    rows = replica.snapshot(new_conn)
    batch = {}
    for t in SYNCED:
        key = _key(t)
        batch[t.name] = [{key: k, "deleted": True} for k in sorted(live.get(t.name, ()))] + rows[t.name]
    return batch


def live_keys(pulled: dict) -> dict[str, set]:
    return {t.name: {r[_key(t)] for r in pulled.get("tables", {}).get(t.name, []) if not r.get("deleted")}
            for t in SYNCED}


def replace_shared(conn, new_path: Path, client, token: str, device: str) -> int:
    """Make the cloud hold exactly the database at new_path and prepare that file to carry on from there (cursor,
    empty queue, cloud mode on). Returns the cloud's revision. Raises NotReady / CloudError with the cloud unchanged."""
    check_ready(conn)
    pulled = twoway.fetch(client, token, 0)
    new = db.connect(new_path)
    try:
        with db.transaction(new):
            new.execute("DELETE FROM sync_outbox")
            replica.set_enabled(new, False)
        batch = build_batch(new, live_keys(pulled))
        answer = twoway.send(client, token, device, int(pulled.get("max_rev") or 0), batch)
        if not answer.get("ok"):
            raise CloudError("Có máy khác hoặc trang web vừa ghi dữ liệu trong lúc thay. Chưa có gì bị đổi; "
                             "hãy làm lại.")
        rev = int(answer["max_rev"])
        with db.transaction(new):
            db.set_meta(new, twoway.CURSOR_KEY, str(rev))
            db.set_meta(new, twoway.CONFLICTS_KEY, "[]")
            undo.forget_doc(new)
            replica.set_enabled(new, True)
        return rev
    finally:
        new.close()
