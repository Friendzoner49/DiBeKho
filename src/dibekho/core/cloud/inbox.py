"""Web inbox: goods-in slips typed on the webapp, pulled by the desktop and applied through core.receipts.

An item is applied locally first; its cloud row is marked 'applied' only during a later push cycle, and
only when the created document still exists -- so an Undo before the push simply lets the item come back
as pending (docs/cloud/04-thiet-ke-chot.md, section 3). The link item->document lives in meta, so it
travels with data packages and rolls back together with the data.
"""

import json
from datetime import date, datetime

from dibekho import db
from dibekho.core import receipts
from dibekho.core.cloud.client import CloudClient
from dibekho.core.stock import LOCATIONS, MAIN
from dibekho.core.text import clean
from dibekho.core.workspace import Workspace

META_KEY = "cloud_inbox_applied"  # {"<item uuid>": document id}


def applied_map(conn) -> dict:
    try:
        return json.loads(db.get_meta(conn, META_KEY, "{}"))
    except ValueError:
        return {}


def fetch_pending(conn, client: CloudClient, access_token: str) -> list[dict]:
    """Pending items, oldest first, minus those already applied locally and awaiting push confirmation."""
    rows = client.get("/rest/v1/web_inbox?status=eq.pending&order=created_at", access_token) or []
    seen = applied_map(conn)
    return [r for r in rows if r.get("id") not in seen and r.get("kind") == "receipt"]


def check(conn, item: dict) -> tuple[receipts.ReceiptInput, list[str]]:
    """Payload -> ReceiptInput + the reasons it cannot be applied as it is (plain Vietnamese)."""
    p = item.get("payload") or {}
    errors: list[str] = []
    try:
        doc_date = date.fromisoformat(str(p.get("doc_date")))
    except ValueError:
        errors.append("Ngày không hợp lệ.")
        doc_date = date.today()
    location = p.get("location_id") if p.get("location_id") in LOCATIONS else MAIN
    lines = []
    for raw in p.get("lines") or []:
        try:
            product_id, qty = int(raw.get("product_id")), float(raw.get("qty"))
        except (TypeError, ValueError):
            errors.append("Có dòng hàng không đọc được.")
            continue
        row = conn.execute("SELECT code, active FROM products WHERE id = ?", (product_id,)).fetchone()
        if row is None:
            errors.append(f"Mặt hàng #{product_id} không còn trong danh mục (đã xoá hoặc gộp).")
            continue
        if qty <= 0:
            errors.append(f"Số lượng của {row['code']} phải lớn hơn 0.")
            continue
        lines.append(receipts.ReceiptLineInput(qty, product_id, note=clean(str(raw.get("note") or ""))))
    if not lines:
        errors.append("Phiếu không có dòng hàng nào dùng được.")
    data = receipts.ReceiptInput(doc_date, receipts.SUPPLIER,
                                 supplier_name=clean(str(p.get("supplier_name") or "")) or "Web",
                                 note=clean(str(p.get("note") or "")), lines=lines, location_id=location)
    return data, errors


def describe(conn, item: dict) -> str:
    """One line per goods line, for the confirm dialog."""
    data, _ = check(conn, item)
    out = []
    for ln in data.lines:
        row = conn.execute("SELECT code, name_vi, spec FROM products WHERE id = ?", (ln.product_id,)).fetchone()
        label = f"{row['code']} {row['name_vi']} {row['spec']}".strip() if row else f"#{ln.product_id}"
        out.append(f"• {label}: {ln.qty:g}")
    return "\n".join(out)


def apply_item(conn, ws: Workspace, item: dict) -> int:
    """Record the receipt through the normal business path, then remember item -> document."""
    data, errors = check(conn, item)
    if errors:
        raise ValueError(" ".join(errors))
    doc_id = receipts.save(conn, data, ws=ws)
    receipts.export_file(conn, ws, doc_id)
    with db.transaction(conn):
        m = applied_map(conn)
        m[item["id"]] = doc_id
        db.set_meta(conn, META_KEY, json.dumps(m))
        db.log(conn, "web_inbox_applied", f"{str(item['id'])[:8]} -> #{doc_id}")
    return doc_id


def reject(client: CloudClient, access_token: str, item_id: str, reason: str = "") -> None:
    client.patch(f"/rest/v1/web_inbox?id=eq.{item_id}",
                 {"status": "rejected", "result": {"reason": reason},
                  "applied_at": datetime.now().astimezone().isoformat(timespec="seconds")}, access_token)


def finish_applied(conn, client: CloudClient, access_token: str) -> int:
    """After a successful mirror push: confirm each locally applied item whose document still exists;
    one undone in the meantime is forgotten here and comes back as pending on the next pull.
    Progress is saved per item, so a network failure halfway is retried next cycle (PATCH is idempotent)."""
    confirmed = 0
    for item_id, doc_id in list(applied_map(conn).items()):
        row = conn.execute("SELECT code FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if row is not None:
            client.patch(f"/rest/v1/web_inbox?id=eq.{item_id}",
                         {"status": "applied", "result": {"doc_id": doc_id, "code": row["code"]},
                          "applied_at": datetime.now().astimezone().isoformat(timespec="seconds")}, access_token)
            confirmed += 1
        with db.transaction(conn):
            m = applied_map(conn)
            m.pop(item_id, None)
            db.set_meta(conn, META_KEY, json.dumps(m))
    return confirmed


def reconcile_applied(conn, client: CloudClient, access_token: str, limit: int = 50) -> int:
    """Web slips shown as recorded whose receipt is no longer in this database (an Undo, a restore or a package
    replaced the data) go back to pending: they reappear in Cần xử lý instead of staying ticked with nothing
    behind them. A receipt that was only cancelled or edited still exists, so its slip stays recorded."""
    rows = client.get(f"/rest/v1/web_inbox?status=eq.applied&order=applied_at.desc&limit={limit}", access_token) or []
    back = 0
    for row in rows:
        code = (row.get("result") or {}).get("code")
        if not code:
            continue
        if conn.execute("SELECT 1 FROM documents WHERE kind = 'receipt' AND code = ?", (code,)).fetchone():
            continue
        client.patch(f"/rest/v1/web_inbox?id=eq.{row['id']}",
                     {"status": "pending", "result": None, "applied_at": None}, access_token)
        back += 1
    return back
