"""The main window and the owner's web commands: when they run, what the user is told, and that Hoàn tác sticks."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from dibekho import db, i18n  # noqa: E402
from dibekho.core import catalog, stock, undo  # noqa: E402
from dibekho.core.cloud import sync as cloud_sync  # noqa: E402
from dibekho.core.workspace import Config  # noqa: E402

OWNER = "u-owner"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def vietnamese():
    i18n.set_language("vi")
    yield
    i18n.set_language("vi")


class Cloud:
    def __init__(self, pending):
        self.pending, self.patches = pending, []

    def get(self, path, token):
        if "profiles" in path:
            return [{"user_id": OWNER, "display_name": "Chủ", "role": "desktop"},
                    {"user_id": "u-staff", "display_name": "Lan", "role": "editor"}]
        return self.pending

    def patch(self, path, body, token):
        self.patches.append((path.split("eq.")[-1], body["status"]))


def _window(ws):
    from dibekho.ui.common import AppContext
    from dibekho.ui.main_window import MainWindow
    ctx = AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="test"), ws)
    with db.transaction(ctx.conn):
        pid = catalog.create_product(ctx.conn, "Keo A", spec="15kg", unit="thùng")
        doc = stock.insert_document(ctx.conn, "delivery", date(2026, 11, 2), [stock.Line(pid, 5)], code="7",
                                    code_norm="7")
    row = ctx.conn.execute("SELECT kind, code, created_at FROM documents WHERE id = ?", (doc,)).fetchone()
    cancel = {"id": "cmd-1", "kind": "cmd_cancel_doc", "created_by": OWNER, "created_at": "2026-11-10T08:00:00Z",
              "payload": {"target": {"id": doc, "kind": row["kind"], "code": row["code"],
                                     "created_at": row["created_at"]}}}
    window = MainWindow(ctx)
    window.nav.setCurrentRow(0)
    return window, ctx, doc, cancel


def _wire(monkeypatch, cloud, shown):
    import dibekho.ui.main_window as mw
    monkeypatch.setattr(cloud_sync, "session", lambda cfg, timeout=None: (cloud, "tok"))
    monkeypatch.setattr(cloud_sync, "push_mirror", lambda *a, **k: {"conflict": False, "push_id": 1})
    monkeypatch.setattr(cloud_sync, "finish_push", lambda *a, **k: None)
    monkeypatch.setattr(mw, "info", lambda parent, text: shown.append(text))


def _status(conn, doc):
    return conn.execute("SELECT status FROM documents WHERE id = ?", (doc,)).fetchone()[0]


def test_commands_wait_on_pages_with_typed_work(app, ws, monkeypatch):
    from dibekho.ui.main_window import COUNT, PENDING
    window, ctx, doc, cancel = _window(ws)
    shown = []
    cloud = Cloud([cancel])
    _wire(monkeypatch, cloud, shown)
    window._take_inbox(cloud, "tok")
    assert [i["id"] for i in ctx.owner_waiting] == ["cmd-1"] and ctx.web_inbox == []

    for page in (PENDING, COUNT):  # Cần xử lý and Kiểm kê: a refresh would wipe what the user typed
        window.nav.setCurrentRow(page)
        assert not window._owner_safe()
        window._apply_owner_waiting()
        assert _status(ctx.conn, doc) == "active" and shown == []
    window._update_badge()
    assert "đang chờ" in window.status.text()  # the user is told something is waiting

    window.nav.setCurrentRow(0)  # leaving the page is the safe moment
    assert window._owner_safe()
    window._apply_owner_waiting()
    assert _status(ctx.conn, doc) == "cancelled"
    assert ctx.owner_waiting == []
    assert undo.latest(ws).action == "web_commands"  # one undo point for the batch
    assert len(shown) == 1 and "1 lệnh" in shown[0] and "Huỷ phiếu 7" in shown[0] and "Hoàn tác" in shown[0]
    assert cloud.patches == [("cmd-1", "applied")]
    window.close()


def test_a_dialog_in_front_blocks_it(app, ws, monkeypatch):
    from PySide6.QtWidgets import QDialog
    window, ctx, doc, cancel = _window(ws)
    _wire(monkeypatch, Cloud([cancel]), [])
    window._take_inbox(Cloud([cancel]), "tok")
    dialog = QDialog(window)
    dialog.setModal(True)
    dialog.show()
    app.processEvents()
    assert not window._owner_safe()  # e.g. a receipt form is open: its product ids must not change under it
    dialog.close()
    window.close()


def test_undo_of_the_batch_is_not_undone_by_the_next_poll(app, ws, monkeypatch):
    window, ctx, doc, cancel = _window(ws)
    shown = []
    cloud = Cloud([cancel])
    _wire(monkeypatch, cloud, shown)
    window._take_inbox(cloud, "tok")
    window._apply_owner_waiting()
    assert _status(ctx.conn, doc) == "cancelled"

    ctx.close()  # the owner presses Hoàn tác
    undo.undo(ws, undo.latest(ws))
    ctx.reopen()
    assert _status(ctx.conn, doc) == "active"

    window._take_inbox(cloud, "tok")  # the cloud (say the answer got lost) still lists the command as pending
    assert ctx.owner_waiting == [] and ctx.web_inbox == []  # it is neither re-applied nor offered
    window._apply_owner_waiting()
    assert _status(ctx.conn, doc) == "active" and len(shown) == 1
    window.close()


def test_staff_requests_still_go_to_the_approval_list(app, ws, monkeypatch):
    window, ctx, doc, cancel = _window(ws)
    staff_receipt = {"id": "r-1", "kind": "receipt", "created_by": "u-staff", "created_at": "2026-11-10T08:00:00Z",
                     "payload": {}}
    staff_cmd = {**cancel, "id": "cmd-2", "created_by": "u-staff"}  # not obeyed, not offered
    cloud = Cloud([staff_receipt, staff_cmd, cancel])
    _wire(monkeypatch, cloud, [])
    window._take_inbox(cloud, "tok")
    assert [i["id"] for i in ctx.web_inbox] == ["r-1"] and ctx.web_inbox[0]["sender"] == "Lan"
    assert [i["id"] for i in ctx.owner_waiting] == ["cmd-1"]
    window.close()


def test_a_refused_command_is_reported_to_the_user_too(app, ws, monkeypatch):
    window, ctx, doc, cancel = _window(ws)
    cancel["payload"]["target"]["created_at"] = "1999-01-01 00:00:00"  # stale
    shown = []
    cloud = Cloud([cancel])
    _wire(monkeypatch, cloud, shown)
    window._take_inbox(cloud, "tok")
    window._apply_owner_waiting()
    assert _status(ctx.conn, doc) == "active"
    assert cloud.patches == [("cmd-1", "rejected")]
    assert "Không làm được" in shown[0] and "Hoàn tác" in shown[0]
    window.close()
