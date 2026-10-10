"""'Dữ liệu gốc': export products and customers to Excel, import them on another computer."""

import openpyxl
import pytest

from dibekho import db
from dibekho.core import catalog
from dibekho.excel import master_data
from tests.test_features import setup_notes

PRODUCT_COLS = "code, name_vi, name_zh, spec, variant, unit, category, min_stock, active, created_at"
CUSTOMER_COLS = "name, contact, phone, phone_norm, address"


def snapshot(conn):
    return ([tuple(r) for r in conn.execute(f"SELECT {PRODUCT_COLS} FROM products ORDER BY code")],
            [tuple(r) for r in conn.execute(f"SELECT {CUSTOMER_COLS} FROM customers ORDER BY name")])


def test_export_then_import_on_an_empty_computer_gives_the_same_data(conn, ws, tmp_path):
    setup_notes(conn, ws)
    with db.transaction(conn):
        pid = catalog.create_product(conn, "Màng PPE", "高分子防水卷材", "16.5KG", category="Màng", min_stock=5,
                                     variant="Nguyên sinh")
        catalog.update_product(conn, pid, active=0)
    path = master_data.export(tmp_path / "goc.xlsx", conn)

    wb = openpyxl.load_workbook(path)
    customers_sheet = wb.worksheets[1]
    assert [c.value for c in customers_sheet[4]] == ["STT", "Khách hàng", "Điện thoại", "Người liên hệ", "Địa chỉ",
                                                     "Số đơn"]
    orders = {r[1]: r[5] for r in customers_sheet.iter_rows(min_row=5, values_only=True)}
    assert orders == {"Khách Một": 2, "Khách Hai": 1}

    other = db.connect(":memory:")
    result = catalog.import_master(other, *master_data.read(path))
    assert (result["products_new"], result["customers_new"], result["skipped"]) == (3, 2, [])
    assert snapshot(other) == snapshot(conn)

    # importing again changes nothing and creates no duplicates
    result = catalog.import_master(other, *master_data.read(path))
    assert (result["products_new"], result["products_updated"], result["customers_new"]) == (0, 3, 0)
    assert snapshot(other) == snapshot(conn)


def test_edited_file_updates_and_never_duplicates(conn, ws, tmp_path):
    setup_notes(conn, ws)
    path = master_data.export(tmp_path / "goc.xlsx", conn)
    wb = openpyxl.load_workbook(path)
    sheet = wb.worksheets[0]
    sheet.cell(5, 10).value = 12  # low-stock alert of the first product
    sheet.append([None, "", "Sơn lót lạnh", "冷底油", "15KG"])  # new product without a code
    wb.save(path)
    result = catalog.import_master(conn, *master_data.read(path))
    assert (result["products_new"], result["products_updated"]) == (1, 2)
    first = conn.execute("SELECT min_stock FROM products ORDER BY code LIMIT 1").fetchone()[0]
    assert first == 12
    assert conn.execute("SELECT code FROM products WHERE name_vi = 'Sơn lót lạnh'").fetchone()[0] == "SP003"


def test_same_product_under_another_code_is_skipped(conn, ws, tmp_path):
    setup_notes(conn, ws)
    path = master_data.export(tmp_path / "goc.xlsx", conn)
    name_vi, name_zh, spec = conn.execute("SELECT name_vi, name_zh, spec FROM products WHERE code = 'SP002'").fetchone()
    other = db.connect(":memory:")
    other.execute("INSERT INTO products(code, name_vi, name_zh, spec) VALUES('SP009', ?, ?, ?)", (name_vi, name_zh, spec))
    result = catalog.import_master(other, *master_data.read(path))
    assert result["products_new"] == 1 and result["skipped"] == [(6, "SP002", "SP009")]
    assert other.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 2  # no duplicate


def test_rejects_other_excel_files(tmp_path):
    from tests.conftest import make_note

    with pytest.raises(master_data.NotMasterData):
        master_data.read(make_note(tmp_path / "phieu.xlsx"))
