"""The app's background sync (ui/sync_runner.py) against a real Postgres: a round pulls on a worker thread, merges on
the main thread only at a safe moment, pushes, and the status line says so."""

import os
import time

import pytest

from dibekho import db
from dibekho.core import catalog
from dibekho.core.cloud import replica, twoway
from tests.pgdb import FakeCloud, Session, needs_pg

pytestmark = needs_pg
OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@pytest.fixture
def setup(ws, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from dibekho import i18n
    from dibekho.core.workspace import Config
    from dibekho.ui import common, sync_runner

    app = QApplication.instance() or QApplication([])
    i18n.set_language("vi")
    pg = Session()
    pg.add_account(OWNER)
    cloud = FakeCloud(pg)
    monkeypatch.setattr(sync_runner.cloud_sync, "session", lambda cfg, timeout=None: (cloud, OWNER))
    cfg = Config(workspace=str(ws.root), language="vi", device_id="dev-a", device_name="A")
    cfg.cloud_url, cfg.cloud_refresh_token = "https://x.supabase.co", "tok"
    ctx = common.AppContext(cfg, ws)
    yield app, ctx, pg
    ctx.close()
    pg.close()


def _wait(app, runner):
    end = time.monotonic() + 60
    while runner.busy and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)
    assert not runner.busy


def test_a_round_pushes_what_changed_here_and_says_so(setup):
    from dibekho.ui.sync_runner import SyncRunner

    app, ctx, pg = setup
    with db.transaction(ctx.conn):
        catalog.create_product(ctx.conn, "Keo A")
    twoway.start_from_this_machine(ctx.conn)
    told = []
    runner = SyncRunner(ctx, lambda: True, told.append)
    runner.start()
    _wait(app, runner)
    assert pg.query("select name_vi from public.products")[0]["name_vi"] == "Keo A"
    assert twoway.queued_count(ctx.conn) == 0
    assert "đã đồng bộ" in runner.status_text()
    runner.timer.stop()


def test_nothing_is_merged_while_the_user_is_busy(setup):
    from dibekho.ui.sync_runner import SyncRunner

    app, ctx, pg = setup
    pg.query("insert into public.meta(key, value) values ('low_stock_default', '12')")
    replica.set_enabled(ctx.conn, True)
    runner = SyncRunner(ctx, lambda: False, lambda text: None)
    runner.start()
    _wait(app, runner)
    assert db.get_meta(ctx.conn, "low_stock_default", "") != "12" and twoway.cursor(ctx.conn) == 0
    assert runner.soon.isActive()  # tried again soon
    runner.is_safe = lambda: True
    runner.start()
    _wait(app, runner)
    assert db.get_meta(ctx.conn, "low_stock_default") == "12"
    runner.timer.stop()
    runner.soon.stop()


def test_the_main_window_shows_the_cloud_state_only_in_cloud_mode(setup):
    from dibekho.ui.main_window import MainWindow

    app, ctx, pg = setup
    window = MainWindow(ctx)
    assert window.sync_btn.isHidden()
    replica.set_enabled(ctx.conn, True)
    window._update_sync()
    assert not window.sync_btn.isHidden() and "Cloud" in window.sync_btn.text()
    window._owner_timer.stop()
    window.sync.timer.stop()
