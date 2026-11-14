"""Reader for the customer's bilingual delivery notes (销售单 PHIẾU GIAO HÀNG).

Pure function: workbook in, structured data out. No database access.
Cells are located by their Vietnamese labels, never by fixed coordinates,
because the layout shifts between files (one sample has an extra row).
Prices (unit price, amount, fees, the 'Tổng cộng' total) are read too, but never block a note: a price that
cannot be read is None with a warning. Line notes are kept for display only.
"""

import math
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
# the same labels in Chinese, used when the Vietnamese one is missing from the note
HEADER_LABELS_ZH = {
    "customer": "客户名称",
    "phone": "联系电话",
    "code": "订货单号",
    "contact": "联系人",
    "date": "送货日期",
    "address": "地址",
}
# what may follow a Chinese label before its value: '( Tên khách hàng )', ':', '：'
_LEADING_LABEL_REST = re.compile(r"^\s*(\([^)]*\)|（[^）]*）)?\s*[:：]?\s*")
COLUMN_LABELS = {
    "name": "ten hang",
    "spec": "quy cach",
    "qty": "so luong",
    "note": "ghi chu",
}
# price columns: the Vietnamese header often reads only 'VND' (单 价|VND, 金 额|VND), so the Chinese label
# (spaces removed) is the reliable one
# optional (hidden) columns of the stock issue notes DiBeKho writes itself (Phiếu xuất kho): the product code, read
# before the name, and where the goods of each line are taken from ('Kho tổng 总仓: 3; Văn phòng 办公室: 2').
# Customer notes without them read as before.
EXTRA_LABELS = {
    "code": ("ma hang", "货号"),
    "place": ("lay tu kho", "取货地点"),
}
# the place names of a 'Lấy từ kho' cell -> location id (1 Kho tổng, 2 Văn phòng)
PLACE_VALUES = {"kho tong": 1, "总仓": 1, "van phong": 2, "办公室": 2}
PRICE_LABELS = {
    "price": ("don gia", "单价"),
    "amount": ("thanh tien", "金额"),
}
END_MARKERS = ("tong cong", "nguoi giao hang")
# the title row of a note; the lines above it are the shop's letterhead (company name, address)
TITLE_MARKERS = ("phieu giao hang", "phieu xuat kho", "销售单", "出库单")
TOTAL_MARKER = "tong cong"
_COLON = re.compile(r"[:：]")
_DATE = re.compile(r"(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{4})")
_GROUPED = re.compile(r"-?\d{1,3}([.,]\d{3})+")  # 1.188.000 or 1,188,000


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
    unit_price: float | None = None
    amount: float | None = None
    product_code: str = ""  # 'Mã hàng' column (issue notes written by the app); '' when there is none
    # 'Lấy từ kho' column: ((location id, qty), ...) adding up to qty; () = not said (or edited so it no longer adds up)
    places: tuple = ()

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
    fees: list[tuple[str, float]] = field(default_factory=list)  # rows without quantity that have an amount
    total: float | None = None  # the amount printed on the 'Tổng cộng' row, only to check against
    warnings: list[str] = field(default_factory=list)
    title: str = ""  # '销售单 PHIẾU GIAO HÀNG', '出库单 PHIẾU XUẤT KHO'; '' when the note has none
    letterhead: list[str] = field(default_factory=list)  # the lines above the title (company name, address)

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
    title, letterhead = _title(grid[:header_row])
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
    fees: list[tuple[str, float]] = []
    bad_qty: list[str] = []
    total = None
    for r in range(header_row + 1, len(grid)):
        row = grid[r]
        # not the Ghi chú cell: a line noted 'người giao hàng thu tiền' is not the end of the table
        marks = [unaccent(_text(v)) for c, v in enumerate(row) if c != columns.get("note")]
        if any(m in text for text in marks for m in END_MARKERS):
            if any(TOTAL_MARKER in text for text in marks):
                total = _to_money(_cell(row, columns.get("amount")))
            break
        raw_name = _text(_cell(row, columns["name"]))
        qty_value = _cell(row, columns["qty"])
        if isinstance(qty_value, str) and not clean(qty_value):
            qty_value = None
        if not clean(raw_name) and qty_value in (None, ""):
            continue
        excel_row = r + 1
        if qty_value in (None, ""):
            skipped.append(clean(raw_name))
            fee = _to_money(_cell(row, columns.get("amount")))
            if fee:
                fees.append((clean(raw_name), fee))
            continue
        qty = _to_number(qty_value)
        if qty == 0:
            warnings.append(f"Dòng {excel_row}: số lượng 0, bỏ qua.")
            continue
        if (qty is None or qty < 0) and clean(raw_name):
            # never import the note without this line: its stock would be wrong without anyone knowing
            bad_qty.append(f"{excel_row} ('{clean(_text(qty_value))}')")
            continue
        if qty is None or qty < 0:
            warnings.append(f"Dòng {excel_row}: số lượng không hợp lệ ({qty_value!r}), bỏ qua.")
            continue
        if not clean(raw_name):
            warnings.append(f"Dòng {excel_row}: có số lượng nhưng thiếu tên hàng, bỏ qua.")
            continue
        price, amount = _line_money(row, columns, qty, excel_row, warnings)
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
                unit_price=price,
                amount=amount,
                product_code=clean(_text(_cell(row, columns.get("code")))).upper(),
                places=_places(_text(_cell(row, columns.get("place"))), qty),
            )
        )

    if bad_qty:
        raise DeliveryNoteError(f"Dòng {', '.join(bad_qty)}: không đọc được số lượng. Hãy sửa file phiếu "
                                f"(ô Số lượng chỉ ghi số, ví dụ 1500 hoặc 2,5) rồi bấm Quét lại.")
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
        fees=fees,
        total=total,
        warnings=warnings,
        title=title,
        letterhead=letterhead,
    )


def _title(rows) -> tuple[str, list[str]]:
    """The title of the note and the lines above it (the first text of each row)."""
    for r, row in enumerate(rows):
        for value in row:
            text = clean(_text(value))
            if any(m in unaccent(text) or m in text for m in TITLE_MARKERS):
                above = [_lines(next((v for v in prev if clean(_text(v))), "")) for prev in rows[:r]]
                return text, [x for x in above if x]
    return "", []


def _lines(value) -> str:
    """A cell's text with its own line breaks kept ('中文名\n Tên Việt' -> '中文名\nTên Việt')."""
    return "\n".join(x for x in (clean(part) for part in _text(value).split("\n")) if x)


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
    # Some notes keep only the Chinese label: '客户名称 Khách Mẫu' (no 'Tên khách hàng', no colon)
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            text = _text(value)
            for key, label in HEADER_LABELS_ZH.items():
                if key in found or not text.lstrip().startswith(label):
                    continue
                rest = _LEADING_LABEL_REST.sub("", text.lstrip()[len(label):])
                found[key] = clean(rest) or _neighbour_value(rows, r, c)
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
            return None if _is_label(value) else value  # an empty field: the next cell is another field's label
    if r + 1 < len(rows) and c < len(rows[r + 1]):
        below = rows[r + 1][c]
        if below not in (None, "") and not _is_label(below):
            return below
    return None


def _is_label(value) -> bool:
    text = _text(value)
    return any(label in unaccent(text) for label in HEADER_LABELS.values()) or         any(label in text for label in HEADER_LABELS_ZH.values())


def _map_columns(header) -> dict:
    columns: dict = {}
    for c, value in enumerate(header):
        plain = unaccent(_text(value))
        for key, label in COLUMN_LABELS.items():
            if key not in columns and label in plain:
                columns[key] = c
        compact = re.sub(r"\s+", "", _text(value))
        for key, labels in EXTRA_LABELS.items():
            if key not in columns and (labels[0] in plain or labels[1] in compact):
                columns[key] = c
        for key, labels in PRICE_LABELS.items():
            if key not in columns and (labels[0] in plain or labels[1] in compact):
                columns[key] = c
    if "qty" not in columns:
        raise DeliveryNoteError("Không tìm thấy cột 'Số lượng'.")
    return columns


def _place(text: str) -> int | None:
    """'Kho tổng' / 'Văn phòng' / '总仓' / '办公室' (also 'Kho tổng 总仓') -> location id; '' or anything else -> None."""
    plain = unaccent(text)
    found = {loc for word, loc in PLACE_VALUES.items() if word in plain or word in text}
    return found.pop() if len(found) == 1 else None


def _places(text: str, qty: float) -> tuple:
    """'Kho tổng 总仓: 3; Văn phòng 办公室: 2' -> ((1, 3.0), (2, 2.0)). Anything that does not add up to the line's
    quantity (the quantity edited in Excel afterwards) or cannot be read -> (): the app asks where, as for any note."""
    found: dict[int, float] = {}
    for part in clean(text).split(";"):
        if not part.strip():
            continue
        name, _, number = part.rpartition(":")
        loc, value = _place(name), _to_number(number.strip())
        if loc is None or value is None or value <= 0 or loc in found:
            return ()
        found[loc] = value
    if not found or abs(sum(found.values()) - qty) > 1e-9:
        return ()
    return tuple(sorted(found.items()))


def _cell(row, index):
    if index is None or index >= len(row):
        return None
    return row[index]


def _to_number(value) -> float | None:
    """A quantity. Text with thousands dots ('1.500': 1500 or 1,5?) is not guessed: None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    text = clean(_text(value))
    if _GROUPED.fullmatch(text) or re.search(r"\d[.,]\d{3}[.,]", text):
        return None
    try:
        number = float(text.replace(",", "."))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _to_money(value) -> float | None:
    """1188000, '1.188.000', '1,188,000 đ', '1188000.5' -> float; anything else -> None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^\d.,-]", "", clean(_text(value)))
    if _GROUPED.fullmatch(text):
        text = re.sub(r"[.,]", "", text)
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def _line_money(row, columns, qty: float, excel_row: int, warnings: list[str]):
    """(unit price, amount) of a goods line; one is worked out from the other when missing."""
    raw_price, raw_amount = _cell(row, columns.get("price")), _cell(row, columns.get("amount"))
    price, amount = _to_money(raw_price), _to_money(raw_amount)
    for raw, value in ((raw_price, price), (raw_amount, amount)):
        if raw not in (None, "") and value is None:
            warnings.append(f"Dòng {excel_row}: không đọc được giá ({raw!r}).")
    if amount is None and price is not None:
        amount = price * qty
    if price is None and amount is not None:
        price = amount / qty
    return price, amount


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
