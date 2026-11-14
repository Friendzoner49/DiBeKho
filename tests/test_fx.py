"""The ₫ / ¥ switch (14/11/2026): the provider's answer, the cache for offline use, every amount on screen in yuan.
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


@pytest.fixture(autouse=True)
def dong_again():
    yield
    fx.Display.currency, fx.Display.rate = "vnd", None
    i18n.set_language("vi")


def test_amounts_on_screen_in_dong_or_yuan():
    assert fx.show_money(1188000) == "1.188.000" and fx.show_money(None) == "—"
    fx.Display.rate = fx.parse(ANSWER)
    assert fx.show_money(1188000) == "1.188.000"  # the switch still says dong
    fx.Display.currency = "cny"
    assert fx.show_money(1188000, "vi") == "¥308,88"
    assert fx.show_money(5000000, "vi") == "¥1.300"
    assert fx.show_money(5000000, "zh") == "¥1,300" and fx.show_money(1188000, "en") == "¥308.88"
    fx.Display.rate = None
    assert fx.show_money(1188000) == "1.188.000"  # no rate: dong, never a wrong number


class Ctx:
    def __init__(self):
        from dibekho.core.workspace import Config
        self.cfg = Config(workspace="x")


def wait_for(app, switch):
    for _ in range(200):
        app.processEvents()
        if switch.refresh_btn.isEnabled():
            return
        QApplication.instance().thread().msleep(10)
    raise AssertionError("the rate never arrived")


def test_the_switch_turns_every_amount_into_yuan_and_back(app):
    from dibekho.ui.currency_switch import CurrencySwitch

    i18n.set_language("vi")
    ctx, seen = Ctx(), []
    switch = CurrencySwitch(ctx, fetch=lambda: fx.parse(ANSWER))
    switch.changed.connect(lambda: seen.append(fx.Display.currency))
    assert switch.vnd.isChecked() and fx.Display.currency == "vnd"
    switch.cny.click()            # no rate yet: fetched first, then the amounts change
    wait_for(app, switch)
    assert switch.cny.isChecked() and fx.Display.in_cny() and ctx.cfg.currency == "cny"
    assert seen[-1] == "cny" and "3.846" in switch.info.text()
    switch.vnd.click()
    assert fx.Display.currency == "vnd" and ctx.cfg.currency == "vnd" and seen[-1] == "vnd"

    again = CurrencySwitch(ctx, fetch=lambda: fx.parse(ANSWER))  # the choice and the kept rate come back
    assert again.vnd.isChecked()
    ctx.cfg.currency = "cny"
    again = CurrencySwitch(ctx, fetch=lambda: fx.parse(ANSWER))
    wait_for(app, again)
    assert again.cny.isChecked() and fx.Display.in_cny()


def test_no_rate_offline_stays_in_dong(app, monkeypatch):
    from dibekho.ui import currency_switch
    from dibekho.ui.currency_switch import CurrencySwitch

    i18n.set_language("zh")
    said = []
    monkeypatch.setattr(currency_switch, "error", lambda parent, text: said.append(text))

    def offline():
        raise OSError("no network")

    switch = CurrencySwitch(Ctx(), fetch=offline)
    switch.cny.click()
    wait_for(app, switch)
    assert switch.vnd.isChecked() and fx.Display.currency == "vnd"
    assert said == [i18n.t("fx.no_rate_error")]
