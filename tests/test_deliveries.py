import unicodedata
from datetime import date

from dibekho import db
from dibekho.core import catalog, deliveries
from dibekho.core.stock import stock_levels
from tests.conftest import make_note

LINE_A = ("背水涂\nvữa chống thấm", "10KG/thùng", 3, "")
LINE_B = ("固沙剂\nchất cố định cát", "10KG/thùng", 2, "")


def map_everything(conn, ws):
    deliveries.scan(conn, ws)
    for line in deliveries.unknown_lines(conn, ws):
        deliveries.create_product_for_line(conn, line)
    return deliveries.scan(conn, ws)


def stock_of(conn, name_part):
    pid = conn.execute("SELECT id FROM products WHERE name_vi LIKE ?", (f"%{name_part}%",)).fetchone()[0]
    return stock_levels(conn).get(pid, 0)


def test_unknown_lines_wait_for_mapping_then_import(conn, ws):
    make_note(ws.deliveries / "a.xlsx", lines=[LINE_A, LINE_B])
    first = deliveries.scan(conn, ws)
    assert first.imported == [] and first.pending == 1
    unknown = deliveries.unknown_lines(conn, ws)
    assert {u.name_zh for u in unknown} == {"背水涂", "固沙剂"}

    second = map_everything(conn, ws)
    assert second.imported == ["a.xlsx"] and second.pending == 0
    assert stock_of(conn, "vữa") == -3
    assert stock_of(conn, "cát") == -2


def test_file_name_in_nfd_is_found_again(conn, ws):
    """'phiếu giao hàng.xlsx' written in NFD (accents as separate marks, from a Mac or a chat app) is another
    name for Windows than the NFC rel_path stored: the waiting lines must still be listed and importable."""
    name = unicodedata.normalize("NFD", "phiếu giao hàng đơn số 113.xlsx")
    make_note(ws.deliveries / name, lines=[LINE_A])
    assert deliveries.scan(conn, ws).pending == 1
    [u] = deliveries.unknown_lines(conn, ws)
    assert deliveries.note_path(ws, u.files[0]).exists()
    deliveries.create_product_for_line(conn, u, opening=10)
    assert deliveries.scan(conn, ws).pending == 0
    assert stock_of(conn, "vữa") == 7


def test_rescan_never_double_counts(conn, ws):
    make_note(ws.deliveries / "a.xlsx", lines=[LINE_A])
    map_everything(conn, ws)
    for _ in range(3):
        assert deliveries.scan(conn, ws).imported == []
    assert stock_of(conn, "vữa") == -3


def test_learned_alias_is_reused(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="1", lines=[LINE_A])
    map_everything(conn, ws)
    spaced = ("背水涂 \n vữa  chống thấm", "10kg/ thùng", 4, "")
    make_note(ws.deliveries / "thang10" / "b.xlsx", code="2", lines=[spaced])
    result = deliveries.scan(conn, ws)
    assert result.imported == ["thang10/b.xlsx"]
    assert stock_of(conn, "vữa") == -7


def test_same_file_copied_twice_counts_once(conn, ws):
    p = make_note(ws.deliveries / "a.xlsx", lines=[LINE_A])
    content = p.read_bytes()
    map_everything(conn, ws)
    (ws.deliveries / "copy.xlsx").write_bytes(content)
    deliveries.scan(conn, ws)
    assert stock_of(conn, "vữa") == -3
    assert (ws.deliveries_done / "copy.xlsx").exists()  # same content: also done


def test_same_code_different_content_asks_user(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="74", lines=[LINE_A])
    map_everything(conn, ws)
    edited = make_note(ws.deliveries / "a_sua.xlsx", code="074", lines=[(*LINE_A[:2], 5, "")])
    result = deliveries.scan(conn, ws)
    assert result.pending == 1
    [row] = deliveries.pending_files(conn)
    assert row["status"] == "changed"
    assert stock_of(conn, "vữa") == -3  # nothing changes until the user decides

    deliveries.replace_changed(conn, ws, deliveries.file_hash(edited))
    assert stock_of(conn, "vữa") == -5
    statuses = [r[0] for r in conn.execute("SELECT status FROM documents ORDER BY id")]
    assert statuses == ["replaced", "active"]


def test_keep_old_version(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="74", lines=[LINE_A])
    map_everything(conn, ws)
    edited = make_note(ws.deliveries / "b.xlsx", code="74", lines=[(*LINE_A[:2], 9, "")])
    deliveries.scan(conn, ws)
    deliveries.keep_old(conn, deliveries.file_hash(edited))
    assert deliveries.scan(conn, ws).pending == 0
    assert stock_of(conn, "vữa") == -3


def test_deleted_file_keeps_stock_and_can_be_restored(conn, ws):
    make_note(ws.deliveries / "a.xlsx", lines=[LINE_A])
    map_everything(conn, ws)
    p = ws.deliveries_done / "a.xlsx"
    h = deliveries.file_hash(p)
    p.unlink()

    result = deliveries.scan(conn, ws)
    assert result.pending == 1
    assert deliveries.pending_files(conn)[0]["status"] == "missing"
    assert stock_of(conn, "vữa") == -3

    restored = deliveries.restore_missing(conn, ws, h)
    assert restored.exists()
    assert deliveries.scan(conn, ws).pending == 0
    assert stock_of(conn, "vữa") == -3


def test_deleted_file_can_cancel_the_order(conn, ws):
    make_note(ws.deliveries / "a.xlsx", lines=[LINE_A])
    map_everything(conn, ws)
    p = ws.deliveries_done / "a.xlsx"
    h = deliveries.file_hash(p)
    p.unlink()
    deliveries.scan(conn, ws)
    deliveries.cancel_missing(conn, h)
    assert stock_of(conn, "vữa") == 0
    assert deliveries.scan(conn, ws).pending == 0


def test_moving_or_renaming_is_not_a_deletion(conn, ws):
    make_note(ws.deliveries / "a.xlsx", lines=[LINE_A])
    map_everything(conn, ws)
    (ws.deliveries / "2026-10").mkdir()
    (ws.deliveries_done / "a.xlsx").rename(ws.deliveries / "2026-10" / "phieu 101.xlsx")
    result = deliveries.scan(conn, ws)
    assert result.pending == 0 and result.imported == []
    assert stock_of(conn, "vữa") == -3


def test_customer_matched_by_phone(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="1", customer="Công ty A", phone="0901 234 567", lines=[LINE_A])
    make_note(ws.deliveries / "b.xlsx", code="2", customer="CÔNG TY A", phone="+84 901234567", lines=[LINE_A])
    map_everything(conn, ws)
    assert conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 1


def test_non_delivery_files_are_reported(conn, ws):
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.append(["ghi chép"])
    wb.save(ws.deliveries / "note.xlsx")
    (ws.deliveries / "~$a.xlsx").write_bytes(b"lock")
    deliveries.scan(conn, ws)
    [row] = deliveries.pending_files(conn)
    assert row["status"] == "error"


def test_guess_unit():
    assert catalog.guess_unit("10KG/Thùng") == "thùng"
    assert catalog.guess_unit("1m*20m/ cuộn") == "cuộn"
    assert catalog.guess_unit("Gói ") == "gói"


def test_dates_come_from_the_note(conn, ws):
    make_note(ws.deliveries / "a.xlsx", day="09-09-2026", lines=[LINE_A])
    map_everything(conn, ws)
    assert stock_levels(conn, as_of=date(2026, 9, 8)) == {}
    assert list(stock_levels(conn, as_of=date(2026, 9, 9)).values()) == [-3]


def test_fee_line_dropped_once_is_skipped_on_every_note(conn, ws):
    fee = ("运费\nPhí vận chuyển", "", 1, "")
    make_note(ws.deliveries / "a.xlsx", code="1", lines=[LINE_A, fee])
    deliveries.scan(conn, ws)
    lines = {u.name_vi: u for u in deliveries.unknown_lines(conn, ws)}
    assert lines["Phí vận chuyển"].is_fee and lines["Phí vận chuyển"].suggestion is None
    assert lines["Phí vận chuyển"].orders == ["1 · Công ty A · SL 1"]
    deliveries.ignore_unknown(conn, lines.pop("Phí vận chuyển"))
    for u in lines.values():
        deliveries.create_product_for_line(conn, u)
    assert deliveries.scan(conn, ws).imported == ["a.xlsx"]
    doc = conn.execute("SELECT id FROM documents").fetchone()[0]
    assert conn.execute("SELECT COUNT(*) FROM document_lines WHERE document_id = ?", (doc,)).fetchone()[0] == 1

    # a later note with the same fee line goes straight in
    make_note(ws.deliveries / "b.xlsx", code="2", lines=[LINE_A, fee])
    assert deliveries.scan(conn, ws).imported == ["b.xlsx"]
    assert stock_of(conn, "vữa") == -6


def test_unignored_line_is_asked_again(conn, ws):
    fee = ("服务费\nPhí dịch vụ", "", 1, "")
    make_note(ws.deliveries / "a.xlsx", code="1", lines=[fee])
    deliveries.scan(conn, ws)
    [u] = deliveries.unknown_lines(conn, ws)
    deliveries.ignore_unknown(conn, u)
    assert [r["label"] for r in catalog.ignored_lines(conn)] == ["Phí dịch vụ"]
    catalog.unignore_line(conn, u.key)
    make_note(ws.deliveries / "b.xlsx", code="2", lines=[fee, LINE_A])
    deliveries.scan(conn, ws)
    assert {x.name_vi for x in deliveries.unknown_lines(conn, ws)} >= {"Phí dịch vụ"}


def test_looks_like_fee():
    for name in ("Phí vận chuyển", "phi ship", "运费", "Cước xe", "服务费 Phí dịch vụ"):
        assert catalog.looks_like_fee(name), name
    for name in ("Sơn FS-101", "Phụ gia", "背水涂 vữa chống thấm"):
        assert not catalog.looks_like_fee(name), name


def test_reread_document_uses_current_names(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="7", lines=[LINE_A])
    map_everything(conn, ws)
    old = conn.execute("SELECT id FROM documents").fetchone()[0]
    assert stock_of(conn, "vữa") == -3

    deliveries.reread_document(conn, ws, old)
    assert stock_of(conn, "vữa") == 0  # reversed until it is read again
    assert deliveries.scan(conn, ws).imported == ["da-xu-ly/a.xlsx"]
    rows = conn.execute("SELECT id, status FROM documents ORDER BY id").fetchall()
    assert [r["status"] for r in rows] == ["replaced", "active"]
    assert stock_of(conn, "vữa") == -3


def test_reread_restores_a_deleted_file(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="7", lines=[LINE_A])
    map_everything(conn, ws)
    path = ws.deliveries_done / "a.xlsx"
    path.unlink()
    deliveries.scan(conn, ws)
    doc = conn.execute("SELECT id FROM documents").fetchone()[0]
    deliveries.reread_document(conn, ws, doc)
    assert path.exists()
    assert deliveries.scan(conn, ws).imported == ["da-xu-ly/a.xlsx"]


def test_forget_wrong_mapping_and_choose_again(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="1", lines=[LINE_A, LINE_B])
    make_note(ws.deliveries / "b.xlsx", code="2", lines=[LINE_B])
    map_everything(conn, ws)
    learned = {n.label: n for n in deliveries.learned_names(conn, ws)}
    b = next(n for label, n in learned.items() if "cố định cát" in label)
    assert len(b.documents) == 2

    assert deliveries.forget_name(conn, ws, b.key) == 2
    deliveries.scan(conn, ws)
    [u] = deliveries.unknown_lines(conn, ws)  # LINE_B asks again, in both notes
    assert sorted(u.files) == ["a.xlsx", "b.xlsx"]
    a_product = conn.execute("SELECT product_id FROM product_aliases WHERE label LIKE 'vữa%'").fetchone()[0]
    deliveries.map_line(conn, u.key, a_product, deliveries.line_label(u))  # this time: the other product
    assert sorted(deliveries.scan(conn, ws).imported) == ["a.xlsx", "b.xlsx"]
    assert stock_of(conn, "vữa") == -(3 + 2 + 2)


def test_forget_a_dropped_line(conn, ws):
    fee = ("运费\nPhí vận chuyển", "", 1, "")
    make_note(ws.deliveries / "a.xlsx", code="1", lines=[LINE_A, fee])
    deliveries.scan(conn, ws)
    for u in deliveries.unknown_lines(conn, ws):
        (deliveries.ignore_unknown if u.is_fee else deliveries.create_product_for_line)(conn, u)
    deliveries.scan(conn, ws)
    [dropped] = [n for n in deliveries.learned_names(conn, ws) if n.product_id is None]
    assert len(dropped.documents) == 1
    assert deliveries.forget_name(conn, ws, dropped.key) == 1
    deliveries.scan(conn, ws)
    assert [u.name_vi for u in deliveries.unknown_lines(conn, ws)] == ["Phí vận chuyển"]


def test_forget_works_for_notes_read_by_an_older_version(conn, ws):
    """Notes imported before document_skipped_lines existed: their stored copies are read once."""
    fee = ("运费\nPhí vận chuyển", "", 1, "")
    make_note(ws.deliveries / "a.xlsx", code="1", lines=[LINE_A, fee])
    deliveries.scan(conn, ws)
    for u in deliveries.unknown_lines(conn, ws):
        (deliveries.ignore_unknown if u.is_fee else deliveries.create_product_for_line)(conn, u)
    deliveries.scan(conn, ws)
    conn.execute("DELETE FROM document_skipped_lines")  # what an older version left behind
    [dropped] = [n for n in deliveries.learned_names(conn, ws) if n.product_id is None]
    assert len(dropped.documents) == 1
    assert deliveries.forget_name(conn, ws, dropped.key) == 1


def test_forget_order_rereads_the_whole_note_and_notes_sharing_a_name(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="1", lines=[LINE_A, LINE_B])
    make_note(ws.deliveries / "b.xlsx", code="2", lines=[LINE_B])
    map_everything(conn, ws)
    doc_a = conn.execute("SELECT id FROM documents WHERE code = '1'").fetchone()[0]
    doc_b = conn.execute("SELECT id FROM documents WHERE code = '2'").fetchone()[0]
    assert deliveries.documents_sharing_names(conn, doc_a) == [doc_b]
    assert deliveries.forget_order(conn, ws, doc_a) == 2  # a (its own lines) and b (shares LINE_B)
    deliveries.scan(conn, ws)
    unknown = {u.name_vi for u in deliveries.unknown_lines(conn, ws)}
    assert unknown == {"vữa chống thấm", "chất cố định cát"}
    files = sorted({f for u in deliveries.unknown_lines(conn, ws) for f in u.files})
    assert files == ["a.xlsx", "b.xlsx"]


def test_forget_order_leaves_fee_lines_dropped(conn, ws):
    fee = ("运费\nPhí vận chuyển", "", 1, "")
    make_note(ws.deliveries / "a.xlsx", code="1", lines=[LINE_A, fee])
    deliveries.scan(conn, ws)
    for u in deliveries.unknown_lines(conn, ws):
        (deliveries.ignore_unknown if u.is_fee else deliveries.create_product_for_line)(conn, u)
    deliveries.scan(conn, ws)
    doc_a = conn.execute("SELECT id FROM documents").fetchone()[0]
    assert deliveries.forget_order(conn, ws, doc_a) == 1
    deliveries.scan(conn, ws)
    assert [u.name_vi for u in deliveries.unknown_lines(conn, ws)] == ["vữa chống thấm"]  # the fee stays dropped


def test_forget_order_refuses_a_cancelled_document(conn, ws):
    import pytest

    make_note(ws.deliveries / "a.xlsx", code="1", lines=[LINE_A])
    map_everything(conn, ws)
    doc_a = conn.execute("SELECT id FROM documents").fetchone()[0]
    with db.transaction(conn):
        from dibekho.core.stock import close_document

        close_document(conn, doc_a, "cancelled")
    with pytest.raises(ValueError):
        deliveries.forget_order(conn, ws, doc_a)


LINE_NEW = ("新产品\nHàng chưa duyệt", "5KG/thùng", 4, "")


def _decide(conn, ws, keep_waiting):
    """Map every unknown line except the ones whose Vietnamese name is in keep_waiting."""
    for u in deliveries.unknown_lines(conn, ws):
        if u.name_vi not in keep_waiting:
            deliveries.create_product_for_line(conn, u)


def test_partly_approved_note_is_imported_and_completed_later(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="74", customer="Khách Chờ", lines=[LINE_A, LINE_B, LINE_NEW])
    deliveries.scan(conn, ws)
    # opening the app / rescanning never imports a waiting note on its own
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0

    _decide(conn, ws, keep_waiting={"Hàng chưa duyệt"})
    deliveries.scan(conn, ws)  # a plain rescan still does not import a partly known note
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0

    deliveries.scan(conn, ws, allow_partial=True)  # 'Apply'
    doc = conn.execute("SELECT * FROM documents").fetchone()
    assert doc["code"] == "74" and conn.execute("SELECT name FROM customers").fetchone()[0] == "Khách Chờ"
    assert conn.execute("SELECT COUNT(*) FROM document_lines").fetchone()[0] == 2
    assert stock_of(conn, "vữa") == -3 and stock_of(conn, "cố định") == -2
    assert deliveries.pending_count(conn) == 1
    assert [u.name_vi for u in deliveries.unknown_lines(conn, ws)] == ["Hàng chưa duyệt"]

    # rescanning adds nothing twice
    deliveries.scan(conn, ws, allow_partial=True)
    assert conn.execute("SELECT COUNT(*) FROM document_lines").fetchone()[0] == 2

    # the last line decided later goes into the same order
    _decide(conn, ws, keep_waiting=set())
    deliveries.scan(conn, ws)
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM document_lines").fetchone()[0] == 3
    assert stock_of(conn, "chưa duyệt") == -4
    assert deliveries.pending_count(conn) == 0


def test_partly_imported_note_deleted_and_restored_asks_again(conn, ws):
    path = make_note(ws.deliveries / "a.xlsx", code="74", lines=[LINE_A, LINE_NEW])
    deliveries.scan(conn, ws)
    _decide(conn, ws, keep_waiting={"Hàng chưa duyệt"})
    deliveries.scan(conn, ws, allow_partial=True)
    path.unlink()
    deliveries.scan(conn, ws)
    [row] = deliveries.pending_files(conn)
    assert row["status"] == "missing"
    deliveries.restore_missing(conn, ws, row["hash"])
    deliveries.scan(conn, ws)
    assert [u.name_vi for u in deliveries.unknown_lines(conn, ws)] == ["Hàng chưa duyệt"]
    assert stock_of(conn, "vữa") == -3


def test_done_notes_move_to_da_xu_ly_and_back_when_waiting_again(conn, ws):
    make_note(ws.deliveries / "2026-10" / "a.xlsx", code="1", lines=[LINE_A])
    make_note(ws.deliveries / "b.xlsx", code="2", lines=[LINE_A, ("新产品\nHàng lạ", "5KG", 1, "")])
    deliveries.scan(conn, ws)
    assert (ws.deliveries / "2026-10" / "a.xlsx").exists()  # nothing decided yet: nothing moves
    vua = next(u for u in deliveries.unknown_lines(conn, ws) if u.name_vi.startswith("vữa"))
    deliveries.create_product_for_line(conn, vua)
    deliveries.scan(conn, ws)
    # a.xlsx is fully recorded -> da-xu-ly (sub-folder kept, emptied sub-folder removed); b.xlsx still waits
    assert (ws.deliveries_done / "2026-10" / "a.xlsx").exists()
    assert not (ws.deliveries / "2026-10").exists()
    assert (ws.deliveries / "b.xlsx").exists()
    row = conn.execute("SELECT rel_path FROM scanned_files WHERE status = 'imported'").fetchone()
    assert row[0] == "da-xu-ly/2026-10/a.xlsx"
    assert deliveries.scan(conn, ws).imported == []  # nothing read twice after the move
    assert stock_of(conn, "vữa") == -3

    # a learned name forgotten -> the note needs a decision again -> back out of da-xu-ly
    deliveries.forget_name(conn, ws, vua.key)
    deliveries.scan(conn, ws)
    assert (ws.deliveries / "2026-10" / "a.xlsx").exists()


def test_reset_stock_keeps_products_and_reads_notes_again(conn, ws):
    from dibekho.core import reset
    from dibekho.core.stock import Line, insert_document

    make_note(ws.deliveries / "a.xlsx", code="1", lines=[LINE_A])
    map_everything(conn, ws)
    pid = conn.execute("SELECT id FROM products").fetchone()[0]
    with db.transaction(conn):
        insert_document(conn, "receipt", date(2026, 10, 1), [Line(pid, 10)])
    assert (ws.deliveries_done / "a.xlsx").exists()

    assert reset.reset_stock(conn, ws) == 1
    assert (ws.deliveries / "a.xlsx").exists() and not list(ws.deliveries_done.iterdir())
    for table in ("documents", "stock_movements", "scanned_files", "customers"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1
    assert list(ws.backups.glob("truoc-dat-lai-ton_*.sqlite"))
    # learned names are kept: the note goes straight in again
    assert deliveries.scan(conn, ws).imported == ["a.xlsx"]
    assert stock_of(conn, "vữa") == -3


def test_reset_all_gives_an_empty_database(ws):
    from dibekho.core import reset

    conn = db.connect(ws.db_path)
    make_note(ws.deliveries / "a.xlsx", code="1", lines=[LINE_A])
    map_everything(conn, ws)
    assert reset.reset_all(conn, ws) == 1
    conn.close()
    reset.wipe_database(ws)
    conn = db.connect(ws.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        assert (ws.deliveries / "a.xlsx").exists()
        assert list(ws.backups.glob("truoc-xoa-toan-bo_*.sqlite"))
        deliveries.scan(conn, ws)
        assert deliveries.pending_count(conn) == 1  # read again: product names unknown
    finally:
        conn.close()


def test_opening_stock_of_a_new_product_comes_before_its_notes(conn, ws):
    make_note(ws.deliveries / "a.xlsx", code="1", day="05-10-2026", lines=[LINE_A])
    make_note(ws.deliveries / "b.xlsx", code="2", day="03-10-2026", lines=[(*LINE_A[:2], 2, "")])
    deliveries.scan(conn, ws)
    [u] = deliveries.unknown_lines(conn, ws)
    assert u.first_date == date(2026, 10, 3)
    deliveries.create_product_for_line(conn, u, opening=40)
    deliveries.scan(conn, ws)
    assert stock_of(conn, "vữa") == 40 - 3 - 2  # opening stock, then both notes
    assert stock_levels(conn, as_of=date(2026, 10, 2)) == {1: 40}  # recorded the day before the first note
