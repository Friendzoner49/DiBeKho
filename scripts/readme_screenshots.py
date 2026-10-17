"""Screenshots for README.md (docs/images/en), README.vi.md (docs/images) and README.zh.md (docs/images/zh), from
invented demo data - never customer data.

Run from the repo root:  PYTHONPATH=. uv run python scripts/readme_screenshots.py [vi|en|zh]   (default: all)
"""

import os
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
if sys.platform == "win32":
    os.environ["QT_QPA_FONTDIR"] = "C:/Windows/Fonts"
from PySide6.QtWidgets import QApplication  # noqa: E402

from dibekho import db, i18n  # noqa: E402
from dibekho.core import catalog, deliveries, receipts  # noqa: E402
from dibekho.core.stock import stock_count  # noqa: E402
from dibekho.core.workspace import Config, Workspace  # noqa: E402
from tests.conftest import make_note  # noqa: E402

LANG = sys.argv[1] if len(sys.argv) > 1 else None
if LANG is None:  # one Qt application per process: run once per language
    import subprocess
    for lang in ("vi", "en", "zh"):
        subprocess.run([sys.executable, __file__, lang], check=True)
    sys.exit(0)
out, tmp = Path({"en": "docs/images/en", "zh": "docs/images/zh"}.get(LANG, "docs/images")), Path(tempfile.mkdtemp())
out.mkdir(parents=True, exist_ok=True)
root = tmp / "demo"
shutil.rmtree(root, ignore_errors=True)
ws = Workspace(root)
ws.ensure()

P = [  # name_vi, name_zh, spec, unit, category, variant, min_stock
    ("Sơn chống thấm FS-101", "防水涂料 FS-101", "20KG", "thùng", "Sơn, vữa, keo", "Trắng", 10),
    ("Sơn chống thấm FS-101", "防水涂料 FS-101", "10KG", "thùng", "Sơn, vữa, keo", "Xám nhạt", 10),
    ("Sơn chống thấm gốc xi măng", "水泥基防水涂料", "20KG", "thùng", "Sơn, vữa, keo", "", 8),
    ("Vữa chống thấm ngược", "背水涂", "10KG", "thùng", "Sơn, vữa, keo", "", 5),
    ("Keo trám khe", "密封胶", "5KG", "thùng", "Sơn, vữa, keo", "", 0),
    ("Màng chống thấm tự dính", "自粘防水卷材", "1.5mm 1m*20m", "cuộn", "Màng tự dính", "", 6),
    ("Màng chống thấm PPE", "高分子防水卷材", "16.5KG", "cuộn", "Màng PPE/PPP", "Nguyên sinh", 0),
    ("Vải polyester 65g", "聚酯布 65g", "65g 1m*100m", "cuộn", "Vải polyester", "", 3),
    ("Bột chống thấm", "防水粉", "", "gói", "", "", 20),
]
NOTE_NAMES = {i: f"{zh}\n{vi}" for i, (vi, zh, *_r) in enumerate(P)}
SPECS = ["20KG/thùng", "10KG/thùng", "20KG/thùng", "10KG/thùng", "5KG/thùng", "1m*20m/ cuộn", "cuộn", "1m*100m/ cuộn",
         "Gói"]
CUSTOMERS = [("Công ty Xây dựng An Phát", "0900 000 101"), ("Anh Minh - Thợ chống thấm", "0900 000 202"),
             ("Cửa hàng VLXD Hoà Bình", "0900 000 303"), ("Công ty Nội thất Sao Mai", "0900 000 404")]
NOTES = [  # code, day, customer, [(product index, qty, note)]
    ("101", "03-09-2026", 0, [(0, 12, ""), (5, 4, "")]),
    ("102", "08-09-2026", 1, [(3, 6, ""), (8, 10, "")]),
    ("103", "15-09-2026", 2, [(0, 8, ""), (1, 5, ""), (7, 3, "")]),
    ("104", "22-09-2026", 0, [(2, 10, ""), (5, 6, "giao 2 đợt")]),
    ("105", "29-09-2026", 3, [(4, 2, ""), (6, 3, "")]),
    ("106", "02-10-2026", 1, [(0, 6, ""), (3, 4, "")]),
    ("107", "05-10-2026", 2, [(1, 8, ""), (8, 25, "")]),
    ("108", "07-10-2026", 0, [(0, 15, ""), (5, 8, ""), (7, 2, "")]),
    ("109", "09-10-2026", 3, [(2, 6, ""), (6, 2, "")]),
]

app = QApplication([])
app.setStyle("Fusion")
f = app.font()
f.setPointSize(10)
if sys.platform == "win32":  # the offscreen platform does not find .ttc fonts by itself
    from PySide6.QtGui import QFontDatabase

    for name in ("msyh.ttc", "msyhbd.ttc", "seguisym.ttf"):
        QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{name}")
f.setFamilies(["Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI Symbol"])
app.setFont(f)
i18n.set_language(LANG)
from dibekho.ui.common import AppContext  # noqa: E402
from dibekho.ui.details import CustomerDialog, DocumentDialog  # noqa: E402
from dibekho.ui.main_window import PENDING, SEARCH, MainWindow  # noqa: E402
from dibekho.ui.search_page import WINDOWS  # noqa: E402

ctx = AppContext(Config(str(root), LANG, "demo", "MAY-VAN-PHONG"), ws)
conn = ctx.conn
ids = []
with db.transaction(conn):
    for vi, zh, spec, unit, cat, variant, mn in P:
        ids.append(catalog.create_product(conn, vi, zh, spec, unit=unit, category=cat, min_stock=mn, variant=variant))
stock_count(conn, date(2026, 9, 1), dict(zip(ids, [40, 30, 25, 12, 6, 20, 8, 10, 60])), "Kiểm kê đầu kỳ")
receipts.save(conn, receipts.ReceiptInput(
    date(2026, 9, 20), receipts.SUPPLIER, supplier_name="Công ty mẹ", note="Hàng về quý 3",
    lines=[receipts.ReceiptLineInput(30, ids[0]), receipts.ReceiptLineInput(15, ids[5]),
           receipts.ReceiptLineInput(10, ids[2])]))
for code, day, c, lines in NOTES:
    name, phone = CUSTOMERS[c]
    make_note(ws.deliveries / f"2026-{day[3:5]}" / f"phieu-{code}.xlsx", code=code, day=day, customer=name,
              phone=phone, lines=[(NOTE_NAMES[i], SPECS[i], q, n) for i, q, n in lines])
deliveries.scan(conn, ws)
def spec_key(spec):
    return spec.split("/")[0].strip().lower()


by_note = {(zh, spec_key(SPECS[i])): ids[i] for i, (vi, zh, *_r) in enumerate(P)}
for u in deliveries.unknown_lines(conn, ws):
    deliveries.map_line(conn, u.key, by_note[(u.name_zh, spec_key(u.spec))])
deliveries.scan(conn, ws)

win = MainWindow(ctx)
win.resize(1280, 760)
win.show()
win.rescan()


def shot(widget, name):
    app.processEvents()
    widget.grab().save(str(out / name))


win.nav.setCurrentRow(0)
shot(win, "ton-kho.png")

# a new note with an unknown product and a shipping fee -> 'Cần xử lý'
make_note(ws.deliveries / "2026-10" / "phieu-110.xlsx", code="110", day="10-10-2026", customer=CUSTOMERS[1][0],
          phone=CUSTOMERS[1][1], lines=[(NOTE_NAMES[0], SPECS[0], 4, ""), ("冷底油\nSơn lót gốc dầu", "15KG/thùng", 2, ""),
                                        ("运费\nPhí vận chuyển", "", 1, "")])
win.rescan()
win.nav.setCurrentRow(PENDING)
shot(win, "can-xu-ly.png")

win.nav.setCurrentRow(SEARCH)
win.search.box.setText("an phat")
win.search.refresh()
shot(win, "tra-cuu.png")

stats = win.search.open_window(*WINDOWS[2])
stats.resize(1280, 760)
shot(stats, "thong-ke.png")
stats.close()

doc = conn.execute("SELECT id FROM documents WHERE code = '108'").fetchone()[0]
d = DocumentDialog(ctx, doc, win)
d.resize(1000, 560)
d.show()
shot(d, "chi-tiet-don.png")
d.close()
cust = conn.execute("SELECT id FROM customers WHERE name LIKE 'Công ty Xây%'").fetchone()[0]
d = CustomerDialog(ctx, cust, win)
d.resize(1100, 640)
d.show()
shot(d, "chi-tiet-khach.png")
d.close()

from dibekho.ui.receipt_form import ReceiptForm  # noqa: E402

form = ReceiptForm(ctx, win)
form.resize(1100, 600)
form.rows[0].qty.setValue(20)
form.rows[1].qty.setValue(10)
row = form.add_row()
form._set_product(row, None, receipts.NewProduct(P[0][0] + " (mới)", P[0][1], "5KG", unit=P[0][3]))
row.qty.setValue(6)
form.show()
shot(form, "hang-ve.png")
form.saved_doc = -1  # close without asking
form.close()
print("ok")
