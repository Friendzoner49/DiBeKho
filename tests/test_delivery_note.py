from datetime import date

import pytest

from dibekho.excel.delivery_note import DeliveryNoteError, NotDeliveryNote, read_delivery_note
from tests.conftest import SAMPLES, make_note


def test_reads_header_and_lines(tmp_path):
    note = read_delivery_note(make_note(tmp_path / "a.xlsx", code="076", day="10/09/2026"))
    assert note.code == "076"
    assert note.code_norm == "76"
    assert note.doc_date == date(2026, 9, 10)
    assert note.customer_name == "Công ty A"
    assert note.phone == "0901 234 567"
    assert note.contact == "Anh B"
    assert note.address == "1 Đường X, Hà Nội"
    [line] = note.lines
    assert line.qty == 3
    assert line.name_zh == "背水涂"
    assert line.name_vi.startswith("vữa chống thấm")
    assert line.spec == "10KG/thùng"


def test_layout_shift_does_not_matter(tmp_path):
    a = read_delivery_note(make_note(tmp_path / "a.xlsx"))
    b = read_delivery_note(make_note(tmp_path / "b.xlsx", extra_top_row=True))
    assert [(ln.key, ln.qty) for ln in a.lines] == [(ln.key, ln.qty) for ln in b.lines]


def test_fee_rows_without_quantity_are_skipped(tmp_path):
    path = make_note(tmp_path / "a.xlsx", extra_rows=[[None, "Phí vận chuyển", None, None, None, 190000]])
    note = read_delivery_note(path)
    assert len(note.lines) == 1
    assert note.skipped_rows == ["Phí vận chuyển"]


def test_note_is_kept_but_quantity_column_wins(tmp_path):
    path = make_note(tmp_path / "a.xlsx", lines=[("FS-101\nMatit", "10KG/thùng", 50, "gửi đi 2 thùng còn lại")])
    [line] = read_delivery_note(path).lines
    assert line.qty == 50
    assert line.note == "gửi đi 2 thùng còn lại"


def test_missing_date_is_an_error(tmp_path):
    with pytest.raises(DeliveryNoteError):
        read_delivery_note(make_note(tmp_path / "a.xlsx", day=""))


def test_other_workbooks_are_rejected(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.append(["Bảng thống kê"])
    wb.save(tmp_path / "x.xlsx")
    with pytest.raises(NotDeliveryNote):
        read_delivery_note(tmp_path / "x.xlsx")


@pytest.mark.skipif(not (SAMPLES / "phieu-mau-2.xlsx").exists(), reason="customer samples not present")
def test_real_samples():
    n1 = read_delivery_note(SAMPLES / "phieu-mau-1.xlsx")
    n2 = read_delivery_note(SAMPLES / "phieu-mau-2.xlsx")
    n3 = read_delivery_note(SAMPLES / "phieu-mau-3.xlsx")
    assert (n1.code_norm, n1.doc_date, len(n1.lines)) == ("113", date(2026, 10, 1), 1)
    assert (n2.code_norm, n2.doc_date, len(n2.lines)) == ("74", date(2026, 9, 9), 13)
    assert sum(ln.qty for ln in n2.lines) == 167  # matches 'Tổng số lượng' printed on the note
    assert (n3.code_norm, n3.doc_date, len(n3.lines)) == ("76", date(2026, 9, 10), 2)
    assert n3.skipped_rows == ["Phí vận chuyển"]
    # same product written with different spacing on two notes -> same key
    assert n2.lines[7].key == n3.lines[1].key
    with pytest.raises(NotDeliveryNote):
        read_delivery_note(SAMPLES / "danh-muc-mau.xlsx")
