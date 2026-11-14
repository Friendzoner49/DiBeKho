"""Cần xử lý → 'Thay đổi của nhân viên chờ duyệt' (user's request 15/11/2026): what machines signed in with a staff
account want to write to the shared data. Only the owner's account sees it. Duyệt writes the changes exactly as
shown (cloud/supabase/016_staff_push.sql); Từ chối sends a reason back, the staff machine keeps its changes.
The list comes with every background sync round (ui/sync_runner.py -> ctx.staff_pushes)."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QInputDialog, QPushButton, QVBoxLayout, QWidget

from dibekho.core import activity
from dibekho.core.cloud import approval
from dibekho.core.cloud import sync as cloud_sync
from dibekho.core.cloud.client import CloudError, local_time
from dibekho.i18n import t
from dibekho.ui.common import ask, error, fill_table, fmt_date, hint_label, info, make_table

SHOWN = 30  # lines of one request in the question before approving; the rest is counted


def describe(summary) -> list[str]:
    """The lines the owner reads, in the interface language."""
    lines, items = [], summary if isinstance(summary, list) else []
    for it in items:
        if not isinstance(it, dict):
            continue
        kind = it.get("t")
        if kind == "doc":
            name = t(f"kind.{it.get('kind')}") if it.get("kind") else t("sync.table.documents")
            key = "staff.item_doc" if it.get("status") == "active" else "staff.item_doc_closed"
            text = t(key, kind=name, code=str(it.get("code") or ""), date=fmt_date(str(it.get("date") or "")),
                     n=int(it.get("lines") or 0))
            lines.append(text + (f" · {it['customer']}" if it.get("customer") else ""))
        elif kind == "doc_deleted":
            lines.append(t("staff.item_doc_deleted"))
        elif kind == "product":
            lines.append(t("staff.item_product", code=str(it.get("code") or ""), name=str(it.get("name") or "")))
        elif kind == "product_deleted":
            lines.append(t("staff.item_product_deleted"))
        elif kind == "customer":
            lines.append(t("staff.item_customer", name=str(it.get("name") or "")))
        elif kind == "other":
            lines.append(t("staff.item_other", n=int(it.get("n") or 0)))
    return lines


def short(summary) -> str:
    items = [it for it in (summary if isinstance(summary, list) else []) if isinstance(it, dict)]
    docs = sum(1 for it in items if it.get("t") in ("doc", "doc_deleted"))
    return t("staff.short", docs=docs, rest=len(items) - docs)


class StaffPushPanel(QGroupBox):
    def __init__(self, ctx, parent=None):
        super().__init__(t("staff.title"), parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.addWidget(hint_label(t("staff.hint")))
        self.table = make_table([t("web.col_sender"), t("cloud.col_device"), t("web.col_detail"), t("web.col_sent"),
                                 t("pending.actions")], stretch=2)
        lay.addWidget(self.table)

    def refresh(self):
        items = getattr(self.ctx, "staff_pushes", [])
        fill_table(self.table, [[it.get("sender") or t("web.unknown_sender"), it.get("device") or "",
                                 short(it.get("summary")), local_time(it.get("created_at")), ""] for it in items])
        for i, it in enumerate(items):
            box = QWidget()
            row = QHBoxLayout(box)
            row.setContentsMargins(2, 0, 2, 0)
            for label, run in ((t("staff.approve"), self.approve), (t("pending.web_reject"), self.reject)):
                b = QPushButton(label)
                b.clicked.connect(lambda _=False, x=it, f=run: f(x))
                row.addWidget(b)
            self.table.setCellWidget(i, 4, box)
            self.table.item(i, 2).setToolTip("\n".join(describe(it.get("summary"))[:SHOWN]))
        self.table.resizeColumnsToContents()
        self.setVisible(bool(items))

    def _decide(self, item, approve: bool, reason: str = "") -> dict | None:
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            pair = cloud_sync.session(self.ctx.cfg, timeout=30)
            if pair is None:
                raise CloudError(t("admin.need_cloud"))
            return approval.decide(pair[0], pair[1], item["id"], approve, reason)
        except CloudError as exc:
            error(self, str(exc))
            return None
        finally:
            QGuiApplication.restoreOverrideCursor()

    def _done(self, item):
        self.ctx.staff_pushes = [x for x in self.ctx.staff_pushes if x.get("id") != item.get("id")]
        self.refresh()
        runner = getattr(self.ctx, "sync_runner", None)
        if runner is not None:
            runner.start()  # what was approved comes to this machine too
        self.ctx.notify()

    def approve(self, item):
        lines = describe(item.get("summary"))
        text = "\n".join("• " + x for x in lines[:SHOWN])
        if len(lines) > SHOWN:
            text += "\n" + t("staff.more", n=len(lines) - SHOWN)
        if not ask(self, t("staff.confirm_approve", sender=item.get("sender") or t("web.unknown_sender"),
                           device=item.get("device") or "", lines=text)):
            return
        activity.log("click", "staff_push approve")
        answer = self._decide(item, True)
        if answer is None:
            return
        if answer.get("ok"):
            self._done(item)
            info(self, t("staff.approved"))
        elif answer.get("reason") == "stale":
            error(self, t("staff.stale"))
        else:
            self._done(item)
            info(self, t("staff.gone"))

    def reject(self, item):
        reason, ok = QInputDialog.getText(self, t("pending.web_reject"),
                                          t("staff.reject_reason", sender=item.get("sender") or t("web.unknown_sender")))
        if not ok:
            return
        activity.log("click", "staff_push reject")
        answer = self._decide(item, False, reason.strip())
        if answer is None:
            return
        self._done(item)
        if not answer.get("ok"):
            info(self, t("staff.gone"))
