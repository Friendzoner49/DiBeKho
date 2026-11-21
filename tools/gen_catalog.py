"""Phase 5a: editing the catalog (update, delete, merge, import from a sheet) as the Python app does it.

    uv --project K:/HeThongSonDiBe run python -X utf8 tools/gen_catalog.py K:/HeThongSonDiBe

Writes Tests/DiBeKhoCoreTests/Generated/GoldenCatalog.swift: what each step returned (name=value) or the error it
raised (name!message), and the products / meta / stock movements after it. Made-up shop of Golden.swift.
"""

import re
import sqlite3
import subprocess
import sys
from pathlib import Path

SRC = Path(sys.argv[1]).resolve()
OUT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dibekho import db  # noqa: E402
from dibekho.core import catalog, stock  # noqa: E402
from dibekho.core.text import matches_words, unaccent  # noqa: E402
from dibekho.excel.catalog_sheet import CatalogItem  # noqa: E402
from note_lines import swift_str  # noqa: E402

commit = subprocess.run(["git", "-C", str(SRC), "log", "-1", "--format=%h"], capture_output=True, text=True).stdout.strip()
TESTS = OUT / "Tests" / "DiBeKhoCoreTests"
golden = (TESTS / "Generated/Golden.swift").read_text(encoding="utf-8")
SHOP = re.search(r'static let shop = #"""\n(.*?)\n"""#', golden, re.S).group(1)

conn = sqlite3.connect(":memory:", isolation_level=None)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")
conn.create_function("unaccent", 1, unaccent, deterministic=True)
conn.create_function("matches_words", 2, lambda n, h: matches_words(n or "", h or ""), deterministic=True)
db.migrate(conn)
for statement in db._split_sql(SHOP):
    conn.execute(statement)
db.set_meta(conn, "freed_codes", "SP010,SP008")
db.set_meta(conn, "product_code_max", "4")

checks: list[str] = []


def canon(v) -> str:
    if v is None:
        return "∅"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"{float(v):.4f}"
    return str(v)


def run(name, fn):
    try:
        checks.append(f"{name}={fn()}")
    except ValueError as e:
        checks.append(f"{name}!{e}")


def state(label: str):
    rows = conn.execute("SELECT id, code, name_vi, name_zh, spec, unit, category, variant, min_stock, active, stock_note "
                        "FROM products ORDER BY id").fetchall()
    checks.append(f"{label}_products=" + ";".join("|".join(canon(r[k]) for k in r.keys()) for r in rows))
    checks.append(f"{label}_freed=" + db.get_meta(conn, "freed_codes", "") + f" max={db.get_meta(conn, 'product_code_max', '')}")
    checks.append(f"{label}_aliases=" + ";".join(f"{r[0]}>{r[1]}" for r in conn.execute(
        "SELECT key, product_id FROM product_aliases ORDER BY key")))
    checks.append(f"{label}_moves=" + ";".join(f"{r[0]}:{canon(r[1])}:{r[2]}" for r in conn.execute(
        "SELECT product_id, qty, kind FROM stock_movements ORDER BY id")))
    checks.append(f"{label}_lines=" + ",".join(f"{r[0]}x{r[1]}" for r in conn.execute(
        "SELECT product_id, COUNT(*) FROM document_lines GROUP BY product_id ORDER BY product_id")))


ids = [r[0] for r in conn.execute("SELECT id FROM products ORDER BY id")]
checks.append("ids=" + ",".join(map(str, ids)))
state("start")
checks.append("categories=" + "|".join(catalog.categories(conn)))
checks.append("docs_of=" + ",".join(f"{i}:{catalog.product_documents(conn, i)}" for i in ids))

# a new one takes a freed code first; editing; the same name again is another row on purpose (the editor warns)
new1 = catalog.create_product(conn, " Băng keo Y ", "胶带Y", "5cm", "", "Keo", variant="Xanh")
checks.append(f"new1={new1}:{conn.execute('SELECT code, unit FROM products WHERE id = ?', (new1,)).fetchone()[0]}")
catalog.update_product(conn, new1, name_vi="Băng keo Y2", min_stock=7, active=0, bogus="x")
catalog.update_product(conn, new1)
state("edited")

# delete: one that no document uses goes (its code is never given out again), one that is used is refused
new2 = catalog.create_product(conn, "Đinh", "", "", "hộp", "Sắt")
run("delete_unused", lambda: catalog.delete_product(conn, new2))
used = next(i for i in ids if catalog.product_documents(conn, i))
run("delete_used", lambda: catalog.delete_product(conn, used))
state("deleted")
checks.append("next_code=" + catalog.next_product_code(conn))

# merge: the larger code goes into the smaller; empty fields are filled; the larger code is freed
a = catalog.create_product(conn, "Sơn M", "", "5KG", "", "")
b = catalog.create_product(conn, "Sơn M", "油漆M", "5KG", "", "Sơn", min_stock=3)
catalog.set_alias(conn, "son m", b, "Sơn M")
catalog.update_product(conn, b, stock_note="ghi chú b")
stock.stock_count(conn, __import__("datetime").date(2026, 11, 14), {b: 9.0}, "đếm")
run("merge_same", lambda: catalog.merge_products(conn, a, a))
run("merge_missing", lambda: catalog.merge_products(conn, a, 9999))
run("merge", lambda: catalog.merge_products(conn, b, a))
state("merged")
checks.append("next_code_after_merge=" + catalog.next_product_code(conn))

# import a sheet: the same item (even typed with other accents/case) is skipped; stock counts only when a date is given
items = [CatalogItem(2, "Băng keo Y2", "", "5cm", "", "", "Xanh", 4.0),
         CatalogItem(3, "BANG KEO Z", "", "7cm", "cuộn", "Keo", "", 10.0),
         CatalogItem(4, "Sơn M", "", "5KG", "", "", "", None),
         CatalogItem(5, "Vít", "螺丝", "", "", "Sắt", "", 25.0)]
run("import_no_stock", lambda: catalog.import_catalog(conn, items[1:2]))
run("import_stock", lambda: catalog.import_catalog(conn, items, __import__("datetime").date(2026, 11, 15), "đợt nhập"))
state("imported")
checks.append("log=" + ";".join(f"{r[0]}:{r[1]}" for r in conn.execute(
    "SELECT action, detail FROM app_log WHERE action = 'catalog_import' ORDER BY id")))

# the monthly stock sheet: a made-up one (single rows with a category, a merged block of variants, colour in brackets)
import openpyxl  # noqa: E402
from dibekho.excel.catalog_sheet import read_catalog, sheet_columns  # noqa: E402

wb = openpyxl.Workbook()
ws = wb.active
ws.append(["Bảng thống kê"])
ws.append(["Tên sản phẩm\n产品名称", "Phân loại", "Tồn đầu", "Nhập", "Xuất", "Lượng tồn kho còn lại\n利余库存"])
ws.append(["A", "B", "C", "D", "E", "F"])
ws.append(["Sơn lót (20KG)\n底漆（20kg）", "涂料类", 5, 1, 2, 12])
ws.append(["Màng PPE 1.5mm 1m*20m\n聚乙烯卷材", None, 1, 0, 0, 7])
ws.append([None, "纯原料", 2, 0, 0, 3])
ws.append([None, "再生料", 2, 0, 0, None])
ws.append(["Keo dán (16,5 kg)\n胶水（白色）", "涂料类", 0, 0, 0, "8,5"])
ws.append(["螺丝袋", "", 0, 0, 0, 4])
ws.merge_cells("A5:A7")
FILES = TESTS / "InboxFiles"
FILES.mkdir(exist_ok=True)
sheet_path = FILES / "catalog_sheet.xlsx"
wb.save(sheet_path)
cols = sheet_columns(sheet_path)
checks.append(f"sheet_stock_col={cols.stock_col}")
checks.append("sheet_columns=" + ";".join(f"{c.col}{c.letter}[{c.label}]{'/'.join(c.samples)}" for c in cols.columns))
for it in read_catalog(sheet_path):
    checks.append("sheet_item=" + "|".join(canon(v) if not isinstance(v, str) else (v or "∅") for v in (
        it.row, it.name_vi, it.name_zh, it.spec, it.unit, it.category, it.variant, it.stock)))
for it in read_catalog(sheet_path, 3):
    checks.append(f"sheet_stock_c={it.row}:{canon(it.stock)}")

body = "".join(f"        {swift_str(c)},\n" for c in checks)
(TESTS / "Generated/GoldenCatalog.swift").write_text(
    f"// GENERATED by tools/gen_catalog.py from the Python app (commit {commit}). Do not edit.\n\n"
    "enum GoldenCatalog {\n    static let checks: [String] = [\n" + body + "    ]\n}\n", encoding="utf-8", newline="\n")
print(f"{len(checks)} checks, from commit {commit}")
for c in checks:
    print(" ", c[:230])
