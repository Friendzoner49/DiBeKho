import json
import re
from datetime import date
from pathlib import Path

import openpyxl
import pytest

from dibekho import db
from dibekho.core import backup, catalog, deliveries, inbox, queries, stats, transfer
from dibekho.core.stock import close_document, stock_count, stock_levels
from dibekho.core.workspace import Config, Workspace
from dibekho.excel import report
from dibekho.excel.receipt import write_template
from tests.conftest import make_note

A = ("背水涂\nvữa chống thấm", "10KG/thùng")
B = ("固沙剂\nchất cố định cát", "10KG/thùng")


def setup_notes(conn, ws):
    make_note(ws.deliveries / "1.xlsx", code="1", day="02-09-2026", customer="Khách Một", phone="0901",
              lines=[(*A, 3, ""), (*B, 1, "")])
    make_note(ws.deliveries / "2.xlsx", code="2", day="15-09-2026", customer="Khách Hai", phone="0902",
              lines=[(*A, 5, "")])
    make_note(ws.deliveries / "3.xlsx", code="3", day="03-10-2026", customer="Khách Một", phone="0901",
              lines=[(*A, 2, ""), (*B, 4, "giao sau")])
    deliveries.scan(conn, ws)
    for u in deliveries.unknown_lines(conn, ws):
        deliveries.create_product_for_line(conn, u)
    deliveries.scan(conn, ws)
    ids = {r["name_zh"]: r["id"] for r in conn.execute("SELECT id, name_zh FROM products")}
    return ids["背水涂"], ids["固沙剂"]


def test_receipt_template_roundtrip(conn, ws):
    a, b = setup_notes(conn, ws)
    path = write_template(ws.input / "hang-ve.xlsx", catalog.products(conn), date(2026, 9, 1))
    wb = openpyxl.load_workbook(path)
    sheet = wb.active
    for row in sheet.iter_rows(min_row=7):
        if row[0].value == conn.execute("SELECT code FROM products WHERE id=?", (a,)).fetchone()[0]:
            row[5].value = 20
    wb.save(path)

    [item] = inbox.items(conn, ws)
    assert item.kind == "receipt" and item.receipt.doc_date == date(2026, 9, 1)
    inbox.apply_receipt(conn, ws, item)
    assert stock_levels(conn)[a] == 20 - 3 - 5 - 2
    assert not (ws.input / "hang-ve.xlsx").exists()
    assert len(list(ws.processed.iterdir())) == 1

    # the same file dropped again is refused
    processed = next(ws.processed.iterdir())
    (ws.input / "again.xlsx").write_bytes(processed.read_bytes())
    [again] = inbox.items(conn, ws)
    assert again.kind == "error"


def test_delivery_note_in_input_gets_helpful_error(conn, ws):
    make_note(ws.input / "phieu.xlsx")
    [item] = inbox.items(conn, ws)
    assert item.kind == "error" and "phieu-giao-hang" in item.error


def test_stock_count_sets_stock(conn, ws):
    a, b = setup_notes(conn, ws)
    with db.transaction(conn):
        stock_count(conn, date(2026, 8, 31), {a: 50, b: 10})
    levels = stock_levels(conn)
    assert levels[a] == 50 - 3 - 5 - 2
    assert levels[b] == 10 - 1 - 4


def test_cancel_reverses_and_keeps_history(conn, ws):
    a, _ = setup_notes(conn, ws)
    doc = conn.execute("SELECT id FROM documents WHERE code = '2'").fetchone()[0]
    with db.transaction(conn):
        close_document(conn, doc)
    assert stock_levels(conn)[a] == -5
    assert conn.execute("SELECT status FROM documents WHERE id = ?", (doc,)).fetchone()[0] == "cancelled"
    with pytest.raises(ValueError):
        with db.transaction(conn):
            close_document(conn, doc)


def test_period_summary(conn, ws):
    a, b = setup_notes(conn, ws)
    with db.transaction(conn):
        stock_count(conn, date(2026, 8, 31), {a: 50, b: 10})
    s, e = stats.month_range(2026, 9)
    rows = {r.product_id: r for r in stats.summary(conn, s, e)}
    assert (rows[a].opening, rows[a].qty_out, rows[a].closing) == (50, 8, 42)
    assert (rows[b].opening, rows[b].qty_out, rows[b].closing) == (10, 1, 9)

    q = stats.summary(conn, *stats.quarter_range(2026, 3), by="month")
    qa = next(r for r in q if r.product_id == a)
    assert qa.per_bucket["09/2026"] == (0, 8)

    one = stats.summary(conn, s, e, stats.Filters(customer_ids=[_customer(conn, "Khách Hai")]))
    assert [(r.product_id, r.qty_out, r.opening) for r in one] == [(a, 5, None)]

    only_b = stats.summary(conn, s, e, stats.Filters(product_ids=[b]))
    assert [r.product_id for r in only_b] == [b]


def _customer(conn, name):
    return conn.execute("SELECT id FROM customers WHERE name = ?", (name,)).fetchone()[0]


def test_customer_products(conn, ws):
    a, b = setup_notes(conn, ws)
    rows = queries.customer_products(conn, _customer(conn, "Khách Một"))
    got = {r["id"]: (r["total_qty"], r["times"], r["last_date"]) for r in rows}
    assert got == {a: (5, 2, "2026-10-03"), b: (5, 2, "2026-10-03")}


def test_search_accent_insensitive(conn, ws):
    setup_notes(conn, ws)
    res = queries.search(conn, "vua chong tham")
    assert len(res["products"]) == 1
    assert queries.search(conn, "khach mot")["customers"]
    assert queries.search(conn, "背水")["products"]
    assert queries.search(conn, "giao sau")["documents"]
    assert [d["code"] for d in queries.search(conn, "003")["documents"]] == ["3"]


def test_report_export(conn, ws, tmp_path):
    setup_notes(conn, ws)
    path = report.export(tmp_path / "r.xlsx", conn, *stats.quarter_range(2026, 3), stats.Filters(), "month",
                         set(report.SHEETS), "Q3/2026", "Tất cả")
    wb = openpyxl.load_workbook(path)
    assert len(wb.sheetnames) == 4
    text = " ".join(str(c.value) for ws_ in wb.worksheets for row in ws_.iter_rows() for c in row if c.value)
    assert "VND" not in text and "giá" not in text.lower()


def test_transfer_roundtrip(tmp_path):
    ws_a = Workspace(tmp_path / "A")
    ws_a.ensure()
    conn_a = db.connect(ws_a.db_path)
    setup_notes(conn_a, ws_a)
    cfg = Config(workspace=str(ws_a.root), device_id="a1", device_name="MayA")
    pkg = transfer.export_package(conn_a, ws_a, cfg)
    assert not transfer.has_unsent_changes(conn_a)
    levels_a = stock_levels(conn_a)

    ws_b = Workspace(tmp_path / "B")
    ws_b.ensure()
    conn_b = db.connect(ws_b.db_path)
    with db.transaction(conn_b):
        catalog.create_product(conn_b, "Hàng của máy B")
    assert transfer.has_unsent_changes(conn_b)
    target = ws_b.input / pkg.name
    target.write_bytes(pkg.read_bytes())
    [item] = inbox.items(conn_b, ws_b)
    assert item.kind == "package" and item.manifest.device_name == "MayA"

    backup.named_backup(conn_b, ws_b, "truoc-nhap-du-lieu")
    conn_b.close()
    manifest = transfer.import_package(ws_b, target)
    conn_b = db.connect(ws_b.db_path)
    transfer.after_import(conn_b, manifest)
    assert stock_levels(conn_b) == levels_a
    assert len(list(ws_b.originals.glob("*.xlsx"))) == 3
    # B's own folder has none of A's files: no 'missing' warnings
    assert deliveries.scan(conn_b, ws_b).pending == 0
    # B later gets a copy of one of A's notes: recognised, not counted twice
    (ws_b.deliveries / "1.xlsx").write_bytes((ws_a.deliveries / "1.xlsx").read_bytes())
    assert deliveries.scan(conn_b, ws_b).imported == []
    assert stock_levels(conn_b) == levels_a


def test_daily_backup_keeps_14(conn, ws):
    for day in range(1, 20):
        backup.daily_backup(conn, ws, date(2026, 9, day))
    assert len(list(ws.backups.glob("DiBeKho_*.sqlite"))) == 14
    assert backup.daily_backup(conn, ws, date(2026, 9, 19)) is None


def test_every_translation_key_exists():
    root = Path(__file__).resolve().parent.parent / "src" / "dibekho"
    vi = json.loads((root / "i18n" / "vi.json").read_text(encoding="utf-8"))
    en = json.loads((root / "i18n" / "en.json").read_text(encoding="utf-8"))
    assert set(vi) == set(en), set(vi) ^ set(en)
    used = set()
    for f in root.rglob("*.py"):
        used |= set(re.findall(r'\bt\(\s*"([a-z_.0-9]+)"', f.read_text(encoding="utf-8")))
    used |= {f"search.{k}" for k in ("products", "customers", "documents")}
    dynamic = (
        [f"status.{s}" for s in ("active", "cancelled", "replaced")]
        + [f"kind.{k}" for k in ("delivery", "receipt", "stock_count")]
        + [f"kind.{k}_plural" for k in ("delivery", "receipt", "stock_count")]
        + [f"move.{k}" for k in ("delivery_out", "delivery_reverse", "receipt_in", "receipt_reverse",
                                 "count_adjust", "count_reverse")]
        + [f"file.{k}" for k in ("error", "changed", "missing")]
        + [f"inbox.{k}" for k in ("receipt", "catalog", "package", "error")]
        + [f"period.{k}" for k in ("day", "month", "quarter", "year", "range")]
        + [f"split.{k}" for k in ("none", "day", "month")]
        + [f"sheet.{k}" for k in report.SHEETS]
    )
    missing = (used | set(dynamic)) - set(vi) - {"key"}
    assert not missing, missing


def test_chinese_input(conn, ws):
    from dibekho.core.text import parse_number

    setup_notes(conn, ws)
    assert [p["name_zh"] for p in queries.search(conn, "背水")["products"]] == ["背水涂"]
    assert queries.search(conn, "固沙剂")["products"][0]["name_zh"] == "固沙剂"
    assert parse_number("１２") == 12 and parse_number("１２，５") == 12.5 and parse_number(" 3,5 ") == 3.5


def test_catalog_sheet_dropped_into_input_is_recognised(conn, ws):
    from tests.test_catalog import make_sheet

    make_sheet(ws.input / "danh-muc.xlsx")
    [item] = inbox.items(conn, ws)
    assert item.kind == "catalog" and len(item.catalog) == 6


def test_unusable_file_in_input_is_hidden_not_moved(conn, ws):
    path = ws.input / "ghi-chu.xlsx"
    openpyxl.Workbook().save(path)
    [item] = inbox.items(conn, ws)
    assert item.kind == "error"
    inbox.hide(conn, item)
    assert inbox.items(conn, ws) == [] and path.exists()
    assert not ws.processed.exists() or not any(ws.processed.iterdir())


def test_discarded_receipt_can_still_be_imported_from_da_xu_ly(conn, ws):
    from dibekho.excel.receipt import write_template

    a, _ = setup_notes(conn, ws)
    path = write_template(ws.input / "hang-ve.xlsx", catalog.products(conn), date(2026, 9, 1)) or ws.input / "hang-ve.xlsx"
    wb = openpyxl.load_workbook(path)
    for row in wb.active.iter_rows(min_row=7):
        if row[0].value == conn.execute("SELECT code FROM products WHERE id=?", (a,)).fetchone()[0]:
            row[5].value = 7
    wb.save(path)
    [item] = inbox.items(conn, ws)
    inbox.discard(ws, item)  # 'Bỏ' in Cần xử lý
    [moved] = list(ws.processed.iterdir())
    again = inbox.read_item(conn, moved)  # 'Chọn file để nhập…' on the goods-in page
    assert again.kind == "receipt"
    inbox.apply_receipt(conn, ws, again)
    assert moved.exists()  # a file picked outside input/ is left where it is
    assert stock_levels(conn)[a] == 7 - 3 - 5 - 2


def test_waiting_notes_from_the_other_computer_do_not_stay_in_to_do(tmp_path):
    """Machine A exports while a note still waits for product names; on B that file does not exist."""
    ws_a = Workspace(tmp_path / "A")
    ws_a.ensure()
    conn_a = db.connect(ws_a.db_path)
    setup_notes(conn_a, ws_a)
    make_note(ws_a.deliveries / "moi.xlsx", code="99", lines=[("新产品\nHàng mới tinh", "5KG/thùng", 1, "")])
    deliveries.scan(conn_a, ws_a)
    assert deliveries.pending_count(conn_a) == 1
    pkg = transfer.export_package(conn_a, ws_a, Config(workspace=str(ws_a.root), device_id="a", device_name="A"))

    ws_b = Workspace(tmp_path / "B")
    ws_b.ensure()
    db.connect(ws_b.db_path).close()
    manifest = transfer.import_package(ws_b, pkg)
    conn_b = db.connect(ws_b.db_path)
    transfer.after_import(conn_b, manifest)
    assert deliveries.scan(conn_b, ws_b).pending == 0
    assert inbox.items(conn_b, ws_b) == []

    # the note copied to B later: asked again
    (ws_b.deliveries / "moi.xlsx").write_bytes((ws_a.deliveries / "moi.xlsx").read_bytes())
    deliveries.scan(conn_b, ws_b)
    assert [u.name_vi for u in deliveries.unknown_lines(conn_b, ws_b)] == ["Hàng mới tinh"]


def test_delete_product_only_when_unused(conn, ws):
    a, _ = setup_notes(conn, ws)
    spare = catalog.create_product(conn, "Sơn thừa", spec="5KG")
    catalog.set_alias(conn, "son thua|5kg", spare, "Sơn thừa")
    assert catalog.product_documents(conn, a) == 3
    assert catalog.product_documents(conn, spare) == 0
    with pytest.raises(ValueError):
        catalog.delete_product(conn, a)
    catalog.delete_product(conn, spare)
    assert conn.execute("SELECT COUNT(*) FROM products WHERE id = ?", (spare,)).fetchone()[0] == 0
    assert catalog.alias_product(conn, "son thua|5kg") is None


def test_config_keeps_ui_scale(tmp_path, monkeypatch):
    from dibekho.core import workspace

    monkeypatch.setattr(workspace, "config_dir", lambda: tmp_path)
    cfg = workspace.Config.create(tmp_path / "w")
    assert cfg.ui_scale == 1.2
    cfg.ui_scale = 1.4
    cfg.save()
    assert workspace.Config.load().ui_scale == 1.4
