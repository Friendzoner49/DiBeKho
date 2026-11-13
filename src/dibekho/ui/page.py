from PySide6.QtWidgets import QVBoxLayout, QWidget

from dibekho.core import activity
from dibekho.ui.common import AppContext, hint_label, title_label


class Page(QWidget):
    """A screen in the main window. Refreshes when data changes, lazily if hidden."""

    def __init__(self, ctx: AppContext, title: str, hint: str = ""):
        super().__init__()
        self.ctx = ctx
        self._dirty = True
        self.title_text = title
        self.layout_ = QVBoxLayout(self)
        self.layout_.addWidget(title_label(title))
        if hint:
            self.layout_.addWidget(hint_label(hint))
        ctx.changed.connect(self._on_changed)

    def _on_changed(self):
        if self.isVisible():
            self._timed_refresh()
        else:
            self._dirty = True

    def showEvent(self, event):
        super().showEvent(event)
        if self._dirty:
            self._dirty = False
            self._timed_refresh()

    def _timed_refresh(self):
        with activity.slow_watch(f"refresh {type(self).__name__}"):
            self.refresh()

    def refresh(self):
        pass
