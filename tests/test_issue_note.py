"""Phiếu xuất kho (14/11/2026): the app writes a stock issue note shaped like a delivery note and records it at once;
the file read again never counts twice; a product taken from both places is two lines with their own place."""

from datetime import date, datetime

import pytest

from dibekho import db
from dibekho.core import backup, catalog, deliveries, issues, reset, undo
from dibekho.core.issues import IssueInput, IssueLineInput
from dibekho.core.stock import MAIN, OFFICE, close_document, is_mixed, set_location, stock_count, stock_levels
from dibekho.excel.delivery_note import read_delivery_note
from tests.conftest import make_note

NOW = datetime(2026, 11, 14, 9, 30, 15)


@pytest.fixture
def goods(conn):
    with db.transaction(conn):
        paint = catalog.create_product(conn, "Sơn chống thấm", "防水涂料", "20KG/thùng", "thùng", "Sơn")
        sand = catalog.create_product(conn, "Keo cố định cát", "固沙剂", "5KG", "can", "Keo")
        stock_count(conn, date(2026, 11, 1), {(paint, MAIN): 50, (paint, OFFICE): 8, (sand, MAIN): 20})
    return paint, sand


def places(conn, pid):
    levels = stock_levels(conn, by_location=True)
    return levels.get((pid, MAIN), 0), levels.get((pid, OFFICE), 0)


def note_for(paint, sand, **kw):
    return IssueInput(date(2026, 11, 14), kw.get("customer", "Công ty A"), phone="0900 000 001",
                      contact="Anh B", address="1 Đường X", lines=[
                          IssueLineInput(paint, qty_main=10, qty_office=3, unit_price=500000, note="giao sáng"),
                          IssueLineInput(sand, qty_main=2, unit_price=120000),
                      ])


def test_saving_takes_each_place_at_once_and_counts_the_revenue(conn, ws, goods):
    paint, sand = goods
    doc_id, path = issues.save(conn, ws, note_for(paint, sand), now=NOW)
    assert places(conn, paint) == (40, 5)
    assert places(conn, sand) == (18, 0)
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    assert (doc["kind"], doc["code"], doc["status"], doc["location_set"]) == ("delivery", "PX261114-093015",
                                                                              "active", 1)
    assert is_mixed(conn, doc_id)
    amounts = sorted(r[0] for r in conn.execute("SELECT amount FROM document_lines WHERE document_id = ?",
                                                (doc_id,)))
    assert amounts == [240000, 1500000, 5000000]
    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (doc["customer_id"],)).fetchone()
    assert customer["name"] == "Công ty A"
    assert path.parent == ws.output / issues.FOLDER and path.exists()
    assert deliveries.unplaced_count(conn) == 0
    assert deliveries.pending_count(conn) == 0


def test_the_file_reads_back_with_codes_places_and_prices(conn, ws, goods):
    paint, sand = goods
    _, path = issues.save(conn, ws, note_for(paint, sand), now=NOW)
    note = read_delivery_note(path)
    assert note.code == "PX261114-093015" and note.doc_date == date(2026, 11, 14)
    assert (note.customer_name, note.phone, note.contact, note.address) == ("Công ty A", "0900 000 001", "Anh B",
                                                                              "1 Đường X")
    got = [(ln.product_code, ln.location_id, ln.qty, ln.unit_price, ln.amount, ln.note) for ln in note.lines]
    assert got == [("SP001", MAIN, 10, 500000, 5000000, "giao sáng"), ("SP001", OFFICE, 3, 500000, 1500000, "giao sáng"),
                   ("SP002", MAIN, 2, 120000, 240000, "")]
    assert note.lines[0].name_zh == "防水涂料" and note.lines[0].name_vi == "Sơn chống thấm"
    assert note.total == 6740000
    assert not note.warnings


def test_scanning_again_or_dropping_the_copy_into_the_folder_never_counts_twice(conn, ws, goods):
    paint, sand = goods
    _, path = issues.save(conn, ws, note_for(paint, sand), now=NOW)
    deliveries.scan(conn, ws)
    (ws.deliveries / "ban-sao.xlsx").write_bytes(path.read_bytes())
    deliveries.scan(conn, ws)
    assert places(conn, paint) == (40, 5)
    assert conn.execute("SELECT COUNT(*) FROM documents WHERE kind = 'delivery'").fetchone()[0] == 1
    assert deliveries.pending_count(conn) == 0


def test_a_file_from_elsewhere_is_recorded_by_product_code_even_if_renamed(conn, ws, goods):
    """The web page writes the same file; the app reads it by code, the product may have been renamed."""
    paint, sand = goods
    from dibekho.excel.issue_note import IssueHead, IssueRow, write_issue_note

    write_issue_note(ws.deliveries / "tu-web.xlsx", IssueHead("PX261114-120000", date(2026, 11, 14), "Khách Mẫu"),
                     [IssueRow("SP002", "Tên cũ của keo", "", "5KG", "can", 4, OFFICE, None, None)])
    with db.transaction(conn):
        catalog.update_product(conn, sand, name_vi="Keo cát mới")
    deliveries.scan(conn, ws)
    assert places(conn, sand) == (20, -4)
    assert deliveries.pending_count(conn) == 0 and deliveries.unplaced_count(conn) == 0


def test_cancel_gives_back_each_place(conn, ws, goods):
    paint, sand = goods
    doc_id, _ = issues.save(conn, ws, note_for(paint, sand), now=NOW)
    with db.transaction(conn):
        close_document(conn, doc_id)
    assert places(conn, paint) == (50, 8) and places(conn, sand) == (20, 0)


def test_a_mixed_note_cannot_be_moved_to_one_place_but_a_single_place_one_can(conn, ws, goods):
    paint, sand = goods
    doc_id, _ = issues.save(conn, ws, note_for(paint, sand), now=NOW)
    with pytest.raises(ValueError):
        with db.transaction(conn):
            set_location(conn, doc_id, OFFICE)
    single = IssueInput(date(2026, 11, 14), "Công ty A", lines=[IssueLineInput(sand, qty_main=1)])
    doc2, _ = issues.save(conn, ws, single, now=datetime(2026, 11, 14, 10, 0, 0))
    with db.transaction(conn):
        set_location(conn, doc2, OFFICE)
    assert places(conn, sand) == (18, -1)
    line_place = conn.execute("SELECT location_id FROM document_lines WHERE document_id = ?", (doc2,)).fetchone()[0]
    assert line_place == OFFICE


def test_read_again_keeps_the_places_of_the_file(conn, ws, goods):
    paint, sand = goods
    doc_id, _ = issues.save(conn, ws, note_for(paint, sand), now=NOW)
    deliveries.reread_document(conn, ws, doc_id)
    deliveries.scan(conn, ws)
    assert places(conn, paint) == (40, 5) and places(conn, sand) == (18, 0)
    assert deliveries.unplaced_count(conn) == 0


def test_undo_takes_the_note_back_and_the_scan_does_not_record_it_again(conn, ws, goods, tmp_path):
    """Local data: Hoàn tác puts the old database back; the copy in the folder must leave it."""
    paint, sand = goods
    path_db = ws.db_path
    backup.snapshot(conn, path_db)  # the fixture data as a real file
    conn = db.connect(path_db)
    try:
        undo.mark(conn, ws, "issue_note")
        issues.save(conn, ws, note_for(paint, sand), now=NOW)
        before = issues.known_issue_files(conn, ws)
        assert len(before) == 1
        conn.close()
        undo.undo(ws, undo.latest(ws))
        conn = db.connect(path_db)
        assert issues.after_undo(conn, ws, before) == 1
        deliveries.scan(conn, ws)
        assert places(conn, paint) == (50, 8)
        assert conn.execute("SELECT COUNT(*) FROM documents WHERE kind = 'delivery'").fetchone()[0] == 0
        assert list((ws.output / issues.FOLDER / issues.UNDONE).glob("*.xlsx"))
    finally:
        conn.close()


def test_reset_stock_reads_the_issue_notes_again(conn, ws, goods):
    paint, sand = goods
    issues.save(conn, ws, note_for(paint, sand), now=NOW)
    reset.reset_stock(conn, ws)
    deliveries.scan(conn, ws)
    assert conn.execute("SELECT COUNT(*) FROM documents WHERE kind = 'delivery' AND status = 'active'"
                        ).fetchone()[0] == 1
    assert deliveries.unplaced_count(conn) == 0


def test_problems_and_prices(conn, ws, goods):
    paint, sand = goods
    empty = IssueInput(date(2026, 11, 14), "", lines=[IssueLineInput(paint), IssueLineInput(paint, 1)])
    keys = [k for k, _ in issues.problems(conn, empty)]
    assert keys == ["issue.need_customer"]
    twice = IssueInput(date(2026, 11, 14), "A", lines=[IssueLineInput(paint, 1), IssueLineInput(paint, 2)])
    assert [k for k, _ in issues.problems(conn, twice)] == ["issue.same_product_twice"]
    assert issues.problems(conn, IssueInput(date(2026, 11, 14), "A")) == [("issue.need_lines", {})]
    short = issues.short_of(conn, IssueInput(date(2026, 11, 14), "A", lines=[IssueLineInput(paint, 60, 9)]))
    assert short == [(paint, MAIN, 60, 50), (paint, OFFICE, 9, 8)]
    assert issues.last_price(conn, "Công ty A", paint) is None
    issues.save(conn, ws, note_for(paint, sand), now=NOW)
    assert issues.last_price(conn, "Công ty A", paint) == 500000
    assert issues.last_price(conn, "Khách khác", paint) == 500000


def test_customer_notes_without_the_new_columns_read_as_before(tmp_path):
    note = read_delivery_note(make_note(tmp_path / "a.xlsx"))
    assert all(ln.product_code == "" and ln.location_id is None for ln in note.lines)


def test_a_place_cell_that_says_something_else_stops_the_note(tmp_path):
    from dibekho.excel.delivery_note import DeliveryNoteError
    from dibekho.excel.issue_note import IssueHead, IssueRow, write_issue_note

    path = write_issue_note(tmp_path / "x.xlsx", IssueHead("PX1", date(2026, 11, 14), "A"),
                            [IssueRow("SP001", "Sơn", "", "", "", 1, MAIN)])
    import openpyxl

    wb = openpyxl.load_workbook(path)
    wb.active.cell(row=8, column=7, value="Kho Hải Phòng")
    wb.save(path)
    with pytest.raises(DeliveryNoteError, match="Lấy từ kho"):
        read_delivery_note(path)
