"""Restore / data package / delete all while the data is shared (core/cloud/admin.py): the cloud ends up holding
exactly the new database in one push, other machines follow, and anything going wrong leaves the cloud as it was."""

import shutil
from datetime import date

import pytest

from dibekho import db
from dibekho.core import backup, catalog, receipts, stock
from dibekho.core.cloud import admin, replica, twoway
from dibekho.core.cloud.client import CloudError
from tests.pgdb import ALL_FILES, FakeCloud, PgError, Session, needs_pg

pytestmark = needs_pg
OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
STAFF = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


@pytest.fixture
def shop(tmp_path):
    pg = Session([*ALL_FILES, "cloud/supabase/009_web_rpc.sql"])
    pg.add_account(OWNER)
    pg.add_account(STAFF, "editor")
    cloud = FakeCloud(pg)
    a = db.connect(tmp_path / "a.sqlite")
    with db.transaction(a):
        k = catalog.create_product(a, "Keo A", spec="15kg")
        catalog.create_product(a, "Mang B", spec="3mm")
    receipts.save(a, receipts.ReceiptInput(date(2026, 11, 1), receipts.SUPPLIER, supplier_name="Cua khau",
                                           lines=[receipts.ReceiptLineInput(50, k)]))
    twoway.start_from_this_machine(a)
    twoway.sync_round(a, cloud, OWNER, "A")
    yield pg, cloud, a, tmp_path
    a.close()
    pg.close()


def _picture(conn):
    products = sorted((r["code"], r["name_vi"]) for r in conn.execute("SELECT code, name_vi FROM products"))
    docs = sorted((r["kind"], r["code"], r["status"]) for r in conn.execute("SELECT kind, code, status FROM documents"))
    return products, docs, stock.stock_levels(conn)


def _cloud_live(pg):
    products = sorted((r["code"], r["name_vi"]) for r in pg.query(
        "select code, name_vi from public.products where not deleted"))
    docs = pg.query("select count(*) as n from public.documents where not deleted")[0]["n"]
    return products, docs


def _swap(conn_path, new_path):
    shutil.copy2(new_path, conn_path)
    return db.connect(conn_path)


def test_a_backup_put_back_becomes_the_shared_data_and_other_machines_follow(shop):
    pg, cloud, a, tmp = shop
    old = backup.snapshot(a, tmp / "old.sqlite")
    # a second machine joins, then more work is done after the backup
    b = db.connect(tmp / "b.sqlite")
    twoway.start_from_cloud(b)
    twoway.sync_round(b, cloud, OWNER, "B")
    with db.transaction(a):
        catalog.create_product(a, "Bot C", spec="25kg")
    twoway.sync_round(a, cloud, OWNER, "A")
    assert len(_cloud_live(pg)[0]) == 3

    new = tmp / "new.sqlite"
    shutil.copy2(old, new)
    rev = admin.replace_shared(a, new, cloud, OWNER, "A")
    a.close()
    a = _swap(tmp / "a.sqlite", new)
    assert twoway.cursor(a) == rev and twoway.queued_count(a) == 0 and replica.enabled(a)
    assert _cloud_live(pg) == (sorted([("SP001", "Keo A"), ("SP002", "Mang B")]), 1)
    assert twoway.sync_round(a, cloud, OWNER, "A").pushed == 0  # nothing to send, nothing new

    twoway.sync_round(b, cloud, OWNER, "B")
    assert _picture(b) == _picture(a)
    b.close()


def test_delete_all_leaves_the_cloud_empty(shop):
    pg, cloud, a, tmp = shop
    empty = tmp / "empty.sqlite"
    db.connect(empty).close()
    admin.replace_shared(a, empty, cloud, OWNER, "A")
    assert _cloud_live(pg) == ([], 0)
    assert pg.query("select count(*) as n from public.stock_movements where not deleted")[0]["n"] == 0


def test_a_data_package_with_its_own_numbering_replaces_it(shop):
    """A package from a machine that never shared: no uuids, codes that clash with the cloud's."""
    pg, cloud, a, tmp = shop
    other = tmp / "other.sqlite"
    o = db.connect(other)
    with db.transaction(o):
        catalog.create_product(o, "Son X", spec="5L")  # also SP001
    o.close()
    admin.replace_shared(a, other, cloud, OWNER, "A")
    assert _cloud_live(pg) == ([("SP001", "Son X")], 0)


def test_nothing_changes_when_this_machine_still_has_changes_to_send(shop):
    pg, cloud, a, tmp = shop
    with db.transaction(a):
        catalog.create_product(a, "Bot C")
    copy = backup.snapshot(a, tmp / "copy.sqlite")
    with pytest.raises(admin.NotReady):
        admin.replace_shared(a, copy, cloud, OWNER, "A")
    assert len(_cloud_live(pg)[0]) == 2


def test_someone_writing_meanwhile_leaves_the_cloud_as_it_was(shop, monkeypatch):
    pg, cloud, a, tmp = shop
    empty = tmp / "empty.sqlite"
    db.connect(empty).close()
    real_send = twoway.send

    def send_after_a_web_write(client, token, device, expected, batch):
        pg.query("select public.web_product_add(p => $1::jsonb)", ['{"name_vi": "Keo web", "spec": "1kg"}'],
                 sub=OWNER)
        return real_send(client, token, device, expected, batch)
    monkeypatch.setattr(twoway, "send", send_after_a_web_write)
    with pytest.raises(CloudError):
        admin.replace_shared(a, empty, cloud, OWNER, "A")
    assert len(_cloud_live(pg)[0]) == 3  # the two products + the web's, nothing deleted


def test_only_the_owner_account_can_do_it(shop):
    pg, cloud, a, tmp = shop
    empty = tmp / "empty.sqlite"
    db.connect(empty).close()
    with pytest.raises((PgError, CloudError)):
        admin.replace_shared(a, empty, cloud, STAFF, "A")
    assert len(_cloud_live(pg)[0]) == 2


def test_the_settings_button_replaces_the_shared_data_and_this_computers_file(shop, monkeypatch):
    """The path a user takes (ui/shared_admin.py): asked, backed up, the cloud first, then the file here."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from dibekho import i18n
    from dibekho.core.workspace import Config, Workspace
    from dibekho.ui import common, shared_admin

    pg, cloud, a, tmp = shop
    QApplication.instance() or QApplication([])
    i18n.set_language("vi")
    ws = Workspace(tmp / "ws")
    ws.ensure()
    a.close()
    shutil.copy2(tmp / "a.sqlite", ws.db_path)
    ctx = common.AppContext(Config(workspace=str(ws.root), language="vi", device_id="A", device_name="A"), ws)
    monkeypatch.setattr(shared_admin, "ask", lambda parent, text: True)
    monkeypatch.setattr(shared_admin, "error", lambda parent, text: pytest.fail(text))
    monkeypatch.setattr(shared_admin.cloud_sync, "session", lambda cfg, timeout=None: (cloud, OWNER))

    def build(folder):
        new = folder / "kho.sqlite"
        db.connect(new).close()
        return new
    assert shared_admin.replace_shared_data(ctx, None, build, "Xoá toàn bộ dữ liệu")
    assert ctx.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
    assert _cloud_live(pg) == ([], 0)
    assert any("truoc-thay-du-lieu-chung" in f.name for f in backup.list_backups(ws))
    ctx.close()
