"""User, 21/11/2026: the app was removed, the data came back from the cloud, but no order could open its original
('Mở file gốc'): the database comes down, the files in data/phieu-goc do not. They are on the cloud (core.cloud.backup
uploads them), so the owner's window downloads every missing one in the background, and 'Mở file gốc' downloads the
one it needs when it is still missing."""

import hashlib
import time

import pytest

from dibekho import db
from dibekho.core import deliveries
from tests.test_currency import CopiesOnCloud, shop
from tests.test_prices import doc


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _to_cloud(ws, *docs):
    """Move the stored copies of these orders to a made-up cloud bucket: this computer no longer has them."""
    bucket = {}
    for d in docs:
        copy = deliveries.original_copy(ws, d["source_hash"])
        bucket[f"phieu-goc/{copy.name}"] = copy.read_bytes()
        copy.unlink()
    return bucket


def test_every_missing_original_is_listed_the_undecided_ones_first(conn, ws, monkeypatch):
    yuan, dong = shop(conn, ws, monkeypatch)
    assert deliveries.missing_originals(conn, ws) == []
    _to_cloud(ws, yuan, dong)
    with db.transaction(conn):
        conn.execute("UPDATE documents SET currency = '' WHERE id = ?", (dong["id"],))
    # both currencies decided or not: both lack their file; the undecided one is fetched first
    assert deliveries.missing_originals(conn, ws) == [f"{dong['source_hash']}.xlsx", f"{yuan['source_hash']}.xlsx"]
    assert deliveries.missing_copies(conn, ws) == [f"{dong['source_hash']}.xlsx"]


def test_the_owners_window_downloads_the_originals_of_decided_orders_too(app, ws, monkeypatch):
    from dibekho.ui import main_window
    from tests.test_locations import window

    ctx, win = window(ws)
    yuan, dong = shop(ctx.conn, ws, monkeypatch)
    cloud = CopiesOnCloud(_to_cloud(ws, yuan, dong))
    monkeypatch.setattr(main_window.cloud_sync, "session", lambda cfg, timeout=None: (cloud, "tok"))
    win.rescan(quiet=True)
    for _ in range(200):
        app.processEvents()
        if not deliveries.missing_originals(ctx.conn, ws):
            break
        time.sleep(0.02)
    assert deliveries.missing_originals(ctx.conn, ws) == []
    assert doc(ctx.conn, "155")["currency"] == "CNY"  # nothing else changed
    win.deleteLater()


def _wait(app, done):
    for _ in range(300):
        app.processEvents()
        if done():
            return
        time.sleep(0.02)
    raise AssertionError("the download did not finish")


def test_open_original_downloads_the_missing_file_first(app, ws, monkeypatch):
    import dibekho.ui.details as details_mod
    from dibekho.ui import originals
    from tests.test_locations import window

    ctx, win = window(ws)
    yuan, dong = shop(ctx.conn, ws, monkeypatch)
    cloud = CopiesOnCloud(_to_cloud(ws, yuan))
    opened, errors = [], []
    monkeypatch.setattr(details_mod, "open_path", opened.append)
    monkeypatch.setattr(details_mod, "error", lambda parent, text: errors.append(text))
    monkeypatch.setattr(originals.cloud_sync, "session", lambda cfg, timeout=None: (cloud, "tok"))
    ctx.cfg.cloud_user = "maychinh"

    dlg = details_mod.DocumentDialog(ctx, yuan["id"], win)
    assert not dlg.download_button.isHidden()
    dlg.open_original()
    _wait(app, lambda: opened)
    assert errors == [] and opened[0].read_bytes() == cloud.files[f"phieu-goc/{yuan['source_hash']}.xlsx"]
    assert deliveries.original_copy(ws, yuan["source_hash"]) is not None  # kept: the next open needs no network
    assert dlg.download_button.isHidden()
    dlg.deleteLater()

    # not on the cloud: said so (another machine has to send it), nothing opened
    deliveries.original_copy(ws, dong["source_hash"]).unlink()
    dlg = details_mod.DocumentDialog(ctx, dong["id"], win)
    dlg.open_original()
    _wait(app, lambda: errors)
    assert len(opened) == 1 and errors == [originals.t("originals.absent", codes=dong["code"])]

    # offline: the check-the-network message
    def offline(cfg, timeout=None):
        raise OSError("offline")

    monkeypatch.setattr(originals.cloud_sync, "session", offline)
    dlg.open_original()
    _wait(app, lambda: len(errors) == 2)
    assert errors[-1] == details_mod.t("doc.original_not_fetched")

    # not signed in to the cloud, or a staff machine: the old message, no network tried, no download button
    asked = len(cloud.asked)
    for user, role in (("", ""), ("nhanvien", "editor")):
        ctx.cfg.cloud_user, ctx.cfg.cloud_role = user, role
        other = details_mod.DocumentDialog(ctx, dong["id"], win)
        assert other.download_button.isHidden()
        other.open_original()
        assert errors[-1] == details_mod.t("doc.original_missing") and len(cloud.asked) == asked
        other.deleteLater()
    dlg.deleteLater()
    win.deleteLater()


def test_download_reports_progress_and_tells_not_on_cloud_from_failed(ws):
    from dibekho.core.cloud import backup as cloud_backup

    files = {f"{hashlib.sha256(t).hexdigest()}.xlsx": t for t in (b"mot", b"hai")}
    good, broken = files
    absent = f"{hashlib.sha256(b'ba').hexdigest()}.xlsx"
    cloud = CopiesOnCloud({f"phieu-goc/{good}": files[good], f"phieu-goc/{broken}": b"damaged"})
    seen = []
    result = cloud_backup.download_originals(ws, cloud, "tok", [good, broken, absent],
                                             progress=lambda done, total, name: seen.append((done, total, name)))
    assert (result.got, result.failed, result.absent) == ([good], [broken], [absent])
    assert seen == [(0, 2, good), (1, 2, broken)] and not result.cancelled
    stopped = cloud_backup.download_originals(ws, cloud, "tok", [good], cancelled=lambda: True)
    assert stopped.cancelled and stopped.got == []


def test_only_one_upload_of_the_originals_at_a_time(ws):
    from dibekho.core.cloud import backup as cloud_backup

    ws.originals.mkdir(parents=True, exist_ok=True)
    (ws.originals / f"{hashlib.sha256(b'mot').hexdigest()}.xlsx").write_bytes(b"mot")
    with cloud_backup._UPLOADING:  # another thread is sending: nothing is asked of the cloud, no error
        assert cloud_backup.upload_originals(ws, None, "tok") == (0, 0)
    assert not cloud_backup._UPLOADING.locked()


def test_closing_waits_for_an_upload_under_way_then_sends(ws):
    """User, 27/11/2026: an order saved and the app closed at once must still send its file."""
    import threading

    from dibekho.core.cloud import backup as cloud_backup

    ws.originals.mkdir(parents=True, exist_ok=True)
    name = f"{hashlib.sha256(b'mot').hexdigest()}.xlsx"
    (ws.originals / name).write_bytes(b"mot")
    sent = []

    class Cloud:
        def storage_list(self, *a, **k):
            return []

        def storage_upload(self, path, data, token):
            sent.append(path)

    cloud_backup._UPLOADING.acquire()
    other = threading.Timer(0.3, cloud_backup._UPLOADING.release)
    other.start()
    assert cloud_backup.upload_originals(ws, Cloud(), "tok", wait=5) == (1, 0) and sent == [f"phieu-goc/{name}"]
    other.join()


def test_the_order_list_downloads_the_chosen_orders(app, ws, monkeypatch):
    from dibekho.ui import orders_page, originals
    from tests.test_locations import window

    ctx, win = window(ws)
    yuan, dong = shop(ctx.conn, ws, monkeypatch)
    cloud = CopiesOnCloud(_to_cloud(ws, yuan, dong))
    told = []
    monkeypatch.setattr(orders_page, "info", lambda parent, text: told.append(text))
    monkeypatch.setattr(orders_page, "error", lambda parent, text: told.append(text))
    monkeypatch.setattr(originals.cloud_sync, "session", lambda cfg, timeout=None: (cloud, "tok"))
    ctx.cfg.cloud_user = "maychinh"
    page = orders_page.OrdersPage(ctx)
    page.all_time.setChecked(True)
    page.refresh()
    assert not page.download_button.isHidden()
    page.download_selected()
    assert told == [orders_page.t("originals.select_first")]
    page.table.selectAll()
    page.download_selected()
    _wait(app, lambda: len(told) == 2)
    assert told[-1] == orders_page.t("originals.got", n=2) and deliveries.missing_originals(ctx.conn, ws) == []
    page.table.selectAll()
    page.download_selected()
    assert told[-1] == orders_page.t("originals.have_all")
    page.deleteLater()
    win.deleteLater()


def test_a_sync_round_sends_the_new_original_files_up(app, ws, monkeypatch):
    from dibekho.ui import sync_runner
    from tests.test_locations import window

    ctx, win = window(ws)
    answers = [(1, 1), (0, 0)]
    monkeypatch.setattr(sync_runner.cloud_backup, "upload_originals", lambda *a: answers.pop(0))
    runner = sync_runner.SyncRunner(ctx, lambda: True, lambda text: None)
    runner.timer.stop()
    for left_to_send in (1, 0):  # one still to send: asked again after the next round
        runner._send_originals("client", "tok")
        _wait(app, lambda: not runner._originals_busy)
        assert runner._originals_due is bool(left_to_send)
    runner._send_originals("client", "tok")  # nothing new: not asked
    assert answers == [] and not runner._originals_busy
    win.deleteLater()
