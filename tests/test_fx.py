"""The yuan / dong converter (14/11/2026): the provider's answer, the cache for offline use, the window both ways.
No test goes to the internet: fetch is replaced."""

import os
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from dibekho import i18n  # noqa: E402
from dibekho.core import fx  # noqa: E402

ANSWER = {"result": "success", "base_code": "CNY", "time_last_update_unix": 1794614551,
          "rates": {"CNY": 1, "VND": 3846.153846, "USD": 0.14}}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_parse_and_convert():
    rate = fx.parse(ANSWER, fetched=datetime(2026, 11, 14, 9, 0))
    assert rate.vnd_per_cny == pytest.approx(3846.153846)
    assert rate.updated.date().isoformat() in ("2026-11-14", "2026-11-13")  # 00:02 UTC, local time zone
    assert round(rate.to_vnd(100)) == 384615
    assert rate.to_cny(3846.153846) == pytest.approx(1)


@pytest.mark.parametrize("bad", [{}, {"result": "error"}, {**ANSWER, "base_code": "USD"},
                                 {**ANSWER, "rates": {"VND": 0}}, {**ANSWER, "rates": {}}])
def test_a_wrong_answer_is_refused(bad):
    with pytest.raises(ValueError):
        fx.parse(bad)


def test_the_last_rate_is_kept_for_offline_use():
    assert fx.cached() is None
    rate = fx.parse(ANSWER, fetched=datetime(2026, 11, 14, 9, 0))
    fx.save(rate)
    again = fx.cached()
    assert again == rate
    assert fx.is_fresh(again, now=datetime(2026, 11, 14, 14, 0))
    assert not fx.is_fresh(again, now=datetime(2026, 11, 14, 16, 0))
    assert not fx.is_fresh(None)


def wait_for(app, dialog):
    for _ in range(200):
        app.processEvents()
        if dialog.refresh_btn.isEnabled():
            return
        QApplication.instance().thread().msleep(10)
    raise AssertionError("the rate never arrived")


def test_window_converts_both_ways_and_says_when_offline(app):
    from dibekho.ui.fx_dialog import FxDialog

    i18n.set_language("vi")
    dialog = FxDialog(fetch=lambda: fx.parse(ANSWER))
    wait_for(app, dialog)
    assert dialog.vnd.value() == 3846  # 1 ¥ to start with
    dialog.cny.setValue(250)
    assert dialog.vnd.value() == 961538
    dialog.vnd.setValue(1000000)
    assert dialog.cny.value() == 260.0
    assert "3.846" in dialog.info.text()

    def offline():
        raise OSError("no network")

    fx.save(fx.parse(ANSWER, fetched=datetime(2026, 11, 1, 8, 0)))
    later = FxDialog(fetch=offline)  # old cache: asks again, fails, keeps the old rate
    wait_for(app, later)
    assert later.vnd.value() == 3846
    assert "01/11/2026 08:00" in later.info.text()
    for d in (dialog, later):
        d.done(0)


def test_window_with_no_rate_at_all(app):
    from dibekho.ui.fx_dialog import FxDialog

    i18n.set_language("zh")

    def offline():
        raise OSError("no network")

    dialog = FxDialog(fetch=offline)
    wait_for(app, dialog)
    assert dialog.vnd.value() == 0 and dialog.info.text() == i18n.t("fx.no_rate_error")
    dialog.done(0)
