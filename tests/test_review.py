"""Found in the customer's data (14/10/2026), and the tools to review and undo a wrong choice."""

import openpyxl

from dibekho import db
from dibekho.core import catalog, deliveries, undo
from dibekho.core.stock import stock_levels
from dibekho.excel.delivery_note import read_delivery_note
from tests.conftest import make_note

PIPE_50 = ("管根套50-75\nBọc ống chân chống thấm 50-75", "Cái", 20, "")
PIPE_90 = ("管根套 90-110\nBọc ống chân chống thấm 90-100", "Cái", 20, "")


def pipe_collars(conn):
    with db.transaction(conn):
        for size in ("90-110", "50-75", "32-50"):
            catalog.create_product(conn, f"Bọc chống thấm cổ ống nước {size}", f"管根套{size}", size, unit="cái")
        catalog.create_product(conn, "Màng chống thấm PPE", "高分子聚乙烯涤纶防水卷材", "16.5KG", unit="cuộn")


def code_of(conn, product_id):
    return conn.execute("SELECT code FROM products WHERE id = ?", (product_id,)).fetchone()[0]


def test_the_sizes_of_the_same_product_are_suggested_first(conn):
    pipe_collars(conn)
    suggested = [p["code"] for p in catalog.suggest_products(conn, "管根套 90-110 Bọc ống chân chống thấm 90-100", "Cái")]
    assert suggested[0] == "SP001" and set(suggested) == {"SP001", "SP002", "SP003"}  # never the PPE membrane


def test_customer_name_behind_a_chinese_only_label(conn, ws):
    """'客户名称 Anh Ba': no '(Tên khách hàng)' and no colon. The name was lost and the phone number became the
    customer's name; a later note of the same customer then showed the number instead of the name."""
    path = make_note(ws.deliveries / "116.xlsx", code="116", phone="0912442118")
    wb = openpyxl.load_workbook(path)
    wb.active["A4"] = "客户名称 Anh Ba"
    wb.save(path)
    assert read_delivery_note(path).customer_name == "Anh Ba"


def test_customers_saved_under_their_phone_number_get_their_name_back(conn, ws):
    path = make_note(ws.deliveries / "116.xlsx", code="116", phone="0912442118")
    wb = openpyxl.load_workbook(path)
    wb.active["A4"] = "客户名称 Anh Ba"
    wb.save(path)
    with db.transaction(conn):
        product = catalog.create_product(conn, "vữa chống thấm", "背水涂", "10KG/thùng")
    deliveries.scan(conn, ws)
    catalog.set_alias(conn, deliveries.unknown_lines(conn, ws)[0].key, product)
    deliveries.scan(conn, ws)
    conn.execute("UPDATE customers SET name = phone")  # what the old version recorded
    assert deliveries.backfill_customers(conn, ws) == 1  # from the stored copy of the note
    assert conn.execute("SELECT name FROM customers").fetchone()[0] == "Anh Ba"
    assert deliveries.backfill_customers(conn, ws) == 0  # done once


def test_waiting_notes_show_every_line_of_the_order(conn, ws):
    pipe_collars(conn)
    make_note(ws.deliveries / "125.xlsx", code="125", lines=[PIPE_50, PIPE_90])
    deliveries.scan(conn, ws)
    known = deliveries.unknown_lines(conn, ws)[0]
    catalog.set_alias(conn, known.key, 2)  # 50-75 already learned
    [note] = deliveries.waiting_notes(conn, ws)
    assert note.code == "125" and len(note.lines) == 2
    assert [ln.product_id for ln in note.lines] == [2, None]
    assert [ln.name_zh for ln in note.unknown] == ["管根套 90-110"]


def test_learned_names_grouped_by_order_and_forget_one_line(conn, ws):
    """The customer's case: 管根套 90-110 learned as the PPE membrane. Find it under order 125, forget it,
    choose the right product: order 125 takes 20 pipe collars and the membrane gets its 20 rolls back."""
    pipe_collars(conn)
    make_note(ws.deliveries / "125.xlsx", code="125", lines=[PIPE_50, PIPE_90])
    deliveries.scan(conn, ws)
    for u in deliveries.unknown_lines(conn, ws):
        catalog.set_alias(conn, u.key, 2 if "50-75" in u.raw_name else 4)  # 90-110 -> PPE: the mistake
    deliveries.scan(conn, ws)
    [order] = deliveries.learned_by_order(conn, ws)
    assert order.code == "125" and [code_of(conn, ln.product_id) for ln in order.lines] == ["SP002", "SP004"]

    deliveries.forget_name(conn, ws, order.lines[1].key)
    deliveries.scan(conn, ws)
    [u] = deliveries.unknown_lines(conn, ws)
    catalog.set_alias(conn, u.key, 1)
    deliveries.scan(conn, ws, allow_partial=True)
    levels = {code_of(conn, pid): qty for pid, qty in stock_levels(conn).items()}
    assert levels == {"SP001": -20, "SP002": -20, "SP004": 0}


def test_undo_puts_the_data_back_step_by_step(conn, ws):
    """Undo needs a database file: the in-memory one of the other tests cannot be swapped."""
    conn = db.connect(ws.db_path)
    with db.transaction(conn):
        catalog.create_product(conn, "A", "甲", "")
    undo.mark(conn, ws, "product_add")
    with db.transaction(conn):
        catalog.create_product(conn, "B", "乙", "")
    undo.mark(conn, ws, "product_delete")
    with db.transaction(conn):
        conn.execute("DELETE FROM products")
    assert [p.action for p in undo.points(ws)] == ["product_delete", "product_add"]

    for expected in (["A", "B"], ["A"]):
        conn.close()
        undo.undo(ws, undo.latest(ws))
        conn = db.connect(ws.db_path)
        assert [r[0] for r in conn.execute("SELECT name_vi FROM products ORDER BY id")] == expected
    assert undo.latest(ws) is None
    conn.close()
