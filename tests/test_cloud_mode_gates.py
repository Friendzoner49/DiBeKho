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
    assert not window.undo_btn.isEnabled()  # a product edit is not a document: nothing to take back on shared data
    window.undo_last()
    assert ctx.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1  # nothing rolled back
    window._owner_timer.stop()
    window.sync.timer.stop()


def test_undo_in_cloud_mode_cancels_the_document_just_saved(ctx, monkeypatch):
    from datetime import date

    from dibekho.core import stock, undo
    from dibekho.ui import main_window
    from dibekho.ui.main_window import MainWindow

    replica.set_enabled(ctx.conn, True)
    with db.transaction(ctx.conn):
        a = catalog.create_product(ctx.conn, "Keo A")
    ctx.undo_point("trial_use")
    with db.transaction(ctx.conn):
        doc = stock.record_trial_use(ctx.conn, date(2026, 11, 12), stock.MAIN, [stock.Line(a, 2)])
        undo.remember_doc(ctx.conn, "trial_use", doc)
    window = MainWindow(ctx)
    window._update_undo()
    assert window.undo_btn.isEnabled() and "DT001" in window.undo_btn.text()
    monkeypatch.setattr(main_window, "ask", lambda parent, text: True)
    monkeypatch.setattr(main_window, "info", lambda parent, text: ctx.told.append(text))
    window.undo_last()
    assert ctx.conn.execute("SELECT status FROM documents WHERE id = ?", (doc,)).fetchone()[0] == "cancelled"
    assert stock.stock_levels(ctx.conn).get(a, 0) == 0
    assert not window.undo_btn.isEnabled()  # once only
    assert any("DT001" in t for t in ctx.told)
    window._owner_timer.stop()
    window.sync.timer.stop()


def test_local_mode_is_not_affected(ctx):
    from dibekho.ui.common import blocked_in_cloud_mode

    assert blocked_in_cloud_mode(None, ctx.conn) is False
    replica.set_enabled(ctx.conn, True)
    assert blocked_in_cloud_mode(None, ctx.conn) is True


def test_a_saved_size_larger_than_the_screen_is_brought_back_inside(ctx):
    from PySide6.QtWidgets import QApplication

    from dibekho.ui.main_window import MainWindow

    window = MainWindow(ctx)
    avail = window.screen().availableGeometry()
    window.resize(avail.width() + 400, avail.height() + 300)
    window.move(avail.x() + 200, avail.y() + 150)
    window._keep_on_screen()
    QApplication.processEvents()
    frame = window.frameGeometry()
    assert avail.contains(frame), (avail, frame)
    window._owner_timer.stop()
    window.sync.timer.stop()
