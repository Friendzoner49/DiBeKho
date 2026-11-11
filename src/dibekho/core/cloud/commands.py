"""Owner commands: things the owner does on the web, carried out by the main machine without a second approval.

Why this is safe on a database that Undo, restore and package import can swap at any time:
- every command names its target with a FINGERPRINT (id + code + created_at): after a swap an id may point at a
  different row, and the command is then refused with a reason instead of hitting the wrong one;
- a command is applied at most once, tracked in core.cloud.state (outside the database, so Undo cannot make it
  run again), and the owner sees "done" or the reason on the web;
- each command goes through the same core function the app's own window calls, with the same side effects
  (cancelling a delivery also settles its scanned-file row, a new product runs the duplicate check...);
- only an account whose profile role is 'desktop' is obeyed, and an unknown role is never trusted.
The web sends the owner's other requests (goods in, delivery file, stock count) the same way and they are applied
here too, through core.cloud.inbox. Design: docs/cloud/04-thiet-ke-chot.md.
"""

from dataclasses import dataclass
from datetime import date, datetime

from dibekho import db
from dibekho.core import activity, catalog, receipts, stock
from dibekho.core.cloud import inbox, state
from dibekho.core.cloud.client import CloudClient, CloudError
from dibekho.core.stock import LOCATIONS
from dibekho.core.text import clean
from dibekho.core.workspace import Workspace

OWNER_ROLE = "desktop"
STALE_DOC = ("Phiếu này đã thay đổi hoặc không còn trên máy chính (có thể đã Hoàn tác). "
             "Hãy tải lại trang web, kiểm tra rồi làm lại.")
STALE_PRODUCT = "Mặt hàng này đã thay đổi hoặc không còn trên máy chính. Hãy tải lại trang web rồi làm lại."
STALE_CUSTOMER = "Khách hàng này đã thay đổi hoặc không còn trên máy chính. Hãy tải lại trang web rồi làm lại."


class CommandError(Exception):
    """A command that cannot be carried out; the text (plain Vietnamese) is shown to the owner on the web."""


# ---- fingerprints -------------------------------------------------------------------------------------------

def verify_document(conn, fp, kinds: tuple | None = None, active: bool = False):
    if not isinstance(fp, dict):
        raise CommandError(STALE_DOC)
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (fp.get("id"),)).fetchone()
    if (row is None or row["created_at"] != fp.get("created_at") or row["kind"] != fp.get("kind")
            or (row["code"] or "") != (fp.get("code") or "")):
        raise CommandError(STALE_DOC)
    if kinds and row["kind"] not in kinds:
        raise CommandError("Thao tác này không dùng được cho loại phiếu này.")
    if active and row["status"] != "active":
        raise CommandError("Phiếu này đã huỷ hoặc đã được thay bằng bản sửa.")
    return row


def verify_product(conn, fp):
    row = None
    if isinstance(fp, dict):
        row = conn.execute("SELECT * FROM products WHERE id = ?", (fp.get("id"),)).fetchone()
    if row is None or row["code"] != fp.get("code") or row["created_at"] != fp.get("created_at"):
        raise CommandError(STALE_PRODUCT)
    return row


def verify_customer(conn, fp):
    row = None
    if isinstance(fp, dict):
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (fp.get("id"),)).fetchone()
    if row is None or row["created_at"] != fp.get("created_at"):
        raise CommandError(STALE_CUSTOMER)
    return row


# ---- small parsers ------------------------------------------------------------------------------------------

def _date(value) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise CommandError("Ngày không hợp lệ.") from None


def _place(value) -> int:
    if value not in LOCATIONS:
        raise CommandError("Nơi chứa hàng không hợp lệ.")
    return value


def _lines(conn, raw) -> list[stock.Line]:
    """[{product_id, code, qty, note}] -> Lines. id AND code must match: after a swap an id can mean another product."""
    out, seen = [], set()
    for entry in raw or []:
        try:
            product_id, qty = int(entry.get("product_id")), float(entry.get("qty"))
        except (TypeError, ValueError, AttributeError):
            raise CommandError("Có dòng hàng không đọc được.") from None
        row = conn.execute("SELECT code FROM products WHERE id = ?", (product_id,)).fetchone()
        if row is None or row["code"] != entry.get("code"):
            raise CommandError(STALE_PRODUCT)
        if not qty > 0:
            raise CommandError(f"Số lượng của {row['code']} phải lớn hơn 0.")
        if product_id in seen:
            raise CommandError(f"Mặt hàng {row['code']} xuất hiện hai lần.")
        seen.add(product_id)
        out.append(stock.Line(product_id, qty, note=clean(str(entry.get("note") or ""))))
    if not out:
        raise CommandError("Chưa có dòng hàng nào.")
    return out


def _doc_code(conn, doc_id: int) -> str:
    return conn.execute("SELECT code FROM documents WHERE id = ?", (doc_id,)).fetchone()["code"]


def _product_fields(p: dict) -> dict:
    fields = {k: clean(str(p.get(k) or "")) for k in ("name_vi", "name_zh", "spec", "variant", "unit", "category")}
    if not fields["name_vi"]:
        raise CommandError("Mặt hàng phải có tên tiếng Việt.")
    return fields


# ---- the commands -------------------------------------------------------------------------------------------

def _transfer(conn, ws, p):
    lines = _lines(conn, p.get("lines"))
    try:
        with db.transaction(conn):
            doc_id = stock.transfer(conn, _date(p.get("date")), _place(p.get("from")), _place(p.get("to")), lines,
                                    clean(str(p.get("note") or "")))
    except ValueError as exc:
        raise CommandError(str(exc)) from None
    return f"Chuyển hàng {_doc_code(conn, doc_id)}"


def _trial(conn, ws, p):
    lines = _lines(conn, p.get("lines"))
    try:
        with db.transaction(conn):
            doc_id = stock.record_trial_use(conn, _date(p.get("date")), _place(p.get("location")), lines,
                                            clean(str(p.get("note") or "")))
    except ValueError as exc:
        raise CommandError(str(exc)) from None
    return f"Xuất dùng thử {_doc_code(conn, doc_id)}"


def _product_add(conn, ws, p):
    fields = _product_fields(p)
    if not p.get("allow_duplicate"):
        dups = catalog.find_possible_duplicates(conn, fields["name_vi"], fields["name_zh"], fields["spec"],
                                                fields["variant"])
        if dups:
            raise CommandError(f"Có thể trùng với {dups[0]['code']} ({catalog.long_label(dups[0])}). Nếu đúng là "
                               f"mặt hàng mới, hãy gửi lại và chọn «Vẫn tạo dù có thể trùng».")
    with db.transaction(conn):
        product_id = catalog.create_product(conn, **fields)
    return f"Thêm mặt hàng {conn.execute('SELECT code FROM products WHERE id = ?', (product_id,)).fetchone()[0]}"


def _product_edit(conn, ws, p):
    row = verify_product(conn, p.get("target"))
    given = p.get("fields") if isinstance(p.get("fields"), dict) else {}
    fields = {}
    for key in ("name_vi", "name_zh", "spec", "variant", "unit", "category", "stock_note"):
        if key in given:
            fields[key] = clean(str(given[key] or ""))
    if "active" in given:
        fields["active"] = int(bool(given["active"]))
    if "name_vi" in fields and not fields["name_vi"]:
        raise CommandError("Mặt hàng phải có tên tiếng Việt.")
    if not fields:
        raise CommandError("Không có gì để sửa.")
    with db.transaction(conn):
        catalog.update_product(conn, row["id"], **fields)
        if "stock_note" in fields and fields["stock_note"] != row["stock_note"]:
            db.log(conn, "stock_note", row["code"])
    return f"Sửa mặt hàng {row['code']}"


def _product_merge(conn, ws, p):
    a, b = verify_product(conn, p.get("a")), verify_product(conn, p.get("b"))
    if a["id"] == b["id"]:
        raise CommandError("Chọn hai mặt hàng khác nhau để gộp.")
    keep, drop = (a, b) if catalog._code_num(a["code"]) <= catalog._code_num(b["code"]) else (b, a)
    try:
        with db.transaction(conn):
            catalog.merge_products(conn, a["id"], b["id"])
            db.log(conn, "product_merged", f"{drop['code']} -> {keep['code']}")
    except ValueError as exc:
        raise CommandError(str(exc)) from None
    return f"Gộp {drop['code']} vào {keep['code']}"


def _customer_merge(conn, ws, p):
    targets = p.get("targets") if isinstance(p.get("targets"), list) else []
    rows = [verify_customer(conn, fp) for fp in targets]
    if len({r["id"] for r in rows}) < 2:
        raise CommandError("Chọn từ 2 khách hàng trở lên để gộp.")
    try:
        with db.transaction(conn):
            catalog.merge_customers(conn, [r["id"] for r in rows], str(p.get("name") or ""))
    except ValueError as exc:
        raise CommandError(str(exc)) from None
    return f"Gộp {len(rows)} khách hàng thành «{clean(str(p.get('name') or ''))}»"


def _cancel_doc(conn, ws, p):
    row = verify_document(conn, p.get("target"), active=True)
    try:
        with db.transaction(conn):
            stock.close_document(conn, row["id"], "cancelled")
            if row["kind"] == "delivery":
                # the note's file stays in the folder; do not warn about it later (what the order window does)
                conn.execute("UPDATE scanned_files SET status = 'imported' WHERE document_id = ? "
                             "AND status = 'missing'", (row["id"],))
    except ValueError as exc:
        raise CommandError(str(exc)) from None
    return f"Huỷ phiếu {row['code']}"


def _set_location(conn, ws, p):
    row = verify_document(conn, p.get("target"), kinds=("delivery", "receipt"))
    place = _place(p.get("location"))
    try:
        with db.transaction(conn):
            stock.set_location(conn, row["id"], place)
    except ValueError as exc:
        raise CommandError(str(exc)) from None
    return f"Đặt nơi {'lấy' if row['kind'] == 'delivery' else 'nhập'} hàng của phiếu {row['code']}"


def _receipt_edit(conn, ws, p):
    row = verify_document(conn, p.get("target"), kinds=("receipt",), active=True)
    data, errors = inbox.receipt_input(conn, p.get("receipt") if isinstance(p.get("receipt"), dict) else {})
    if errors:
        raise CommandError(" ".join(errors))
    try:
        doc_id = receipts.save(conn, data, replaces=row["id"], ws=ws)  # opens its own transaction
    except ValueError as exc:
        raise CommandError(str(exc)) from None
    try:
        receipts.export_file(conn, ws, doc_id)
    except Exception as exc:  # e.g. the old file is open in Excel: the receipt is recorded anyway
        activity.log("error", f"receipt file after web edit: {exc}")
    return f"Sửa phiếu hàng về {row['code']}"


HANDLERS = {
    "cmd_transfer": _transfer, "cmd_trial": _trial, "cmd_product_add": _product_add,
    "cmd_product_edit": _product_edit, "cmd_product_merge": _product_merge, "cmd_customer_merge": _customer_merge,
    "cmd_cancel_doc": _cancel_doc, "cmd_set_location": _set_location, "cmd_receipt_edit": _receipt_edit,
}
assert set(HANDLERS) == set(inbox.CMD_KINDS)


def run(conn, ws: Workspace, item: dict) -> str:
    """Carry out one command and return a short description of what was done. Raises CommandError."""
    handler = HANDLERS.get(item.get("kind"))
    if handler is None:
        raise CommandError("Lệnh không nhận ra (có thể app cần cập nhật).")
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    return handler(conn, ws, payload)


# ---- who is obeyed, and applying a batch --------------------------------------------------------------------

def partition(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """(owner items to carry out now, requests for the owner to approve by hand).
    An owner item is one from a 'desktop' account that has not been auto-applied before; one that was and came back
    (an Undo, a restore) is shown for approval instead -- it must not undo the owner's Undo by itself. Commands
    are never shown for approval: a command from anyone else than the owner is simply not obeyed."""
    done = state.load()
    auto, manual = [], []
    for item in items:
        owner = item.get("sender_role") == OWNER_ROLE
        if owner and item["id"] not in done:
            auto.append(item)
        elif item.get("kind") in inbox.KINDS:
            manual.append(item)
    return auto, manual


def pull(conn, client: CloudClient, token: str) -> tuple[list[dict], list[dict]]:
    """Fetch the pending requests and commands, resend any outcome the cloud missed, and split them:
    (the owner's items to carry out, the requests for the owner to approve by hand)."""
    items = inbox.fetch_pending(conn, client, token)
    retry_unconfirmed(client, token, {i["id"] for i in items})
    return partition(items)


@dataclass
class Outcome:
    item: dict
    ok: bool
    summary: str  # what was done, or why it could not be


def _tell_cloud(client: CloudClient, token: str, item: dict, ok: bool, summary: str) -> bool:
    """Answer the owner on the web. False when the network failed: the answer is retried later, the command never is."""
    body = ({"status": "applied", "result": {"summary": summary}} if ok
            else {"status": "rejected", "result": {"reason": summary}})
    body["applied_at"] = _now()
    try:
        client.patch(f"/rest/v1/web_inbox?id=eq.{item['id']}", body, token)
        return True
    except CloudError as exc:
        activity.log("error", f"cloud inbox answer: {exc}")
        return False


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def apply_owner_items(conn, ws: Workspace, client: CloudClient, token: str, items: list[dict]) -> list[Outcome]:
    """Carry out the owner's items, oldest first, each in its own transaction so one failure stops nothing else.
    The caller took an undo point first and rescans afterwards (a delivery file is only placed here)."""
    outcomes = []
    for item in items:
        kind = item.get("kind")
        confirmed = False  # whether the cloud already knows the outcome
        try:
            if kind in HANDLERS:
                summary = run(conn, ws, item)
            elif kind == inbox.RECEIPT:
                doc_id = inbox.apply_item(conn, ws, item)
                summary, confirmed = f"Hàng về {_doc_code(conn, doc_id)}", True  # confirmed after the next push
            elif kind == inbox.STOCK_COUNT:
                inbox.apply_count(conn, item)
                summary, confirmed = "Kiểm kê đã vào sổ", True
            elif kind == inbox.DELIVERY_FILE:
                result = inbox.apply_delivery(conn, ws, client, token, item)
                summary = ("Phiếu giao hàng: app đã có phiếu này" if result["placed"] is None
                           else f"Phiếu giao hàng: đã nhận file {result['placed'].name}")
                confirmed = True  # apply_delivery answered the cloud itself
            else:
                continue
            ok = True
        except CloudError as exc:
            activity.log("error", f"owner item {kind}: {exc}")  # transient (a download): nothing applied, retried
            continue
        except (CommandError, ValueError) as exc:
            ok, summary = False, str(exc)
        if not confirmed or not ok:
            confirmed = _tell_cloud(client, token, item, ok, summary)
        state.mark(item["id"], ok, summary, confirmed)
        activity.log("action", f"web command {kind} {'ok' if ok else 'refused'}")
        outcomes.append(Outcome(item, ok, summary))
    return outcomes


def retry_unconfirmed(client: CloudClient, token: str, pending_ids: set[str]) -> int:
    """Tell the cloud about outcomes it missed (the network was down at that moment). Only the answer is resent."""
    sent = 0
    for item_id, entry in state.unconfirmed().items():
        if item_id not in pending_ids:
            state.mark(item_id, entry["ok"], entry["summary"], True)  # already answered some other way
            continue
        if _tell_cloud(client, token, {"id": item_id}, entry["ok"], entry["summary"]):
            state.mark(item_id, entry["ok"], entry["summary"], True)
            sent += 1
    return sent

