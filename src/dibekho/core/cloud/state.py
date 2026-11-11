"""Which owner commands this machine has already carried out -- kept OUTSIDE the database.

Undo, a restore and a package import all replace the whole database, so anything stored in it rolls back too. If
"already applied" lived there, pressing Hoàn tác on the owner's batch would make the next poll apply the same
commands again, silently undoing the Undo. This file survives those: a command is auto-applied at most once.

An entry is {"ok": bool, "summary": str, "confirmed": bool}; "confirmed" says the cloud was told the outcome. When the
network failed at that moment the entry is kept unconfirmed and only the confirmation is retried -- never the command.
It lives next to config.json (workspace.config_dir()), so the test suite's isolated config dir covers it too.
"""

import json

from dibekho.core import workspace

FILE = "cloud_state.json"
KEEP = 1000  # newest entries; a request older than that has long been answered


def _path():
    return workspace.config_dir() / FILE


def load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(done: dict) -> None:
    if len(done) > KEEP:
        done = dict(list(done.items())[-KEEP:])
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def mark(item_id: str, ok: bool, summary: str, confirmed: bool) -> None:
    done = load()
    done.pop(item_id, None)  # re-insert at the end: the newest entries are the ones kept
    done[item_id] = {"ok": ok, "summary": summary, "confirmed": confirmed}
    _save(done)


def is_done(item_id: str) -> bool:
    return item_id in load()


def unconfirmed() -> dict:
    return {k: v for k, v in load().items() if not v.get("confirmed")}
