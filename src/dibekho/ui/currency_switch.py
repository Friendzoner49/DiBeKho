"""The '₫ | ¥' switch at the bottom left of the main window (user's request 14/11/2026): ¥ shows every amount of the
app (revenue, prices, totals, statistics) in yuan at today's market rate; ₫ goes back to dong. The data and every
file (Excel, packages, the issue note) stay in VND: only the text on screen changes (core/fx.Display).

The rate comes from core/fx.py: kept in fx.json for offline use, fetched again in the background when older than six
hours. The choice is remembered in config.json. Nothing here writes the shop's data: no undo point."""

import threading

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from dibekho.core import fx
from dibekho.core.text import fmt_money
from dibekho.i18n import t
from dibekho.ui.common import error


class CurrencySwitch(QWidget):
    _got = Signal(object, str)  # Rate or None, error text; emitted from the fetching thread
    changed = Signal()          # the screens must draw their amounts again

    def __init__(self, ctx, parent=None, fetch=fx.fetch):
        super().__init__(parent)
        self.ctx = ctx
        self._fetch = fetch
        self._busy = False
        self._explicit = False
        self._switch_after = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        row = QHBoxLayout()
        row.setSpacing(0)
        self.vnd = QPushButton("₫")
        self.cny = QPushButton("¥")
        self.group = QButtonGroup(self)
        for b, tip in ((self.vnd, "fx.show_vnd"), (self.cny, "fx.show_cny")):
            b.setCheckable(True)
            b.setToolTip(t(tip))
            b.setMinimumWidth(48)
            b.setStyleSheet("QPushButton:checked { background: palette(highlight); color: palette(highlighted-text); font-weight: bold; }")
            self.group.addButton(b)
            row.addWidget(b)
        self.refresh_btn = QToolButton()
        self.refresh_btn.setText("⟳")
        self.refresh_btn.setToolTip(t("fx.refresh"))
        self.refresh_btn.clicked.connect(lambda: self.refresh(explicit=True))
        row.addSpacing(6)
        row.addWidget(self.refresh_btn)
        row.addStretch()
        lay.addLayout(row)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(self.info)
        self._got.connect(self._arrived)

        fx.Display.rate = fx.cached()
        fx.Display.currency = "cny" if getattr(ctx.cfg, "currency", "vnd") == "cny" and fx.Display.rate else "vnd"
        (self.cny if fx.Display.currency == "cny" else self.vnd).setChecked(True)
        self.cny.toggled.connect(self._toggled)
        self._show()
        if fx.Display.currency == "cny" and not fx.is_fresh(fx.Display.rate):
            self.refresh()
        elif getattr(ctx.cfg, "currency", "vnd") == "cny" and fx.Display.rate is None:
            self._switch_after = True  # yuan chosen but no rate kept on this computer: dong until it arrives
            self.refresh()

    # ---------------------------------------------------------------- choice

    def _toggled(self, cny: bool):
        if cny and fx.Display.rate is None:
            self.vnd.setChecked(True)  # no rate yet: stay in dong while it is fetched, then switch
            self._switch_after = True
            self.refresh(explicit=True)
            return
        self._set("cny" if cny else "vnd")
        if cny and not fx.is_fresh(fx.Display.rate):
            self.refresh()

    def _set(self, currency: str):
        fx.Display.currency = currency
        self.ctx.cfg.currency = currency
        try:
            self.ctx.cfg.save()
        except OSError:
            pass  # only a preference
        self._show()
        self.changed.emit()

    def _show(self, problem: str = ""):
        rate = fx.Display.rate
        if rate is None:
            self.info.setText(t("fx.no_rate") if self._busy else (t("fx.no_rate_error") if problem else ""))
            return
        text = t("fx.rate_short", rate=fmt_money(round(rate.vnd_per_cny)), when=rate.updated.strftime("%d/%m"))
        if problem:
            text += "\n" + t("fx.offline", when=rate.fetched.strftime("%d/%m %H:%M"))
        self.info.setText(text)
        self.info.setToolTip(t("fx.source", source=fx.SOURCE))

    # ---------------------------------------------------------------- the rate

    def refresh(self, explicit: bool = False):
        if self._busy:
            return
        self._busy = True
        self._explicit = explicit
        self.refresh_btn.setEnabled(False)
        self._show()

        def work():
            try:
                rate, problem = self._fetch(), ""
            except Exception as exc:  # offline, VPN, the provider down: the cached rate stays
                rate, problem = None, str(exc) or "?"
            try:
                self._got.emit(rate, problem)
            except RuntimeError:  # the window was closed meanwhile
                pass

        threading.Thread(target=work, daemon=True).start()

    def _arrived(self, rate, problem: str):
        self._busy = False
        self.refresh_btn.setEnabled(True)
        if rate is not None:
            fx.Display.rate = rate
        self._show(problem)
        if self._switch_after:
            self._switch_after = False
            if fx.Display.rate is not None:
                self.cny.blockSignals(True)
                self.cny.setChecked(True)
                self.cny.blockSignals(False)
                self._set("cny")
                return
        if fx.Display.rate is None and self._explicit:
            error(self, t("fx.no_rate_error"))
        if rate is not None and fx.Display.currency == "cny":
            self.changed.emit()  # new rate: the amounts change


