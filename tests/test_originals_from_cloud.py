"""User, 21/11/2026: the app was removed, the data came back from the cloud, but no order could open its original
('Mở file gốc'): the database comes down, the files in data/phieu-goc do not. They are on the cloud (core.cloud.backup
uploads them), so the owner's window downloads every missing one in the background, and 'Mở file gốc' downloads the
one it needs when it is still missing."""

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


def test_open_original_downloads_the_missing_file_first(app, ws, monkeypatch):
    import dibekho.ui.details as details_mod
    from tests.test_locations import window

    ctx, win = window(ws)
    yuan, dong = shop(ctx.conn, ws, monkeypatch)
    cloud = CopiesOnCloud(_to_cloud(ws, yuan))
    opened, errors = [], []
    monkeypatch.setattr(details_mod, "open_path", opened.append)
    monkeypatch.setattr(details_mod, "error", lambda parent, text: errors.append(text))
    monkeypatch.setattr(details_mod.cloud_sync, "session", lambda cfg, timeout=None: (cloud, "tok"))
    ctx.cfg.cloud_user = "maychinh"

    dlg = details_mod.DocumentDialog(ctx, yuan["id"], win)
    dlg.open_original()
    assert errors == [] and len(opened) == 1 and opened[0].read_bytes() == cloud.files[f"phieu-goc/{yuan['source_hash']}.xlsx"]
    assert deliveries.original_copy(ws, yuan["source_hash"]) is not None  # kept: the next open needs no network
    dlg.deleteLater()

    # not on the cloud either (or offline): a plain message, nothing opened
    deliveries.original_copy(ws, dong["source_hash"]).unlink()
    dlg = details_mod.DocumentDialog(ctx, dong["id"], win)
    dlg.open_original()
    assert len(opened) == 1 and errors == [details_mod.t("doc.original_not_fetched")]

    # not signed in to the cloud: the old message, no network tried
    ctx.cfg.cloud_user = ""
    asked = len(cloud.asked)
    dlg.open_original()
    assert errors[-1] == details_mod.t("doc.original_missing") and len(cloud.asked) == asked
    dlg.deleteLater()

    # a staff machine cannot read the owner's backups: nothing tried
    ctx.cfg.cloud_user, ctx.cfg.cloud_role = "nhanvien", "editor"
    dlg = details_mod.DocumentDialog(ctx, dong["id"], win)
    dlg.open_original()
    assert errors[-1] == details_mod.t("doc.original_missing") and len(cloud.asked) == asked
    dlg.deleteLater()
    win.deleteLater()
