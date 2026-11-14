"""The small '¥ ⇄ ₫' converter (bottom left of the main window): type yuan or dong, the other box follows.

The rate is fetched in the background (core/fx.py) so the window opens at once; offline, the last rate is used
and its date is shown. Nothing here writes data: no undo point.
"""

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from dibekho.core import fx
from dibekho.core.text import fmt_money
from dibekho.i18n import t
from dibekho.ui.common import NoWheelSpin, fit_window, hint_label, title_label


class FxDialog(QDialog):
    _got = Signal(object, str)  # Rate or None, error text; emitted from the fetching thread

    def __init__(self, parent=None, fetch=fx.fetch):
        super().__init__(parent)
        self._fetch = fetch
        self.setWindowTitle(t("fx.title"))
        fit_window(self, 460, 300)
        self.rate = fx.cached()
        lay = QVBoxLayout(self)
        lay.addWidget(title_label(self.windowTitle()))
        form = QFormLayout()
        self.cny = NoWheelSpin()
        self.vnd = NoWheelSpin()
        for box, decimals in ((self.cny, 2), (self.vnd, 0)):
            box.setRange(0, 1e13)
            box.setDecimals(decimals)
            box.setMinimumWidth(260)
        self.cny.setSuffix(" ¥")
        self.vnd.setSuffix(" ₫")
        form.addRow(t("fx.cny") + ":", self.cny)
        form.addRow(t("fx.vnd") + ":", self.vnd)
        lay.addLayout(form)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        source = hint_label(t("fx.source", source=f'<a href="{fx.SOURCE_URL}">{fx.SOURCE}</a>'))
        source.setTextFormat(Qt.RichText)
        source.setOpenExternalLinks(True)
        lay.addWidget(source)
        buttons = QHBoxLayout()
        self.refresh_btn = QPushButton(t("fx.refresh"))
        self.refresh_btn.clicked.connect(self.refresh)
        close = QPushButton(t("btn.close"))
        close.clicked.connect(self.accept)
        buttons.addWidget(self.refresh_btn)
        buttons.addStretch()
        buttons.addWidget(close)
        lay.addLayout(buttons)

        self._busy = False
        self._from_cny = True  # which box the user typed in last: the other one follows
        self.cny.valueChanged.connect(lambda _: self._typed(True))
        self.vnd.valueChanged.connect(lambda _: self._typed(False))
        self._got.connect(self._arrived)
        self.cny.setValue(1)
        self._show()
        if not fx.is_fresh(self.rate):
            self.refresh()

    def _typed(self, from_cny: bool):
        if self._busy:
            return
        self._from_cny = from_cny
        self._convert()

    def _convert(self):
        if self.rate is None:
            return
        self._busy = True
        if self._from_cny:
            self.vnd.setValue(round(self.rate.to_vnd(self.cny.value())))
        else:
            self.cny.setValue(round(self.rate.to_cny(self.vnd.value()), 2))
        self._busy = False

    def _show(self, problem: str = ""):
        if self.rate is None:
            self.info.setText(t("fx.no_rate") if not problem else t("fx.no_rate_error"))
            return
        text = t("fx.rate", rate=fmt_money(round(self.rate.vnd_per_cny)), when=self.rate.updated.strftime("%d/%m/%Y"))
        if problem:
            text += "\n" + t("fx.offline", when=self.rate.fetched.strftime("%d/%m/%Y %H:%M"))
        self.info.setText(text)

    def refresh(self):
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText(t("fx.refreshing"))

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
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText(t("fx.refresh"))
        if rate is not None:
            self.rate = rate
        self._show(problem)
        self._convert()
