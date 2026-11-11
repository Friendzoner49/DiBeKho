"""Web inbox: requests staff send from the webapp, pulled by the desktop and approved by the owner.

Three kinds (cloud/supabase/001_init.sql + 004_staff_requests.sql):
- receipt        a goods-in slip typed on the web, recorded through core.receipts
- delivery_file  an Excel delivery note uploaded to the private bucket 'inbox-files'; approving it only puts the
                 file in phieu-giao-hang/, so the normal scan reads it (names, prices, duplicates, "Mở file gốc")
- stock_count    a physical count, recorded through core.stock.stock_count at the moment it was SENT, so what
                 happened in the shop afterwards is not folded into its difference

Nothing reaches the books before the owner approves. A receipt or count is applied locally first; its cloud row is
marked 'applied' only after a later successful push, and only while the created document still exists -- so an Undo
before the push simply lets the request come back as pending (docs/cloud/04-thiet-ke-chot.md, section 3). The
link request -> document lives in meta, so it travels with data packages and rolls back together with the data.
"""

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from dibekho import db
from dibekho.core import activity, receipts, stock
from dibekho.core.cloud.client import CloudClient, CloudError
from dibekho.core.stock import LOCATIONS, MAIN
from dibekho.core.text import clean
from dibekho.core.workspace import Workspace

RECEIPT, DELIVERY_FILE, STOCK_COUNT = "receipt", "delivery_file", "stock_count"
KINDS = (RECEIPT, DELIVERY_FILE, STOCK_COUNT)
# operations only the owner (a `desktop` account) can send; core/cloud/commands.py carries them out
CMD_KINDS = ("cmd_transfer", "cmd_trial", "cmd_product_add", "cmd_product_edit", "cmd_product_merge",
             "cmd_customer_merge", "cmd_cancel_doc", "cmd_set_location", "cmd_receipt_edit")
FILES_BUCKET = "inbox-files"
MAX_FILE = 2 * 1024 * 1024   # an Excel delivery note is tens of KB
MAX_UNZIPPED = 50 * 1024 * 1024  # guard against a zip bomb behind a small .xlsx
META_KEY = "cloud_inbox_applied"  # {"<request uuid>": document id} for receipts and counts


def applied_map(conn) -> dict:
    try:
        return json.loads(db.get_meta(conn, META_KEY, "{}"))
    except ValueError:
        return {}


def _store_applied(conn, mapping: dict) -> None:
    db.set_meta(conn, META_KEY, json.dumps(mapping))


def payload_of(item: dict) -> dict:
    p = item.get("payload")
    return p if isinstance(p, dict) else {}


def sent_at(item: dict) -> datetime:
    """When the request reached the cloud, as this machine's local time (naive, like the database's created_at)."""
    text = str(item.get("created_at") or "")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except ValueError:
        return datetime.now()


# ---- pulling ------------------------------------------------------------------------------------------------

def fetch_pending(conn, client: CloudClient, access_token: str) -> list[dict]:
    """Pending requests and owner commands, oldest first, minus those already applied locally and awaiting push
    confirmation. Each gets 'sender' (the account's display name) and 'sender_role' ('desktop', 'editor', 'viewer');
    both are '' when the profiles cannot be read, and an unknown role is never trusted: nothing is auto-applied."""
    rows = client.get("/rest/v1/web_inbox?status=eq.pending&order=created_at", access_token) or []
    seen = applied_map(conn)
    items = [r for r in rows if r.get("id") not in seen and r.get("kind") in KINDS + CMD_KINDS]
    if items:
        who = sender_info(client, access_token)
        for item in items:
            known = who.get(item.get("created_by"), {})
            item["sender"] = known.get("name", "")
            item["sender_role"] = known.get("role", "")
    return items


def sender_info(client: CloudClient, access_token: str) -> dict:
    """{user id: {"name", "role"}}. Empty when the profiles cannot be read (then no one is treated as the owner)."""
    try:
        rows = client.get("/rest/v1/profiles?select=user_id,display_name,role", access_token) or []
    except CloudError:
        return {}
    return {r["user_id"]: {"name": r.get("display_name") or "", "role": r.get("role") or ""}
            for r in rows if r.get("user_id")}


# ---- receipt ------------------------------------------------------------------------------------------------

def check(conn, item: dict) -> tuple[receipts.ReceiptInput, list[str]]:
    """Payload -> ReceiptInput + the reasons it cannot be applied as it is (plain Vietnamese)."""
    return receipt_input(conn, payload_of(item))


def receipt_input(conn, p: dict) -> tuple[receipts.ReceiptInput, list[str]]:
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
        if raw.get("code") and raw.get("code") != row["code"]:  # the web sends the code it saw: the id may mean another product now
            errors.append(f"Mặt hàng {raw.get('code')} đã thay đổi trên máy chính (có thể đã Hoàn tác). Hãy tải lại trang web.")
            continue
        if qty <= 0:
            errors.append(f"Số lượng của {row['code']} phải lớn hơn 0.")
            continue
        lines.append(receipts.ReceiptLineInput(qty, product_id, note=clean(str(raw.get("note") or ""))))
    if not lines:
        errors.append("Phiếu không có dòng hàng nào dùng được.")
    source = receipts.RETURN if p.get("source") == receipts.RETURN else receipts.SUPPLIER
    customer_id, customer_name = None, ""
    if source == receipts.RETURN:  # goods a customer sent back
        if p.get("customer_id") is not None:
            row = conn.execute("SELECT id FROM customers WHERE id = ?", (p.get("customer_id"),)).fetchone()
            if row is None:
                errors.append("Khách hàng không còn trong danh sách (có thể đã gộp).")
            else:
                customer_id = row["id"]
        customer_name = clean(str(p.get("customer_name") or ""))
        if customer_id is None and not customer_name:
            errors.append("Hãy chọn khách hàng trả lại hàng.")
    data = receipts.ReceiptInput(
        doc_date, source,
        supplier_name=(clean(str(p.get("supplier_name") or "")) or "Web") if source == receipts.SUPPLIER else "",
        customer_name=customer_name, customer_id=customer_id,
        ref_code=clean(str(p.get("ref_code") or "")) if source == receipts.RETURN else "",
        note=clean(str(p.get("note") or "")), lines=lines, location_id=location)
    if not errors and receipts.problems(data):
        errors.append("Phiếu hàng về chưa đủ thông tin (kiểm tra mặt hàng bị lặp hoặc thiếu nguồn hàng).")
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
    """Record the receipt through the normal business path, then remember request -> document."""
    data, errors = check(conn, item)
    if errors:
        raise ValueError(" ".join(errors))
    doc_id = receipts.save(conn, data, ws=ws)
    receipts.export_file(conn, ws, doc_id)
    with db.transaction(conn):
        m = applied_map(conn)
        m[item["id"]] = doc_id
        _store_applied(conn, m)
        db.log(conn, "web_inbox_applied", f"{str(item['id'])[:8]} -> #{doc_id}")
    return doc_id


# ---- delivery note file -------------------------------------------------------------------------------------

_STORAGE_PATH = re.compile(r"^[0-9a-fA-F-]{36}/[^/\\]{1,200}$")
_NAME_BAD = re.compile(r'[\x00-\x1f<>:"/\\|?*]')


def safe_file_name(name: str) -> str:
    """The uploader's file name, made safe to put in the delivery folder (no path, no odd characters)."""
    base = _NAME_BAD.sub("_", Path(str(name or "")).name).strip(" .")
    stem = base[:-5] if base.lower().endswith(".xlsx") else base
    return (stem or "phieu-web") + ".xlsx"


def check_delivery(item: dict) -> list[str]:
    p = payload_of(item)
    errors = []
    if not _STORAGE_PATH.match(str(p.get("file_path") or "")):
        errors.append("Đường dẫn file trên Cloud không hợp lệ.")
    if not str(p.get("file_name") or "").lower().endswith(".xlsx"):
        errors.append("Chỉ nhận file Excel .xlsx.")
    size = p.get("size")
    if not isinstance(size, int) or not 0 < size <= MAX_FILE:
        errors.append("Kích thước file không hợp lệ (tối đa 2 MB).")
    sha = str(p.get("sha256") or "")
    if sha and not re.fullmatch(r"[0-9a-f]{64}", sha.lower()):
        errors.append("Mã kiểm tra của file không hợp lệ.")
    return errors


def known_hash(conn, digest: str) -> str | None:
    """Status of a delivery file this database has already taken in (by content), else None."""
    row = conn.execute("SELECT status FROM scanned_files WHERE hash = ?", (digest,)).fetchone()
    return row["status"] if row else None


def _free_path(folder: Path, name: str) -> Path:
    target = folder / name
    n = 2
    while target.exists():
        target = folder / f"{Path(name).stem} ({n}).xlsx"
        n += 1
    return target


def _check_xlsx(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if "xl/workbook.xml" not in z.namelist():
                raise ValueError("File không phải Excel .xlsx hợp lệ.")
            if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
                raise ValueError("File Excel giải nén ra quá lớn, không nhận.")
    except zipfile.BadZipFile as exc:
        raise ValueError("File không phải Excel .xlsx hợp lệ.") from exc


def _confirm_file(client, access_token, item: dict, result: dict) -> None:
    """Mark the request applied and drop the uploaded copy. Best effort: the file is already safe in the delivery
    folder, and a request that stays pending is recognised by its hash the next time (no second copy)."""
    try:
        client.patch(f"/rest/v1/web_inbox?id=eq.{item['id']}",
                     {"status": "applied", "result": result,
                      "applied_at": datetime.now().astimezone().isoformat(timespec="seconds")}, access_token)
        client.storage_delete([payload_of(item)["file_path"]], access_token, FILES_BUCKET)
    except CloudError as exc:
        activity.log("error", f"cloud inbox confirm file: {exc}")


def apply_delivery(conn, ws: Workspace, client: CloudClient, access_token: str, item: dict) -> dict:
    """Put the uploaded note into phieu-giao-hang/ (the caller then scans). Returns {"placed": Path | None,
    "status": str | None}: placed is None, with the status, when the app already has a note with this content."""
    errors = check_delivery(item)
    if errors:
        raise ValueError(" ".join(errors))
    p = payload_of(item)
    want = str(p.get("sha256") or "").lower()
    if want and known_hash(conn, want) is not None:
        status = known_hash(conn, want)
        _confirm_file(client, access_token, item, {"already": True, "hash": want, "status": status})
        return {"placed": None, "status": status}
    data = client.storage_download(p["file_path"], access_token, FILES_BUCKET)
    if len(data) > MAX_FILE:
        raise ValueError("File quá lớn (tối đa 2 MB).")
    digest = hashlib.sha256(data).hexdigest()
    if want and digest != want:
        raise ValueError("File tải về bị lỗi (mã kiểm tra không khớp). Hãy nhờ nhân viên gửi lại.")
    _check_xlsx(data)
    status = known_hash(conn, digest)
    if status is not None:
        _confirm_file(client, access_token, item, {"already": True, "hash": digest, "status": status})
        return {"placed": None, "status": status}
    ws.deliveries.mkdir(parents=True, exist_ok=True)
    target = _free_path(ws.deliveries, safe_file_name(p["file_name"]))
    target.write_bytes(data)
    _confirm_file(client, access_token, item, {"file": target.name, "hash": digest})
    return {"placed": target, "status": None}


# ---- stock count --------------------------------------------------------------------------------------------

@dataclass
class CountLine:
    product_id: int
    code: str
    name: str
    counted: float
    system: float  # what the app knew at the moment the request was sent

    @property
    def diff(self) -> float:
        return self.counted - self.system


def check_count(conn, item: dict) -> tuple[date, int, list[tuple[int, float]], list[str]]:
    """-> (count date, place, [(product_id, counted)], reasons it cannot be applied)."""
    p = payload_of(item)
    errors: list[str] = []
    sent = sent_at(item)
    try:
        day = date.fromisoformat(str(p.get("count_date")))
    except ValueError:
        errors.append("Ngày kiểm kê không hợp lệ.")
        day = sent.date()
    if day > sent.date():
        errors.append("Ngày kiểm kê ở tương lai.")
    location = p.get("location_id")
    if location not in LOCATIONS:
        errors.append("Nơi kiểm kê không hợp lệ.")
        location = MAIN
    lines, seen = [], set()
    for raw in p.get("lines") or []:
        try:
            product_id, qty = int(raw.get("product_id")), float(raw.get("qty"))
        except (TypeError, ValueError):
            errors.append("Có dòng kiểm kê không đọc được.")
            continue
        row = conn.execute("SELECT code FROM products WHERE id = ?", (product_id,)).fetchone()
        if row is None:
            errors.append(f"Mặt hàng #{product_id} không còn trong danh mục (đã xoá hoặc gộp).")
        elif raw.get("code") and raw.get("code") != row["code"]:
            errors.append(f"Mặt hàng {raw.get('code')} đã thay đổi trên máy chính (có thể đã Hoàn tác). Hãy tải lại trang web.")
        elif qty < 0 or qty != qty:
            errors.append(f"Số đếm của {row['code']} không được âm.")
        elif product_id in seen:
            errors.append(f"Mặt hàng {row['code']} xuất hiện hai lần.")
        else:
            seen.add(product_id)
            lines.append((product_id, qty))
    if not lines:
        errors.append("Phiếu kiểm kê không có dòng nào dùng được.")
    return day, location, lines, errors


def count_preview(conn, item: dict) -> list[CountLine]:
    """Counted vs the system's stock at the moment of sending, product by product."""
    day, location, lines, _ = check_count(conn, item)
    levels = stock.stock_levels(conn, as_of=day, by_location=True, created_until=stock.stamp_of(sent_at(item)))
    out = []
    for product_id, qty in lines:
        p = conn.execute("SELECT code, name_vi, spec, variant FROM products WHERE id = ?", (product_id,)).fetchone()
        name = " · ".join(x for x in (p["name_vi"], p["spec"], p["variant"]) if x)
        out.append(CountLine(product_id, p["code"], name, qty, levels.get((product_id, location), 0.0)))
    return out


def apply_count(conn, item: dict) -> int:
    day, location, lines, errors = check_count(conn, item)
    if errors:
        raise ValueError(" ".join(errors))
    sender = clean(str(item.get("sender") or "")) or "nhân viên"
    note = clean(f"Kiểm kê từ web ({sender}). {payload_of(item).get('note') or ''}")
    with db.transaction(conn):
        doc_id = stock.stock_count(conn, day, {(pid, location): qty for pid, qty in lines}, note,
                                   at=sent_at(item))
        m = applied_map(conn)
        m[item["id"]] = doc_id
        _store_applied(conn, m)
        db.log(conn, "web_inbox_applied", f"{str(item['id'])[:8]} -> #{doc_id}")
    return doc_id


# ---- rejecting, confirming ----------------------------------------------------------------------------------

def reject(client: CloudClient, access_token: str, item: dict, reason: str = "") -> None:
    client.patch(f"/rest/v1/web_inbox?id=eq.{item['id']}",
                 {"status": "rejected", "result": {"reason": reason},
                  "applied_at": datetime.now().astimezone().isoformat(timespec="seconds")}, access_token)
    path = payload_of(item).get("file_path")
    if item.get("kind") == DELIVERY_FILE and path and _STORAGE_PATH.match(str(path)):
        try:
            client.storage_delete([path], access_token, FILES_BUCKET)
        except CloudError as exc:
            activity.log("error", f"cloud inbox drop rejected file: {exc}")


def finish_applied(conn, client: CloudClient, access_token: str) -> int:
    """After a successful mirror push: confirm each locally applied request whose document still exists;
    one undone in the meantime is forgotten here and comes back as pending on the next pull.
    Progress is saved per request, so a network failure halfway is retried next cycle (PATCH is idempotent)."""
    confirmed = 0
    for item_id, doc_id in list(applied_map(conn).items()):
        row = conn.execute("SELECT kind, code, created_at FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if row is not None:
            result = ({"doc_id": doc_id, "code": row["code"]} if row["kind"] == "receipt"
                      else {"doc_id": doc_id, "stamp": row["created_at"]})  # a count has no code: its time identifies it
            client.patch(f"/rest/v1/web_inbox?id=eq.{item_id}",
                         {"status": "applied", "result": result,
                          "applied_at": datetime.now().astimezone().isoformat(timespec="seconds")}, access_token)
            confirmed += 1
        with db.transaction(conn):
            m = applied_map(conn)
            m.pop(item_id, None)
            _store_applied(conn, m)
    return confirmed


def reconcile_applied(conn, client: CloudClient, access_token: str, limit: int = 50) -> int:
    """Requests shown as recorded whose document is no longer in this database (an Undo, a restore or a package
    replaced the data) go back to pending: they reappear in Cần xử lý instead of staying ticked with nothing
    behind them. A receipt that was only cancelled or edited still exists, so its request stays recorded.
    Delivery files are not reconciled: the file in phieu-giao-hang/ is read again by the scan on its own."""
    rows = client.get(f"/rest/v1/web_inbox?status=eq.applied&order=applied_at.desc&limit={limit}", access_token) or []
    back = 0
    for row in rows:
        result = row.get("result") or {}
        if row.get("kind") == STOCK_COUNT and result.get("stamp"):
            exists = conn.execute("SELECT 1 FROM documents WHERE id = ? AND kind = 'stock_count' AND created_at = ?",
                                  (result.get("doc_id"), result["stamp"])).fetchone()
        elif result.get("code"):
            exists = conn.execute("SELECT 1 FROM documents WHERE kind = 'receipt' AND code = ?",
                                  (result["code"],)).fetchone()
        else:
            continue
        if not exists:
            client.patch(f"/rest/v1/web_inbox?id=eq.{row['id']}",
                         {"status": "pending", "result": None, "applied_at": None}, access_token)
            back += 1
    return back
