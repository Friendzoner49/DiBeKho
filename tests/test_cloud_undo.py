"""Hoàn tác on data shared through the cloud: it cancels the document this machine has just saved (reverse
movements, like Huỷ phiếu) and the cancel reaches the cloud like any change -- never an old copy of the file put
back, which would erase what the web and the other machines wrote (docs/cloud/06-cloud-la-goc.md)."""

from datetime import date

from dibekho import db
from dibekho.core import backup, catalog, receipts, stock, undo
from dibekho.core.cloud import replica, twoway
from tests.pgdb import ALL_FILES, FakeCloud, Session, needs_pg

OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def _receipt(conn, pid, qty=10):
    doc = receipts.save(conn, receipts.ReceiptInput(date(2026, 11, 12), receipts.SUPPLIER, supplier_name="Cua khau",
                                                    lines=[receipts.ReceiptLineInput(qty, pid)]))
    undo.remember_doc(conn, "receipt", doc)
    return doc


def test_only_the_last_saved_document_and_only_while_it_is_active(tmp_path):
    conn = db.connect(tmp_path / "k.sqlite")
    with db.transaction(conn):
        a = catalog.create_product(conn, "Keo A")
    assert undo.cloud_latest(conn) is None
    doc = _receipt(conn, a)
    point = undo.cloud_latest(conn)
    assert (point.doc_id, point.action, point.code) == (doc, "receipt", "HV001")
    undo.forget_doc(conn)  # what every new undo point does: a later action is not a document
    assert undo.cloud_latest(conn) is None
    _receipt(conn, a)
    with db.transaction(conn):
        stock.close_document(conn, undo.cloud_latest(conn).doc_id)  # cancelled some other way
    assert undo.cloud_latest(conn) is None


@needs_pg
def test_the_cancel_reaches_the_cloud_and_a_cancel_from_elsewhere_ends_it(tmp_path):
    pg = Session([*ALL_FILES, "cloud/supabase/009_web_rpc.sql"])
    try:
        pg.add_account(OWNER)
        cloud = FakeCloud(pg)
        conn = db.connect(tmp_path / "k.sqlite")
        replica.set_enabled(conn, True)
        with db.transaction(conn):
            a = catalog.create_product(conn, "Keo A")
        _receipt(conn, a)
        twoway.sync_round(conn, cloud, OWNER, "S")
        undo.cloud_undo(conn, undo.cloud_latest(conn))
        twoway.sync_round(conn, cloud, OWNER, "S")
        on_cloud = pg.query("select status from public.documents where kind = 'receipt'")
        assert [r["status"] for r in on_cloud] == ["cancelled"]
        total = pg.query("select coalesce(sum(qty), 0) as q from public.stock_movements where not deleted")[0]["q"]
        assert float(total) == 0
        # the key itself never travels (it is this machine's)
        assert pg.query("select count(*) as n from public.meta where key = $1", [undo.CLOUD_KEY])[0]["n"] == 0

        doc = _receipt(conn, a, 5)
        twoway.sync_round(conn, cloud, OWNER, "S")
        uid = replica.uid_for(conn, "documents", doc, create=False)
        pg.query("select public.web_cancel(p_doc => $1::uuid)", [uid], sub=OWNER)  # cancelled on the web meanwhile
        twoway.sync_round(conn, cloud, OWNER, "S")
        assert undo.cloud_latest(conn) is None
    finally:
        pg.close()


def test_a_daily_copy_of_the_shared_data_beside_the_opening_one(ws):
    conn = db.connect(ws.db_path)
    day = date(2026, 11, 12)
    assert backup.daily_backup(conn, ws, today=day) is not None
    shared = backup.daily_backup(conn, ws, today=day, prefix=backup.SHARED_PREFIX)
    assert shared is not None and shared.name == "DiBeKho_dulieu-chung_2026-11-12.sqlite"
    assert backup.daily_backup(conn, ws, today=day, prefix=backup.SHARED_PREFIX) is None  # once a day


def test_a_sign_in_ended_elsewhere_asks_for_the_password_not_for_the_network(monkeypatch):
    """Signing out on the web once ended the app's sign-in too; the app only said 'chưa kết nối được'."""
    import pytest

    from dibekho.core.cloud.client import CloudClient, CloudError, SessionExpired

    client = CloudClient("https://example.supabase.co", "k")

    def refused(*args, **kwargs):
        raise CloudError("Cloud báo lỗi 400: Invalid Refresh Token: Refresh Token Not Found")
    monkeypatch.setattr(client, "_post", refused)
    with pytest.raises(SessionExpired, match="gõ mật khẩu"):
        client.refresh("old")

    def offline(*args, **kwargs):
        raise CloudError("Không kết nối được Cloud. Kiểm tra mạng rồi thử lại.")
    monkeypatch.setattr(client, "_post", offline)
    with pytest.raises(CloudError) as caught:
        client.refresh("old")
    assert not isinstance(caught.value, SessionExpired)


def test_web_sign_out_ends_only_this_browser():
    from pathlib import Path

    app = (Path(__file__).resolve().parent.parent / "webapp" / "app.js").read_text(encoding="utf-8")
    assert 'signOut({ scope: "local" })' in app and "signOut()" not in app
