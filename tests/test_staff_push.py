"""Staff accounts in the app (user, 15/11/2026; cloud/supabase/016_staff_push.sql, core/cloud/approval.py): what a
machine signed in with a staff account does waits for the owner's approval; the owner approves or refuses it.

Owner machine A (role desktop) and staff machine B (role editor) on PGlite. Each scenario ends with no request left
waiting and nothing sent for approval again by itself."""

from datetime import date

import pytest

from dibekho import db
from dibekho.core import catalog, receipts, stock
from dibekho.core.cloud import account, approval, replica, twoway
from tests.pgdb import WEB_FILES, FakeCloud, PgError, Session, needs_pg

pytestmark = needs_pg
OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
STAFF = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
VIEWER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


@pytest.fixture(scope="module")
def pg():
    s = Session(WEB_FILES)
    s.add_account(OWNER)
    s.add_account(STAFF, "editor")
    s.add_account(VIEWER, "viewer")
    s.query("update public.profiles set display_name = 'Lan' where user_id = $1", [STAFF])
    yield s
    s.close()


@pytest.fixture
def cloud(pg):
    for t in ("push_requests", "meta", "document_skipped_lines", "stock_movements", "document_lines", "documents",
              "ignored_lines", "product_aliases", "products", "customers", "suppliers"):
        pg.query(f"delete from public.{t}")
    return FakeCloud(pg)


def _by_code(conn) -> dict:
    codes = {r["id"]: r["code"] for r in conn.execute("SELECT id, code FROM products")}
    return {(codes[p], loc): q for (p, loc), q in stock.stock_levels(conn, by_location=True).items() if q}


def _pid(conn, code) -> int:
    return conn.execute("SELECT id FROM products WHERE code = ?", (code,)).fetchone()[0]


def _shop(tmp_path, cloud):
    a = db.connect(tmp_path / "a.sqlite")
    with db.transaction(a):
        p = catalog.create_product(a, "Keo A", spec="15kg", unit="thung")
    receipts.save(a, receipts.ReceiptInput(date(2026, 11, 1), receipts.SUPPLIER, supplier_name="Cua khau",
                                           lines=[receipts.ReceiptLineInput(50, p)]))
    twoway.start_from_this_machine(a)
    twoway.sync_round(a, cloud, OWNER, "A")
    b = db.connect(tmp_path / "b.sqlite")
    owner_b = account.Session(cloud, STAFF, approval.STAFF)
    assert account.link(b, None, owner_b, lambda: pytest.fail("an empty machine is not asked")) == account.ADOPTED
    approval.staff_round(b, cloud, STAFF, "B")
    assert _by_code(b) == _by_code(a) == {("SP001", stock.MAIN): 50}
    return a, b


def _waiting(cloud) -> list[dict]:
    return approval.pending(cloud, OWNER)


def _receipt(conn, qty):
    return receipts.save(conn, receipts.ReceiptInput(date(2026, 11, 2), receipts.SUPPLIER, supplier_name="Cua khau",
                                                     lines=[receipts.ReceiptLineInput(qty, _pid(conn, "SP001"))]))


def test_staff_changes_wait_for_the_owner_then_reach_everyone(tmp_path, cloud):
    a, b = _shop(tmp_path, cloud)
    _receipt(b, 7)
    with pytest.raises(PgError):  # a staff account never writes the shared data itself
        twoway.send(cloud, STAFF, "B", twoway.cursor(b), twoway.prepare(b)[0])
    approval.staff_round(b, cloud, STAFF, "B")
    assert approval.state(b)["status"] == "pending"
    twoway.sync_round(a, cloud, OWNER, "A")
    assert _by_code(a) == {("SP001", stock.MAIN): 50}  # not yet on the shared data
    [req] = _waiting(cloud)
    assert req["sender"] == "Lan" and req["device"] == "B"
    assert {"t": "doc", "kind": "receipt", "code": "HV002", "date": "2026-11-02", "customer": "", "status": "active",
            "lines": 1} in req["summary"]
    approval.staff_round(b, cloud, STAFF, "B")  # nothing changed: not sent again
    assert len(_waiting(cloud)) == 1

    assert approval.decide(cloud, OWNER, req["id"], True) == {"ok": True, "max_rev": pytest.approx(0, abs=1e9)}
    twoway.sync_round(a, cloud, OWNER, "A")
    assert _by_code(a) == {("SP001", stock.MAIN): 57}
    approval.staff_round(b, cloud, STAFF, "B")
    assert twoway.queued_count(b) == 0 and approval.state(b).get("status") == ""
    assert _by_code(b) == _by_code(a)
    for _ in range(2):  # and nothing comes back for approval by itself
        approval.staff_round(b, cloud, STAFF, "B")
    assert _waiting(cloud) == []


def test_a_new_product_on_a_staff_machine_does_not_loop(tmp_path, cloud):
    """The shared meta key product_code_max travels with a new product: approved once, then nothing more."""
    a, b = _shop(tmp_path, cloud)
    with db.transaction(b):
        catalog.create_product(b, "Son D", spec="5kg", unit="thung")
    approval.staff_round(b, cloud, STAFF, "B")
    [req] = _waiting(cloud)
    assert any(it == {"t": "product", "code": "SP002", "name": "Son D"} for it in req["summary"])
    approval.decide(cloud, OWNER, req["id"], True)
    for _ in range(3):
        approval.staff_round(b, cloud, STAFF, "B")
    assert _waiting(cloud) == [] and twoway.queued_count(b) == 0
    twoway.sync_round(a, cloud, OWNER, "A")
    assert {r[0] for r in a.execute("SELECT name_vi FROM products")} == {"Keo A", "Son D"}


def test_the_owner_refuses_with_a_reason(tmp_path, cloud):
    a, b = _shop(tmp_path, cloud)
    with db.transaction(b):
        stock.record_trial_use(b, date(2026, 11, 3), stock.MAIN, [stock.Line(_pid(b, "SP001"), 2)])
    approval.staff_round(b, cloud, STAFF, "B")
    [req] = _waiting(cloud)
    assert approval.decide(cloud, OWNER, req["id"], False, "Sai số lượng") == {"ok": True}
    approval.staff_round(b, cloud, STAFF, "B")
    assert approval.state(b) | {} == {"status": "rejected", "reason": "Sai số lượng", "at": approval.state(b)["at"]}
    approval.staff_round(b, cloud, STAFF, "B")
    assert _waiting(cloud) == []  # refused: not sent again unchanged
    with db.transaction(b):  # fixed: sent again
        stock.record_trial_use(b, date(2026, 11, 3), stock.MAIN, [stock.Line(_pid(b, "SP001"), 1)])
    approval.staff_round(b, cloud, STAFF, "B")
    assert len(_waiting(cloud)) == 1 and approval.state(b)["status"] == "pending"
    # or given up: the machine takes the shared data again
    approval.discard(b)
    approval.cancel(cloud, STAFF, "B")
    approval.staff_round(b, cloud, STAFF, "B")
    assert _waiting(cloud) == [] and _by_code(b) == {("SP001", stock.MAIN): 50}
    twoway.sync_round(a, cloud, OWNER, "A")
    assert _by_code(a) == {("SP001", stock.MAIN): 50}


def test_a_row_changed_after_the_staff_sent_it_is_not_overwritten(tmp_path, cloud):
    a, b = _shop(tmp_path, cloud)
    with db.transaction(b):
        catalog.update_product(b, _pid(b, "SP001"), stock_note="nhân viên ghi")
    approval.staff_round(b, cloud, STAFF, "B")
    [req] = _waiting(cloud)
    with db.transaction(a):
        catalog.update_product(a, _pid(a, "SP001"), stock_note="chủ ghi")
    twoway.sync_round(a, cloud, OWNER, "A")
    assert approval.decide(cloud, OWNER, req["id"], True) == {"ok": False, "reason": "stale"}
    assert cloud.session.query("select stock_note from public.products")[0]["stock_note"] == "chủ ghi"
    approval.staff_round(b, cloud, STAFF, "B")  # merged: the same row changed on both sides is a conflict here
    assert [c.table for c in twoway.conflicts(b)] == ["products"]
    assert _waiting(cloud) == []  # nothing else to send


def test_who_may_use_the_app(tmp_path, cloud):
    assert account.role_of(cloud, OWNER) == "desktop" and account.role_of(cloud, STAFF) == "editor"
    with pytest.raises(account.NotForApp):
        account._allowed(account.role_of(cloud, VIEWER))
    with pytest.raises(PgError):
        approval.pending(cloud, STAFF)  # the list is the owner's
    with pytest.raises(PgError):
        approval.send(cloud, OWNER, "A", 0, {}, [])  # the owner pushes directly


def test_the_owner_machine_with_data_of_its_own_takes_the_cloud_after_asking(tmp_path, cloud):
    a, _ = _shop(tmp_path, cloud)
    c = db.connect(tmp_path / "c.sqlite")
    with db.transaction(c):
        catalog.create_product(c, "Hang rieng")
    from dibekho.core.workspace import Workspace

    ws = Workspace(tmp_path / "W")
    ws.ensure()
    owner = account.Session(cloud, OWNER, approval.OWNER)
    assert account.link(c, ws, owner, lambda: False) == account.REFUSED
    assert not replica.enabled(c)
    assert account.link(c, ws, owner, lambda: True) == account.ADOPTED
    assert list(ws.backups.glob("*truoc-dung-du-lieu-cloud*"))
    twoway.sync_round(c, cloud, OWNER, "C")
    assert _by_code(c) == _by_code(a)
    assert account.link(c, ws, owner, lambda: pytest.fail("linked already")) == account.ALREADY


def test_a_web_issue_may_list_a_product_twice(tmp_path, cloud):
    a, _ = _shop(tmp_path, cloud)
    pid = cloud.session.query("select id from public.products")[0]["id"]
    made = cloud.rpc("web_issue", {"p": {"doc_date": "2026-11-05", "customer": "Cong ty A", "lines": [
        {"product_id": pid, "qty_main": 2, "unit_price": 100}, {"product_id": pid, "qty_main": 3, "unit_price": 90}]}},
        OWNER)
    assert made["code"].startswith("W")
    twoway.sync_round(a, cloud, OWNER, "A")
    assert _by_code(a) == {("SP001", stock.MAIN): 45}
    rows = a.execute("SELECT qty, unit_price FROM document_lines l JOIN documents d ON d.id = l.document_id "
                     "WHERE d.code = ? ORDER BY line_no", (made["code"],)).fetchall()
    assert [tuple(r) for r in rows] == [(2, 100), (3, 90)]
