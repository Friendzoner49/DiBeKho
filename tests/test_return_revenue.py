"""Goods a customer sends back come off the revenue: the price the return takes, every screen's number, old returns."""

from datetime import date

from dibekho import db
from dibekho.core import catalog, queries, receipts, stats
from dibekho.core.receipts import RETURN, SUPPLIER, ReceiptInput, ReceiptLineInput
from dibekho.core.stock import Line, close_document, insert_document


def shop(conn):
    with db.transaction(conn):
        a = catalog.create_product(conn, "Son A", spec="20KG", unit="thung", category="Son")
        b = catalog.create_product(conn, "Mang B", spec="3mm", unit="cuon", category="Mang")
        c1 = catalog.upsert_customer(conn, "Cong ty A", phone="0900 000 001")
        c2 = catalog.upsert_customer(conn, "Khach X", phone="0900 000 002")
        insert_document(conn, "delivery", date(2026, 10, 1), [Line(a, 10, unit_price=100, amount=1000),
                                                              Line(b, 2, unit_price=50, amount=100)],
                        code="50", code_norm="50", customer_id=c1)
        insert_document(conn, "delivery", date(2026, 10, 20), [Line(a, 5, unit_price=120, amount=600)],
                        code="51", code_norm="51", customer_id=c1)
        insert_document(conn, "delivery", date(2026, 10, 3), [Line(a, 1, unit_price=90, amount=90)],
                        code="60", code_norm="60", customer_id=c2)
    return a, b, c1, c2


def give_back(conn, customer, product, qty, price, day=date(2026, 10, 25), ref=""):
    return receipts.save(conn, ReceiptInput(day, RETURN, customer_id=customer, ref_code=ref,
                                            lines=[ReceiptLineInput(qty, product, unit_price=price)]))


def test_the_price_comes_from_the_named_order_else_the_latest_purchase_before_the_return(conn):
    a, b, c1, c2 = shop(conn)
    assert receipts.return_price(conn, c1, a, "50", date(2026, 10, 25)) == 100   # the order it came back from
    assert receipts.return_price(conn, c1, a, "", date(2026, 10, 25)) == 120     # no order: the latest purchase
    assert receipts.return_price(conn, c1, a, "", date(2026, 10, 10)) == 100     # ...up to the day of the return
    assert receipts.return_price(conn, c1, a, "60", date(2026, 10, 25)) == 120   # another customer's order: ignored
    assert receipts.return_price(conn, c1, b, "51", date(2026, 10, 25)) == 50    # the order lacks it: latest purchase
    assert receipts.return_price(conn, c2, b) is None and receipts.return_price(conn, None, a) is None


def test_a_return_takes_its_money_off_every_revenue_number(conn):
    a, b, c1, c2 = shop(conn)
    doc = give_back(conn, c1, a, 2, 100, ref="50")
    row = conn.execute("SELECT unit_price, amount FROM document_lines WHERE document_id = ?", (doc,)).fetchone()
    assert tuple(row) == (100, 200)
    assert receipts.load(conn, doc).lines[0].unit_price == 100  # editing shows the price again

    by_customer = {r["name"]: r["revenue"] for r in queries.customers(conn)}
    assert by_customer == {"Cong ty A": 1500, "Khach X": 90}
    money = queries.customer_money(conn, c1)
    assert (money["orders"], money["goods"], money["returned"], money["total"]) == (2, 1700, 200, 1500)
    assert queries.customer_money(conn, c2)["returned"] == 0 and queries.customer_money(conn, c2)["total"] == 90
    # by the day of the return: October before the 25th still has the full sale
    assert queries.customer_money(conn, c1, date(2026, 10, 1), date(2026, 10, 24))["total"] == 1700
    bought = {r["id"]: r for r in queries.customer_products(conn, c1)}
    assert (bought[a]["total_qty"], bought[a]["times"], bought[a]["revenue"], bought[a]["last_date"]) == \
        (15, 2, 1400, "2026-10-20")  # quantity and orders are what was bought; only the money is netted
    assert (bought[a]["min_price"], bought[a]["max_price"]) == (100, 120)
    top = {r["name"]: (r["total_qty"], r["revenue"]) for r in queries.product_top_customers(conn, a)}
    assert top == {"Cong ty A": (15, 1400), "Khach X": (1, 90)}

    start, end = date(2026, 10, 1), date(2026, 10, 31)
    m = stats.money(conn, start, end)
    assert (m.orders, m.goods, m.returned, m.total) == (3, 1790, 200, 1590)
    assert stats.money(conn, start, end, stats.Filters(customer_ids=[c2])).returned == 0
    assert stats.money(conn, start, end, stats.Filters(product_ids=[b])).total == 100
    rows = {r.product_id: r.revenue for r in stats.summary(conn, start, end)}
    assert rows[a] == 1490 and rows[b] == 100
    pairs = {(r["customer_name"], r["code"]): r["revenue"] for r in stats.customer_product(conn, start, end)}
    assert pairs[("Cong ty A", "SP001")] == 1400
    back = [r for r in stats.detail_lines(conn, start, end) if r["doc_kind"] == "receipt"]
    assert [(r["unit_price"], r["amount"]) for r in back] == [(100, -200)]  # the sheet's money column adds up

    with db.transaction(conn):
        close_document(conn, doc)  # cancelling the return gives the revenue back
    assert stats.money(conn, start, end).total == 1790 and queries.customer_money(conn, c1)["total"] == 1700


def test_no_price_takes_nothing_off_and_a_supplier_receipt_never_does(conn):
    a, b, c1, c2 = shop(conn)
    doc = give_back(conn, c1, a, 2, None)
    receipts.save(conn, ReceiptInput(date(2026, 10, 26), SUPPLIER, supplier_name="Cua khau",
                                     lines=[ReceiptLineInput(7, a, unit_price=999)]))
    assert conn.execute("SELECT COUNT(*) FROM document_lines WHERE amount IS NOT NULL AND document_id IN "
                        "(SELECT id FROM documents WHERE kind = 'receipt')").fetchone()[0] == 0
    assert stats.money(conn, date(2026, 10, 1), date(2026, 10, 31)).total == 1790
    assert receipts.backfill_return_prices(conn) == 0  # saved with the price left empty: stays empty
    assert conn.execute("SELECT unit_price FROM document_lines WHERE document_id = ?", (doc,)).fetchone()[0] is None


def test_returns_saved_before_this_version_get_their_price_once(conn):
    a, b, c1, c2 = shop(conn)
    with db.transaction(conn):  # the way 0.5.0 wrote a return: no price, prices_read 0
        old = insert_document(conn, "receipt", date(2026, 10, 25), [Line(a, 2), Line(b, 1)], code="HV001",
                              code_norm="HV001", customer_id=c1)
        conn.execute("UPDATE documents SET receipt_source = 'return', ref_code = '50' WHERE id = ?", (old,))
        never = insert_document(conn, "receipt", date(2026, 10, 25), [Line(b, 1)], code="HV002", code_norm="HV002",
                                customer_id=c2)  # this customer never bought it: no price to find
        conn.execute("UPDATE documents SET receipt_source = 'return' WHERE id = ?", (never,))
    assert receipts.backfill_return_prices(conn) == 2
    got = conn.execute("SELECT unit_price, amount FROM document_lines WHERE document_id = ? ORDER BY line_no",
                       (old,)).fetchall()
    assert [tuple(r) for r in got] == [(100, 200), (50, 50)]
    assert queries.customer_money(conn, c1)["total"] == 1450
    with db.transaction(conn):  # the user clears a price on purpose: it is not put back
        conn.execute("UPDATE document_lines SET unit_price = NULL, amount = NULL WHERE document_id = ?", (old,))
    assert receipts.backfill_return_prices(conn) == 0
    assert queries.customer_money(conn, c1)["total"] == 1700
