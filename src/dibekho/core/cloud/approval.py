"""Staff accounts in the app: what a staff machine would write waits for the owner (cloud/supabase/016_staff_push.sql).

Only the owner's account (role 'desktop') writes the shared data. A machine signed in with a staff account ('editor')
works as usual on its own copy and pulls what the others wrote; instead of pushing, it sends its whole queue as one
request (send_if_changed) with a summary the owner can read. The owner approves or refuses it in Cần xử lý (decide).
Approved: the cloud writes that very batch under the staff machine's name, so the machine finds its own rows at the
next pull and its queue empties by itself (twoway.merge: echoes). Refused: the machine keeps its changes and shows
the owner's reason; it sends again as soon as something changed, or gives the changes up (discard).

No Qt here; the network calls touch no database and the database calls no network (see ui/sync_runner.py)."""

import hashlib
import json

from dibekho import db
from dibekho.core.cloud import replica, twoway

OWNER, STAFF, VIEWER = "desktop", "editor", "viewer"
SENT_KEY = "staff_sent_hash"  # per machine: the queue as it was last sent for approval
STATE_KEY = "staff_request"  # per machine: JSON of the newest request's state, for the screens
_DOC_KINDS = ("delivery", "receipt", "stock_count", "transfer", "trial")


def is_staff(cfg) -> bool:
    return getattr(cfg, "cloud_role", "") == STAFF


def is_owner(cfg) -> bool:
    """An account that writes the shared data. A machine not signed in at all (tests, a build without the cloud)
    counts too: nothing is sent anywhere."""
    return getattr(cfg, "cloud_role", "") in (OWNER, "")


# ---- the staff machine --------------------------------------------------------------------------------------------

def batch_hash(batch: dict) -> str:
    return hashlib.sha256(json.dumps(batch, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def summarize(conn, batch: dict) -> list[dict]:
    """What the owner reads before approving: the documents (kind, code, date, customer, how many lines), products
    and customers added or changed, and how many other rows (names learned, lines dropped, settings)."""
    out: list[dict] = []
    customers = {}
    for r in batch.get("customers", []):
        if not r.get("deleted"):
            customers[r["id"]] = r.get("name") or ""
    lines: dict[str, int] = {}
    for r in batch.get("document_lines", []):
        if not r.get("deleted") and r.get("document_id"):
            lines[r["document_id"]] = lines.get(r["document_id"], 0) + 1
    for r in batch.get("documents", []):
        if r.get("deleted"):
            out.append({"t": "doc_deleted"})
            continue
        name = customers.get(r.get("customer_id"))
        if name is None and r.get("customer_id"):
            local = replica.local_for(conn, "customers", r["customer_id"])
            row = None if local is None else conn.execute("SELECT name FROM customers WHERE id = ?", (local,)).fetchone()
            name = row[0] if row else ""
        out.append({"t": "doc", "kind": r.get("kind") if r.get("kind") in _DOC_KINDS else "", "code": r.get("code") or "",
                    "date": str(r.get("doc_date") or "")[:10], "customer": name or "",
                    "status": r.get("status") or "", "lines": lines.get(r["id"], 0)})
    for r in batch.get("products", []):
        if r.get("deleted"):
            out.append({"t": "product_deleted"})
        else:
            out.append({"t": "product", "code": r.get("code") or "",
                        "name": " ".join(x for x in (r.get("name_vi"), r.get("variant")) if x) or r.get("name_zh") or ""})
    for name in customers.values():
        out.append({"t": "customer", "name": name})
    rest = sum(len(batch.get(t, [])) for t in ("suppliers", "product_aliases", "ignored_lines", "meta"))
    rest += sum(1 for r in batch.get("customers", []) if r.get("deleted"))
    if rest:
        out.append({"t": "other", "n": rest})
    return out


def state(conn) -> dict:
    """{"status": "" | "pending" | "approved" | "rejected", "reason", "at"} of this machine's newest request."""
    try:
        data = json.loads(db.get_meta(conn, STATE_KEY, "") or "{}")
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _set_state(conn, **values) -> None:
    db.set_meta(conn, STATE_KEY, json.dumps(values, ensure_ascii=False))


def _sent_info(conn) -> dict:
    """{"hash", "seq", "id"} of the request last sent from here ({} = none waiting)."""
    try:
        data = json.loads(db.get_meta(conn, SENT_KEY, "") or "{}")
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def needs_sending(conn, batch: dict) -> bool:
    """The queue differs from what was last sent (a refused request is not sent again unchanged)."""
    return not twoway.empty(batch) and _sent_info(conn).get("hash") != batch_hash(batch)


def send(client, token: str, device: str, base_rev: int, batch: dict, summary: list[dict]) -> dict:
    """Network only."""
    return client.rpc("push_request_send", {"p_device": device, "p_base": base_rev, "p_batch": batch,
                                            "p_summary": summary}, token)


def mine(client, token: str, device: str) -> dict | None:
    """Network only: this machine's newest request on the cloud, or None."""
    answer = client.rpc("push_request_mine", {"p_device": device}, token)
    return answer if isinstance(answer, dict) else None


def sent(conn, batch: dict, seq: int, answer) -> None:
    """After send(): remember which queue entries (up to seq) the request carries."""
    request_id = answer.get("id") if isinstance(answer, dict) else None
    with db.transaction(conn):
        db.set_meta(conn, SENT_KEY, json.dumps({"hash": batch_hash(batch), "seq": int(seq), "id": request_id}))
        _set_state(conn, status="pending", reason="", at="")


STALE = "__stale__"


def take_answer(conn, request: dict | None) -> bool:
    """What the cloud says about this machine's newest request, taken BEFORE merging the pull of the same round.

    - approved (the request sent from here): its queue entries are cleared, as twoway.finish does after a push, so
      the rows coming back are applied as the cloud's (not seen as changes of ours: shared meta keys would be
      queued again and sent for approval for ever);
    - closed as stale by the cloud: sent again after this round's merge;
    - refused by the owner: the reason is shown; sent again only once something changed.
    Returns True when what the screens show changed."""
    before, info = state(conn), _sent_info(conn)
    mine_now = request is not None and info.get("id") and request.get("id") == info.get("id")
    status = str(request.get("status") or "") if mine_now else ""
    reason = str(request.get("reason") or "") if mine_now else ""
    with db.transaction(conn):
        if mine_now and status == "approved":
            replica.clear_outbox(conn, int(info.get("seq") or 0), keep=twoway.held(conn))
            db.set_meta(conn, SENT_KEY, "")
            status = ""
        elif mine_now and status == "rejected" and reason == STALE:
            db.set_meta(conn, SENT_KEY, "")
            status, reason = "", ""
        elif not mine_now and info.get("id") and request is None:
            db.set_meta(conn, SENT_KEY, "")  # the request is gone (deleted on the cloud): send again
        new = {"status": status, "reason": reason,
               "at": str(request.get("decided_at") or request.get("created_at") or "") if mine_now else ""}
        changed = {k: before.get(k, "") for k in ("status", "reason")} != {k: new[k] for k in ("status", "reason")}
        if changed:
            _set_state(conn, **new)
    return changed


def forget_answer_if_idle(conn) -> None:
    """Nothing queued here any more: no request is waiting."""
    if twoway.queued_count(conn) == 0 and (state(conn).get("status") or _sent_info(conn)):
        with db.transaction(conn):
            db.set_meta(conn, SENT_KEY, "")
            _set_state(conn, status="", reason="", at="")


def send_queue(conn, client, token: str, device: str) -> bool:
    """After merging: send this machine's queue for approval when it changed. True when a request went out.
    (The background runner does the same in steps: network off the main thread.)"""
    batch, seq, _ = twoway.prepare(conn)
    forget_answer_if_idle(conn)
    if not needs_sending(conn, batch):
        return False
    answer = send(client, token, device, twoway.cursor(conn), batch, summarize(conn, batch))
    sent(conn, batch, seq, answer)
    return True


def staff_round(conn, client, token: str, device: str) -> "twoway.Merged":
    """One whole round of a staff machine, in order: the answer about its request, the pull and merge, then the
    queue sent for approval (tests, and callers that do not need threads)."""
    take_answer(conn, mine(client, token, device))
    merged = twoway.merge(conn, twoway.fetch(client, token, twoway.cursor(conn)))
    send_queue(conn, client, token, device)
    return merged


def discard(conn) -> None:
    """Give up everything this machine did that the owner has not approved: its copy is emptied and the next round
    pulls the shared data again (the caller backed the file up first, and tells the cloud: cancel())."""
    twoway.start_from_cloud(conn)
    with db.transaction(conn):
        db.set_meta(conn, SENT_KEY, "")
        _set_state(conn, status="", reason="", at="")


def cancel(client, token: str, device: str) -> None:
    client.rpc("push_request_cancel", {"p_device": device}, token)


# ---- the owner ----------------------------------------------------------------------------------------------------

def pending(client, token: str) -> list[dict]:
    """Network only: requests waiting for the owner, oldest first: {id, sender, device, summary, created_at}."""
    rows = client.rpc("push_requests_pending", {}, token)
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def decide(client, token: str, request_id: str, approve: bool, reason: str = "") -> dict:
    """Network only. -> {"ok": True} | {"ok": False, "reason": "gone" | "stale"}."""
    answer = client.rpc("push_request_decide", {"p_id": request_id, "p_approve": bool(approve),
                                                "p_reason": reason or ""}, token)
    return answer if isinstance(answer, dict) else {"ok": False, "reason": "gone"}
