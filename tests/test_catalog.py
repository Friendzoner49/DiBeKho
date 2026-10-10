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
    ws.append(["商品名称\nTên sản phẩm", "分类\nPhân loại", "Tồn kho tháng trước"])
    ws.append([None, None])
    ws.append(["A", "B", "C"])
    ws.append(["Sơn FS-101 (20KG)\n雨堡垒FS-101防水涂料   （白色）", "涂料类", 179])
    ws.append(["Sơn FS-101 (10KG)\n雨堡垒FS-101防水涂料   （浅灰色）", "涂料类", 0])
    ws.append(["Vải polyester 65g/m² (1m*100m/Cuộn)\n缝织聚酯布65g", "聚酯布", 117])
    ws.append(["MÀNG PPP (33 kg)\n高分子聚乙烯丙纶防水卷材(33 kg)", "纯原料", 148])
    ws.append([None, "再生料", 30])
    ws.merge_cells("A8:A9")
    ws.append(["袋装胶粉", None, 74])
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


def test_import_twice_skips_existing(conn, tmp_path):
    items = read_catalog(make_sheet(tmp_path / "t7.xlsx"))
    assert catalog.import_catalog(conn, items) == (6, 0)
    assert catalog.import_catalog(conn, items) == (0, 6)


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
