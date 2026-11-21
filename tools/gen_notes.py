"""Phase 2: made-up delivery notes (.xlsx) and what the Python reader reads in them, for the Swift reader's tests.

    uv --project K:/HeThongSonDiBe run python -X utf8 tools/gen_notes.py K:/HeThongSonDiBe

Writes Tests/DiBeKhoCoreTests/Notes/*.xlsx and Tests/DiBeKhoCoreTests/Generated/GoldenNotes.swift.
Made-up names only. The same canonical lines are made by tools/gen_real_notes.py for the customer's own notes (kept
on the developer's machines only, never committed).
"""

import shutil
import sys
from datetime import date, datetime
from pathlib import Path

SRC = Path(sys.argv[1]).resolve()
OUT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC / "src"))
sys.path.insert(0, str(SRC / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import openpyxl  # noqa: E402
from conftest import make_note  # noqa: E402

from dibekho.excel.issue_note import IssueHead, IssueRow, write_issue_note  # noqa: E402
from note_lines import note_lines, swift_str  # noqa: E402

NOTES = OUT / "Tests" / "DiBeKhoCoreTests" / "Notes"
shutil.rmtree(NOTES, ignore_errors=True)
NOTES.mkdir(parents=True)
CNY_FORMAT = r'_-* #,##0\ [$CNY]_-;\-* #,##0\ [$CNY]_-;_-* "-"\ [$CNY]_-;_-@_-'
MEMBRANE = ("防水卷材\nMàng khò nóng SBS 3mm", "1m×10m", 5, "", 1200)
GLUE = ("Keo FS-101", "5KG", 2.5, "giao trước", 380000)


def edit(path: Path, change) -> Path:
    wb = openpyxl.load_workbook(path)
    change(wb.active)
    wb.save(path)
    return path


def cells(ws):
    return [c for row in ws.iter_rows() for c in row]


made = []


def note(name: str, **kw) -> Path:
    path = make_note(NOTES / f"{name}.xlsx", **kw)
    made.append(path)
    return path


note("01-basic")
note("02-shifted", extra_top_row=True, code="0076")
note("03-fees", lines=[GLUE, MEMBRANE],
     extra_rows=[[None, "Phí vận chuyển", None, None, None, 50000, None], [None, "Ghi chú: giao trước 9h", None, None, None, None, None]],
     total=1050000)
note("04-prices-as-text", lines=[("Sơn chống thấm", "20KG/thùng", 3, "", "1.188.000"), ("Keo", "5KG", 1, "", "abc"),
                                 ("Băng keo butyl", "10cm", "2,5", "", 95000)])
edit(note("05-date-cell"), lambda ws: [setattr(c, "value", datetime(2026, 11, 3)) for c in cells(ws)
                                       if isinstance(c.value, str) and c.value.startswith("送货日期")]
     and None)
# the date cell only works next to a label: put the label alone and the date in the next cell
p = note("06-date-next-cell")


def date_next(ws):
    for c in cells(ws):
        if isinstance(c.value, str) and c.value.startswith("送货日期"):
            c.value = "送货日期 ( Ngày giao hàng )"
            ws.cell(row=c.row, column=c.column + 1, value=datetime(2026, 11, 3))
            ws.cell(row=c.row, column=c.column + 1).number_format = "dd/mm/yyyy"


edit(p, date_next)
for how in ("format", "words", "header"):
    p = note(f"07-yuan-{how}", code="155", lines=[MEMBRANE, GLUE])

    def yuan(ws, how=how):
        for c in cells(ws):
            if how == "format" and c.column in (5, 6) and isinstance(c.value, (int, float)):
                c.number_format = CNY_FORMAT
            if how == "words" and c.value == "MỘT TRIỆU":
                c.value = "Bốn nghìn tám trăm nhân dân tệ"
            if how == "header" and isinstance(c.value, str) and c.value.endswith("\nVND"):
                c.value = c.value.replace("VND", "CNY")
    edit(p, yuan)
p = note("08-chinese-labels")


def chinese(ws):
    for c in cells(ws):
        if isinstance(c.value, str) and c.value.startswith("客户名称"):
            c.value = "客户名称 Khách Mẫu"
        elif isinstance(c.value, str) and c.value.startswith("联系电话"):
            c.value = "联系电话：0900 000 002"


edit(p, chinese)
note("09-bad-quantity", lines=[("Sơn", "20KG", "1.500", ""), ("Keo", "5KG", 2, "")])
note("10-no-date", day="")
note("11-zero-and-nameless", lines=[("Sơn", "20KG", 0, ""), ("", "", 4, ""), ("Keo", "5KG", 3, "", None)])
note("11b-negative", lines=[("Keo", "5KG", 3, ""), ("Băng", "", -2, "")])
note("12-note-says-total", lines=[("Sơn", "20KG", 3, "người giao hàng thu tiền"), ("Keo", "5KG", 1, "")])
note("13-several-lines", code="160", day="5/11/2026", customer="Công ty  A ",
     lines=[MEMBRANE, GLUE, ("背水涂\nvữa chống thấm (BACKWATER COATING)", "10KG/thùng", 1, "", None)], total=999)
wb = openpyxl.Workbook()
wb.active.append(["Bảng lương tháng 10"])
wb.active.append(["Họ tên", "Số tiền"])
wb.save(NOTES / "14-not-a-note.xlsx")
made.append(NOTES / "14-not-a-note.xlsx")
write_issue_note(NOTES / "15-issue-note.xlsx",
                 IssueHead("A161", date(2026, 11, 14), "Công ty A", "0900 000 001", "Anh B", "1 Đường X, Hà Nội", "0101234567", "a@example.com",
                           ["CÔNG TY MẪU", "Hà Nội"]),
                 [IssueRow("SP001", "Sơn chống thấm", "防水涂料", "20KG/thùng", 13, [(1, 10), (2, 3)], 512500.5, None, "giao sáng"),
                  IssueRow("SP002", "Keo FS-101", "", "5KG", 2.5, [(1, 2.5)], None, None, "")])
made.append(NOTES / "15-issue-note.xlsx")
(NOTES / "16-broken.xlsx").write_bytes(b"this is not a zip file")
made.append(NOTES / "16-broken.xlsx")

# the new template of 18/11/2026: MST and e-mail on their own row (cases of the Python tests/test_customer_tax_email.py)
sys.path.insert(0, str(SRC))
from test_customer_tax_email import _template_note  # noqa: E402

made.append(_template_note(NOTES / "17-template.xlsx", "0101234567", "a@example.com", "0900 000 001", "Khách Mẫu"))
made.append(_template_note(NOTES / "18-template-empty.xlsx"))
p19 = _template_note(NOTES / "19-mst-number.xlsx")
wb = openpyxl.load_workbook(p19)
wb.active["C6"], wb.active["D6"] = "MST 税号：", 101234567
wb.save(p19)
made.append(p19)
p20 = _template_note(NOTES / "20-mst-in-product.xlsx", "0101234567")
wb = openpyxl.load_workbook(p20)
wb.active["B10"] = "Màng AMST 3mm"
wb.save(p20)
made.append(p20)

expected = {p.name: note_lines(p) for p in sorted(made)}
body = "".join(f"        {swift_str(k)}: [\n" + "".join(f"            {swift_str(x)},\n" for x in v) + "        ],\n"
               for k, v in expected.items())
gold = OUT / "Tests" / "DiBeKhoCoreTests" / "Generated" / "GoldenNotes.swift"
gold.write_text("// GENERATED by tools/gen_notes.py from the Python reader (excel/delivery_note.py). Do not edit.\n\n"
                "enum GoldenNotes {\n    /// file in Notes/ -> what the Python reader reads (tools/note_lines.py)\n"
                "    static let notes: [String: [String]] = [\n" + body + "    ]\n}\n", encoding="utf-8", newline="\n")
for k, v in expected.items():
    print(k, "->", v[0][:110])
