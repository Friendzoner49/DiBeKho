
# ---- every other page and dialog, for comparing the Swift app (made-up shop, never real data)
from PySide6.QtWidgets import QRadioButton  # noqa: E402


def safe(name, fn):
    try:
        fn()
    except Exception as e:  # one broken shot must not hide the others
        print("FAILED", name, repr(e))


def dialog(widget, name, w=1100, h=650):
    widget.resize(w, h)
    widget.show()
    shot(widget, name)
    widget.hide()
    widget.deleteLater()


def pages():
    names = {0: "01-ton-kho", PENDING: "02-can-xu-ly", SEARCH: "03-tra-cuu", 3: "04-hang-ve", 4: "05-kiem-ke"}
    for row, name in names.items():
        win.nav.setCurrentRow(row)
        shot(win, name + ".png")
    win.nav.setCurrentRow(0)
    stock = win.stack.widget(0)
    for box in stock.findChildren(__import__("PySide6.QtWidgets", fromlist=["QCheckBox"]).QCheckBox):
        box.setChecked(True)
        shot(win, "01b-ton-kho-chi-hang-sap-het.png")
        box.setChecked(False)
        break


def settings():
    win.nav.setCurrentRow(5)
    page = win.stack.widget(5)
    for i in range(page.tabs.count()):
        page.tabs.setCurrentIndex(i)
        shot(win, f"06-cai-dat-{i + 1}.png")
    page.tabs.setCurrentIndex(1)
    if page.learned.topLevelItemCount():
        page.learned.topLevelItem(0).setExpanded(True)
        shot(win, "06b-cai-dat-2-ten-da-hoc-mo-ra.png")
    page.tabs.setCurrentIndex(0)


def windows():
    for name, (key, cls) in zip(("07-cua-so-don-hang", "08-cua-so-khach-hang", "09-cua-so-thong-ke"), WINDOWS):
        w = win.search.open_window(key, cls)
        w.resize(1280, 760)
        shot(w, name + ".png")
        w.close()


def history():
    win.nav.setCurrentRow(4)
    count = win.stack.widget(4)
    for kind, name in (("transfer", "10-phieu-chuyen-hang"), ("trial", "11-phieu-dung-thu"), ("stock_count", "12-phieu-kiem-ke")):
        count.open_history(kind)
        w = count._history_windows[kind]
        w.resize(1100, 600)
        shot(w, name + ".png")
        w.close()


def count_dialogs():
    from dibekho.ui.count_page import TransferDialog, TrialUseDialog
    dialog(TransferDialog(ctx, win), "13-chuyen-hang.png", 980, 560)
    dialog(TrialUseDialog(ctx, win), "14-dung-thu.png", 980, 560)


def issue_forms():
    from dibekho.ui.issue_form import IssueForm
    f = IssueForm(ctx, win)
    f.resize(1280, 720)
    f.show()
    shot(f, "15-phieu-xuat-kho-trong.png")
    f._set_existing(f.rows[0], ids[0])
    f.rows[0].qty_main.setValue(5)
    f._set_existing(f.rows[1], ids[5])
    f.rows[1].qty_main.setValue(2)
    f.rows[1].qty_office.setValue(1)
    shot(f, "15b-phieu-xuat-kho-co-hang.png")
    f.saved = True
    f.done(0)


def receipt_forms():
    from dibekho.ui.receipt_form import ReceiptForm
    f = ReceiptForm(ctx, win)
    f.resize(1100, 600)
    f.show()
    shot(f, "16-nhap-hang-ve-trong.png")
    radios = f.findChildren(QRadioButton)
    if len(radios) > 1:
        radios[1].setChecked(True)
        shot(f, "16b-nhap-hang-ve-khach-tra.png")
    if len(radios) > 2:
        radios[2].setChecked(True)
        shot(f, "16c-nhap-hang-ve-ncc-khac.png")
    f.saved_doc = -1
    f.close()


def details():
    from dibekho.ui.details import ProductDialog
    for code_sql, name in (("SELECT id FROM documents WHERE code = '108'", "17-chi-tiet-don"),
                           ("SELECT id FROM documents WHERE kind = 'receipt' LIMIT 1", "18-chi-tiet-hang-ve"),
                           ("SELECT id FROM documents WHERE kind = 'transfer' LIMIT 1", "19-chi-tiet-chuyen-hang"),
                           ("SELECT id FROM documents WHERE kind = 'stock_count' LIMIT 1", "20-chi-tiet-kiem-ke")):
        row = conn.execute(code_sql).fetchone()
        if row:
            safe(name, lambda: dialog(DocumentDialog(ctx, row[0], win), name + ".png", 1000, 560))
    cust = conn.execute("SELECT id FROM customers ORDER BY id LIMIT 1").fetchone()[0]
    safe("cust", lambda: dialog(CustomerDialog(ctx, cust, win), "21-chi-tiet-khach.png", 1150, 820))
    safe("product", lambda: dialog(ProductDialog(ctx, ids[0], win), "22-chi-tiet-mat-hang.png", 1000, 600))


def small_dialogs():
    from dibekho.i18n import t
    from dibekho.ui.customer_form import CustomerInfoDialog
    from dibekho.ui.license_dialog import LicenseDialog
    from dibekho.ui.log_dialog import LogDialog
    from dibekho.ui.login_dialog import LoginDialog
    from dibekho.ui.orders_page import _MergeCustomersDialog
    from dibekho.ui.pending_page import ProductPicker
    from dibekho.ui.receipt_form import NewProductDialog
    from dibekho.ui.settings_page import ProductEditor
    product = conn.execute("SELECT * FROM products WHERE id = ?", (ids[0],)).fetchone()
    custs = conn.execute("SELECT id, name FROM customers ORDER BY id LIMIT 2").fetchall()
    for name, make, w, h in (
        ("23-them-mat-hang", lambda: ProductEditor(ctx, None, win), 620, 480),
        ("24-sua-mat-hang", lambda: ProductEditor(ctx, product, win), 620, 480),
        ("25-mat-hang-moi-tu-phieu", lambda: NewProductDialog(ctx, None, win), 620, 480),
        ("26-chon-mat-hang", lambda: ProductPicker(ctx, win), 900, 600),
        ("27-thong-tin-khach", lambda: CustomerInfoDialog(win, t("issue.new_customer"), {"name": custs[0][1]}), 620, 420),
        ("28-gop-khach-hang", lambda: _MergeCustomersDialog(win, [(c[0], c[1], 1000000.0) for c in custs]), 720, 420),
        ("29-giay-phep", lambda: LicenseDialog(win), 900, 600),
        ("30-nhat-ky", lambda: LogDialog(ctx, win), 1000, 640),
        ("31-dang-nhap-cloud", lambda: LoginDialog(ctx.cfg, "", win), 560, 420),
    ):
        safe(name, lambda make=make, name=name, w=w, h=h: dialog(make(), name + ".png", w, h))


def more_dialogs():
    """32–37: the dialogs of Excel imports, restoring products, a count from the web, choosing the copy to keep."""
    from datetime import datetime as _dt

    from dibekho.core import catalog as _catalog
    from dibekho.excel import master_data
    from dibekho.excel.catalog_sheet import NotCatalogSheet, read_catalog, sheet_columns
    from dibekho.ui.catalog_import import CatalogImportDialog, StockColumnDialog
    from dibekho.ui.conflict_dialog import ConflictDialog
    from dibekho.ui.transfer_page import RestoreProductDialog, StockMatchDialog
    from dibekho.ui.web_requests import WebCountDialog

    sheet = Path(DIBEKHOMAC) / "Tests" / "DiBeKhoCoreTests" / "InboxFiles" / "catalog_sheet.xlsx"

    def catalog_items():
        try:
            return read_catalog(sheet)
        except NotCatalogSheet:
            return []

    safe("32", lambda: dialog(CatalogImportDialog(ctx, sheet, catalog_items(), win), "32-nhap-danh-muc.png", 1200, 720))
    safe("33", lambda: dialog(StockColumnDialog(sheet, sheet_columns(sheet).columns, win), "33-chon-cot-ton.png", 640, 460))

    def master():
        path = master_data.export(Path(tmp) / "du-lieu-goc.xlsx", conn)
        products, _, stock = master_data.read(path)
        dialog(StockMatchDialog(win, products, stock), "34-du-lieu-goc-khop-ton.png", 1250, 640)
    safe("34", master)

    gone = [_catalog.DeletedProduct("SP010", "Sơn lót kháng kiềm", "抗碱底漆", "18L", "thùng", "Sơn, vữa, keo", 0.0,
                                    "", "", _dt(2026, 11, 2, 9, 30)),
            _catalog.DeletedProduct("SP011", "Lưới thuỷ tinh", "玻璃纤维网", "1m×50m", "cuộn", "Vải polyester", 0.0,
                                    "", "", _dt(2026, 10, 28, 17, 5))]
    safe("35", lambda: dialog(RestoreProductDialog(gone, win), "35-khoi-phuc-mat-hang.png", 900, 460))

    item = {"sender": "Nhân viên kho", "created_at": _dt.now().isoformat(),
            "payload": {"count_date": _dt.now().date().isoformat(), "location_id": 1,
                        "lines": [{"product_id": ids[0], "qty": 50}, {"product_id": ids[1], "qty": 12}]}}
    safe("36", lambda: dialog(WebCountDialog(conn, item, win), "36-kiem-ke-tu-web.png", 900, 620))
    safe("37", lambda: dialog(ConflictDialog(ctx, win), "37-chon-ban-giu.png", 900, 480))


for n, fn in [("pages", pages), ("settings", settings), ("windows", windows), ("history", history),
              ("count_dialogs", count_dialogs), ("issue", issue_forms), ("receipt", receipt_forms),
              ("details", details), ("small", small_dialogs), ("more", more_dialogs)]:
    safe(n, fn)
print("ok")
