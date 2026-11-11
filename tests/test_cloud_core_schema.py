"""The cloud's real tables (cloud/supabase/007_core.sql) on a real Postgres (PGlite): every local column has a home,
a whole shop survives SQLite -> cloud -> a fresh SQLite unchanged, and stock computed on the cloud matches the app."""

import json
from datetime import date, datetime

import pytest

from dibekho import db
from dibekho.core import catalog, receipts, stock
from dibekho.core.cloud import replica
from dibekho.db.sync_schema import SYNCED
from tests.pgdb import needs_pg, run

BOOKKEEPING = {"rev", "deleted", "updated_at", "origin"}
OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
STRANGER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

pytestmark = needs_pg


def _shop(conn):
    with db.transaction(conn):
        a = catalog.create_product(conn, "Keo A", spec="15kg", unit="thung", category="Keo")
        b = catalog.create_product(conn, "Mang B", spec="3mm", unit="cuon", category="Mang")
        conn.execute("UPDATE products SET stock_note = '2 thung mop', active = 0 WHERE id = ?", (b,))
        cust = catalog.upsert_customer(conn, "Cong ty A", phone="0900 000 001")
        catalog.set_alias(conn, "keo a|15kg", a, "Keo A 15kg")
        catalog.ignore_line(conn, "phi van chuyen|", "Phí vận chuyển")
        db.set_meta(conn, "low_stock_default", "25")
        db.set_meta(conn, "cloud_last_push_id", "3")  # per machine: must not travel
        d1 = stock.insert_document(conn, "delivery", date(2026, 11, 2), [stock.Line(a, 5)], code="7", code_norm="7",
                                   customer_id=cust)
        conn.execute("UPDATE document_lines SET unit_price = 12000.5, amount = 60002.5 WHERE document_id = ?", (d1,))
        conn.execute("UPDATE documents SET fee_amount = 30000, prices_read = 1, location_set = 0 WHERE id = ?", (d1,))
        d2 = stock.insert_document(conn, "delivery", date(2026, 11, 3), [stock.Line(a, 3)], code="8", code_norm="8",
                                   customer_id=cust)
        stock.close_document(conn, d2)
        conn.execute("INSERT INTO document_skipped_lines(document_id, key, raw_name) VALUES (?, 'x|', 'X')", (d1,))
    receipts.save(conn, receipts.ReceiptInput(date(2026, 11, 1), receipts.SUPPLIER, supplier_name="Cua khau",
                                              lines=[receipts.ReceiptLineInput(50, a), receipts.ReceiptLineInput(20, b)]))
    with db.transaction(conn):
        stock.transfer(conn, date(2026, 11, 4), stock.MAIN, stock.OFFICE, [stock.Line(a, 12)])
        stock.record_trial_use(conn, date(2026, 11, 5), stock.OFFICE, [stock.Line(a, 2)])
        stock.stock_count(conn, date(2026, 11, 6), {(b, stock.MAIN): 18}, at=datetime(2026, 11, 6, 17, 30))
    return a, b


def _load_steps(conn, snap) -> list[dict]:
    return [{"sql": replica.cloud_insert_sql(conn, t), "params": [json.dumps(snap[t.name]), "dev-a"]} for t in SYNCED]


def _canonical(conn) -> dict:
    """Every synced row in cloud form (uuids instead of local ids), sorted: comparable across two databases."""
    snap = replica.snapshot(conn)
    key = lambda r: str(r.get("id") or r.get("key"))  # noqa: E731
    return {name: sorted(rows, key=key) for name, rows in snap.items()}


def _levels_by_code(conn) -> dict:
    codes = {r["id"]: r["code"] for r in conn.execute("SELECT id, code FROM products")}
    return {(codes[p], loc): q for (p, loc), q in stock.stock_levels(conn, by_location=True).items()}


def test_every_local_column_has_a_cloud_column_and_back(conn):
    rows = run([{"sql": "select table_name t, column_name c from information_schema.columns where table_schema = 'public'"}])[0]
    cloud = {}
    for r in rows:
        cloud.setdefault(r["t"], set()).add(r["c"])
    for t in SYNCED:
        assert set(replica.cloud_columns(conn, t)) == cloud[t.name] - BOOKKEEPING, t.name


def test_a_shop_survives_sqlite_cloud_sqlite_unchanged(conn, tmp_path):
    _shop(conn)
    snap = replica.snapshot(conn)
    assert "low_stock_default" in [r["key"] for r in snap["meta"]]
    steps = _load_steps(conn, snap) + [{"sql": replica.cloud_select_sql(t)} for t in SYNCED] + [
        {"sql": "select p.code, m.location_id, sum(m.qty) qty from stock_movements m join products p on p.id = m.product_id "
                "group by 1, 2 order by 1, 2"}]
    out = run(steps)
    pulled = {t.name: [r["r"] for r in out[len(SYNCED) + i]] for i, t in enumerate(SYNCED)}

    other = db.connect(tmp_path / "other.sqlite")
    replica.apply(other, pulled)
    assert _canonical(other) == _canonical(conn)
    assert _levels_by_code(other) == _levels_by_code(conn)  # local ids differ between machines; codes do not
    # the per-machine bookkeeping stayed home
    assert other.execute("SELECT COUNT(*) FROM meta WHERE key = 'cloud_last_push_id'").fetchone()[0] == 0

    # stock summed on the cloud = the app's own figures (an independent total)
    codes = {r["id"]: r["code"] for r in conn.execute("SELECT id, code FROM products")}
    app = {(codes[p], loc): q for (p, loc), q in stock.stock_levels(conn, by_location=True).items() if q}
    cloud = {(r["code"], r["location_id"]): r["qty"] for r in out[-1] if r["qty"]}
    assert cloud == pytest.approx(app)
    other.close()


def test_rev_moves_on_every_change_and_rls_lets_only_known_accounts_read(conn):
    _shop(conn)
    snap = replica.snapshot(conn)
    out = run(_load_steps(conn, snap) + [
        {"sql": "insert into auth.users(id) values ($1)", "params": [OWNER]},
        {"sql": "insert into public.profiles(user_id, role) values ($1, 'desktop')", "params": [OWNER]},
        {"sql": "select max(rev) r from public.products"},
        {"sql": "update public.products set stock_note = 'x' where code = 'SP001' returning rev"},
        {"sql": "select count(*)::int n from public.documents", "sub": OWNER},
        {"sql": "select count(*)::int n from public.documents", "sub": STRANGER},
    ])
    before, after = out[len(SYNCED) + 2][0]["r"], out[len(SYNCED) + 3][0]["rev"]
    assert after > before
    assert out[-2][0]["n"] == len(snap["documents"]) and out[-1][0]["n"] == 0


def test_the_cloud_refuses_two_live_documents_with_one_code(conn):
    _shop(conn)
    snap = replica.snapshot(conn)
    hv = next(r for r in snap["documents"] if r["code"] == "HV001")
    twin = {**hv, "id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc"}
    with pytest.raises(AssertionError, match="documents_code_unique"):
        run(_load_steps(conn, snap) + [{"sql": replica.cloud_insert_sql(conn, SYNCED[5]),
                                        "params": [json.dumps([twin]), "dev-b"]}])
