"""Rows edited differently here and on the cloud (another machine or the web): the user picks which version stays.
Everything else keeps syncing meanwhile (docs/cloud/06-cloud-la-goc.md)."""

from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout

from dibekho.core import activity
from dibekho.core.cloud import twoway
from dibekho.i18n import t
from dibekho.ui.common import error, fill_table, fit_window, hint_label, make_table, selected_id

HIDDEN = {"id", "deleted", "rev", "created_at", "code_norm", "phone_norm"}


def _what(c: twoway.Conflict) -> str:
    row = c.cloud or c.local
    name = row.get("code") or row.get("name") or row.get("name_vi") or row.get("key") or ""
    extra = row.get("name_vi") if row.get("code") and row.get("name_vi") else ""
    return " · ".join(x for x in (t(f"sync.table.{c.table}"), name, extra) if x)


def _differences(c: twoway.Conflict) -> str:
    out = []
    for col in sorted(set(c.local) | set(c.cloud)):
        if col in HIDDEN or c.local.get(col) == c.cloud.get(col):
            continue
        label = t(f"sync.col.{col}") if t(f"sync.col.{col}") != f"sync.col.{col}" else col
        out.append(t("sync.diff", col=label, mine=c.local.get(col) if c.local.get(col) is not None else "",
                     theirs=c.cloud.get(col) if c.cloud.get(col) is not None else ""))
    return "\n".join(out)


class ConflictDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(t("sync.conflict_title"))
        fit_window(self, 900, 480)
        lay = QVBoxLayout(self)
        lay.addWidget(hint_label(t("sync.conflict_hint")))
        self.table = make_table([t("sync.conflict_what"), t("sync.conflict_diff")], stretch=1)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        mine = QPushButton(t("sync.keep_mine"))
        mine.clicked.connect(lambda: self.choose(True))
        theirs = QPushButton(t("sync.keep_cloud"))
        theirs.clicked.connect(lambda: self.choose(False))
        close = QPushButton(t("btn.close"))
        close.clicked.connect(self.accept)
        for b in (mine, theirs):
            b.setAutoDefault(False)
            row.addWidget(b)
        row.addStretch()
        row.addWidget(close)
        lay.addLayout(row)
        self.fill()

    def fill(self):
        self.items = twoway.conflicts(self.ctx.conn)
        fill_table(self.table, [[_what(c), _differences(c)] for c in self.items], ids=list(range(len(self.items))))
        self.table.resizeRowsToContents()

    def choose(self, keep_mine: bool):
        idx = selected_id(self.table)
        if idx is None:
            error(self, t("sync.pick_first"))
            return
        c = self.items[idx]
        activity.log("click", f"conflict {c.table} {'mine' if keep_mine else 'cloud'}")
        twoway.resolve(self.ctx.conn, c, keep_mine)
        self.ctx.notify()
        runner = getattr(self.ctx, "sync_runner", None)
        if runner is not None:
            runner.start()
        self.fill()
        if not self.items:
            self.accept()
