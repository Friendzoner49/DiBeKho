"""A second office (user, 25/11/2026): 3 = Văn phòng Bắc Ninh; 2 (Văn phòng until 0.6.6) is Văn phòng Hà Nội and keeps
everything recorded there. Kiểm kê counts one place at a time; Phiếu xuất kho takes from any of the three."""

import os
from datetime import date

import openpyxl
import pytest

from dibekho import db, i18n
from dibekho.core import catalog, deliveries, issues, queries
from dibekho.core.issues import IssueInput, IssueLineInput
from dibekho.core.stock import (BAC_NINH, LOCATION_CODES, LOCATIONS, MAIN, OFFICE, close_document, set_location,
                                stock_count, stock_levels, stock_table, transfer)
from dibekho.core.stock import Line
from dibekho.excel import master_data
from dibekho.excel.delivery_note import _place, _places, read_delivery_note
from dibekho.excel.issue_note import PLACES, places_text

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def vietnamese():
    i18n.set_language("vi")


@pytest.fixture
def goods(conn):
    with db.transaction(conn):
        paint = catalog.create_product(conn, "Sơn chống thấm", "防水涂料", "20KG/thùng", "thùng", "Sơn")
        sand = catalog.create_product(conn, "Keo cố định cát", "固沙剂", "5KG", "can", "Keo")
        stock_count(conn, date(2026, 11, 20), {(paint, MAIN): 50, (paint, OFFICE): 8, (paint, BAC_NINH): 6,
                                               (sand, MAIN): 20})
    return paint, sand


def places(conn, pid):
    levels = stock_levels(conn, by_location=True)
    return tuple(levels.get((pid, loc), 0) for loc in LOCATIONS)


def test_three_places_with_their_names_in_every_language():
    assert LOCATIONS == (1, 2, 3) and LOCATION_CODES[BAC_NINH] == "office_bn"
    names = {}
    for lang in ("vi", "en", "zh"):
        i18n.set_language(lang)
        names[lang] = [i18n.t(f"loc.{LOCATION_CODES[loc]}") for loc in LOCATIONS]
    assert names["vi"] == ["Kho tổng", "Văn phòng Hà Nội", "Văn phòng Bắc Ninh"]
    assert names["zh"] == ["总仓", "河内办公室", "北宁办公室"]
    assert len(set(names["en"])) == 3


def test_the_migration_adds_bac_ninh_and_keeps_what_was_at_the_office(tmp_path):
    """A 0.6.6 database (schema 12): goods at Văn phòng stay there, now shown as Văn phòng Hà Nội."""
    path = tmp_path / "old.sqlite"
    conn = db.connect(path)
    with db.transaction(conn):
        pid = catalog.create_product(conn, "Sơn", "", "", "thùng", "")
        stock_count(conn, date(2026, 11, 1), {(pid, OFFICE): 7})
        conn.execute("DELETE FROM locations WHERE id = 3")
    conn.execute("PRAGMA user_version = 12")
    conn.close()
    conn = db.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.schema_version() >= 13
    assert dict(conn.execute("SELECT id, code FROM locations").fetchall()) == {1: "main", 2: "office", 3: "office_bn"}
    assert places(conn, pid) == (0, 7, 0)
    conn.close()


# ---- the 'Lấy từ kho' cell --------------------------------------------------------------------------------

def test_the_place_cell_reads_old_and_new_names():
    assert PLACES == {1: "Kho tổng 总仓", 2: "Văn phòng Hà Nội 河内办公室", 3: "Văn phòng Bắc Ninh 北宁办公室"}
    assert _place("Văn phòng 办公室") == OFFICE  # notes written before 25/11/2026
    assert _place("Văn phòng") == OFFICE and _place("办公室") == OFFICE
    assert _place("Văn phòng Hà Nội 河内办公室") == OFFICE
    assert _place("Văn phòng Bắc Ninh 北宁办公室") == BAC_NINH
    assert _place("van phong bac ninh") == BAC_NINH and _place("北宁办公室") == BAC_NINH
    assert _place("Kho tổng 总仓") == MAIN
    assert _place("Văn phòng Hà Nội Bắc Ninh") is None  # two offices in one name: not guessed
    text = places_text([(MAIN, 3), (OFFICE, 2), (BAC_NINH, 1)])
    assert _places(text, 6) == ((MAIN, 3), (OFFICE, 2), (BAC_NINH, 1))
    assert _places("Kho tổng 总仓: 3; Văn phòng 办公室: 2", 5) == ((MAIN, 3), (OFFICE, 2))


# ---- Phiếu xuất kho ---------------------------------------------------------------------------------------

def three_places_note(paint, sand):
    return IssueInput(date(2026, 11, 25), "Công ty A", lines=[
        IssueLineInput(paint, qty_main=10, qty_office=3, unit_price=500000, qty_bn=2),
        IssueLineInput(sand, qty_bn=1, unit_price=120000),
    ])


def test_an_issue_note_takes_from_the_three_places_and_reads_back(conn, ws, goods):
    paint, sand = goods
    doc_id, path = issues.save(conn, ws, three_places_note(paint, sand))
    assert places(conn, paint) == (40, 5, 4)
    assert places(conn, sand) == (20, 0, -1)
    note = read_delivery_note(path)
    assert [ln.places for ln in note.lines] == [((MAIN, 10), (OFFICE, 3), (BAC_NINH, 2)), ((BAC_NINH, 1),)]
    deliveries.scan(conn, ws)  # the file in the folder is the same note: nothing twice
    assert places(conn, paint) == (40, 5, 4)
    code, again = issues.load(conn, doc_id)
    assert [(ln.qty_main, ln.qty_office, ln.qty_bn) for ln in again.lines] == [(10, 3, 2), (0, 0, 1)]
    with db.transaction(conn):
        close_document(conn, doc_id)
    assert places(conn, paint) == (50, 8, 6) and places(conn, sand) == (20, 0, 0)


def test_a_note_from_bac_ninh_only_is_at_bac_ninh_and_can_be_moved(conn, ws, goods):
    paint, sand = goods
    doc_id, _ = issues.save(conn, ws, IssueInput(date(2026, 11, 25), "Công ty A",
                                                 lines=[IssueLineInput(paint, qty_bn=2)]))
    doc = conn.execute("SELECT location_id FROM documents WHERE id = ?", (doc_id,)).fetchone()
    assert doc["location_id"] == BAC_NINH
    with db.transaction(conn):
        set_location(conn, doc_id, OFFICE)
    assert places(conn, paint) == (50, 6, 6)


def test_editing_a_note_moves_goods_between_the_offices(conn, ws, goods):
    paint, sand = goods
    doc_id, _ = issues.save(conn, ws, three_places_note(paint, sand))
    edited = IssueInput(date(2026, 11, 25), "Công ty A", lines=[IssueLineInput(paint, qty_office=1, qty_bn=4)])
    issues.edit(conn, ws, doc_id, edited)
    assert places(conn, paint) == (50, 7, 2) and places(conn, sand) == (20, 0, 0)


def test_short_of_names_bac_ninh(conn, goods):
    paint, sand = goods
    short = issues.short_of(conn, IssueInput(date(2026, 11, 25), "Công ty A",
                                             lines=[IssueLineInput(paint, qty_bn=9)]))
    assert short == [(paint, BAC_NINH, 9, 6)]


def test_a_draft_keeps_the_bac_ninh_quantities(conn, ws, goods):
    paint, sand = goods
    path = issues.save_draft(conn, ws, three_places_note(paint, sand))
    _, data = issues.load_draft(conn, path)
    assert [(ln.qty_main, ln.qty_office, ln.qty_bn) for ln in data.lines] == [(10, 3, 2), (0, 0, 1)]


# ---- Kiểm kê, chuyển hàng, Tồn kho ------------------------------------------------------------------------

def test_counting_one_place_leaves_the_other_two(conn, goods):
    paint, sand = goods
    with db.transaction(conn):
        stock_count(conn, date(2026, 11, 25), {(paint, BAC_NINH): 4})
    assert places(conn, paint) == (50, 8, 4)


def test_goods_carried_between_the_two_offices(conn, goods):
    paint, sand = goods
    with db.transaction(conn):
        doc = transfer(conn, date(2026, 11, 25), OFFICE, BAC_NINH, [Line(paint, 5)])
    assert places(conn, paint) == (50, 3, 11)
    with db.transaction(conn):
        close_document(conn, doc)
    assert places(conn, paint) == (50, 8, 6)


def test_the_stock_page_and_the_product_have_bac_ninh(conn, goods):
    paint, sand = goods
    row = next(r for r in stock_table(conn) if r["id"] == paint)
    assert (row["stock"], row["stock_main"], row["stock_office"], row["stock_bn"]) == (64, 50, 8, 6)
    p = queries.product(conn, paint)
    assert (p["stock_main"], p["stock_office"], p["stock_bn"]) == (50, 8, 6)


def test_master_data_shows_three_places_and_old_files_still_import(conn, goods, tmp_path):
    paint, sand = goods
    path = master_data.export(tmp_path / "goc.xlsx", conn)
    ws3 = openpyxl.load_workbook(path).worksheets[2]
    header = [c.value for c in ws3[master_data.HEADER_ROW]]
    assert header[5:9] == ["Kho tổng", "Văn phòng Hà Nội", "Văn phòng Bắc Ninh", "Ghi chú tồn kho"]
    with db.transaction(conn):
        catalog.update_product(conn, paint, stock_note="2 thùng móp")
    path = master_data.export(tmp_path / "goc2.xlsx", conn)
    _, _, stock = master_data.read(path)
    assert sorted((st.stock, st.note) for st in stock) == [(20, ""), (64, "2 thùng móp")]
    # a file of 0.6.6: Kho tổng | Văn phòng | note
    wb = openpyxl.load_workbook(path)
    ws3 = wb.worksheets[2]
    ws3.delete_cols(8)
    wb.save(tmp_path / "cu.xlsx")
    _, _, stock = master_data.read(tmp_path / "cu.xlsx")
    assert sorted((st.stock, st.note) for st in stock) == [(20, ""), (64, "2 thùng móp")]


# ---- the screens -------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_count_page_counts_the_place_picked_and_asks_before_dropping_numbers(app, ws, monkeypatch):
    import dibekho.ui.count_page as count_mod
    from tests.test_locations import window

    asked = []
    monkeypatch.setattr(count_mod, "ask", lambda *a, **k: asked.append(a[1]) or True)
    monkeypatch.setattr(count_mod, "info", lambda *a, **k: None)
    ctx, win = window(ws)
    with db.transaction(ctx.conn):
        paint = catalog.create_product(ctx.conn, "Sơn chống thấm", "防水涂料", "20KG/thùng", "thùng", "Sơn")
        stock_count(ctx.conn, date(2026, 11, 20), {(paint, MAIN): 50, (paint, BAC_NINH): 6})
    count = win.stack.widget(4)
    win.nav.setCurrentRow(win.stack.indexOf(count))
    app.processEvents()
    count.refresh()
    assert [count.place.itemData(i) for i in range(count.place.count())] == list(LOCATIONS)
    row = lambda: next(r for r in range(count.table.rowCount())  # noqa: E731
                       if count.table.item(r, 0).data(count_mod.Qt.UserRole) == paint)
    assert count.table.horizontalHeaderItem(count_mod.COUNT_COL).text().endswith("Kho tổng")
    assert count.table.item(row(), count_mod.APP_COL).key == 50
    count.table.item(row(), count_mod.COUNT_COL).setText("48")
    count.place.setCurrentIndex(count.place.findData(BAC_NINH))  # numbers typed: asked first, then dropped
    assert asked and "Kho tổng" in asked[-1]
    assert "Bắc Ninh" in count.table.horizontalHeaderItem(count_mod.APP_COL).text().replace("\n", " ")
    assert count.table.item(row(), count_mod.APP_COL).key == 6 and count.table.item(row(), count_mod.COUNT_COL).text() == ""
    count.table.item(row(), count_mod.COUNT_COL).setText("4")
    assert count.table.item(row(), count_mod.DIFF_COL).text() == "-2"
    count.save()
    assert "Văn phòng Bắc Ninh" in asked[-1]
    assert places(ctx.conn, paint) == (50, 0, 4)
    win.close()
