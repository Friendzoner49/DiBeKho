"""Opt-in key/input-method logger for diagnosing the "digit doubles on macOS Telex" report (29/10/2026,
mục 9.13) inside the real packaged app, after a bare PySide6 script could not reproduce it. Only installed
when the DIBEKHO_KEYLOG environment variable is set (see app.main()) -- normal use never loads this module
or prints anything. Remove once the Mac bug is understood; this is a throwaway diagnostic, not a feature."""

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QInputMethodEvent, QKeyEvent


class KeyLogFilter(QObject):
    def eventFilter(self, obj, event):
        tag = f"{type(obj).__name__}#{obj.objectName() or id(obj)}"
        if isinstance(event, QKeyEvent) and event.type() == QEvent.KeyPress:
            print(f"[KEYLOG] [{tag}] KeyPress text={event.text()!r} key={event.key()}", flush=True)
        elif isinstance(event, QInputMethodEvent):
            print(f"[KEYLOG] [{tag}] InputMethod commit={event.commitString()!r} "
                  f"preedit={event.preeditString()!r}", flush=True)
        return False
