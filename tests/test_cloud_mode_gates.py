"""In cloud mode the whole-file operations (Undo, restore, package import, delete all) are locked: putting an old
copy of the database in place would bring back or erase other machines' work, and roll back the sync queue."""

import os

import pytest

from dibekho import db
from dibekho.core import catalog
from dibekho.core.cloud import replica


@pytest.fixture
def ctx(ws, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from dibekho import i18n
    from dibekho.core.workspace import Config
    from dibekho.ui import common

    QApplication.instance() or QApplication([])
    i18n.set_language("vi")
    told = []
    monkeypatch.setattr(common, "info", lambda parent, text: told.append(text))
    c = common.AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)
    c.told = told
    yield c
    c.close()


def test_undo_is_locked_in_cloud_mode_and_the_data_stays(ctx):
    from dibekho.ui.main_window import MainWindow

    ctx.undo_point("product_add")
    with db.transaction(ctx.conn):
        catalog.create_product(ctx.conn, "Keo A")
    replica.set_enabled(ctx.conn, True)
    window = MainWindow(ctx)
    window.undo_last()
    assert ctx.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1  # nothing rolled back
    assert any("dữ liệu chung ở Cloud" in t for t in ctx.told)
    window._owner_timer.stop()


def test_local_mode_is_not_affected(ctx):
    from dibekho.ui.common import blocked_in_cloud_mode

    assert blocked_in_cloud_mode(None, ctx.conn) is False
    replica.set_enabled(ctx.conn, True)
    assert blocked_in_cloud_mode(None, ctx.conn) is True
