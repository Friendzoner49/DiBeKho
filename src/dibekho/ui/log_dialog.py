"""The activity log window, and the hidden way to it: click the version number 3 times in Settings → Chung,
a small 'Nhật ký…' button appears next to it (until the app is closed).

From 25/10/2026 a data package carries the sending machine's own log along (core.transfer), saved here as
data/nhat-ky-<máy>.log, one file per machine ever imported from (replaced, not added to, on a later import
from the same machine). The dropdown at the top switches between this machine's own log and any of those."""

import shutil
import time
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from dibekho.core import activity
from dibekho.i18n import t
from dibekho.ui.common import ask, fit_window, hint_label, info, open_path


class TripleClickLabel(QLabel):
    """Emits `revealed` on the third click within 1.5 s. Counted on release: the second click of a quick series
    arrives as a double-click event, not a press, so counting presses would rarely reach 3."""

    revealed = Signal()
    WINDOW = 1.5

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._clicks: list[float] = []

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            now = time.monotonic()
            self._clicks = [c for c in self._clicks if now - c < self.WINDOW] + [now]
            if len(self._clicks) >= 3:
                self._clicks = []
                self.revealed.emit()
        super().mouseReleaseEvent(event)


class LogDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(t("log.title"))
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        fit_window(self, 1100, 680)
        lay = QVBoxLayout(self)
        picker = QHBoxLayout()
        picker.addWidget(QLabel(t("log.which")))
        self.which = QComboBox()
        self.which.currentIndexChanged.connect(self._show_selected)
        picker.addWidget(self.which, 1)
        lay.addLayout(picker)
        self.hint = hint_label("")
        lay.addWidget(self.hint)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        lay.addWidget(self.text, 1)
        row = QHBoxLayout()
        for key, slot in (("log.refresh", self.refresh), ("log.copy", self.copy), ("log.save", self.save),
                          ("log.open_folder", self.open_folder), ("log.clear", self.clear)):
            b = QPushButton(t(key))
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        close = QPushButton(t("btn.close"))
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        self.refresh()

    def _fill_which(self):
        current = self.which.currentData()
        self.which.blockSignals(True)
        self.which.clear()
        self.which.addItem(t("log.this_device", name=self.ctx.cfg.device_name), None)
        for p in sorted(self.ctx.ws.data.glob("nhat-ky-*.log")) if self.ctx.ws.data.exists() else []:
            self.which.addItem(t("log.other_device", name=p.stem[len("nhat-ky-"):]), p)
        idx = self.which.findData(current) if current is not None else 0
        self.which.setCurrentIndex(max(idx, 0))
        self.which.blockSignals(False)

    def _current_path(self):
        chosen = self.which.currentData()
        return chosen if chosen is not None else activity.path()

    def _show_selected(self):
        path = self._current_path()
        self.hint.setText(t("log.hint", path=str(path or ""), size=activity.MAX_BYTES // 1000))
        text = ""
        if path is not None and path.exists():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
        self.text.setPlainText(text or t("log.empty"))
        bar = self.text.verticalScrollBar()
        bar.setValue(bar.maximum())

    def refresh(self):
        self._fill_which()
        self._show_selected()

    def copy(self):
        QGuiApplication.clipboard().setText(self.text.toPlainText())
        info(self, t("log.copied"))

    def save(self):
        """A copy in output/, to send (Zalo, email) to whoever looks after the app."""
        src = self._current_path()
        if src is None or not src.exists():
            info(self, t("log.empty"))
            return
        self.ctx.ws.output.mkdir(parents=True, exist_ok=True)
        dest = self.ctx.ws.output / f"NhatKy_{datetime.now():%Y-%m-%d_%H%M}.log"
        shutil.copyfile(src, dest)
        if ask(self, t("log.saved", path=str(dest))):
            open_path(dest.parent)

    def open_folder(self):
        if activity.path() is not None:
            open_path(activity.path().parent)

    def clear(self):
        if not ask(self, t("log.confirm_clear")):
            return
        path = self._current_path()
        if path is not None and path == activity.path():
            activity.clear()
            activity.log("log", "cleared")
        elif path is not None:
            try:
                path.write_text("", encoding="utf-8")
            except OSError:
                pass
        self.refresh()
