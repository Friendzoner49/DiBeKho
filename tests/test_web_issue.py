"""The Phiếu xuất kho made on the web (14/11/2026) is the app's own file: webapp/xlsx.js run in Node writes it, the
app's reader reads it like the file core/issues.py writes, and the file dropped into the notes folder takes the stock
of each place once. Skipped without Node."""

import dataclasses
import json
import shutil
import subprocess
from datetime import date
from pathlib import Path

import openpyxl
import pytest

from dibekho import db
from dibekho.core import catalog, deliveries, issues
from dibekho.core.issues import IssueInput, IssueLineInput
from dibekho.core.stock import MAIN, OFFICE, stock_count, stock_levels
from dibekho.excel.delivery_note import read_delivery_note
from dibekho.excel.issue_note import IssueHead, write_issue_note

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is not installed")


def _node(*args) -> str:
    done = subprocess.run([NODE, str(ROOT / "tests" / "web_issue_cli.js"), *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.fixture
def goods(conn):
    with db.transaction(conn):
        paint = catalog.create_product(conn, "Sơn chống thấm", "防水涂料", "20KG/thùng", "thùng", "Sơn", variant="Xám")
        sand = catalog.create_product(conn, "Keo cố định cát", "", "5KG", "can", "Keo")
        stock_count(conn, date(2026, 11, 1), {(paint, MAIN): 50, (paint, OFFICE): 8, (sand, MAIN): 20})
    return paint, sand


def _input(paint, sand):
    return IssueInput(date(2026, 11, 14), "Công ty A", phone="0900 000 001", contact="Anh B", address="1 Đường X, Hà Nội",
                      lines=[IssueLineInput(paint, qty_main=10, qty_office=3, unit_price=512500.5, note="  giao   sáng "),
                             IssueLineInput(sand, qty_main=2.5, unit_price=None)])


def _web_rows(conn, data, tmp_path):
    """noteRows() of xlsx.js for the same input as the app's note_rows()."""
    products = {str(r["id"]): dict(r) for r in conn.execute("SELECT * FROM products")}
    lines = [{"product_id": str(ln.product_id), "qty_main": ln.qty_main, "qty_office": ln.qty_office,
              "unit_price": ln.unit_price, "note": ln.note} for ln in data.lines]
    src, out = tmp_path / "rows-in.json", tmp_path / "rows-out.json"
    src.write_text(json.dumps({"products": products, "lines": lines}, ensure_ascii=False), encoding="utf-8")
    _node("rows", src, out)
    return json.loads(out.read_text(encoding="utf-8"))


def _web_file(head: dict, rows: list, path: Path) -> Path:
    src = path.with_suffix(".json")
    src.write_text(json.dumps({"head": head, "rows": rows}, ensure_ascii=False), encoding="utf-8")
    _node("file", src, path)
    return path


def test_the_code_is_the_apps():
    assert _node("code") == "PX261114-093015" == issues.new_code(__import__("datetime").datetime(2026, 11, 14, 9, 30, 15))


def test_the_rows_are_the_apps(conn, goods, tmp_path):
    paint, sand = goods
    data = _input(paint, sand)
    app = [dataclasses.asdict(r) for r in issues.note_rows(conn, data)]
    web = _web_rows(conn, data, tmp_path)
    assert web == app
    assert [(r["location_id"], r["qty"]) for r in web] == [(MAIN, 10), (OFFICE, 3), (MAIN, 2.5)]


def test_the_web_file_reads_like_the_apps_file(conn, goods, tmp_path):
    paint, sand = goods
    data = _input(paint, sand)
    rows = issues.note_rows(conn, data)
    head = IssueHead("PX261114-093015", data.doc_date, data.customer_name, data.phone, data.contact, data.address)
    app_file = write_issue_note(tmp_path / "app.xlsx", head, rows)
    web_file = _web_file({"code": head.code, "doc_date": "2026-11-14", "customer": head.customer, "phone": head.phone,
                          "contact": head.contact, "address": head.address},
                         [dataclasses.asdict(r) for r in rows], tmp_path / "web.xlsx")
    app_note, web_note = read_delivery_note(app_file), read_delivery_note(web_file)
    assert web_note == app_note
    assert (web_note.code, web_note.customer_name, web_note.doc_date) == ("PX261114-093015", "Công ty A", date(2026, 11, 14))
    assert [(ln.product_code, ln.location_id, ln.qty, ln.unit_price) for ln in web_note.lines] == [
        ("SP001", MAIN, 10, 512500.5), ("SP001", OFFICE, 3, 512500.5), ("SP002", MAIN, 2.5, None)]
    assert not web_note.warnings

    # cell by cell, merged ranges, widths: the same sheet
    a, w = openpyxl.load_workbook(app_file).active, openpyxl.load_workbook(web_file).active
    assert w.title == a.title == "出库单"
    cells = lambda ws: {(c.row, c.column): c.value for row in ws.iter_rows() for c in row if c.value not in (None, "")}  # noqa: E731
    assert cells(w) == cells(a)
    assert sorted(map(str, w.merged_cells.ranges)) == sorted(map(str, a.merged_cells.ranges))
    assert {k: v.width for k, v in w.column_dimensions.items()} == {k: v.width for k, v in a.column_dimensions.items()}
    assert w["I8"].number_format == a["I8"].number_format == "#,##0"
    assert w["A1"].font.b and w["A1"].font.sz == 16


def test_a_web_file_dropped_in_the_folder_takes_each_place_once(conn, ws, goods, tmp_path):
    paint, sand = goods
    data = _input(paint, sand)
    web = _web_rows(conn, data, tmp_path)
    _web_file({"code": "PX261114-093015", "doc_date": "2026-11-14", "customer": "Công ty A", "phone": "0900 000 001",
               "contact": "", "address": ""}, web, ws.deliveries / "PhieuXuat_PX261114-093015.xlsx")
    deliveries.scan(conn, ws)
    levels = stock_levels(conn, by_location=True)
    assert (levels[(paint, MAIN)], levels[(paint, OFFICE)], levels[(sand, MAIN)]) == (40, 5, 17.5)
    doc = conn.execute("SELECT * FROM documents WHERE kind = 'delivery'").fetchone()
    assert (doc["code"], doc["location_set"], doc["status"]) == ("PX261114-093015", 1, "active")
    amounts = sorted(r[0] for r in conn.execute("SELECT amount FROM document_lines WHERE document_id = ? AND amount IS NOT NULL",
                                                (doc["id"],)))
    assert amounts == [1537501.5, 5125005]
    assert deliveries.pending_count(conn) == 0 and deliveries.unplaced_count(conn) == 0
    deliveries.scan(conn, ws)  # read again: nothing more is taken
    assert stock_levels(conn, by_location=True) == levels
