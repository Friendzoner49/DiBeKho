"""What an .xlsx file holds, as plain JSON: every cell (value, font, borders, alignment, number format), merged ranges,
column widths and hidden columns, row heights, page setup, print area, file properties.

Used twice: tools/gen_issue.py dumps the files the Python app wrote (the reference), and tools/check_xlsx.py dumps the
files the Swift app wrote and compares them with it, on CI, with openpyxl (an independent reader of the files).
Python only; made-up data only.
"""

import json
import sys
import zipfile
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter


def _value(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return ["b", v]
    if isinstance(v, (int, float)):
        return ["n", round(float(v), 6)]
    if hasattr(v, "isoformat"):
        return ["d", v.isoformat()]
    return ["s", str(v)]


def _rgb(color):
    rgb = getattr(color, "rgb", None) if color is not None else None
    return rgb[-6:].upper() if isinstance(rgb, str) else None


def dump(path) -> dict:
    wb = openpyxl.load_workbook(path)
    ws = wb.worksheets[0]
    cells = {}
    for (row, col), c in sorted(ws._cells.items()):
        if type(c).__name__ == "MergedCell":
            continue
        if c.value is None and not c.has_style:
            continue
        b, a, f = c.border, c.alignment, c.font
        cells[c.coordinate] = {
            "v": _value(c.value),
            "font": [f.name or "Calibri", float(f.sz or 11), bool(f.b)],
            "border": [x.style if x is not None and x.style else None for x in (b.left, b.right, b.top, b.bottom)],
            "line": _rgb(b.left.color) if b.left is not None and b.left.style else None,
            "align": [a.horizontal or "", a.vertical or "", bool(a.wrap_text), bool(a.shrink_to_fit)],
            "fmt": c.number_format,
        }
    widths, hidden = {}, []
    for d in ws.column_dimensions.values():
        for i in range(d.min or 0, (d.max or 0) + 1):
            letter = get_column_letter(i)
            if d.width:
                widths[letter] = round(float(d.width), 2)
            if d.hidden:
                hidden.append(letter)
    heights = {str(r): round(float(d.height), 2) for r, d in ws.row_dimensions.items() if d.height}
    m, ps = ws.page_margins, ws.page_setup
    with zipfile.ZipFile(path) as z:
        app = z.read("docProps/app.xml").decode("utf-8")
    return {
        "sheet": ws.title,
        "merges": sorted(str(r) for r in ws.merged_cells.ranges),
        "widths": widths,
        "hidden": sorted(hidden),
        "heights": heights,
        "page": [ps.orientation, ps.paperSize, ps.scale, bool(ws.sheet_properties.pageSetUpPr.fitToPage)
                 if ws.sheet_properties.pageSetUpPr is not None else False,
                 round(m.left, 4), round(m.right, 4), round(m.top, 4), round(m.bottom, 4), round(m.header, 4),
                 round(m.footer, 4), ws.print_area, bool(ws.print_options.horizontalCentered)],
        "creator": wb.properties.creator or "",
        "last_modified_by": wb.properties.lastModifiedBy or "",
        "app": "<Application>Microsoft Excel</Application>" in app,
        "cells": cells,
    }


def compare(expected: dict, got: dict) -> list[str]:
    """What differs, one line per difference."""
    out = []
    for key in ("sheet", "merges", "widths", "hidden", "heights", "page", "creator", "last_modified_by", "app"):
        if expected[key] != got[key]:
            out.append(f"{key}: expected {expected[key]!r}, got {got[key]!r}")
    for coord in sorted(set(expected["cells"]) | set(got["cells"])):
        e, g = expected["cells"].get(coord), got["cells"].get(coord)
        # a number format means the same in either case (Excel reads DD/MM/YYYY and dd/mm/yyyy alike); the Swift app
        # writes it in lower case because Quick Look and Numbers read a capital D as the day of the year
        if e is not None and g is not None:
            e, g = {**e, "fmt": e["fmt"].lower()}, {**g, "fmt": g["fmt"].lower()}
        if e != g:
            out.append(f"{coord}: expected {json.dumps(e, ensure_ascii=False)}, got {json.dumps(g, ensure_ascii=False)}")
    return out


if __name__ == "__main__":
    print(json.dumps(dump(Path(sys.argv[1])), ensure_ascii=False, indent=1))
