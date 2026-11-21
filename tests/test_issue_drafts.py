"""Đơn nháp (customer's request 21/11/2026): the stock issue note's file with NHÁP in the title and its own code, in
output/phieu-xuat/nhap/; nothing recorded (stock, revenue, products). «Xuất từ phiếu nháp…» reads it back; once it is a
real note the draft goes to da-chot/. The scan never records a draft dropped into the notes folder."""

import shutil
from datetime import date

import openpyxl
import pytest

from dibekho import db
from dibekho.core import catalog, deliveries, issues
from dibekho.core.issues import IssueInput, IssueLineInput
from dibekho.core.receipts import NewProduct
from dibekho.core.stock import MAIN, OFFICE, stock_count, stock_levels
from dibekho.excel.issue_note import MONEY_CNY, TITLE_DRAFT, is_draft_title


@pytest.fixture
def goods(conn):
    with db.transaction(conn):
        paint = catalog.create_product(conn, "Sơn chống thấm", "防水涂料", "20KG/thùng", "thùng", "Sơn")
        sand = catalog.create_product(conn, "Keo cố định cát", "固沙剂", "5KG", "can", "Keo")
        stock_count(conn, date(2026, 11, 1), {(paint, MAIN): 50, (paint, OFFICE): 8, (sand, MAIN): 20})
    return paint, sand


def counts(conn):
    return (conn.execute("SELECT COUNT(*) FROM documents WHERE kind = 'delivery'").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
            sorted(stock_levels(conn, by_location=True).items()))


def draft_for(paint, sand, **kw):
    return IssueInput(date(2026, 11, 20), "Công ty A", phone="0900 000 001", contact="Anh B", address="1 Đường X",
                      tax_code="0101234567", email="a@example.com", lines=[
                          IssueLineInput(paint, qty_main=10, qty_office=3, unit_price=500000, note="giao sáng"),
                          IssueLineInput(sand, qty_main=2, unit_price=120000),
                          IssueLineInput(None, qty_office=4, unit_price=9000,
                                         new=NewProduct("Băng keo mới", "胶带", "5cm", unit="cuộn")),
                      ], **kw)


def test_a_draft_records_nothing_and_reads_back(conn, ws, goods):
    paint, sand = goods
    before = counts(conn)
    path = issues.save_draft(conn, ws, draft_for(paint, sand))
    assert counts(conn) == before  # no stock, no revenue, no product, no customer
    assert path == issues.drafts_folder(ws) / "PhieuXuat_NHAP_N1.xlsx"
    sheet = openpyxl.load_workbook(path).active
    assert sheet["A4"].value == TITLE_DRAFT and is_draft_title(TITLE_DRAFT)

    code, data = issues.load_draft(conn, path)
    assert code == "N1"
    assert (data.doc_date, data.customer_name, data.phone, data.contact, data.address, data.tax_code, data.email) == (
        date(2026, 11, 20), "Công ty A", "0900 000 001", "Anh B", "1 Đường X", "0101234567", "a@example.com")
    got = [(ln.product_id, ln.qty_main, ln.qty_office, ln.unit_price, ln.note) for ln in data.lines]
    assert got[:2] == [(paint, 10, 3, 500000, "giao sáng"), (sand, 2, 0, 120000, "")]
    new = data.lines[2]
    assert (new.product_id, new.qty_main, new.qty_office, new.unit_price) == (None, 0, 4, 9000)
    assert (new.new.name_vi, new.new.name_zh, new.new.spec) == ("Băng keo mới", "胶带", "5cm")


def test_saved_again_keeps_its_code_and_numbers_go_on(conn, ws, goods):
    paint, sand = goods
    first = issues.save_draft(conn, ws, draft_for(paint, sand))
    second = issues.save_draft(conn, ws, draft_for(paint, sand))
    assert second.name == "PhieuXuat_NHAP_N2.xlsx"
    _, data = issues.load_draft(conn, first)
    data.lines[0].qty_main = 1
    assert issues.save_draft(conn, ws, data, first) == first
    assert issues.load_draft(conn, first)[1].lines[0].qty_main == 1
    issues.close_draft(ws, first)
    assert not first.exists() and (issues.drafts_folder(ws) / "da-chot" / first.name).exists()
    assert issues.new_draft_code(ws) == "N3"  # a closed draft's number is not reused


def test_turned_into_a_real_note_it_counts_once(conn, ws, goods):
    paint, sand = goods
    path = issues.save_draft(conn, ws, draft_for(paint, sand))
    _, data = issues.load_draft(conn, path)
    doc_id, real = issues.save(conn, ws, data)
    issues.close_draft(ws, path)
    doc = conn.execute("SELECT code, status FROM documents WHERE id = ?", (doc_id,)).fetchone()
    assert doc[:] == ("A1", "active")
    levels = stock_levels(conn, by_location=True)
    assert (levels[(paint, MAIN)], levels[(paint, OFFICE)], levels[(sand, MAIN)]) == (40, 5, 18)
    tape = conn.execute("SELECT id FROM products WHERE name_vi = 'Băng keo mới'").fetchone()
    assert tape is not None  # the ★ new product is made only now
    assert not is_draft_title(openpyxl.load_workbook(real).active["A4"].value)


def test_a_yuan_draft_stays_in_yuan(conn, ws, goods):
    paint, sand = goods
    path = issues.save_draft(conn, ws, IssueInput(date(2026, 11, 20), "Công ty A", currency="CNY", fx_rate=3800.0,
                                                  lines=[IssueLineInput(paint, qty_main=3, unit_price=6182.98)]))
    sheet = openpyxl.load_workbook(path).active
    assert [c.value for row in sheet.iter_rows() for c in row if c.number_format == MONEY_CNY
            and isinstance(c.value, float)][:1] == [6182.98]
    _, data = issues.load_draft(conn, path)
    assert (data.currency, data.lines[0].unit_price) == ("CNY", 6182.98)


def test_a_draft_dropped_into_the_notes_folder_is_never_recorded(conn, ws, goods):
    paint, sand = goods
    path = issues.save_draft(conn, ws, draft_for(paint, sand))
    before = counts(conn)
    shutil.copy2(path, ws.deliveries / path.name)
    deliveries.scan(conn, ws)
    assert counts(conn) == before
    row = conn.execute("SELECT status, message FROM scanned_files").fetchone()
    assert row["status"] == "error" and "NHÁP" in row["message"]


def test_a_real_note_is_not_a_draft(conn, ws, goods):
    paint, sand = goods
    _, real = issues.save(conn, ws, IssueInput(date(2026, 11, 20), "Công ty A", lines=[IssueLineInput(sand, qty_main=1)]))
    with pytest.raises(ValueError):
        issues.load_draft(conn, real)
    with pytest.raises(ValueError):
        issues.save_draft(conn, ws, IssueInput(date(2026, 11, 20), ""))
