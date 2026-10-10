"""The input/ folder: goods receipt files, catalog sheets and data packages from another machine.

Files are moved to input/da-xu-ly/ only after they were used (or the user discarded a usable file).
A file the app cannot use is never moved: the user can only hide it, and it stays where it is.
"""

from dataclasses import dataclass
from pathlib import Path

from dibekho import db
from dibekho.core.deliveries import file_hash
from dibekho.core.stock import Line, insert_document
from dibekho.core.transfer import EXTENSION, Manifest, TransferError, move_to_processed, read_manifest
from dibekho.core.workspace import Workspace
from dibekho.excel.catalog_sheet import CatalogItem, NotCatalogSheet, read_catalog
from dibekho.excel.delivery_note import NotDeliveryNote, DeliveryNoteError, read_delivery_note
from dibekho.excel.receipt import NotReceipt, ReceiptError, ReceiptFile, read_receipt


@dataclass
class InboxItem:
    path: Path
    kind: str                 # receipt | catalog | package | error
    error: str = ""
    receipt: ReceiptFile | None = None
    resolved: list | None = None  # receipt lines joined with products: (line, product_row|None)
    manifest: Manifest | None = None
    catalog: list[CatalogItem] | None = None


def items(conn, ws: Workspace) -> list[InboxItem]:
    if not ws.input.exists():
        return []
    result = []
    hidden = {r[0] for r in conn.execute("SELECT hash FROM hidden_inputs")}
    for path in sorted(p for p in ws.input.iterdir() if p.is_file()):
        if path.name.startswith(("~$", ".")):
            continue
        if hidden:
            try:
                if file_hash(path) in hidden:
                    continue
            except OSError:
                continue
        suffix = path.suffix.lower()
        if suffix == EXTENSION:
            try:
                result.append(InboxItem(path, "package", manifest=read_manifest(path)))
            except TransferError as exc:
                result.append(InboxItem(path, "error", error=str(exc)))
        elif suffix == ".xlsx":
            result.append(read_item(conn, path))
        else:
            result.append(InboxItem(path, "error", error="Chỉ nhận file hàng về (.xlsx) hoặc gói dữ liệu (.dibekho)."))
    return result


def read_item(conn, path: Path) -> InboxItem:
    """Recognise one Excel file: goods receipt, catalog sheet, or something unusable (with the reason)."""
    try:
        receipt = read_receipt(path)
    except NotReceipt:
        try:
            catalog = read_catalog(path)
            if catalog:
                return InboxItem(path, "catalog", catalog=catalog)
        except NotCatalogSheet:
            pass
        except Exception:  # damaged file: fall through to the generic message
            pass
        try:
            read_delivery_note(path)
            msg = "Đây là phiếu giao hàng — hãy để nó trong thư mục phieu-giao-hang/, không phải input/."
        except (NotDeliveryNote, DeliveryNoteError):
            msg = "Không phải file hàng về hay file danh mục. Hãy dùng 'Tạo file mẫu hàng về' trong app."
        return InboxItem(path, "error", error=msg)
    except ReceiptError as exc:
        return InboxItem(path, "error", error=str(exc))
    resolved = []
    for line in receipt.lines:
        product = conn.execute("SELECT * FROM products WHERE code = ?", (line.code,)).fetchone()
        resolved.append((line, product))
    unknown = [ln.code for ln, p in resolved if p is None]
    item = InboxItem(path, "receipt", receipt=receipt, resolved=resolved)
    if unknown:
        item.kind, item.error = "error", f"Mã hàng không có trong danh mục: {', '.join(unknown)}"
    elif _already_imported(conn, file_hash(path)):
        item.kind, item.error = "error", "File hàng về này đã được nhập trước đó."
    return item


def _already_imported(conn, h: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM documents WHERE kind = 'receipt' AND status = 'active' AND source_hash = ?", (h,)
    ).fetchone() is not None


def apply_receipt(conn, ws: Workspace, item: InboxItem) -> int:
    h = file_hash(item.path)
    with db.transaction(conn):
        doc_id = insert_document(
            conn, "receipt", item.receipt.doc_date,
            [Line(p["id"], ln.qty) for ln, p in item.resolved],
            note=item.receipt.note, source_file=item.path.name, source_hash=h,
        )
        db.log(conn, "receipt_imported", item.path.name)
    done(ws, item.path)
    return doc_id


def done(ws: Workspace, path: Path) -> None:
    """A used file leaves input/ (to input/da-xu-ly/). Files chosen from elsewhere are not touched."""
    if path.parent.resolve() == ws.input.resolve() and path.exists():
        move_to_processed(ws, path)


def discard(ws: Workspace, item: InboxItem) -> None:
    """The user does not want a usable file (receipt, catalog, package): move it out of input/."""
    done(ws, item.path)


def hide(conn, item: InboxItem) -> None:
    """An unusable file: hide it from 'Cần xử lý' but leave it where it is."""
    conn.execute("INSERT OR REPLACE INTO hidden_inputs(hash, name) VALUES(?, ?)", (file_hash(item.path), item.path.name))
