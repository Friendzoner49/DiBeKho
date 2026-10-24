"""The activity log: at most 1 MB (the oldest lines go), never written before setup, never breaks the app;
hidden behind 3 clicks on the version number."""

import os

import pytest

from dibekho.core import activity

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def log_file(tmp_path):
    path = tmp_path / "app.log"
    activity.setup(path)
    yield path
    activity.setup(None)


def test_nothing_is_written_before_setup(tmp_path):
    activity.setup(None)
    activity.log("click", "x")  # no file, no error
    assert activity.read() == ""


def test_the_log_stays_under_1_mb_and_keeps_the_newest_lines(log_file):
    activity.log("start", "đầu tiên")
    line = "Lưu phiếu hàng về · 管根套 90-110 · " * 3
    for i in range(12000):
        activity.log("click", f"{i} {line}")
        if i == 5000:  # a traceback in the middle: continuation lines are indented
            try:
                raise ValueError("lỗi thử")
            except ValueError:
                activity.log_exception("error", "Không lưu được")
    data = log_file.read_bytes()
    assert len(data) <= activity.MAX_BYTES
    text = data.decode("utf-8")  # cut at a line: Vietnamese and Chinese stay whole
    assert "đầu tiên" not in text and text.rstrip().endswith(f"11999 {line}".rstrip())
    assert not text.startswith(" ")
    assert text.splitlines()[0][4] == "-"  # starts with a date


def test_a_traceback_is_kept_with_its_error(log_file):
    try:
        {}["x"]
    except KeyError:
        activity.log_exception("error", "Không đọc được phiếu")
    text = activity.read()
    assert "[error] Không đọc được phiếu" in text and "    Traceback" in text and "KeyError" in text


def test_a_write_that_fails_is_ignored(tmp_path):
    activity.setup(tmp_path / "no-such-folder" / "app.log")
    activity.log("click", "x")  # no exception
    activity.setup(None)


def test_db_log_also_goes_to_the_file(log_file):
    from dibekho import db

    conn = db.connect(":memory:")
    db.log(conn, "receipt_entered", "HV001 #1")
    assert "[data] receipt_entered HV001 #1" in activity.read()
    conn.close()


def test_three_clicks_on_the_version_show_the_log_button(log_file, ws, monkeypatch):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    from dibekho import i18n
    from dibekho.core.workspace import Config
    from dibekho.ui.common import ActivityFilter, AppContext
    from dibekho.ui.log_dialog import LogDialog
    from dibekho.ui.settings_page import SettingsPage

    app = QApplication.instance() or QApplication([])
    i18n.set_language("vi")
    ctx = AppContext(Config(workspace=str(ws.root), language="vi", device_id="x", device_name="t"), ws)
    page = SettingsPage(ctx)
    page.show()
    assert not page.log_btn.isVisible()

    def send(kind):
        app.sendEvent(page.version, QMouseEvent(kind, QPointF(2, 2), QPointF(2, 2), Qt.LeftButton, Qt.LeftButton,
                                                Qt.NoModifier))

    # a quick triple click as Qt delivers it: press, release, double-click, release, press, release
    for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick,
                 QEvent.MouseButtonRelease, QEvent.MouseButtonPress):
        send(kind)
        assert not page.log_btn.isVisible()
    send(QEvent.MouseButtonRelease)
    assert page.log_btn.isVisible()

    # clicks on buttons are written down
    app.installEventFilter(flt := ActivityFilter(app))
    page.log_btn.setVisible(True)
    monkeypatch.setattr(LogDialog, "exec", lambda self: 0)
    from PySide6.QtTest import QTest

    QTest.mouseClick(page.log_btn, Qt.LeftButton)
    app.removeEventFilter(flt)
    assert "[click] Nhật ký…" in activity.read()
    dlg = LogDialog(ctx, page)
    assert "Nhật ký…" in dlg.text.toPlainText()
    dlg.close()
    page.close()
    ctx.close()
