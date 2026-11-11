"""The 'Yêu cầu từ nhân viên (web)' panel and the count approval dialog, with real widgets (offscreen)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from dibekho import db, i18n  # noqa: E402
from dibekho.core import catalog  # noqa: E402
from dibekho.core.workspace import Config  # noqa: E402

UUID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def vietnamese():
    yield
    i18n.set_language("vi")


def _ctx(ws, lang="vi"):
    from dibekho.ui.common import AppContext
    i18n.set_language(lang)
    return AppContext(Config(workspace=str(ws.root), language=lang, device_id="x", device_name="test"), ws)


def _product(ctx):
    with db.transaction(ctx.conn):
        return catalog.create_product(ctx.conn, "Keo chống thấm", spec="15kg", unit="thùng")


def _items(pid):
    sent = "2026-11-10T08:00:00Z"
    return [
        {"id": "r1", "kind": "receipt", "created_at": sent, "sender": "Lan",
         "payload": {"doc_date": "2026-11-10", "supplier_name": "Cửa khẩu", "location_id": 1,
                     "lines": [{"product_id": pid, "qty": 5}]}},
        {"id": "f1", "kind": "delivery_file", "created_at": sent, "sender": "Minh",
         "payload": {"file_path": f"{UUID}/Phieu 7.xlsx", "file_name": "Phieu 7.xlsx", "size": 20480,
                     "sha256": "0" * 64}},
        {"id": "c1", "kind": "stock_count", "created_at": sent, "sender": "Lan",
         "payload": {"count_date": "2026-11-10", "location_id": 2, "lines": [{"product_id": pid, "qty": 3}]}},
    ]


def _run_now(action, undo_action="x"):
    action()


@pytest.mark.parametrize("lang", ["vi", "en", "zh"])
def test_panel_lists_every_kind(app, ws, lang):
    from dibekho.ui.web_requests import WebRequestsPanel

    ctx = _ctx(ws, lang)
    ctx.web_inbox = _items(_product(ctx))
    panel = WebRequestsPanel(ctx, _run_now)
    panel.refresh()
    assert panel.table.rowCount() == 3 and not panel.isHidden()
    cells = [[panel.table.item(r, c).text() for c in range(4)] for r in range(3)]
    assert {row[1] for row in cells} == {"Lan", "Minh"}  # who sent it
    assert any("Phieu 7.xlsx" in row[2] and "20 KB" in row[2] for row in cells)
    assert not panel.all_btn.isHidden()  # there are slips and notes to approve in one go
    ctx.web_inbox = [i for i in ctx.web_inbox if i["kind"] == "stock_count"]
    panel.refresh()
    assert panel.all_btn.isHidden()  # counts are approved one by one
    ctx.web_inbox = []
    panel.refresh()
    assert panel.isHidden()


@pytest.mark.parametrize("lang", ["vi", "en", "zh"])
def test_count_dialog_shows_the_difference_and_blocks_bad_requests(app, ws, lang):
    from dibekho.ui.web_requests import WebCountDialog
    from PySide6.QtWidgets import QDialogButtonBox

    ctx = _ctx(ws, lang)
    pid = _product(ctx)
    good = _items(pid)[2]
    dlg = WebCountDialog(ctx.conn, good)
    assert dlg.table.rowCount() == 1
    assert dlg.table.item(0, 2).text() == "3" and dlg.table.item(0, 4).text() == "+3"  # 0 in the books, counted 3
    assert dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).isEnabled()

    bad = _items(pid)[2]
    bad["payload"]["lines"] = [{"product_id": pid, "qty": -4}]
    dlg_bad = WebCountDialog(ctx.conn, bad)
    assert not dlg_bad.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).isEnabled()  # cannot be approved


def test_apply_all_records_the_good_ones_and_reports_the_rest(app, ws, monkeypatch):
    import dibekho.ui.web_requests as wr
    from dibekho.ui.web_requests import WebRequestsPanel

    ctx = _ctx(ws)
    pid = _product(ctx)
    good = _items(pid)[0]
    broken = {**_items(pid)[0], "id": "r2",
              "payload": {"doc_date": "2026-11-10", "supplier_name": "X", "lines": [{"product_id": 999, "qty": 1}]}}
    ctx.web_inbox = [good, broken]
    shown = []
    monkeypatch.setattr(wr, "ask", lambda *a, **k: True)
    monkeypatch.setattr(wr, "error", lambda parent, text: shown.append(text))
    panel = WebRequestsPanel(ctx, _run_now)
    panel.apply_all()
    assert ctx.conn.execute("SELECT COUNT(*) FROM documents WHERE kind = 'receipt'").fetchone()[0] == 1
    assert [i["id"] for i in ctx.web_inbox] == ["r2"]  # the broken one stays for the owner to look at
    assert len(shown) == 1 and "#999" in shown[0]
