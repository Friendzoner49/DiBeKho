"""MST and e-mail of a customer (customer's request 18/11/2026: the new delivery note template has 'MST 税号' and
'email邮箱'): read from a note, written on a stock issue note and read back, edited by the user, kept by a merge, a
note read again and the master-data file."""

from datetime import date

import openpyxl
import pytest

from dibekho import db
from dibekho.core import catalog, deliveries, issues
from dibekho.core.issues import IssueInput, IssueLineInput
from dibekho.core.stock import MAIN, stock_count
from dibekho.core.text import match_key
from dibekho.excel.delivery_note import read_delivery_note
from dibekho.excel.issue_note import IssueHead, IssueRow, write_issue_note
from tests.conftest import make_note


@pytest.fixture
def paint(conn):
    with db.transaction(conn):
        pid = catalog.create_product(conn, "Sơn chống thấm", "防水涂料", "20KG/thùng", "thùng", "Sơn")
        stock_count(conn, date(2026, 11, 1), {(pid, MAIN): 50})
    return pid


def _template_note(path, tax="", email="", phone="", contact=""):
    """The new template's head: MST / email on their own row, between phone and contact (as the shop's file)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A4"] = "销售单 PHIẾU GIAO HÀNG"
    ws["A5"] = "客户名称 ( Tên khách hàng ):  Công ty A"
    ws["C5"] = "联系电话 ( Điện thoại liên hệ ): " + phone
    ws["F5"] = "订货单号 ( Mã đơn hàng )：900"
    ws["C6"] = "MST 税号： " + tax
    ws["F6"] = "email邮箱：" + email
    ws["C7"] = "联系人( Người liên hệ )：" + contact
    ws["F7"] = "送货日期 ( Ngày giao hàng )：22-06-2026"
    ws["A8"] = "地址( Địa chỉ):  "
    for c, text in enumerate(["编 号\nSTT", "商 品 全 名\nTên hàng", "规格\nQUY CÁCH", "数 量\nSố lượng"], 1):
        ws.cell(9, c, text)
    ws.append([1, "防水涂料\nSơn chống thấm", "20KG/thùng", 2])
    wb.save(path)
    return path


def test_the_new_template_reads_mst_and_email(tmp_path):
    note = read_delivery_note(_template_note(tmp_path / "a.xlsx", "0101234567", "a@example.com", "0900 000 001",
                                             "Khách Mẫu"))
    assert (note.tax_code, note.email, note.phone, note.contact) == ("0101234567", "a@example.com", "0900 000 001",
                                                                     "Khách Mẫu")


def test_empty_cells_of_the_new_template_read_as_empty(tmp_path):
    note = read_delivery_note(_template_note(tmp_path / "a.xlsx"))
    assert (note.phone, note.tax_code, note.email, note.contact, note.address) == ("", "", "", "", "")
    assert note.customer_name == "Công ty A" and note.code == "900" and len(note.lines) == 1


def test_a_tax_code_typed_as_a_number_in_its_own_cell(tmp_path):
    path = _template_note(tmp_path / "a.xlsx")
    wb = openpyxl.load_workbook(path)
    wb.active["C6"], wb.active["D6"] = "MST 税号：", 101234567
    wb.save(path)
    assert read_delivery_note(path).tax_code == "101234567"


def test_an_older_note_without_the_cells_reads_as_before(tmp_path):
    note = read_delivery_note(make_note(tmp_path / "old.xlsx"))
    assert (note.tax_code, note.email) == ("", "")
    assert note.phone and note.contact and note.address


def test_an_mst_inside_a_product_name_is_not_a_label(tmp_path):
    path = _template_note(tmp_path / "a.xlsx", "0101234567")
    wb = openpyxl.load_workbook(path)
    wb.active["B10"] = "Màng AMST 3mm"
    wb.save(path)
    assert read_delivery_note(path).tax_code == "0101234567"


def test_an_issue_note_carries_them_to_the_customer(conn, ws, paint):
    data = IssueInput(date(2026, 11, 18), "Công ty Mới", phone="0900 000 002", contact="Chị C", address="2 Đường Y",
                      tax_code="0101234567", email="moi@example.com",
                      lines=[IssueLineInput(paint, qty_main=2, unit_price=500000)])
    doc_id, path = issues.save(conn, ws, data)
    note = read_delivery_note(path)
    assert (note.tax_code, note.email, note.contact, note.address) == ("0101234567", "moi@example.com", "Chị C",
                                                                       "2 Đường Y")
    c = conn.execute("SELECT c.* FROM customers c JOIN documents d ON d.customer_id = c.id WHERE d.id = ?",
                     (doc_id,)).fetchone()
    assert (c["name"], c["tax_code"], c["email"]) == ("Công ty Mới", "0101234567", "moi@example.com")


def test_an_issue_note_written_before_the_new_row_still_reads(tmp_path):
    """Issue notes saved before 18/11/2026 had the table header on row 8 and no MST / email row."""
    path = write_issue_note(tmp_path / "x.xlsx", IssueHead("A7", date(2026, 11, 14), "Khách Mẫu", "0900 000 003",
                                                           "Anh B", "1 Đường X"),
                            [IssueRow("SP001", "Sơn", "", "", 1, [(MAIN, 1)])])
    wb = openpyxl.load_workbook(path)
    for rng in list(wb.active.merged_cells.ranges):
        wb.active.unmerge_cells(str(rng))
    wb.active.delete_rows(6)
    wb.save(path)
    note = read_delivery_note(path)
    assert (note.code, note.phone, note.contact, note.address, note.tax_code) == ("A7", "0900 000 003", "Anh B",
                                                                                  "1 Đường X", "")
    assert [ln.qty for ln in note.lines] == [1]


def test_a_note_fills_empty_fields_but_never_overwrites_an_edit(conn):
    with db.transaction(conn):
        cid = catalog.upsert_customer(conn, "Công ty A", "0900 000 001")
        assert conn.execute("SELECT tax_code, email FROM customers WHERE id = ?", (cid,)).fetchone()[:] == ("", "")
        catalog.upsert_customer(conn, "Công ty A", "0900 000 001", tax_code="111", email="a@example.com")
        catalog.update_customer(conn, cid, tax_code="222")
        catalog.upsert_customer(conn, "Công ty A", "0900 000 001", tax_code="333", email="b@example.com")
    assert conn.execute("SELECT tax_code, email FROM customers WHERE id = ?", (cid,)).fetchone()[:] == (
        "222", "a@example.com")


def test_edit_changes_every_field_and_the_phone_key(conn):
    with db.transaction(conn):
        cid = catalog.upsert_customer(conn, "Công ty A", "0900 000 001")
        catalog.update_customer(conn, cid, name="Công ty A mới", phone="0900-000-009", contact="Anh D",
                                address="3 Đường Z", tax_code=" 0109 ", email="x@example.com")
    c = conn.execute("SELECT * FROM customers WHERE id = ?", (cid,)).fetchone()
    assert (c["name"], c["phone"], c["phone_norm"], c["contact"], c["address"], c["tax_code"], c["email"]) == (
        "Công ty A mới", "0900-000-009", "0900000009", "Anh D", "3 Đường Z", "0109", "x@example.com")
    with pytest.raises(ValueError):
        catalog.update_customer(conn, cid, name="  ")


def test_a_phone_or_name_of_another_customer_is_found(conn):
    with db.transaction(conn):
        a = catalog.upsert_customer(conn, "Công ty A", "0900 000 001")
        b = catalog.upsert_customer(conn, "Công ty B", "0900 000 002")
    assert catalog.customer_owning_phone(conn, "0900000002", other_than=a)["id"] == b
    assert catalog.customer_owning_phone(conn, "0900000001", other_than=a) is None
    assert catalog.customer_named(conn, "cong ty b", other_than=a)["id"] == b
    assert catalog.customer_named(conn, "Công ty B", other_than=b) is None


def test_reading_a_note_again_keeps_a_renamed_customer(conn, ws, paint):
    """A customer without a phone, renamed by the user: 'Đọc lại cả phiếu' must not make a twin under the old name."""
    make_note(ws.deliveries / "p.xlsx", customer="Khách Mẫu", phone="", lines=[("防水涂料\nSơn chống thấm", "20KG/thùng", 2, "")])
    deliveries.scan(conn, ws)
    with db.transaction(conn):
        deliveries.map_line(conn, match_key("防水涂料\nSơn chống thấm", "20KG/thùng"), paint)
    deliveries.scan(conn, ws)
    doc = conn.execute("SELECT * FROM documents WHERE kind = 'delivery' AND status = 'active'").fetchone()
    assert doc is not None
    with db.transaction(conn):
        catalog.update_customer(conn, doc["customer_id"], name="Khách Mẫu (đổi tên)")
    deliveries.reread_document(conn, ws, doc["id"])
    deliveries.scan(conn, ws)
    new = conn.execute("SELECT * FROM documents WHERE kind = 'delivery' AND status = 'active'").fetchone()
    assert new["id"] != doc["id"] and new["customer_id"] == doc["customer_id"]
    assert [r[0] for r in conn.execute("SELECT name FROM customers")] == ["Khách Mẫu (đổi tên)"]


def test_merging_keeps_a_tax_code_and_email(conn):
    with db.transaction(conn):
        a = catalog.upsert_customer(conn, "Công ty A", "0900 000 001")
        b = catalog.upsert_customer(conn, "Công ty A2", "0900 000 002", tax_code="0101", email="a2@example.com")
        keep = catalog.merge_customers(conn, [a, b], "Công ty A")
    c = conn.execute("SELECT * FROM customers WHERE id = ?", (keep,)).fetchone()
    assert (c["id"], c["tax_code"], c["email"]) == (a, "0101", "a2@example.com")
