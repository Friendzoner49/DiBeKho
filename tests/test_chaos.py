"""Exploratory / chaos tests: virtual users trying to break the app's data flows.

Each test is one attack from the QA run of 2026-11-08 (see the report). Grouped by the "user" doing it:
the careless clerk, the hurried double-clicker, the Excel editor, the two-machine handover, file and disk
troubles, and a random-operations fuzzer that checks the ledger invariants after every step.
Only fake names and numbers are used.
"""

import json
import random
import shutil
import sqlite3
import zipfile
from datetime import date, timedelta

import openpyxl
import pytest

from dibekho import db
from dibekho.core import catalog, deliveries, receipts, stats, transfer, undo
from dibekho.core import reset as reset_mod
from dibekho.core.receipts import SUPPLIER, NewProduct, ReceiptInput, ReceiptLineInput
from dibekho.core.stock import (
    MAIN,
    OFFICE,
    Line,
    close_document,
    record_trial_use,
    stock_count,
    stock_levels,
)
from dibekho.core.stock import transfer as move_goods
from dibekho.core.text import parse_number
from dibekho.core.workspace import Config, Workspace
from dibekho.excel.delivery_note import DeliveryNoteError, read_delivery_note
from tests.conftest import make_note

LINE_A = ("背水涂\nvữa chống thấm", "10KG/thùng", 3, "")
LINE_B = ("固沙剂\nchất cố định cát", "10KG/thùng", 2, "")
DAY = "05-10-2026"


def learn_all(conn, ws):
    deliveries.scan(conn, ws)
    for line in deliveries.unknown_lines(conn, ws):
        deliveries.create_product_for_line(conn, line)
    return deliveries.scan(conn, ws)


def pid_of(conn, name_part):
    return conn.execute("SELECT id FROM products WHERE name_vi LIKE ?", (f"%{name_part}%",)).fetchone()[0]


def total(conn, pid):
    return stock_levels(conn).get(pid, 0.0)


def check_ledger(conn):
    """Invariants that must hold after anything: total = Kho tổng + Văn phòng, and the all-time statistics end
    on the current stock."""
    levels = stock_levels(conn)
    placed = stock_levels(conn, by_location=True)
    for pid, qty in levels.items():
        assert abs(qty - placed.get((pid, MAIN), 0) - placed.get((pid, OFFICE), 0)) < 1e-6
    rows = stats.summary(conn, date(2000, 1, 1), date(2100, 1, 1))
    for r in rows:
        assert abs(r.closing - levels.get(r.product_id, 0.0)) < 1e-6, r.code
    assert conn.execute("SELECT COUNT(*) FROM stock_movements WHERE qty IS NULL").fetchone()[0] == 0


# ---- the Excel editor: notes typed by hand ------------------------------------------------------------------

@pytest.mark.parametrize("qty", ["3 thùng", "abc", "-2", "nan", "inf"])
def test_tc01_unreadable_quantity_stops_the_note_instead_of_dropping_the_line(ws, conn, qty):
    """A line whose quantity cannot be read used to be dropped with a warning nobody saw: the note imported
    without it and stock was wrong. The note must wait in Cần xử lý with the row named."""
    make_note(ws.deliveries / "a.xlsx", lines=[LINE_A, ("固沙剂\nchất cố định cát", "10KG/thùng", qty, "")])
    with pytest.raises(DeliveryNoteError, match="Dòng"):
        read_delivery_note(ws.deliveries / "a.xlsx")
    deliveries.scan(conn, ws)
    [row] = conn.execute("SELECT status, message FROM scanned_files").fetchall()
    assert row["status"] == "error" and "Dòng" in row["message"]


@pytest.mark.parametrize("qty", ["1.500", "1,500", "2.000,5"])
def test_tc02_quantity_with_thousands_dots_is_not_read_as_a_decimal(ws, qty):
    """'1.500' typed Vietnamese-style means 1500; it used to become 1.5."""
    make_note(ws.deliveries / "a.xlsx", lines=[("固沙剂\nchất cố định cát", "10KG/thùng", qty, "")])
    with pytest.raises(DeliveryNoteError):
        read_delivery_note(ws.deliveries / "a.xlsx")


def test_tc03_zero_and_blank_quantities_are_still_harmless(ws):
    make_note(ws.deliveries / "a.xlsx", lines=[LINE_A, ("Hàng tặng", "", 0, ""), ("Dòng trống", "", " ", "")])
    note = read_delivery_note(ws.deliveries / "a.xlsx")
    assert [ln.qty for ln in note.lines] == [3]


def test_tc04_decimal_quantities_typed_as_text_still_work(ws):
    make_note(ws.deliveries / "a.xlsx", lines=[("Sơn", "5KG", "2,5", ""), ("Keo", "1KG", "1.5", "")])
    assert [ln.qty for ln in read_delivery_note(ws.deliveries / "a.xlsx").lines] == [2.5, 1.5]


def test_tc05_total_words_in_a_line_note_do_not_cut_the_table(ws):
    """'Tổng cộng' / 'người giao hàng' written in the Ghi chú cell of a goods line ended the table there and
    silently dropped every line below it."""
    make_note(ws.deliveries / "a.xlsx", lines=[
        ("背水涂\nvữa chống thấm", "10KG/thùng", 3, "người giao hàng thu tiền"),
        ("固沙剂\nchất cố định cát", "10KG/thùng", 2, "tổng cộng 2 thùng"),
        ("Keo", "1KG", 4, ""),
    ])
    assert [ln.qty for ln in read_delivery_note(ws.deliveries / "a.xlsx").lines] == [3, 2, 4]


# ---- the careless clerk: copies, renames, deletes ------------------------------------------------------------

def test_tc06_same_note_copied_three_times_counts_once(conn, ws):
    src = make_note(ws.deliveries / "a.xlsx", lines=[LINE_A])
    for rel in ("ban sao.xlsx", "2026-10/a.xlsx", "Zalo/phiếu (1).xlsx"):
        (ws.deliveries / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, ws.deliveries / rel)
    learn_all(conn, ws)
    for _ in range(5):  # F5 pressed again and again
        deliveries.scan(conn, ws)
    assert total(conn, pid_of(conn, "vữa")) == -3
    assert deliveries.pending_count(conn) == 0
    check_ledger(conn)


def test_tc07_file_that_cannot_be_read_right_now_is_not_reported_missing(conn, ws, monkeypatch):
    """A note open in another program / not yet downloaded by OneDrive cannot be hashed for a moment: it is
    still there, so it must not show up as 'file lost'."""
    make_note(ws.deliveries / "a.xlsx", lines=[LINE_A])
    learn_all(conn, ws)
    real = deliveries.file_hash
    monkeypatch.setattr(deliveries, "file_hash", lambda p: (_ for _ in ()).throw(PermissionError("locked")))
    deliveries.scan(conn, ws)
    monkeypatch.setattr(deliveries, "file_hash", real)
    assert conn.execute("SELECT status FROM scanned_files").fetchone()[0] == "imported"
    assert deliveries.pending_count(conn) == 0


def test_tc08_restore_a_lost_note_whose_stored_copy_is_gone_gives_a_plain_message(conn, ws):
    path = make_note(ws.deliveries / "a.xlsx", lines=[LINE_A])
    learn_all(conn, ws)
    h = deliveries.file_hash(ws.deliveries_done / "a.xlsx")
    (ws.deliveries_done / "a.xlsx").unlink()
    deliveries.scan(conn, ws)
    (ws.originals / f"{h}.xlsx").unlink()
    with pytest.raises(ValueError, match="bản sao"):
        deliveries.restore_missing(conn, ws, h)
    assert not path.exists()


def test_tc09_delete_restore_delete_cancel_keeps_stock_right(conn, ws):
    make_note(ws.deliveries / "a.xlsx", lines=[LINE_A])
    learn_all(conn, ws)
    pid = pid_of(conn, "vữa")
    done = ws.deliveries_done / "a.xlsx"
    h = deliveries.file_hash(done)
    done.unlink()
    deliveries.scan(conn, ws)
    assert total(conn, pid) == -3
    deliveries.restore_missing(conn, ws, h)
    deliveries.scan(conn, ws)
    for f in ws.deliveries.rglob("*.xlsx"):
        f.unlink()
    deliveries.scan(conn, ws)
    deliveries.cancel_missing(conn, h)
    deliveries.scan(conn, ws)
    assert total(conn, pid) == 0
    assert deliveries.pending_count(conn) == 0
    check_ledger(conn)


# ---- the Excel editor: notes changed after they were recorded ------------------------------------------------

def test_tc10_note_edited_twice_after_import(conn, ws):
    path = make_note(ws.deliveries / "a.xlsx", lines=[LINE_A])
    learn_all(conn, ws)
    pid = pid_of(conn, "vữa")
    for qty in (5, 7):
        for f in ws.deliveries.rglob("*.xlsx"):
            f.unlink()
        make_note(path, lines=[(LINE_A[0], LINE_A[1], qty, "")])
        deliveries.scan(conn, ws)
        [h] = [r[0] for r in conn.execute("SELECT hash FROM scanned_files WHERE status = 'changed'")]
        deliveries.replace_changed(conn, ws, h)
        deliveries.scan(conn, ws)
        assert total(conn, pid) == -qty
    assert deliveries.pending_count(conn) == 0
    check_ledger(conn)


def test_tc11_partly_approved_note_edited_then_finished_leaves_nothing_waiting(conn, ws):
    """Partly approved note (one line known), then edited in Excel, 'use the new version', then the last line
    approved: Cần xử lý must end empty (the old version's row used to stay 'waiting' forever)."""
    make_note(ws.deliveries / "x.xlsx", code="1", lines=[LINE_A])
    learn_all(conn, ws)  # LINE_A is known now
    path = make_note(ws.deliveries / "a.xlsx", code="2", lines=[LINE_A, LINE_B])
    deliveries.scan(conn, ws, allow_partial=True)
    assert conn.execute("SELECT COUNT(*) FROM documents WHERE code = '2'").fetchone()[0] == 1
    path.unlink()
    make_note(path, code="2", lines=[(LINE_A[0], LINE_A[1], 4, ""), LINE_B])
    deliveries.scan(conn, ws)
    [h] = [r[0] for r in conn.execute("SELECT hash FROM scanned_files WHERE status = 'changed'")]
    deliveries.replace_changed(conn, ws, h)
    learn_all(conn, ws)
    assert deliveries.pending_count(conn) == 0
    assert total(conn, pid_of(conn, "vữa")) == -7 and total(conn, pid_of(conn, "cát")) == -2
    check_ledger(conn)


def test_tc12_reread_whole_note_fails_cleanly_when_a_related_note_has_no_file(conn, ws):
    """'Đọc lại cả phiếu' rereads every note sharing a name. If one of them can no longer be read (file and
    stored copy gone), nothing may change: the names were forgotten and half the notes reread before."""
    make_note(ws.deliveries / "a.xlsx", code="1", lines=[LINE_A])
    make_note(ws.deliveries / "b.xlsx", code="2", lines=[LINE_A])
    learn_all(conn, ws)
    doc_a, doc_b = (r[0] for r in conn.execute("SELECT id FROM documents ORDER BY code"))
    hb = conn.execute("SELECT source_hash FROM documents WHERE id = ?", (doc_b,)).fetchone()[0]
    (ws.deliveries_done / "b.xlsx").unlink()
    (ws.originals / f"{hb}.xlsx").unlink()
    before = stock_levels(conn)
    with pytest.raises(ValueError):
        deliveries.forget_order(conn, ws, doc_a)
    assert stock_levels(conn) == before
    assert catalog.alias_product(conn, read_delivery_note(ws.deliveries_done / "a.xlsx").lines[0].key)
    assert conn.execute("SELECT COUNT(*) FROM documents WHERE status = 'active'").fetchone()[0] == 2


# ---- the hurried user: double clicks, wrong buttons ----------------------------------------------------------

def make_products(conn, n=3):
    with db.transaction(conn):
        return [catalog.create_product(conn, f"Sơn thử {i}", f"涂料{i}", "20KG", unit="thùng") for i in range(n)]


def test_tc13_same_new_product_twice_in_one_receipt_is_refused(conn):
    data = ReceiptInput(date(2026, 10, 1), SUPPLIER, supplier_name="Nhà cung cấp A", lines=[
        ReceiptLineInput(5, new=NewProduct("Keo mới", "新胶", "5KG")),
        ReceiptLineInput(3, new=NewProduct("keo  mới", "", "5kg")),
    ])
    assert receipts.problems(data)
    with pytest.raises(ValueError):
        receipts.save(conn, data)
    assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0


def test_tc14_edit_or_transfer_cannot_replace_a_document_of_another_kind(conn, ws):
    make_note(ws.deliveries / "a.xlsx", lines=[LINE_A])
    learn_all(conn, ws)
    doc = conn.execute("SELECT id FROM documents WHERE kind = 'delivery'").fetchone()[0]
    pid = pid_of(conn, "vữa")
    with pytest.raises(ValueError), db.transaction(conn):
        move_goods(conn, date(2026, 10, 6), MAIN, OFFICE, [Line(pid, 1)], replaces=doc)
    data = ReceiptInput(date(2026, 10, 6), SUPPLIER, supplier_name="NCC", lines=[ReceiptLineInput(1, pid)])
    with pytest.raises(ValueError):
        receipts.save(conn, data, replaces=doc)
    assert conn.execute("SELECT status FROM documents WHERE id = ?", (doc,)).fetchone()[0] == "active"
    assert total(conn, pid) == -3


def test_tc15_merge_a_product_with_itself_changes_nothing(conn, ws):
    make_note(ws.deliveries / "a.xlsx", lines=[LINE_A])
    learn_all(conn, ws)
    pid = pid_of(conn, "vữa")
    with pytest.raises(ValueError), db.transaction(conn):
        catalog.merge_products(conn, pid, pid)
    assert conn.execute("SELECT COUNT(*) FROM products WHERE id = ?", (pid,)).fetchone()[0] == 1
    assert total(conn, pid) == -3


def test_tc16_count_twice_the_same_day_and_cancel(conn):
    a, b, _ = make_products(conn)
    day = date(2026, 10, 1)
    with db.transaction(conn):
        stock_count(conn, day, {(a, MAIN): 10, (a, OFFICE): 4, (b, MAIN): 7})
        second = stock_count(conn, day, {(a, MAIN): 12})
    assert stock_levels(conn, by_location=True)[(a, MAIN)] == 12
    assert total(conn, a) == 16
    with db.transaction(conn):
        close_document(conn, second)
    assert total(conn, a) == 14
    with pytest.raises(ValueError), db.transaction(conn):
        close_document(conn, second)  # double click on Huỷ phiếu
    check_ledger(conn)


@pytest.mark.parametrize("text", ["nan", "inf", "-inf", "1e999"])
def test_tc17_typed_number_that_is_not_a_real_number_is_refused(text):
    """'Tồn ban đầu', counted quantities, master data... all go through parse_number: NaN/infinity would
    crash the save (NOT NULL) or put infinity into the stock."""
    with pytest.raises(ValueError):
        parse_number(text)


# ---- two machines --------------------------------------------------------------------------------------------

def two_machines(tmp_path):
    ws_a, ws_b = Workspace(tmp_path / "Máy A"), Workspace(tmp_path / "Máy B có dấu")
    ws_a.ensure()
    ws_b.ensure()
    conn_a = db.connect(ws_a.db_path)
    make_note(ws_a.deliveries / "a.xlsx", lines=[LINE_A])
    learn_all(conn_a, ws_a)
    pid = pid_of(conn_a, "vữa")
    with db.transaction(conn_a):
        stock_count(conn_a, date(2026, 10, 1), {(pid, MAIN): 20, (pid, OFFICE): 5})
        move_goods(conn_a, date(2026, 10, 7), MAIN, OFFICE, [Line(pid, 2)])
    return ws_a, ws_b, conn_a, Config(workspace=str(ws_a.root), device_id="a1", device_name="MayA")


def test_tc18_package_roundtrip_keeps_each_place(tmp_path):
    ws_a, ws_b, conn_a, cfg = two_machines(tmp_path)
    pkg = transfer.export_package(conn_a, ws_a, cfg)
    db.connect(ws_b.db_path).close()
    m = transfer.import_package(ws_b, pkg)
    conn_b = db.connect(ws_b.db_path)
    transfer.after_import(conn_b, m)
    assert stock_levels(conn_b, by_location=True) == stock_levels(conn_a, by_location=True)
    check_ledger(conn_b)


def test_tc19_truncated_package_is_refused_and_data_kept(tmp_path):
    ws_a, ws_b, conn_a, cfg = two_machines(tmp_path)
    pkg = transfer.export_package(conn_a, ws_a, cfg)
    broken = ws_b.input / "goi hong.dibekho"
    broken.write_bytes(pkg.read_bytes()[: pkg.stat().st_size // 2])
    conn_b = db.connect(ws_b.db_path)
    with db.transaction(conn_b):
        catalog.create_product(conn_b, "Hàng máy B")
    conn_b.close()
    with pytest.raises(Exception):
        transfer.import_package(ws_b, broken)
    conn_b = db.connect(ws_b.db_path)
    assert conn_b.execute("SELECT name_vi FROM products").fetchone()[0] == "Hàng máy B"


@pytest.mark.parametrize("manifest", [[1, 2], {"schema_version": "9"}, {"schema_version": None}, "x"])
def test_tc20_damaged_manifest_is_a_plain_error_not_a_crash(tmp_path, manifest):
    path = tmp_path / "goi.dibekho"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("kho.sqlite", b"")
    with pytest.raises(transfer.TransferError):
        transfer.read_manifest(path)


@pytest.mark.parametrize("content", ["empty", "not_dibekho"])
def test_tc21_package_without_real_data_never_replaces_the_database(tmp_path, content):
    """An empty or foreign kho.sqlite in a package was 'upgraded' into a brand-new empty database and replaced
    all the data of the receiving machine."""
    ws_a, ws_b, conn_a, cfg = two_machines(tmp_path)
    pkg = transfer.export_package(conn_a, ws_a, cfg)
    fake = tmp_path / "fake.sqlite"
    if content == "not_dibekho":
        other = sqlite3.connect(fake)
        other.execute("CREATE TABLE t(x)")
        other.commit()
        other.close()
    else:
        fake.write_bytes(b"")
    bad = tmp_path / "bad.dibekho"
    with zipfile.ZipFile(pkg) as src, zipfile.ZipFile(bad, "w") as dst:
        dst.writestr("manifest.json", src.read("manifest.json"))
        dst.write(fake, "kho.sqlite")
    conn_b = db.connect(ws_b.db_path)
    with db.transaction(conn_b):
        catalog.create_product(conn_b, "Hàng máy B")
    conn_b.close()
    with pytest.raises(transfer.TransferError):
        transfer.import_package(ws_b, bad)
    conn_b = db.connect(ws_b.db_path)
    assert conn_b.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1


def test_tc22_failed_export_still_warns_about_unsent_work(tmp_path, monkeypatch):
    ws_a, _, conn_a, cfg = two_machines(tmp_path)
    assert transfer.has_unsent_changes(conn_a)
    monkeypatch.setattr(transfer.zipfile, "ZipFile", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        transfer.export_package(conn_a, ws_a, cfg)
    assert transfer.has_unsent_changes(conn_a)


def test_tc22b_export_failing_halfway_leaves_no_broken_package(tmp_path, monkeypatch):
    ws_a, _, conn_a, cfg = two_machines(tmp_path)
    monkeypatch.setattr(transfer, "original_files", lambda ws: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        transfer.export_package(conn_a, ws_a, cfg)
    assert list(ws_a.output.glob("*.dibekho")) == []


# ---- undo, reset, start-up -----------------------------------------------------------------------------------

def test_tc23_undo_pressed_25_times(tmp_path):
    ws = Workspace(tmp_path / "W")
    ws.ensure()
    conn = db.connect(ws.db_path)
    for i in range(25):
        undo.mark(conn, ws, "product")
        with db.transaction(conn):
            catalog.create_product(conn, f"Hàng {i}")
    conn.close()
    steps = 0
    while (p := undo.latest(ws)) is not None:
        undo.undo(ws, p)
        steps += 1
    assert steps == undo.KEEP
    conn = db.connect(ws.db_path)
    assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 25 - undo.KEEP


def test_tc24_reset_stock_then_scan_gives_the_same_numbers(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="1", lines=[LINE_A])
    make_note(ws.deliveries / "2026-10/b.xlsx", code="2", lines=[LINE_A, LINE_B])
    learn_all(conn, ws)
    before = stock_levels(conn)
    reset_mod.reset_stock(conn, ws)
    assert stock_levels(conn) == {}
    deliveries.scan(conn, ws)
    assert stock_levels(conn) == before


def test_tc25_missing_workspace_at_start_is_not_silently_recreated(tmp_path):
    """The data folder on a USB stick / network drive that is not plugged in: the app must say so, not open an
    empty database (nor forget the settings)."""
    from dibekho.core.workspace import workspace_missing

    ws = Workspace(tmp_path / "USB" / "DiBeKho")
    assert workspace_missing(ws, configured=True)
    assert not workspace_missing(ws, configured=False)  # first start: creating it is the point
    ws.ensure()
    db.connect(ws.db_path).close()
    assert not workspace_missing(ws, configured=True)


def test_tc26_second_copy_of_the_app_is_refused(tmp_path):
    """Double-clicking the icon twice opened two windows on one database (undo/restore/import in one of them
    pulls the file from under the other)."""
    from dibekho.ui.single_instance import acquire

    ws = Workspace(tmp_path / "W")
    ws.ensure()
    first = acquire(ws)
    assert first is not None
    assert acquire(ws) is None
    first.unlock()
    again = acquire(ws)
    assert again is not None
    # the workspace copied to another computer while the app was open: its lock names that computer and must
    # not keep the app closed forever here
    lines = (ws.data / "dibekho.lock").read_bytes().split(b"\n")
    again.unlock()
    lines[2] = b"MAY-KHAC"
    (ws.data / "dibekho.lock").write_bytes(b"\n".join(lines))
    moved = acquire(ws)
    assert moved is not None
    moved.unlock()


def test_tc27_old_excel_format_is_reported_not_ignored(conn, ws):
    """A note saved as .xls (Excel 97-2003) was skipped without a word: the order never came in."""
    (ws.deliveries / "phieu cu.xls").write_bytes(b"\xd0\xcf\x11\xe0 old excel")
    deliveries.scan(conn, ws)
    [row] = conn.execute("SELECT status, message FROM scanned_files").fetchall()
    assert row["status"] == "error" and ".xlsx" in row["message"]
    deliveries.dismiss_error(conn, conn.execute("SELECT hash FROM scanned_files").fetchone()[0])
    deliveries.scan(conn, ws)
    assert deliveries.pending_count(conn) == 0


def test_tc28_master_data_file_with_garbage_rows(conn, ws, tmp_path):
    from dibekho.excel import master_data

    a, b, _ = make_products(conn)
    path = master_data.export(tmp_path / "goc.xlsx", conn)
    wb = openpyxl.load_workbook(path)
    prod, _, stock_ws = wb.worksheets
    prod.append(list(next(prod.iter_rows(min_row=5, max_row=5, values_only=True))))  # copied row, same code
    prod.append([None] * 10)
    stock_ws.cell(5, 5).value = "mười"   # text in the stock column
    stock_ws.cell(6, 5).value = -4
    stock_ws.append([None, None, None, None, None])
    wb.save(path)
    result = catalog.import_master(conn, *master_data.read(path), stock_date=date(2026, 10, 1))
    assert len(result["renumbered"]) == 1
    assert conn.execute("SELECT COUNT(DISTINCT code) FROM products").fetchone()[0] == 4
    check_ledger(conn)


# ---- the fuzzer ----------------------------------------------------------------------------------------------

def test_tc29_three_hundred_random_actions_keep_the_ledger_right(conn, ws):
    rng = random.Random(20261108)
    prods = make_products(conn, 5)
    start = date(2026, 9, 1)
    made = []
    for step in range(300):
        day = start + timedelta(days=rng.randrange(60))
        pid = rng.choice(prods)
        op = rng.choice(["receipt", "transfer", "trial", "count", "cancel", "edit_transfer", "place", "note"])
        try:
            with db.transaction(conn):
                if op == "transfer":
                    src = rng.choice([MAIN, OFFICE])
                    made.append(move_goods(conn, day, src, OFFICE if src == MAIN else MAIN,
                                           [Line(pid, rng.randint(1, 5))]))
                elif op == "trial":
                    made.append(record_trial_use(conn, day, rng.choice([MAIN, OFFICE]), [Line(pid, 1)]))
                elif op == "count":
                    made.append(stock_count(conn, day, {(pid, rng.choice([MAIN, OFFICE])): rng.randint(0, 50)}))
                elif op == "cancel" and made:
                    doc = rng.choice([d for d in made if d])
                    close_document(conn, doc)
                elif op == "edit_transfer":
                    ids = [r[0] for r in conn.execute(
                        "SELECT id FROM documents WHERE kind = 'transfer' AND status = 'active'")]
                    if ids:
                        made.append(move_goods(conn, day, OFFICE, MAIN, [Line(pid, 1)], replaces=rng.choice(ids)))
                elif op == "note":
                    pass
        except ValueError:
            pass  # refused (e.g. cancelling a cancelled document): fine, but nothing may be half done
        if op == "receipt":  # has its own transaction
            made.append(receipts.save(conn, ReceiptInput(day, SUPPLIER, supplier_name="NCC",
                                                         lines=[ReceiptLineInput(rng.randint(1, 30), pid)],
                                                         location_id=rng.choice([MAIN, OFFICE]))))
        if op == "place":
            ids = [r[0] for r in conn.execute("SELECT id FROM documents WHERE kind = 'receipt'")]
            if ids:
                with db.transaction(conn):
                    from dibekho.core.stock import set_location
                    set_location(conn, rng.choice(ids), rng.choice([MAIN, OFFICE]))
        check_ledger(conn)
    # cancel everything still active: every product must be back to 0
    with db.transaction(conn):
        for (doc,) in conn.execute("SELECT id FROM documents WHERE status = 'active'").fetchall():
            close_document(conn, doc)
    assert all(abs(v) < 1e-9 for v in stock_levels(conn).values())
    check_ledger(conn)


# ---- decisions after the QA run (2026-11-08): reused order codes, notes read after a stock count ------------

def test_tc30_reused_order_code_can_be_imported_as_another_order(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="1", customer="Công ty A", phone="0900 000 001", lines=[LINE_A])
    learn_all(conn, ws)
    path_b = make_note(ws.deliveries / "b.xlsx", code="1", customer="Công ty B", phone="0900 000 002",
                       day="20-12-2026", lines=[(LINE_A[0], LINE_A[1], 2, "")])
    deliveries.scan(conn, ws)
    row = conn.execute("SELECT hash, message FROM scanned_files WHERE status = 'changed'").fetchone()
    assert "ĐƠN KHÁC" in row["message"] and "khác khách hàng" in row["message"]
    assert deliveries.looks_like_other_order(conn, ws, row["hash"])
    deliveries.import_separately(conn, ws, row["hash"])
    deliveries.scan(conn, ws)
    pid = pid_of(conn, "vữa")
    assert total(conn, pid) == -5 and deliveries.pending_count(conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM documents WHERE status = 'active'").fetchone()[0] == 2
    # B's note edited later: it replaces B's order, never A's
    for f in ws.deliveries.rglob("b.xlsx"):
        f.unlink()
    make_note(path_b, code="1", customer="Công ty B", phone="0900 000 002", day="20-12-2026",
              lines=[(LINE_A[0], LINE_A[1], 4, "")])
    deliveries.scan(conn, ws)
    [h] = [r[0] for r in conn.execute("SELECT hash FROM scanned_files WHERE status = 'changed'")]
    assert not deliveries.looks_like_other_order(conn, ws, h)  # same customer: an edit
    deliveries.replace_changed(conn, ws, h)
    deliveries.scan(conn, ws)
    assert total(conn, pid) == -7 and deliveries.pending_count(conn) == 0
    customers = [r[0] for r in conn.execute(
        "SELECT c.name FROM documents d JOIN customers c ON c.id = d.customer_id WHERE d.status = 'active' "
        "ORDER BY c.name")]
    assert customers == ["Công ty A", "Công ty B"]
    check_ledger(conn)


def test_tc30b_edit_of_the_same_order_is_not_called_another_order(conn, ws):
    path = make_note(ws.deliveries / "a.xlsx", code="1", lines=[LINE_A])
    learn_all(conn, ws)
    for f in ws.deliveries.rglob("a.xlsx"):
        f.unlink()
    make_note(path, code="1", day="07-10-2026", lines=[(LINE_A[0], LINE_A[1], 5, "")])
    deliveries.scan(conn, ws)
    row = conn.execute("SELECT hash, message FROM scanned_files WHERE status = 'changed'").fetchone()
    assert "ĐƠN KHÁC" not in row["message"]
    assert not deliveries.looks_like_other_order(conn, ws, row["hash"])


def test_tc30c_another_order_with_only_unknown_names_waits_then_comes_in(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="1", customer="Công ty A", lines=[LINE_A])
    learn_all(conn, ws)
    make_note(ws.deliveries / "b.xlsx", code="1", customer="Công ty B", phone="0900 000 009", lines=[LINE_B])
    deliveries.scan(conn, ws)
    [h] = [r[0] for r in conn.execute("SELECT hash FROM scanned_files WHERE status = 'changed'")]
    deliveries.import_separately(conn, ws, h)
    assert deliveries.pending_count(conn) == 1
    learn_all(conn, ws)
    assert total(conn, pid_of(conn, "cát")) == -2 and total(conn, pid_of(conn, "vữa")) == -3
    assert deliveries.pending_count(conn) == 0
    check_ledger(conn)


def _note_after_count(conn, ws):
    """Order 1 (05/10) recorded before the count of 06/10; order 2, also dated 05/10, read after it."""
    from dibekho.core.stock import set_location

    make_note(ws.deliveries / "a.xlsx", code="1", lines=[LINE_A])
    learn_all(conn, ws)
    pid = pid_of(conn, "vữa")
    with db.transaction(conn):
        set_location(conn, 1, MAIN)
        conn.execute("UPDATE documents SET created_at = '2026-10-05 09:00:00'")
        stock_count(conn, date(2026, 10, 6), {(pid, MAIN): 10})
        conn.execute("UPDATE documents SET created_at = '2026-10-06 17:00:00' WHERE kind = 'stock_count'")
    make_note(ws.deliveries / "b.xlsx", code="2", lines=[LINE_A])
    deliveries.scan(conn, ws)
    return pid


def test_tc31_note_read_after_a_count_is_listed_and_the_count_can_win(conn, ws):
    from dibekho.core.stock import set_location

    pid = _note_after_count(conn, ws)
    assert deliveries.count_conflicts(conn) == []  # its place is not chosen yet
    doc = conn.execute("SELECT id FROM documents WHERE code = '2'").fetchone()[0]
    with db.transaction(conn):
        set_location(conn, doc, MAIN)
    [c] = deliveries.count_conflicts(conn)
    assert (c["code"], c["count_date"]) == ("2", "2026-10-06")
    assert stock_levels(conn, by_location=True)[(pid, MAIN)] == 7
    deliveries.keep_counted(conn, doc)
    assert stock_levels(conn, by_location=True)[(pid, MAIN)] == 10
    assert deliveries.count_conflicts(conn) == []
    deliveries.reread_document(conn, ws, doc)  # read again later: still decided, stock unchanged
    deliveries.scan(conn, ws)
    assert deliveries.count_conflicts(conn) == [] and total(conn, pid) == 10
    check_ledger(conn)


def test_tc31b_or_the_order_stays_subtracted(conn, ws):
    from dibekho.core.stock import set_location

    pid = _note_after_count(conn, ws)
    doc = conn.execute("SELECT id FROM documents WHERE code = '2'").fetchone()[0]
    with db.transaction(conn):
        set_location(conn, doc, MAIN)
    deliveries.subtract_too(conn, doc)
    assert deliveries.count_conflicts(conn) == [] and total(conn, pid) == 7


def test_tc30d_separate_order_read_again_stays_separate(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="1", customer="Công ty A", lines=[LINE_A])
    learn_all(conn, ws)
    make_note(ws.deliveries / "b.xlsx", code="1", customer="Công ty B", phone="0900 000 009",
              lines=[(LINE_A[0], LINE_A[1], 2, "")])
    deliveries.scan(conn, ws)
    [h] = [r[0] for r in conn.execute("SELECT hash FROM scanned_files WHERE status = 'changed'")]
    deliveries.import_separately(conn, ws, h)
    b = conn.execute("SELECT id FROM documents WHERE source_hash = ? AND status = 'active'", (h,)).fetchone()[0]
    deliveries.reread_document(conn, ws, b)
    deliveries.scan(conn, ws)
    assert deliveries.pending_count(conn) == 0
    assert total(conn, pid_of(conn, "vữa")) == -5
    assert conn.execute("SELECT COUNT(*) FROM documents WHERE status = 'active' AND code = '1'").fetchone()[0] == 2


def _place(conn, code, loc):
    from dibekho.core.stock import set_location

    doc = conn.execute("SELECT id FROM documents WHERE code = ? AND status = 'active'", (code,)).fetchone()[0]
    with db.transaction(conn):
        set_location(conn, doc, loc)
    return doc


def test_tc31c_keep_counted_does_not_wipe_a_receipt_entered_after_the_count(conn, ws):
    pid = _note_after_count(conn, ws)
    receipts.save(conn, ReceiptInput(date(2026, 10, 6), SUPPLIER, supplier_name="NCC",
                                     lines=[ReceiptLineInput(5, pid)], location_id=MAIN))
    doc = _place(conn, "2", MAIN)
    assert stock_levels(conn, by_location=True)[(pid, MAIN)] == 12
    deliveries.keep_counted(conn, doc)
    assert stock_levels(conn, by_location=True)[(pid, MAIN)] == 15  # 10 counted + 5 received, order 2 undone
    check_ledger(conn)


def test_tc31d_keep_counted_leaves_the_decision_on_another_late_order(conn, ws):
    pid = _note_after_count(conn, ws)
    make_note(ws.deliveries / "c.xlsx", code="3", lines=[LINE_A])
    deliveries.scan(conn, ws)
    two, three = _place(conn, "2", MAIN), _place(conn, "3", MAIN)
    assert len(deliveries.count_conflicts(conn)) == 2
    deliveries.subtract_too(conn, two)
    deliveries.keep_counted(conn, three)
    assert stock_levels(conn, by_location=True)[(pid, MAIN)] == 7  # 10 counted − order 2
    assert deliveries.count_conflicts(conn) == []


def test_tc31e_order_from_a_place_that_was_not_counted_is_not_listed(conn, ws):
    _note_after_count(conn, ws)  # only Kho tổng was counted
    _place(conn, "2", OFFICE)
    assert deliveries.count_conflicts(conn) == []
