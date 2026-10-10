"""Goods receipt (hàng về) template: the app writes it, the user fills quantities,
then drops it into input/.

Products are identified by their code (column A), so renaming a product
in the app does not break an already-generated template.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from dibekho.core.text import clean, parse_number, unaccent

MARKER = "PHIẾU HÀNG VỀ / GOODS RECEIPT"
_MARKER_PLAIN = ("phieu hang ve", "goods receipt")
HEADER_ROW = 6
_DATE = re.compile(r"(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{4})")


class NotReceipt(Exception):
    pass


class ReceiptError(Exception):
    pass


@dataclass
class ReceiptLine:
    row: int
    code: str
    qty: float


@dataclass
class ReceiptFile:
    doc_date: date
    note: str
    lines: list[ReceiptLine]
    warnings: list[str] = field(default_factory=list)


def write_template(path: Path, products, today: date) -> Path:
    """products: rows with code, name_vi, name_zh, spec, unit."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "HangVe"
    bold = Font(bold=True)
    ws["A1"] = MARKER
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "Điền số lượng hàng về ở cột F, rồi bỏ file này vào thư mục input/ của DiBeKho. " \
               "/ Fill column F, then put this file into the DiBeKho input/ folder."
    ws["A2"].font = Font(italic=True, color="666666")
    ws["A3"] = "Ngày về / Date:"
    ws["B3"] = today
    ws["B3"].number_format = "DD/MM/YYYY"
    ws["A4"] = "Ghi chú / Note:"
    for cell in ("A3", "A4"):
        ws[cell].font = bold

    headers = ["Mã / Code", "Tên hàng / Product", "中文", "Quy cách / Spec", "Đơn vị / Unit", "Số lượng về / Qty",
               "Loại, màu / Variant"]
    for col, text in enumerate(headers, start=1):
        c = ws.cell(row=HEADER_ROW, column=col, value=text)
        c.font = bold
        c.alignment = Alignment(wrap_text=True, vertical="center")
    fill = PatternFill("solid", fgColor="FFF2CC")
    r = HEADER_ROW
    for r, p in enumerate(products, start=HEADER_ROW + 1):
        ws.cell(row=r, column=1, value=p["code"])
        ws.cell(row=r, column=2, value=p["name_vi"])
        ws.cell(row=r, column=3, value=p["name_zh"])
        ws.cell(row=r, column=4, value=p["spec"])
        ws.cell(row=r, column=5, value=p["unit"])
        ws.cell(row=r, column=6).fill = fill
        ws.cell(row=r, column=7, value=p["variant"])
    if r > HEADER_ROW:
        dv = DataValidation(type="decimal", operator="greaterThanOrEqual", formula1="0", allow_blank=True)
        dv.error = "Chỉ nhập số / Numbers only"
        ws.add_data_validation(dv)
        dv.add(f"F{HEADER_ROW + 1}:F{r}")
    for col, width in zip("ABCDEFG", (10, 45, 20, 16, 10, 16, 22)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = f"A{HEADER_ROW + 1}"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def is_receipt(path: Path) -> bool:
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return False
    try:
        ws = wb.worksheets[0]
        for row in ws.iter_rows(min_row=1, max_row=3, values_only=True):
            if any(m in unaccent(str(v or "")) for v in row for m in _MARKER_PLAIN):
                return True
        return False
    finally:
        wb.close()


def read_receipt(path: Path) -> ReceiptFile:
    if not is_receipt(path):
        raise NotReceipt("Không phải file hàng về (thiếu tiêu đề 'PHIẾU HÀNG VỀ').")
    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        rows = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    finally:
        wb.close()

    doc_date, note, header = None, "", None
    for i, row in enumerate(rows):
        first = unaccent(str(row[0] or "")) if row else ""
        if first.startswith("ngay ve"):
            doc_date = _parse_date(row[1] if len(row) > 1 else None)
        elif first.startswith("ghi chu"):
            note = clean(row[1] if len(row) > 1 else "")
        elif first.startswith("ma"):
            header = i
            break
    if doc_date is None:
        raise ReceiptError("Thiếu hoặc sai 'Ngày về' (ô B3, dạng ngày/tháng/năm).")
    if header is None:
        raise ReceiptError("Không thấy dòng tiêu đề bảng (cột 'Mã / Code').")

    lines, warnings = [], []
    for i in range(header + 1, len(rows)):
        row = rows[i] + [None] * 6
        code, qty = clean(row[0]), row[5]
        if not code or qty in (None, ""):
            continue
        try:
            value = parse_number(qty)
        except ValueError:
            warnings.append(f"Dòng {i + 1}: số lượng '{qty}' không phải số, bỏ qua.")
            continue
        if value < 0:
            warnings.append(f"Dòng {i + 1}: số lượng âm, bỏ qua.")
            continue
        if value > 0:
            lines.append(ReceiptLine(i + 1, code, value))
    if not lines:
        raise ReceiptError("Chưa điền số lượng cho mặt hàng nào.")
    return ReceiptFile(doc_date, note, lines, warnings)


def _parse_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    m = _DATE.search(str(value or ""))
    if not m:
        return None
    d, mth, y = (int(g) for g in m.groups())
    try:
        return date(y, mth, d)
    except ValueError:
        return None
