"""Stock issue note (Phiếu xuất kho 出库单): written by the app (and the same layout by the web page), read back by
excel/delivery_note.py like any delivery note.

The layout follows the customer's own delivery notes (label and value in one cell, then a table from 'Tên hàng'
to 'Tổng cộng'), with two more columns the reader also understands: 'Mã hàng' (the product, by code, so a
renamed product still matches) and 'Lấy từ kho' (Kho tổng / Văn phòng, per line: one product taken from both places
is two lines). Only plain values are written, never formulas: the reader opens files with data_only=True, and a
formula saved by a program has no value until Excel opens it.

webapp/issue.js writes the same file; tests/test_issue_note.py reads both back.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, Side

TITLE = "出库单  PHIẾU XUẤT KHO"
# the labels the reader looks for (excel/delivery_note.HEADER_LABELS); an optional field left empty is not written,
# else the reader would take the next cell as its value
LABELS = {
    "customer": "客户名称 ( Tên khách hàng )",
    "phone": "联系电话 ( Điện thoại liên hệ )",
    "code": "订货单号 ( Mã đơn hàng )",
    "contact": "联系人 ( Người liên hệ )",
    "date": "送货日期 ( Ngày giao hàng )",
    "address": "地址 ( Địa chỉ )",
}
HEADERS = ["编号\nSTT", "货号\nMã hàng", "商品全名\nTên hàng", "规格\nQuy cách", "单位\nĐơn vị", "数量\nSố lượng",
           "取货地点\nLấy từ kho", "单价\nĐơn giá", "金额\nThành tiền", "备注\nGhi chú"]
PLACES = {1: "Kho tổng 总仓", 2: "Văn phòng 办公室"}
TOTAL = "合计  Tổng cộng"
SIGNATURES = ("Người lập phiếu  制单人", "Người giao hàng  送货人", "Người nhận hàng  收货人")
HEADER_ROW = 7
_THIN = Side(style="thin", color="999999")
_BOX = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


@dataclass
class IssueRow:
    code: str
    name_vi: str
    name_zh: str
    spec: str
    unit: str
    qty: float
    location_id: int
    unit_price: float | None = None
    amount: float | None = None
    note: str = ""


@dataclass
class IssueHead:
    code: str
    doc_date: date
    customer: str
    phone: str = ""
    contact: str = ""
    address: str = ""


def product_name(name_vi: str, name_zh: str) -> str:
    """'中文名\\nTên Việt', like the customer's notes (text.split_bilingual_name reads it back)."""
    return f"{name_zh}\n{name_vi}" if name_zh and name_vi else (name_vi or name_zh)


def write_issue_note(path: Path, head: IssueHead, rows: list[IssueRow]) -> Path:
    wb = openpyxl.Workbook()
    wb.properties.creator = ""
    wb.properties.lastModifiedBy = ""
    ws = wb.active
    ws.title = "出库单"
    bold = Font(bold=True)
    last_col = len(HEADERS)
    ws.cell(row=1, column=1, value=TITLE).font = Font(bold=True, size=16)
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="center")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)

    def label(row, col, key, value, span):
        if not value:
            return
        c = ws.cell(row=row, column=col, value=f"{LABELS[key]}：{value}")
        c.alignment = Alignment(wrap_text=True, vertical="center")
        ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + span - 1)

    label(3, 1, "customer", head.customer, 4)
    label(3, 5, "phone", head.phone, 3)
    label(3, 8, "code", head.code, 3)
    label(4, 1, "contact", head.contact, 4)
    label(4, 8, "date", head.doc_date.strftime("%d-%m-%Y"), 3)
    label(5, 1, "address", head.address, last_col)

    for col, text in enumerate(HEADERS, start=1):
        c = ws.cell(row=HEADER_ROW, column=col, value=text)
        c.font = bold
        c.border = _BOX
        c.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
    ws.row_dimensions[HEADER_ROW].height = 34
    r = HEADER_ROW
    qty_total, money_total, priced = 0.0, 0.0, False
    for i, ln in enumerate(rows, start=1):
        r = HEADER_ROW + i
        values = (i, ln.code, product_name(ln.name_vi, ln.name_zh), ln.spec, ln.unit, ln.qty,
                  PLACES[ln.location_id], ln.unit_price, ln.amount, ln.note)
        for col, value in enumerate(values, start=1):
            c = ws.cell(row=r, column=col, value=value)
            c.border = _BOX
            c.alignment = Alignment(wrap_text=True, vertical="center")
        for col in (8, 9):
            ws.cell(row=r, column=col).number_format = "#,##0"
        qty_total += ln.qty
        if ln.amount is not None:
            money_total += ln.amount
            priced = True
    r += 1
    ws.cell(row=r, column=3, value=TOTAL).font = bold
    ws.cell(row=r, column=6, value=qty_total).font = bold
    if priced:
        c = ws.cell(row=r, column=9, value=money_total)
        c.font = bold
        c.number_format = "#,##0"
    for col, text in zip((2, 5, 8), SIGNATURES):
        ws.cell(row=r + 2, column=col, value=text).font = bold
    for col, width in zip("ABCDEFGHIJ", (6, 10, 42, 14, 8, 10, 16, 13, 15, 20)):
        ws.column_dimensions[col].width = width
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    from dibekho.excel.receipt import _plain_app_properties

    _plain_app_properties(path)
    return path
