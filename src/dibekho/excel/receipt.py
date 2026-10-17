"""Goods receipt (hàng về) Excel files.

- write_receipt: the file of a receipt entered in the app (output/hang-ve/), to keep or print.
- read_receipt: a goods-in file dropped into input/ — such a file, or the fill-in template of older versions.

Products are identified by their code (column A), so renaming a product
in the app does not break a file written earlier.
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
    """The fill-in template of the versions before 0.3 (goods in are now entered in the app). No longer offered,
    but customers may still have filled ones, which read_receipt accepts: tests build them with this.
    products: rows with code, name_vi, name_zh, spec, unit."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "HangVe"
    bold = Font(bold=True)
    ws["A1"] = f"{MARKER} / 到货单"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "Điền số lượng hàng về ở cột F, rồi bỏ file này vào thư mục input/ của DiBeKho. " \
               "/ Fill column F, then put this file into the DiBeKho input/ folder. " \
               "/ 在 F 列填写到货数量，然后把此文件放入 DiBeKho 的 input/ 文件夹。"
    ws["A2"].font = Font(italic=True, color="666666")
    # Vietnamese first in every label: the reader finds these rows by 'Ngày về', 'Ghi chú' and 'Mã'
    ws["A3"] = "Ngày về / Date / 到货日期:"
    ws["B3"] = today
    ws["B3"].number_format = "DD/MM/YYYY"
    ws["A4"] = "Ghi chú / Note / 备注:"
    for cell in ("A3", "A4"):
        ws[cell].font = bold

    headers = ["Mã / Code / 编码", "Tên hàng / Product / 品名", "中文名", "Quy cách / Spec / 规格", "Đơn vị / Unit / 单位",
               "Số lượng về / Qty / 到货数量", "Loại, màu / Variant / 类型、颜色"]
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
        dv.error = "Chỉ nhập số / Numbers only / 只能输入数字"
        ws.add_data_validation(dv)
        dv.add(f"F{HEADER_ROW + 1}:F{r}")
    for col, width in zip("ABCDEFG", (10, 45, 20, 16, 10, 16, 22)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = f"A{HEADER_ROW + 1}"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


SOURCE_LABELS = {
    "supplier": "Cửa khẩu / công ty mẹ · Border gate / parent company · 口岸/母公司",
    "return": "Khách hàng trả lại · Customer return · 客户退货",
}


def write_receipt(path: Path, head, lines) -> Path:
    """A receipt entered in the app, for the user to keep or print. Same layout as the template (label rows,
    then a table whose column A is the code and F the quantity), so read_receipt still recognises it.
    head: document row with code, doc_date, note, receipt_source, supplier_name, customer_name, ref_code.
    lines: rows with code, name_vi, name_zh, spec, unit, qty, variant, note."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "HangVe"
    bold = Font(bold=True)
    ws["A1"] = f"{MARKER} / 到货单"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "Phiếu do DiBeKho tạo khi nhập hàng về — đã ghi vào kho, không cần nhập lại. "                "/ Written by DiBeKho — already recorded, do not import it again. / 已入库，无需再次导入。"
    ws["A2"].font = Font(italic=True, color="666666")
    source = head["receipt_source"]
    who = head["supplier_name"] if source == "supplier" else head["customer_name"]
    # labels must not start with 'Mã' (the reader takes that row as the table header)
    rows = [
        ("Ngày về / Date / 到货日期:", date.fromisoformat(head["doc_date"])),
        ("Ghi chú / Note / 备注:", head["note"]),
        ("Số phiếu / No. / 单号:", head["code"]),
        ("Nguồn hàng / Source / 来源:", SOURCE_LABELS.get(source, "")),
        ("Nhà cung cấp / Supplier / 供应商:" if source == "supplier" else "Khách hàng / Customer / 客户:", who or ""),
    ]
    if source == "return" and head["ref_code"]:
        rows.append(("Đơn gốc / Order / 原订单:", head["ref_code"]))
    for r, (label, value) in enumerate(rows, start=3):
        ws.cell(row=r, column=1, value=label).font = bold
        ws.cell(row=r, column=2, value=value)
    ws["B3"].number_format = "DD/MM/YYYY"
    header_row = 3 + len(rows) + 1
    headers = ["Mã / Code / 编码", "Tên hàng / Product / 品名", "中文名", "Quy cách / Spec / 规格", "Đơn vị / Unit / 单位",
               "Số lượng về / Qty / 到货数量", "Loại, màu / Variant / 类型、颜色", "Ghi chú / Note / 备注"]
    for col, text in enumerate(headers, start=1):
        c = ws.cell(row=header_row, column=col, value=text)
        c.font = bold
        c.alignment = Alignment(wrap_text=True, vertical="center")
    total = 0
    r = header_row
    for r, ln in enumerate(lines, start=header_row + 1):
        for col, value in enumerate((ln["code"], ln["name_vi"], ln["name_zh"], ln["spec"], ln["unit"], ln["qty"],
                                     ln["variant"], ln["note"]), start=1):
            ws.cell(row=r, column=col, value=value)
        total += ln["qty"]
    ws.cell(row=r + 1, column=5, value="Tổng / Total / 合计").font = bold
    ws.cell(row=r + 1, column=6, value=total).font = bold
    for col, width in zip("ABCDEFGH", (10, 45, 20, 16, 10, 16, 22, 24)):
        ws.column_dimensions[col].width = width
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
