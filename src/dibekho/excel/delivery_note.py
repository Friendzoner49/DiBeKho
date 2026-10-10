"""Reader for the customer's bilingual delivery notes (销售单 PHIẾU GIAO HÀNG).

Pure function: workbook in, structured data out. No database access.
Cells are located by their Vietnamese labels, never by fixed coordinates,
because the layout shifts between files (one sample has an extra row).
Prices are ignored on purpose. Line notes are kept for display only.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import openpyxl

from dibekho.core.text import clean, match_key, normalize_code, split_bilingual_name, unaccent

# label key -> unaccented text to look for inside a cell
HEADER_LABELS = {
    "customer": "ten khach hang",
    "phone": "dien thoai",
    "code": "ma don hang",
    "contact": "nguoi lien he",
    "date": "ngay giao hang",
    "address": "dia chi",
}
COLUMN_LABELS = {
    "name": "ten hang",
    "spec": "quy cach",
    "qty": "so luong",
    "note": "ghi chu",
}
END_MARKERS = ("tong cong", "nguoi giao hang")
_COLON = re.compile(r"[:：]")
_DATE = re.compile(r"(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{4})")


class NotDeliveryNote(Exception):
    """The workbook does not look like a delivery note at all."""


class DeliveryNoteError(Exception):
    """The workbook is a delivery note but required data is missing or invalid."""


@dataclass
class DeliveryLine:
    row: int
    raw_name: str
    name_vi: str
    name_zh: str
    spec: str
    qty: float
    note: str

    @property
    def key(self) -> str:
        return match_key(self.raw_name, self.spec)


@dataclass
class DeliveryNote:
    code: str
    doc_date: date
    customer_name: str
    phone: str
    contact: str
    address: str
    lines: list[DeliveryLine]
    skipped_rows: list[str] = field(default_factory=list)  # e.g. "Phí vận chuyển" (no quantity)
    warnings: list[str] = field(default_factory=list)

    @property
    def code_norm(self) -> str:
        return normalize_code(self.code)


def read_delivery_note(path: Path | str) -> DeliveryNote:
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    except Exception as exc:  # corrupted file, not a real xlsx, password protected...
        raise NotDeliveryNote(f"Không mở được file Excel: {exc}") from exc
    try:
        for ws in wb.worksheets:
            grid = _grid(ws)
            if _find_header_row(grid) is not None:
                return _parse(grid)
    finally:
        wb.close()
    raise NotDeliveryNote("Không thấy bảng hàng có cột 'Tên hàng' — không phải phiếu giao hàng.")


def _grid(ws) -> list[list]:
    return [list(row) for row in ws.iter_rows(values_only=True)]


def _text(value) -> str:
    return "" if value is None else str(value)


def _find_header_row(grid) -> int | None:
    for r, row in enumerate(grid):
        if any(COLUMN_LABELS["name"] in unaccent(_text(v)) for v in row):
            return r
    return None


def _parse(grid) -> DeliveryNote:
    header_row = _find_header_row(grid)
    head = _read_header_fields(grid[:header_row])
    columns = _map_columns(grid[header_row])

    warnings: list[str] = []
    if not head.get("code"):
        raise DeliveryNoteError("Không tìm thấy 'Mã đơn hàng'.")
    doc_date = _parse_date(head.get("date"))
    if doc_date is None:
        raise DeliveryNoteError(f"Không đọc được 'Ngày giao hàng' ({clean(_text(head.get('date'))) or 'trống'}).")
    if not head.get("customer"):
        warnings.append("Không tìm thấy tên khách hàng.")

    lines: list[DeliveryLine] = []
    skipped: list[str] = []
    for r in range(header_row + 1, len(grid)):
        row = grid[r]
        if any(m in unaccent(_text(v)) for v in row for m in END_MARKERS):
            break
        raw_name = _text(_cell(row, columns["name"]))
        qty_value = _cell(row, columns["qty"])
        if not clean(raw_name) and qty_value in (None, ""):
            continue
        excel_row = r + 1
        if qty_value in (None, ""):
            skipped.append(clean(raw_name))
            continue
        qty = _to_number(qty_value)
        if qty is None or qty <= 0:
            warnings.append(f"Dòng {excel_row}: số lượng không hợp lệ ({qty_value!r}), bỏ qua.")
            continue
        if not clean(raw_name):
            warnings.append(f"Dòng {excel_row}: có số lượng nhưng thiếu tên hàng, bỏ qua.")
            continue
        name_vi, name_zh = split_bilingual_name(raw_name)
        lines.append(
            DeliveryLine(
                row=excel_row,
                raw_name=clean(raw_name),
                name_vi=name_vi or clean(raw_name),
                name_zh=name_zh,
                spec=clean(_text(_cell(row, columns.get("spec")))),
                qty=qty,
                note=clean(_text(_cell(row, columns.get("note")))),
            )
        )

    if not lines:
        raise DeliveryNoteError("Phiếu không có dòng hàng nào có số lượng.")

    return DeliveryNote(
        code=clean(_text(head["code"])),
        doc_date=doc_date,
        customer_name=clean(_text(head.get("customer"))),
        phone=clean(_text(head.get("phone"))),
        contact=clean(_text(head.get("contact"))),
        address=clean(_text(head.get("address"))),
        lines=lines,
        skipped_rows=skipped,
        warnings=warnings,
    )


def _read_header_fields(rows) -> dict:
    found: dict = {}
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            text = _text(value)
            plain = unaccent(text)
            for key, label in HEADER_LABELS.items():
                if key in found or label not in plain:
                    continue
                found[key] = _value_after_label(text, label) or _neighbour_value(rows, r, c)
    return found


def _value_after_label(text: str, label: str):
    """'联系电话 ( Điện thoại liên hệ ): 0901 234 567' -> '0901 234 567'."""
    for m in _COLON.finditer(text):
        if label in unaccent(text[: m.start()]):
            return clean(text[m.end():]) or None
    return None


def _neighbour_value(rows, r: int, c: int):
    """Value placed in the next non-empty cell to the right, or the cell below."""
    row = rows[r]
    for value in row[c + 1:]:
        if value not in (None, ""):
            return value
    if r + 1 < len(rows) and c < len(rows[r + 1]):
        below = rows[r + 1][c]
        if below not in (None, ""):
            return below
    return None


def _map_columns(header) -> dict:
    columns: dict = {}
    for c, value in enumerate(header):
        plain = unaccent(_text(value))
        for key, label in COLUMN_LABELS.items():
            if key not in columns and label in plain:
                columns[key] = c
    if "qty" not in columns:
        raise DeliveryNoteError("Không tìm thấy cột 'Số lượng'.")
    return columns


def _cell(row, index):
    if index is None or index >= len(row):
        return None
    return row[index]


def _to_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = clean(_text(value)).replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    m = _DATE.search(_text(value))
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None
