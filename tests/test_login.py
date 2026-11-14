"""The sign-in window when the app opens and the staff approvals in Cần xử lý (user, 15/11/2026). No network: the
cloud calls are replaced (the real ones run on PGlite in test_staff_push.py)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from dibekho import i18n  # noqa: E402
from dibekho.core.cloud import account, approval, replica  # noqa: E402
from dibekho.core.cloud.client import CloudError, SessionExpired  # noqa: E402
from dibekho.core.workspace import Config  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(ws, tmp_path, monkeypatch):
    from dibekho.core import workspace
    from dibekho.ui.common import AppContext

    monkeypatch.setattr(workspace, "config_dir", lambda: tmp_path / "cfg")
    i18n.set_language("vi")
    c = AppContext(Config(workspace=str(ws.root), language="vi", device_id="dev1", device_name="t"), ws)
    yield c
    if c.conn is not None:
        c.close()


def test_the_window_asks_only_for_the_account_when_the_build_carries_the_address(app, ctx, monkeypatch):
    from dibekho.core.cloud import builtin
    from dibekho.ui.login_dialog import LoginDialog

    monkeypatch.setattr(builtin, "builtin", lambda: ("https://x.supabase.co", "sb_publishable_test"))
    assert account.apply_builtin(ctx.cfg) and ctx.cfg.cloud_url == "https://x.supabase.co"
    dlg = LoginDialog(ctx.cfg)
    assert dlg.url is None and dlg.key is None
    monkeypatch.setattr(builtin, "builtin", lambda: ("", ""))
    assert LoginDialog(ctx.cfg).url is not None  # a build without it: the address can be typed


def test_a_wrong_password_stays_in_the_window(app, ctx, monkeypatch):
    from dibekho.ui import login_dialog

    def wrong(*a, **k):
        raise CloudError("Sai tên đăng nhập hoặc mật khẩu.")
    monkeypatch.setattr(login_dialog.account, "sign_in", wrong)
    dlg = login_dialog.LoginDialog(ctx.cfg)
    dlg.user.setText("lan")
    dlg.password.setText("x")
    dlg.sign_in()
    assert dlg.result() != QDialog.Accepted and "Sai" in dlg.problem.text() and dlg.password.text() == ""


def test_opening_signed_in_and_offline(app, ctx, monkeypatch):
    from dibekho import app as app_mod

    ctx.cfg.cloud_url, ctx.cfg.cloud_key, ctx.cfg.cloud_user = "https://x", "k", "maychinh"
    ctx.cfg.cloud_refresh_token, ctx.cfg.cloud_role = "r", "desktop"
    assert account.has_saved_session(ctx.cfg)

    def offline(cfg, timeout=10):
        raise CloudError("Không kết nối được Cloud.")
    monkeypatch.setattr(account, "resume", offline)
    replica.set_enabled(ctx.conn, True)
    assert app_mod.sign_in_and_link(ctx)  # linked already: opens on the local copy, syncs later

    asked = []

    class Dialog:
        def __init__(self, cfg, message=""):
            asked.append(message)

        def exec(self):
            return QDialog.Rejected
    monkeypatch.setattr("dibekho.ui.login_dialog.LoginDialog", Dialog)

    def expired(cfg, timeout=10):
        raise SessionExpired("x")
    monkeypatch.setattr(account, "resume", expired)
    assert not app_mod.sign_in_and_link(ctx)  # the window was closed: the app does not open
    assert asked == [i18n.t("login.again")]


def test_a_view_only_account_cannot_open_the_app():
    with pytest.raises(account.NotForApp):
        account._allowed("viewer")
    with pytest.raises(account.NotForApp):
        account._allowed("")
    assert account._allowed("editor") == "editor"


def test_the_owner_sees_and_approves_staff_changes(app, ctx, monkeypatch):
    from dibekho.ui import staff_pushes
    from dibekho.ui.pending_page import PendingPage

    ctx.staff_pushes = [{"id": "r1", "sender": "Lan", "device": "may-2", "created_at": "2026-11-15T02:00:00+00:00",
                         "summary": [{"t": "doc", "kind": "receipt", "code": "HV005", "date": "2026-11-15",
                                      "customer": "", "status": "active", "lines": 2},
                                     {"t": "product", "code": "SP070", "name": "Keo mới"}, {"t": "other", "n": 3}]}]
    page = PendingPage(ctx, lambda **k: None)
    page.refresh()
    panel = page.staff_panel
    assert not panel.isHidden() and panel.table.rowCount() == 1
    assert panel.table.item(0, 2).text() == "1 phiếu · 2 mục khác"
    assert "HV005" in panel.table.item(0, 2).toolTip() and "Keo mới" in panel.table.item(0, 2).toolTip()
    asked, decided = [], []
    monkeypatch.setattr(staff_pushes, "ask", lambda parent, text: asked.append(text) or True)
    monkeypatch.setattr(staff_pushes, "info", lambda *a: None)
    monkeypatch.setattr(staff_pushes.cloud_sync, "session", lambda cfg, timeout=None: ("client", "token"))
    monkeypatch.setattr(staff_pushes.approval, "decide",
                        lambda c, tok, rid, ok, reason="": decided.append((rid, ok)) or {"ok": True})
    panel.approve(ctx.staff_pushes[0])
    assert decided == [("r1", True)] and "HV005" in asked[0] and "Lan" in asked[0]
    assert ctx.staff_pushes == [] and panel.isHidden()


def test_staff_status_and_gates(app, ctx, monkeypatch):
    from datetime import date

    from dibekho import db
    from dibekho.core import catalog, stock
    from dibekho.ui import settings_page
    from dibekho.ui.sync_runner import SyncRunner

    ctx.cfg.cloud_role = "editor"
    replica.set_enabled(ctx.conn, True)
    with db.transaction(ctx.conn):
        p = catalog.create_product(ctx.conn, "Keo A")
        stock.record_trial_use(ctx.conn, date(2026, 11, 15), stock.MAIN, [stock.Line(p, 1)])
    runner = SyncRunner(ctx, lambda: True, lambda text: None)
    runner.timer.stop()
    assert "chưa gửi chủ duyệt" in runner.status_text()
    batch, seq, _ = __import__("dibekho.core.cloud.twoway", fromlist=["x"]).prepare(ctx.conn)
    approval.sent(ctx.conn, batch, seq, {"id": "r9"})
    assert "Chờ chủ duyệt" in runner.status_text()
    approval.take_answer(ctx.conn, {"id": "r9", "status": "rejected", "reason": "Sai ngày"})
    assert "Sai ngày" in runner.status_text()
    told = []
    monkeypatch.setattr(settings_page, "error", lambda parent, text: told.append(text))
    settings_page.SettingsPage.reset_stock(type("P", (), {"ctx": ctx})())
    assert told == [i18n.t("staff.not_for_staff")]
