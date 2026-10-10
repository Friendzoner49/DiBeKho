"""Statistics export to Excel. No prices anywhere."""

from datetime import date, datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from dibekho.core import stats
from dibekho.i18n import t

SHEETS = ("summary", "details", "customers", "top")
_HEAD_FILL = PatternFill("solid", fgColor="DDEBF7")
_BOLD = Font(bold=True)


def export(path: Path, conn, start: date, end: date, filters: stats.Filters, by: str,
           sheets: set[str], period_label: str, scope_label: str) -> Path:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    info = [
        t("report.period", period=period_label),
        t("report.scope", scope=scope_label),
        t("report.exported_at", at=datetime.now().strftime("%d/%m/%Y %H:%M")),
    ]
    if "summary" in sheets:
        _summary(wb, conn, start, end, filters, by, info)
    if "details" in sheets:
        _details(wb, conn, start, end, filters, info)
    if "customers" in sheets:
        _customers(wb, conn, start, end, filters, info)
    if "top" in sheets:
        _top(wb, conn, start, end, filters, info)
    if not wb.worksheets:
        raise ValueError("no sheet selected")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def _sheet(wb, title: str, info: list[str], headers: list[str]):
    ws = wb.create_sheet(title[:31])
    for i, line in enumerate(info, start=1):
        ws.cell(row=i, column=1, value=line).font = Font(italic=True, color="555555")
    header_row = len(info) + 2
    for col, text in enumerate(headers, start=1):
        c = ws.cell(row=header_row, column=col, value=text)
        c.font, c.fill = _BOLD, _HEAD_FILL
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    ws.freeze_panes = ws.cell(row=header_row + 1, column=3)
    return ws, header_row + 1


def _widths(ws, widths: list[int]) -> None:
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _summary(wb, conn, start, end, filters, by, info):
    rows = stats.summary(conn, start, end, filters, by)
    labels = [b.label for b in stats.buckets(start, end, by)] if by != "none" else []
    customer_filtered = bool(filters.customer_ids)
    headers = [t("col.code"), t("col.product"), t("col.name_zh"), t("col.spec"), t("col.variant"), t("col.unit"),
               t("col.category")]
    if not customer_filtered:
        headers.append(t("col.opening"))
    headers += [t("col.in"), t("col.out"), t("col.adjust")]
    if not customer_filtered:
        headers.append(t("col.closing"))
    for label in labels:
        headers += [f"{t('col.in')} {label}", f"{t('col.out')} {label}"]
    ws, r = _sheet(wb, t("sheet.summary"), info, headers)
    for row in rows:
        values = [row.code, row.name_vi, row.name_zh, row.spec, row.variant, row.unit, row.category]
        if not customer_filtered:
            values.append(row.opening)
        values += [row.qty_in, row.qty_out, row.adjust]
        if not customer_filtered:
            values.append(row.closing)
        for label in labels:
            qin, qout = row.per_bucket.get(label, (0, 0))
            values += [qin or None, qout or None]
        for col, v in enumerate(values, start=1):
            ws.cell(row=r, column=col, value=v)
        r += 1
    _widths(ws, [9, 45, 20, 16, 14, 8, 14] + [11] * (len(headers) - 7))


def _details(wb, conn, start, end, filters, info):
    kinds = {
        "delivery_out": t("kind.delivery"), "delivery_reverse": t("kind.delivery_cancel"),
        "receipt_in": t("kind.receipt"), "receipt_reverse": t("kind.receipt_cancel"),
        "count_adjust": t("kind.count"), "count_reverse": t("kind.count_cancel"),
    }
    headers = [t("col.date"), t("col.kind"), t("col.doc_code"), t("col.customer"), t("col.code"),
               t("col.product"), t("col.spec"), t("col.variant"), t("col.unit"), t("col.qty_change"), t("col.note")]
    ws, r = _sheet(wb, t("sheet.details"), info, headers)
    for m in stats.detail_lines(conn, start, end, filters):
        values = [date.fromisoformat(m["occurred_on"]), kinds.get(m["kind"], m["kind"]), m["code"],
                  m["customer_name"], m["product_code"], m["name_vi"], m["spec"], m["variant"], m["unit"], m["qty"],
                  m["note"]]
        for col, v in enumerate(values, start=1):
            cell = ws.cell(row=r, column=col, value=v)
            if col == 1:
                cell.number_format = "DD/MM/YYYY"
        r += 1
    _widths(ws, [11, 16, 10, 30, 9, 40, 16, 14, 8, 10, 30])


def _customers(wb, conn, start, end, filters, info):
    headers = [t("col.customer"), t("col.code"), t("col.product"), t("col.spec"), t("col.variant"), t("col.unit"),
               t("col.total_qty"), t("col.times"), t("col.last_date")]
    ws, r = _sheet(wb, t("sheet.customers"), info, headers)
    for row in stats.customer_product(conn, start, end, filters):
        values = [row["customer_name"], row["code"], row["name_vi"], row["spec"], row["variant"], row["unit"],
                  row["total_qty"], row["times"], date.fromisoformat(row["last_date"])]
        for col, v in enumerate(values, start=1):
            cell = ws.cell(row=r, column=col, value=v)
            if col == 9:
                cell.number_format = "DD/MM/YYYY"
        r += 1
    _widths(ws, [32, 9, 40, 16, 14, 8, 12, 10, 12])


def _top(wb, conn, start, end, filters, info):
    headers = [t("col.rank"), t("col.code"), t("col.product"), t("col.spec"), t("col.variant"), t("col.unit"),
               t("col.out")]
    ws, r = _sheet(wb, t("sheet.top"), info, headers)
    for i, row in enumerate(stats.top_out(conn, start, end, filters, limit=50), start=1):
        for col, v in enumerate([i, row.code, row.name_vi, row.spec, row.variant, row.unit, row.qty_out], start=1):
            ws.cell(row=r, column=col, value=v)
        r += 1
    _widths(ws, [6, 9, 45, 16, 14, 8, 12])
