"""Goods in entered in the app: supplier or customer return, new products, the Excel file, editing."""

from datetime import date

from dibekho import db
from dibekho.core import catalog, inbox, receipts
from dibekho.core.receipts import RETURN, SUPPLIER, NewProduct, ReceiptInput, ReceiptLineInput
from dibekho.core.stock import stock_levels
from dibekho.excel.receipt import read_receipt


def products(conn):
    with db.transaction(conn):
        return [catalog.create_product(conn, f"Sơn {x}", f"涂料{x}", "20KG", unit="thùng") for x in "ABCD"]


def code_of(conn, pid):
    return conn.execute("SELECT code FROM products WHERE id = ?", (pid,)).fetchone()[0]


def test_old_database_gets_the_new_columns(tmp_path):
    """A database of the previous version (schema 5) opens: older receipts have no source."""
    path = tmp_path / "old.sqlite"
    conn = db.connect(path)
    with db.transaction(conn):
        conn.execute("INSERT INTO documents(kind, doc_date) VALUES('receipt', '2026-09-01')")
    conn.close()
    conn = db.connect(path)
    row = conn.execute("SELECT receipt_source, supplier_id, ref_code FROM documents").fetchone()
    assert tuple(row) == ("", None, "")
    conn.close()


def test_receipt_from_a_supplier_with_a_new_product(conn, ws):
    a, b, *_ = products(conn)
    data = ReceiptInput(date(2026, 10, 15), SUPPLIER, supplier_name="Cửa khẩu Lạng Sơn", lines=[
        ReceiptLineInput(10, a),
        ReceiptLineInput(0, b),  # a suggested row the user left empty: ignored
        ReceiptLineInput(5, new=NewProduct("Keo dán mới", "新胶", "5KG", unit="thùng")),
    ])
    assert receipts.problems(data) == []
    doc = receipts.save(conn, data)
    new = conn.execute("SELECT * FROM products WHERE name_vi = 'Keo dán mới'").fetchone()
    assert new["code"] == "SP005" and new["unit"] == "thùng"
    assert stock_levels(conn) == {a: 10, new["id"]: 5}
    head = conn.execute("SELECT * FROM documents WHERE id = ?", (doc,)).fetchone()
    assert head["code"] == "HV001" and head["receipt_source"] == SUPPLIER
    assert receipts.supplier_names(conn) == ["Cửa khẩu Lạng Sơn"]

    # the same supplier, written without accents, is the same supplier; its products are suggested first
    second = ReceiptInput(date(2026, 10, 16), SUPPLIER, supplier_name="cua khau lang son",
                          lines=[ReceiptLineInput(1, b)])
    receipts.save(conn, second)
    assert conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0] == 1
    assert receipts.next_code(conn) == "HV003"
    suggested = receipts.suggestions(conn, SUPPLIER, "Cửa khẩu Lạng Sơn")
    assert suggested[0] == b and set(suggested) == {a, b, new["id"]}  # the latest first among equals


def test_customer_return_suggests_what_the_customer_bought(conn, ws):
    a, b, c, d = products(conn)
    with db.transaction(conn):
        cust = catalog.upsert_customer(conn, "Khách Thử", "0900000001")
        from dibekho.core.stock import Line, insert_document

        insert_document(conn, "delivery", date(2026, 10, 1), [Line(c, 2), Line(a, 1)], code="50", code_norm="50",
                        customer_id=cust)
        insert_document(conn, "delivery", date(2026, 10, 5), [Line(d, 4)], code="51", code_norm="51",
                        customer_id=cust)
    assert receipts.suggestions(conn, RETURN, customer_id=cust) == [d, c, a]
    assert receipts.suggestions(conn, RETURN, customer_id=cust, ref_code="50") == [c, a]
    assert receipts.customer_orders(conn, cust) == ["51", "50"]

    data = ReceiptInput(date(2026, 10, 6), RETURN, customer_id=cust, ref_code="51",
                        lines=[ReceiptLineInput(1, d, note="vỡ nắp")])
    doc = receipts.save(conn, data)
    head = conn.execute("SELECT * FROM documents WHERE id = ?", (doc,)).fetchone()
    assert head["customer_id"] == cust and head["ref_code"] == "51" and head["supplier_id"] is None
    assert stock_levels(conn)[d] == -4 + 1


def test_what_cannot_be_saved(conn):
    a, *_ = products(conn)
    keys = lambda data: [k for k, _ in receipts.problems(data)]  # noqa: E731
    assert keys(ReceiptInput(date.today(), SUPPLIER)) == ["receipt_form.need_supplier", "receipt_form.need_lines"]
    assert keys(ReceiptInput(date.today(), RETURN, lines=[ReceiptLineInput(1, a)])) == ["receipt_form.need_customer"]
    twice = ReceiptInput(date.today(), SUPPLIER, supplier_name="X", lines=[ReceiptLineInput(1, a), ReceiptLineInput(2, a)])
    assert keys(twice) == ["receipt_form.twice"]
    # a "new" product that is already in the catalog is pointed out
    dup = ReceiptInput(date.today(), SUPPLIER, supplier_name="X",
                       lines=[ReceiptLineInput(1, new=NewProduct("son a", spec="20kg"))])
    [(line, row)] = receipts.same_as_existing(conn, dup)
    assert row["id"] == a


def test_same_as_existing_also_catches_a_fuzzy_match(conn):
    """Not just an exact name + packing + type match: a new product whose Vietnamese name differs but whose
    Chinese name, packing and colour closely match an existing one is pointed out too."""
    existing = catalog.create_product(conn, "Sơn chống thấm FS-101", "FS-101防水涂料", "20KG", variant="Trắng")
    dup = ReceiptInput(date.today(), SUPPLIER, supplier_name="X",
                       lines=[ReceiptLineInput(1, new=NewProduct("Sơn trắng mới nhập", "FS-101防水涂料",
                                                                 spec="20KG", variant="Trắng"))])
    [(line, row)] = receipts.same_as_existing(conn, dup)
    assert row["id"] == existing


def test_exported_file_cannot_be_imported_twice(conn, ws):
    a, *_ = products(conn)
    doc = receipts.save(conn, ReceiptInput(date(2026, 10, 15), SUPPLIER, supplier_name="Công ty mẹ",
                                           lines=[ReceiptLineInput(7, a)]))
    path = receipts.export_file(conn, ws, doc)
    assert path.parent == ws.output / "hang-ve" and path.name == "HangVe_HV001_2026-10-15.xlsx"
    import zipfile

    with zipfile.ZipFile(path) as z:  # reads like a sheet a person made: no app name anywhere, properties included
        everything = b"".join(z.read(n) for n in z.namelist()).lower()
    assert b"dibekho" not in everything and b"openpyxl" not in everything
    read = read_receipt(path)  # the same layout as the old template
    assert read.doc_date == date(2026, 10, 15) and [(ln.code, ln.qty) for ln in read.lines] == [(code_of(conn, a), 7)]

    (ws.input / path.name).write_bytes(path.read_bytes())
    [item] = inbox.items(conn, ws)
    assert item.kind == "error"  # already recorded
    assert stock_levels(conn)[a] == 7


def test_edit_a_receipt_replaces_it_and_keeps_its_code(conn, ws):
    a, b, *_ = products(conn)
    doc = receipts.save(conn, ReceiptInput(date(2026, 10, 15), SUPPLIER, supplier_name="Công ty mẹ",
                                           lines=[ReceiptLineInput(70, a)]))
    old_file = receipts.export_file(conn, ws, doc)
    data = receipts.load(conn, doc)
    assert data.supplier_name == "Công ty mẹ" and data.lines[0].qty == 70
    data.lines[0].qty = 7  # typed 70 instead of 7
    data.lines.append(ReceiptLineInput(3, b))
    new_doc = receipts.save(conn, data, replaces=doc)
    receipts.export_file(conn, ws, new_doc)
    assert stock_levels(conn) == {a: 7, b: 3}
    statuses = dict(conn.execute("SELECT id, status FROM documents"))
    assert statuses == {doc: "replaced", new_doc: "active"}
    assert conn.execute("SELECT code FROM documents WHERE id = ?", (new_doc,)).fetchone()[0] == "HV001"

    # the first file (70) must not come in again
    (ws.input / "cu.xlsx").write_bytes(old_file.read_bytes())
    [item] = inbox.items(conn, ws)
    assert item.kind == "error"


def test_first_receipt_ever_still_opens_with_3_products(conn):
    """The customer's data has deliveries but no goods in yet: running-out products, then what went out lately."""
    from datetime import timedelta

    from dibekho.core.stock import Line, insert_document

    a, b, c, d = products(conn)
    with db.transaction(conn):
        db.set_meta(conn, "low_stock_default", "0")  # only d has an alarm level (the default one: test_locations)
        catalog.update_product(conn, d, min_stock=5)
        recent = date.today() - timedelta(days=3)
        insert_document(conn, "delivery", recent, [Line(a, 2)], code="1", code_norm="1")  # a: -2, below 0
        insert_document(conn, "delivery", recent, [Line(b, 1), Line(c, 1)], code="2", code_norm="2")
    suggested = receipts.suggestions(conn, SUPPLIER, "Nhà cung cấp mới")
    assert len(suggested) == 3 and suggested[:2] == [d, a]  # the furthest under its level first: d 5 short, a 2; then b or c
    assert receipts.suggestions(conn, RETURN) == []  # a return waits for the customer


def test_code_of_a_receipt_undone_is_not_given_again(conn, ws):
    """Undo forgets the receipt but its file stays in output/hang-ve/: the next receipt gets the next code."""
    a, *_ = products(conn)
    (ws.output / "hang-ve").mkdir(parents=True)
    (ws.output / "hang-ve" / "HangVe_HV004_2026-10-15.xlsx").write_bytes(b"")
    assert receipts.next_code(conn, ws) == "HV005"
    doc = receipts.save(conn, ReceiptInput(date(2026, 10, 16), SUPPLIER, supplier_name="X",
                                           lines=[ReceiptLineInput(1, a)]), ws=ws)
    assert conn.execute("SELECT code FROM documents WHERE id = ?", (doc,)).fetchone()[0] == "HV005"


# migration 007 (prices): a database written by 0.3.0 or earlier has none of these
LOCATIONS_DROP = ("DROP INDEX ix_movements_location", "DROP TABLE locations", "UPDATE stock_movements SET location_id = NULL",
                  "ALTER TABLE document_lines DROP COLUMN location_id", "ALTER TABLE documents DROP COLUMN location_id",
                  "ALTER TABLE documents DROP COLUMN to_location_id", "ALTER TABLE documents DROP COLUMN location_set",
                  "ALTER TABLE products DROP COLUMN stock_note")
PRICE_COLUMNS_DROP = (*LOCATIONS_DROP, "ALTER TABLE document_lines DROP COLUMN unit_price", "ALTER TABLE document_lines DROP COLUMN amount",
                      "ALTER TABLE documents DROP COLUMN fee_amount", "ALTER TABLE documents DROP COLUMN note_total",
                      "ALTER TABLE documents DROP COLUMN prices_read")


def old_package(tmp_path):
    """A data package as DiBeKho 0.2.0 wrote it (schema 5: no suppliers, no receipt source)."""
    import json
    import zipfile

    from dibekho.core.stock import Line, insert_document

    path = tmp_path / "old.sqlite"
    conn = db.connect(path)
    with db.transaction(conn):
        a = catalog.create_product(conn, "Sơn A", "涂料A", "20KG", unit="thùng")
        insert_document(conn, "receipt", date(2026, 9, 1), [Line(a, 30)], note="quý 3")
        insert_document(conn, "delivery", date(2026, 9, 5), [Line(a, 4)], code="7", code_norm="7")
    for sql in (*PRICE_COLUMNS_DROP, "ALTER TABLE documents DROP COLUMN ref_code", "ALTER TABLE documents DROP COLUMN supplier_id",
                "ALTER TABLE documents DROP COLUMN receipt_source", "DROP TABLE suppliers", "PRAGMA user_version = 5"):
        conn.execute(sql)
    conn.close()
    pkg = tmp_path / "DiBeKho_cu.dibekho"
    with zipfile.ZipFile(pkg, "w") as z:
        z.writestr("manifest.json", json.dumps({"device_name": "May cu", "device_id": "x", "exported_at": "2026-10-17T14:48:02",
                                                "schema_version": 5, "app_version": "0.2.0", "deliveries": 1,
                                                "products": 1, "format": 1}))
        z.write(path, "kho.sqlite")
    return pkg


def test_package_from_0_2_0_is_upgraded_on_import(tmp_path, ws):
    from dibekho.core import transfer

    pkg = old_package(tmp_path)
    manifest = transfer.read_manifest(pkg)
    assert transfer.is_older(manifest) and manifest.app_version == "0.2.0"
    db.connect(ws.db_path).close()
    transfer.import_package(ws, pkg)
    import sqlite3

    raw = sqlite3.connect(ws.db_path)  # not db.connect, which would migrate: the file put in place is upgraded
    assert raw.execute("PRAGMA user_version").fetchone()[0] == db.schema_version()
    raw.close()
    conn = db.connect(ws.db_path)
    [a] = [r[0] for r in conn.execute("SELECT id FROM products")]
    assert stock_levels(conn) == {a: 26}
    old = conn.execute("SELECT * FROM documents WHERE kind = 'receipt'").fetchone()
    assert old["receipt_source"] == "" and old["code"] == ""  # older receipts: source unknown, the column stays empty
    doc = receipts.save(conn, ReceiptInput(date(2026, 10, 17), SUPPLIER, supplier_name="Công ty mẹ",
                                           lines=[ReceiptLineInput(5, a)]), ws=ws)
    assert conn.execute("SELECT code FROM documents WHERE id = ?", (doc,)).fetchone()[0] == "HV001"
    assert stock_levels(conn) == {a: 31}
    conn.close()


def test_a_package_that_cannot_be_upgraded_leaves_the_data_here(tmp_path, ws, monkeypatch):
    import pytest

    from dibekho.core import transfer

    pkg = old_package(tmp_path)
    conn = db.connect(ws.db_path)
    with db.transaction(conn):
        catalog.create_product(conn, "Hàng ở máy này")
    conn.close()

    def broken(*a, **k):
        raise RuntimeError("migration failed")

    monkeypatch.setattr(db, "connect", broken)
    with pytest.raises(RuntimeError):
        transfer.import_package(ws, pkg)
    monkeypatch.undo()
    conn = db.connect(ws.db_path)
    assert [r[0] for r in conn.execute("SELECT name_vi FROM products")] == ["Hàng ở máy này"]
    conn.close()
