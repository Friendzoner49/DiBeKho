from datetime import date

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
    map_everything(conn, ws)
    (ws.deliveries / "copy.xlsx").write_bytes(p.read_bytes())
    deliveries.scan(conn, ws)
    assert stock_of(conn, "vữa") == -3


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
    p = make_note(ws.deliveries / "a.xlsx", lines=[LINE_A])
    map_everything(conn, ws)
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
    p = make_note(ws.deliveries / "a.xlsx", lines=[LINE_A])
    map_everything(conn, ws)
    h = deliveries.file_hash(p)
    p.unlink()
    deliveries.scan(conn, ws)
    deliveries.cancel_missing(conn, h)
    assert stock_of(conn, "vữa") == 0
    assert deliveries.scan(conn, ws).pending == 0


def test_moving_or_renaming_is_not_a_deletion(conn, ws):
    p = make_note(ws.deliveries / "a.xlsx", lines=[LINE_A])
    map_everything(conn, ws)
    (ws.deliveries / "2026-10").mkdir()
    p.rename(ws.deliveries / "2026-10" / "phieu 101.xlsx")
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
    assert deliveries.scan(conn, ws).imported == ["a.xlsx"]
    rows = conn.execute("SELECT id, status FROM documents ORDER BY id").fetchall()
    assert [r["status"] for r in rows] == ["replaced", "active"]
    assert stock_of(conn, "vữa") == -3


def test_reread_restores_a_deleted_file(conn, ws):
    path = make_note(ws.deliveries / "a.xlsx", code="7", lines=[LINE_A])
    map_everything(conn, ws)
    path.unlink()
    deliveries.scan(conn, ws)
    doc = conn.execute("SELECT id FROM documents").fetchone()[0]
    deliveries.reread_document(conn, ws, doc)
    assert path.exists()
    assert deliveries.scan(conn, ws).imported == ["a.xlsx"]


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
