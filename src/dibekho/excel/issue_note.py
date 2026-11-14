"""Stock issue note (Phiếu xuất kho 出库单): written by the app (and the very same cells by the web page,
webapp/xlsx.js), read back by excel/delivery_note.py like any delivery note.

The user asked for the two notes to be laid out alike so a file can go either way: this is the grid of the shop's
own delivery notes (销售单 PHIẾU GIAO HÀNG) cell for cell - the company lines, the title, the customer block,
STT · Tên hàng · Quy cách · Số lượng · Đơn giá · Thành tiền · Ghi chú, the total in words, the signatures - with
the same widths, heights, fonts and print setup. Only the title says PHIẾU XUẤT KHO.

The company name and address are not in the code (the repository is public): they are the lines the app read
above the title of the shop's latest delivery note (core/deliveries.keep_letterhead, meta 'note_letterhead').

Two hidden columns (not seen, not printed) keep what the app needs to read the file back exactly: H 'Mã hàng' (the
product, so a renamed one still matches) and I 'Lấy từ kho' ('Kho tổng 总仓: 3; Văn phòng 办公室: 2'). A customer
note has neither and reads as before. Only plain values, never formulas: the reader opens files with
data_only=True, and a formula saved by a program has no value until Excel opens it.

tests/test_web_issue.py compares this file with the web's cell by cell.
"""

import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.worksheet.properties import PageSetupProperties

TITLE = "出库单 PHIẾU XUẤT KHO"
LABELS = {
    "customer": "客户名称 ( Tên khách hàng ): ",
    "phone": "联系电话 ( Điện thoại liên hệ ): ",
    "code": "订货单号 ( Mã đơn hàng )：",
    "contact": "联系人( Người liên hệ )：",
    "date": "送货日期 ( Ngày giao hàng )：",
    "address": "地址( Địa chỉ): ",
}
HEADERS = ["编 号\nSTT", "商 品 全 名\nTên hàng", "规格\nQUY CÁCH", "数 量\nSố lượng", "单 价\nVND", "金 额\nVND",
           "备 注\nGhi chú", "货号\nMã hàng", "取货地点\nLấy từ kho"]
PLACES = {1: "Kho tổng 总仓", 2: "Văn phòng 办公室"}
WORDS_LABEL = "总计大写\n (Tổng cộng viết bằng chữ)"
QTY_LABEL = "页小计 \n( Tổng số lượng ):\n"
SIGN_FROM = "送货单位及经手人（盖章）：Người giao hàng"
SIGN_TO = "收货单位及经手人（盖章）：Người nhận hàng"
SHEET = "出库单"
HEADER_ROW = 8
WIDTHS = [17.1, 62.8, 20.2, 13.0, 34.8, 25.1, 25.8, 12.0, 24.0]  # A..I; H and I hidden
HIDDEN = (8, 9)
HEIGHTS = {1: 61.15, 2: 40.9, 3: 9.0, 4: 40.15, 5: 54.0, 6: 44.25, 7: 31.9, HEADER_ROW: 40.15}
LINE_HEIGHT, TOTAL_HEIGHT, SIGN_HEIGHT = 38.0, 76.5, 82.9
MONEY = '[$VND]\\ #,##0'
TNR = "Times New Roman"  # every cell, as the shop's note shows (Chinese falls back to a CJK font)

_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
_UNITS = ["", "nghìn", "triệu", "tỷ", "nghìn tỷ", "triệu tỷ"]


@dataclass
class IssueRow:
    code: str
    name_vi: str
    name_zh: str
    spec: str
    qty: float
    places: list[tuple[int, float]] = field(default_factory=list)  # [(location id, qty)], adding up to qty
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
    letterhead: list[str] = field(default_factory=list)  # company name, address (from the shop's delivery notes)


@dataclass
class Cell:
    value: object
    font: str = TNR
    size: float = 15
    border: bool = False
    align: str = "center"  # horizontal
    wrap: bool = True
    money: bool = False


@dataclass
class Sheet:
    cells: dict = field(default_factory=dict)  # (row, col) -> Cell
    merges: list[str] = field(default_factory=list)
    heights: dict = field(default_factory=dict)
    last_row: int = 0


def product_name(name_vi: str, name_zh: str) -> str:
    """'中文名\\nTên Việt', like the customer's notes (text.split_bilingual_name reads it back)."""
    return f"{name_zh}\n{name_vi}" if name_zh and name_vi else (name_vi or name_zh)


def number_text(value: float) -> str:
    """3 -> '3', 2.5 -> '2.5' (as webapp/xlsx.js numberText)."""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def places_text(places) -> str:
    return "; ".join(f"{PLACES[loc]}: {number_text(qty)}" for loc, qty in places if qty)


def _three(n: int, full: bool) -> list[str]:
    hundreds, tens, units = n // 100, n // 10 % 10, n % 10
    words = []
    if full or hundreds:
        words += [_DIGITS[hundreds], "trăm"]
    if tens == 0:
        if units and (full or hundreds):
            words.append("linh")
    elif tens == 1:
        words.append("mười")
    else:
        words += [_DIGITS[tens], "mươi"]
    if units:
        words.append("mốt" if units == 1 and tens >= 2 else "lăm" if units == 5 and tens >= 1 else _DIGITS[units])
    return words


def vnd_words(amount: float) -> str:
    """2376000 -> 'HAI TRIỆU BA TRĂM BẢY MƯƠI SÁU NGHÌN VIỆT NAM ĐỒNG', as the shop writes it (webapp/xlsx.js vndWords)."""
    n = int(math.floor(amount + 0.5))
    if n < 0:
        return ""
    if n == 0:
        return "KHÔNG VIỆT NAM ĐỒNG"
    groups = []
    while True:
        groups.append(n % 1000)
        n //= 1000
        if not n:
            break
    words: list[str] = []
    for i in range(len(groups) - 1, -1, -1):
        if groups[i] == 0 and (words or i):
            continue
        words += _three(groups[i], bool(words))
        if _UNITS[i]:
            words.append(_UNITS[i])
    return " ".join(words).upper() + " VIỆT NAM ĐỒNG"


def _wrapped_lines(text: str, width: float, size: float) -> int:
    """About how many lines a wrapped cell takes (Excel does not grow a row a program wrote)."""
    per_line = max(1.0, width * 11 / size)
    total = 0
    for part in str(text).split("\n"):
        units = sum(2 if ord(ch) > 0x2E7F else 1 for ch in part)
        total += max(1, math.ceil(units / per_line))
    return total


def issue_sheet(head: IssueHead, rows: list[IssueRow]) -> Sheet:
    """The cells of the note. webapp/xlsx.js issueSheet builds the same ones."""
    sh = Sheet(heights=dict(HEIGHTS))

    def put(r, c, value, **style):
        sh.cells[(r, c)] = Cell(value, **style)

    letter = (head.letterhead + ["", ""])[:2]
    put(1, 1, letter[0] or None, size=20)
    put(2, 1, letter[1] or None, size=20)
    put(4, 1, TITLE, size=24)
    put(5, 1, LABELS["customer"] + "\n" + head.customer, size=20, align="left")
    put(5, 3, LABELS["phone"] + head.phone, size=14, align="left")
    put(5, 6, LABELS["code"] + head.code, size=14, align="left")
    put(6, 3, LABELS["contact"] + head.contact, size=14, align="left")
    put(6, 6, LABELS["date"] + head.doc_date.strftime("%d-%m-%Y"), size=14, align="left")
    put(7, 1, LABELS["address"] + head.address, size=14, align="left")
    sh.merges += ["A1:G1", "A2:G2", "A3:G3", "A4:G4", "A5:B6", "C5:E5", "F5:G5", "C6:E6", "F6:G6", "A7:E7"]
    for c, text in enumerate(HEADERS, start=1):
        put(HEADER_ROW, c, text, border=c <= 7)
    r = HEADER_ROW
    qty_total, money_total, priced = 0.0, 0.0, False
    for i, ln in enumerate(rows, start=1):
        r = HEADER_ROW + i
        name = product_name(ln.name_vi, ln.name_zh)
        put(r, 1, i, border=True)
        put(r, 2, name, border=True)
        put(r, 3, ln.spec or None, size=18, border=True)
        put(r, 4, ln.qty, size=18, border=True)
        put(r, 5, ln.unit_price, size=18, border=True, money=True)
        put(r, 6, ln.amount, size=18, border=True, money=True)
        put(r, 7, ln.note or None, border=True)
        put(r, 8, ln.code, size=11, wrap=False)
        put(r, 9, places_text(ln.places) or None, size=11, wrap=False)
        lines = max(_wrapped_lines(name, WIDTHS[1], 15), _wrapped_lines(ln.note, WIDTHS[6], 15),
                    _wrapped_lines(ln.spec, WIDTHS[2], 18))
        sh.heights[r] = max(LINE_HEIGHT, 20.0 * lines)
        qty_total += ln.qty
        if ln.amount is not None:
            money_total += ln.amount
            priced = True
    r += 1
    put(r, 1, WORDS_LABEL, border=True)
    put(r, 2, vnd_words(money_total) if priced else None, border=True)
    put(r, 3, None, border=True)
    put(r, 4, QTY_LABEL + number_text(qty_total), border=True)
    put(r, 5, None, border=True)
    put(r, 6, money_total if priced else None, size=18, border=True, money=True)
    put(r, 7, None, border=True)
    sh.merges.append(f"B{r}:C{r}")
    sh.heights[r] = TOTAL_HEIGHT
    r += 1
    put(r, 1, SIGN_FROM, size=14, align="left", wrap=False)
    put(r, 4, SIGN_TO, size=14, align="left", wrap=False)
    sh.merges.append(f"A{r}:C{r}")
    sh.heights[r] = SIGN_HEIGHT
    sh.last_row = r
    return sh


def write_issue_note(path: Path, head: IssueHead, rows: list[IssueRow]) -> Path:
    sh = issue_sheet(head, rows)
    wb = openpyxl.Workbook()
    wb.properties.creator = ""
    wb.properties.lastModifiedBy = ""
    ws = wb.active
    ws.title = SHEET
    thin = Side(style="thin")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    for (r, c), cell in sorted(sh.cells.items()):
        x = ws.cell(row=r, column=c, value=cell.value)
        x.font = Font(name=cell.font, size=cell.size, bold=True)
        x.alignment = Alignment(horizontal=cell.align, vertical="center", wrap_text=cell.wrap or None)
        if cell.border:
            x.border = box
        if cell.money:
            x.number_format = MONEY
    for m in sh.merges:
        ws.merge_cells(m)
    for r, height in sh.heights.items():
        ws.row_dimensions[r].height = height
    for i, width in enumerate(WIDTHS):
        letter = "ABCDEFGHI"[i]
        ws.column_dimensions[letter].width = width
        if i + 1 in HIDDEN:
            ws.column_dimensions[letter].hidden = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.scale = 67
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=False)
    ws.page_margins.left = ws.page_margins.right = 0.0
    ws.page_margins.top = ws.page_margins.bottom = 0.393700787401575
    ws.print_area = f"A1:G{sh.last_row}"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    from dibekho.excel.receipt import _plain_app_properties

    _plain_app_properties(path)
    return path
