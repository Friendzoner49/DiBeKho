"""In cloud mode Undo never puts an old copy of the file back (it cancels the document just saved), and the window keeps
its size on screen. Restore / package / delete all on shared data: tests/test_cloud_admin.py."""

import os

import pytest



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
    window._inbox_timer.stop()
    window.sync.timer.stop()
