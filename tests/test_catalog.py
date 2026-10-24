import openpyxl
import pytest

from dibekho.core import catalog
from dibekho.excel.catalog_sheet import NotCatalogSheet, read_catalog
from dibekho.excel.delivery_note import read_delivery_note
from tests.conftest import SAMPLES


def make_sheet(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Bảng thống kê nhập - xuất kho tháng 7"])
    # columns as in the customer's sheet: C last month, D in, E out, F stock left (read), G notes (ignored)
    ws.append(["商品名称\nTên sản phẩm", "分类\nPhân loại", "上月库存\nTồn kho tháng trước", "入库总量\nTổng lượng nhập kho",
               "出库总量\nTổng lượng xuất kho", "利余库存\nLượng tồn kho còn lại", "\n公司剩余的产品。\nMặt hàng ở công ty"])
    ws.append([None, None])
    ws.append(["A", "B", "C", "D", "E", "F", "G"])
    ws.append(["Sơn FS-101 (20KG)\n雨堡垒FS-101防水涂料   （白色）", "涂料类", 179, 0, 0, 120, 6])
    ws.append(["Sơn FS-101 (10KG)\n雨堡垒FS-101防水涂料   （浅灰色）", "涂料类", 0, 0, 0, 57, "1 已打开"])
    ws.append(["Vải polyester 65g/m² (1m*100m/Cuộn)\n缝织聚酯布65g", "聚酯布", 117, 0, 0, 103, "1已用"])
    ws.append(["MÀNG PPP (33 kg)\n高分子聚乙烯丙纶防水卷材(33 kg)", "纯原料", 148, 0, 0, 103, "1已用"])
    ws.append([None, "再生料", 30, 0, 0, 64])
    ws.merge_cells("A8:A9")
    ws.append(["袋装胶粉", None, 74, None, 0, None])
    wb.save(path)
    return path


def test_reads_products_variants_and_specs(tmp_path):
    items = read_catalog(make_sheet(tmp_path / "t7.xlsx"))
    got = [(i.name_vi, i.name_zh, i.spec, i.unit, i.category, i.variant) for i in items]
    assert got == [
        ("Sơn FS-101", "雨堡垒FS-101防水涂料", "20KG", "thùng", "Sơn, vữa, keo (涂料类)", "Trắng"),
        ("Sơn FS-101", "雨堡垒FS-101防水涂料", "10KG", "thùng", "Sơn, vữa, keo (涂料类)", "Xám nhạt"),
        ("Vải polyester 65g/m² (1m*100m/Cuộn)", "缝织聚酯布65g", "65g 1m*100m", "cuộn", "Vải polyester (聚酯布)", ""),
        ("MÀNG PPP", "高分子聚乙烯丙纶防水卷材", "33KG", "cuộn", "Màng PPE/PPP (卷材)", "Nguyên sinh (纯原料)"),
        ("MÀNG PPP", "高分子聚乙烯丙纶防水卷材", "33KG", "cuộn", "Màng PPE/PPP (卷材)", "Tái chế (再生料)"),
        ("袋装胶粉", "袋装胶粉", "", "gói", "", ""),
    ]
    assert [i.stock for i in items] == [120, 57, 103, 103, 64, None]  # column F; G is ignored


def test_import_records_the_sheet_stock(conn, tmp_path):
    from datetime import date

    from dibekho.core.stock import stock_levels

    items = read_catalog(make_sheet(tmp_path / "t7.xlsx"))
    assert catalog.import_catalog(conn, items, date(2026, 10, 11)) == (6, 0, 5)
    stock = {(p["spec"], p["variant"]): stock_levels(conn).get(p["id"], 0)
             for p in conn.execute("SELECT * FROM products")}
    assert stock[("20KG", "Trắng")] == 120 and stock[("33KG", "Tái chế (再生料)")] == 64
    assert stock[("", "")] == 0  # empty cell: no count for that product
    # importing again with new numbers sets the stock to the new numbers (a stock count, not an addition)
    for it in items:
        if it.stock is not None:
            it.stock += 1
    assert catalog.import_catalog(conn, items, date(2026, 10, 12)) == (0, 6, 5)
    assert sum(stock_levels(conn).values()) == 120 + 57 + 103 + 103 + 64 + 5


def test_import_twice_skips_existing(conn, tmp_path):
    items = read_catalog(make_sheet(tmp_path / "t7.xlsx"))
    assert catalog.import_catalog(conn, items) == (6, 0, 0)
    assert catalog.import_catalog(conn, items) == (0, 6, 0)


def test_delivery_note_is_not_a_catalog(tmp_path):
    from tests.conftest import make_note

    with pytest.raises(NotCatalogSheet):
        read_catalog(make_note(tmp_path / "phieu.xlsx"))


@pytest.mark.skipif(not (SAMPLES / "danh-muc-mau.xlsx").exists(), reason="customer samples not present")
def test_real_catalog_and_suggestions(conn):
    items = read_catalog(SAMPLES / "danh-muc-mau.xlsx")
    assert len(items) == 41
    assert len({(i.name_vi, i.name_zh, i.spec, i.variant) for i in items}) == 41  # every row is distinct
    catalog.import_catalog(conn, items)

    def suggestion(sample, row):
        line = next(ln for ln in read_delivery_note(SAMPLES / sample).lines if ln.row == row)
        pid = catalog.suggest_product(conn, line.raw_name, line.spec)
        return conn.execute("SELECT name_zh, spec FROM products WHERE id = ?", (pid,)).fetchone() if pid else None

    assert tuple(suggestion("phieu-mau-2.xlsx", 8)) == ("雨堡垒FS-101氟硅改性高粘结防水涂料", "20KG")
    assert tuple(suggestion("phieu-mau-2.xlsx", 9)) == ("雨堡垒FS-101氟硅改性高粘结防水涂料", "10KG")
    assert tuple(suggestion("phieu-mau-2.xlsx", 12)) == ("背水涂", "10KG")
    assert suggestion("phieu-mau-2.xlsx", 13) is None  # 背水涂 20KG is not in the catalog -> create new
    assert tuple(suggestion("phieu-mau-2.xlsx", 14)) == ("缝织聚酯布65g", "65g 1m*100m")
    assert tuple(suggestion("phieu-mau-1.xlsx", 9)) == ("油性聚氨酯注浆液 1桶", "10KG")
    assert suggestion("phieu-mau-2.xlsx", 20) is None  # 冷底油 (sơn lót lạnh) is new


def make_other_layout(path):
    """Same products, but the stock column has another title (no 'Lượng tồn kho còn lại')."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Tên sản phẩm", "Phân loại", "Ghi chú", "SL hiện có"])
    ws.append(["Sơn FS-101 (20KG)\n雨堡垒FS-101防水涂料", "涂料类", "kho 1", 12])
    ws.append(["Keo trong suốt (8KG)\n透明胶", "涂料类", "", 7.5])
    ws.append(["Bột chống thấm\n堵漏王", "涂料类", "hết", None])
    wb.save(path)
    return path


def test_stock_column_chosen_by_the_user(tmp_path):
    from dibekho.excel.catalog_sheet import sheet_columns

    path = make_other_layout(tmp_path / "khac.xlsx")
    found = sheet_columns(path)
    assert found.stock_col is None  # not recognised -> the app asks
    assert [(c.letter, c.label, c.samples) for c in found.columns] == [
        ("C", "Ghi chú", ["kho 1", "", "hết"]),
        ("D", "SL hiện có", ["12", "7.5", ""]),
    ]
    assert [i.stock for i in read_catalog(path)] == [None, None, None]
    assert [i.stock for i in read_catalog(path, stock_col=4)] == [12, 7.5, None]  # same row as the product
    assert sheet_columns(make_sheet(tmp_path / "t7.xlsx")).stock_col == 6  # column F found by its title
