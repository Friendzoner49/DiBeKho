"""'Yêu cầu từ nhân viên (web)' in Cần xử lý: goods-in slips, Excel delivery notes and stock counts that staff
sent from the webapp. Nothing reaches the books before the owner approves it here (core.cloud.inbox)."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dibekho.core import activity
from dibekho.core.cloud import inbox as cloud_inbox
from dibekho.core.cloud import sync as cloud_sync
from dibekho.core.cloud.client import CloudError, local_time
from dibekho.core.text import fmt_qty
from dibekho.i18n import t
from dibekho.ui.common import ask, error, fill_table, fit_window, fmt_date, hint_label, info, location_name, make_table


def _buttons(*specs) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(2, 0, 2, 0)
    for text, slot in specs:
        b = QPushButton(text)
        b.clicked.connect(slot)
        lay.addWidget(b)
    return w


class WebCountDialog(QDialog):
    """The owner checks a count sent from the web: counted, what the app knew when it was sent, the difference."""

    def __init__(self, conn, item, parent=None):
        super().__init__(parent)
        sender = item.get("sender") or t("web.unknown_sender")
        self.setWindowTitle(t("web.count_title", sender=sender))
        fit_window(self, 900, 620)
        day, location, _, self.problems = cloud_inbox.check_count(conn, item)
        self.rows = cloud_inbox.count_preview(conn, item)
        lay = QVBoxLayout(self)
        lay.addWidget(hint_label(t("web.count_head", place=location_name(location), date=fmt_date(day.isoformat()),
                                   sent=local_time(item.get("created_at")))))
        if self.problems:
            warn = QLabel("⚠ " + " ".join(self.problems))
            warn.setWordWrap(True)
            lay.addWidget(warn)
        # the products that differ first, the biggest difference at the top
        self.rows.sort(key=lambda r: (-abs(r.diff), r.code))
        different = sum(1 for r in self.rows if abs(r.diff) > 1e-9)
        lay.addWidget(QLabel(t("web.count_summary", different=different, total=len(self.rows))))
        self.table = make_table([t("col.code"), t("col.product"), t("web.col_counted"), t("web.col_system"),
                                 t("web.col_diff")], stretch=1)
        fill_table(self.table, [[r.code, r.name, fmt_qty(r.counted), fmt_qty(r.system), f"{r.diff:+g}"]
                                for r in self.rows])
        lay.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok = buttons.button(QDialogButtonBox.Ok)
        ok.setText(t("web.count_go"))
        ok.setEnabled(not self.problems)
        for b in (ok, buttons.button(QDialogButtonBox.Cancel)):
            b.setAutoDefault(False)  # Enter must not approve a count by accident
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)


class WebRequestsPanel(QGroupBox):
    def __init__(self, ctx, run, parent=None):
        """run(action, undo_action): PendingPage._run -- undo point, the action, then a rescan."""
        super().__init__(t("web.title"), parent)
        self.ctx, self.run = ctx, run
        lay = QVBoxLayout(self)
        lay.addWidget(hint_label(t("web.hint")))
        self.table = make_table([t("web.col_kind"), t("web.col_sender"), t("web.col_detail"), t("web.col_sent"),
                                 t("pending.actions")], stretch=2)
        lay.addWidget(self.table)
        bar = QHBoxLayout()
        self.all_btn = QPushButton(t("web.apply_all"))
        self.all_btn.clicked.connect(self.apply_all)
        bar.addWidget(self.all_btn)
        bar.addStretch()
        lay.addLayout(bar)

    # ---- showing -------------------------------------------------------------------------------------------

    def detail(self, item) -> str:
        p = cloud_inbox.payload_of(item)
        kind = item.get("kind")
        if kind == cloud_inbox.RECEIPT:
            return t("web.detail_receipt", date=fmt_date(str(p.get("doc_date") or "")),
                     source=str(p.get("supplier_name") or ""), n=len(p.get("lines") or []))
        if kind == cloud_inbox.DELIVERY_FILE:
            size = p.get("size") if isinstance(p.get("size"), int) else 0
            return t("web.detail_file", name=str(p.get("file_name") or ""), kb=max(1, round(size / 1024)))
        return t("web.detail_count", date=fmt_date(str(p.get("count_date") or "")),
                 place=location_name(p.get("location_id")), n=len(p.get("lines") or []))

    def refresh(self):
        items = self.ctx.web_inbox
        fill_table(self.table, [[t(f"web.kind_{it['kind']}"), it.get("sender") or t("web.unknown_sender"),
                                 self.detail(it), local_time(it.get("created_at")), ""] for it in items])
        for i, it in enumerate(items):
            self.table.setCellWidget(i, 4, _buttons(
                (t("web.apply"), lambda _=False, x=it: self.apply(x)),
                (t("pending.web_reject"), lambda _=False, x=it: self.reject(x)),
            ))
        self.table.resizeColumnsToContents()
        self.all_btn.setVisible(any(it["kind"] != cloud_inbox.STOCK_COUNT for it in items))
        self.setVisible(bool(items))

    def _forget(self, item):
        self.ctx.web_inbox = [x for x in self.ctx.web_inbox if x["id"] != item["id"]]

    def _session(self):
        pair = cloud_sync.session(self.ctx.cfg)
        if pair is None:
            raise CloudError(t("cloud.need_password"))
        return pair

    # ---- approving -----------------------------------------------------------------------------------------

    def apply(self, item):
        activity.log("click", f"web_request {item.get('kind')}")
        kind = item.get("kind")
        if kind == cloud_inbox.RECEIPT:
            self._apply_receipt(item)
        elif kind == cloud_inbox.DELIVERY_FILE:
            self._apply_file(item)
        else:
            self._apply_count(item)

    def _apply_receipt(self, item):
        conn = self.ctx.conn
        data, problems = cloud_inbox.check(conn, item)
        if problems:
            error(self, " ".join(problems))
            return
        source = data.supplier_name
        if data.source == "return":  # goods a customer sent back: say who (the lines show the refund prices)
            name = data.customer_name or (conn.execute("SELECT name FROM customers WHERE id = ?",
                                                       (data.customer_id,)).fetchone() or [""])[0]
            source = t("receipt_form.source_return") + ": " + name + (
                f" · {t('receipt_form.order')} {data.ref_code}" if data.ref_code else "")
        text = t("pending.web_confirm", date=fmt_date(data.doc_date.isoformat()), source=source,
                 lines=cloud_inbox.describe(conn, item))
        if not ask(self, text):
            return

        def do():
            cloud_inbox.apply_item(conn, self.ctx.ws, item)
            self._forget(item)

        self.run(do, "web_inbox")

    def _apply_file(self, item):
        problems = cloud_inbox.check_delivery(item)
        if problems:
            error(self, " ".join(problems))
            return
        p = cloud_inbox.payload_of(item)
        if not ask(self, t("web.file_confirm", name=p.get("file_name", ""),
                           sender=item.get("sender") or t("web.unknown_sender"))):
            return

        def do():
            client, token = self._session()
            result = cloud_inbox.apply_delivery(self.ctx.conn, self.ctx.ws, client, token, item)
            self._forget(item)
            if result["placed"] is None:
                info(self, t("web.file_already", status=result["status"]))

        self.run(do, "web_inbox")

    def _apply_count(self, item):
        dlg = WebCountDialog(self.ctx.conn, item, self)
        if dlg.exec() != QDialog.Accepted:
            return

        def do():
            cloud_inbox.apply_count(self.ctx.conn, item)
            self._forget(item)

        self.run(do, "web_inbox")

    def apply_all(self):
        """End-of-day: every goods-in slip and delivery file in one go. Counts are checked one by one."""
        todo = [it for it in self.ctx.web_inbox if it["kind"] in (cloud_inbox.RECEIPT, cloud_inbox.DELIVERY_FILE)]
        receipts_n = sum(1 for it in todo if it["kind"] == cloud_inbox.RECEIPT)
        if not todo or not ask(self, t("web.apply_all_confirm", receipts=receipts_n, files=len(todo) - receipts_n)):
            return

        def do():
            failed = []
            pair = None
            for it in todo:
                label = f"{t('web.kind_' + it['kind'])} · {self.detail(it)}"
                try:
                    if it["kind"] == cloud_inbox.RECEIPT:
                        cloud_inbox.apply_item(self.ctx.conn, self.ctx.ws, it)
                    else:
                        pair = pair or self._session()
                        cloud_inbox.apply_delivery(self.ctx.conn, self.ctx.ws, *pair, it)
                    self._forget(it)
                except (ValueError, CloudError) as exc:
                    failed.append(f"• {label}: {exc}")
            if failed:
                error(self, t("web.apply_all_failed", n=len(failed), list="\n".join(failed)))

        self.run(do, "web_inbox")

    def reject(self, item):
        if not ask(self, t("pending.web_reject_ask")):
            return
        try:
            client, token = self._session()
            cloud_inbox.reject(client, token, item)
        except CloudError as exc:
            error(self, str(exc))
            return
        activity.log("action", "web_inbox_rejected")
        self._forget(item)
        self.refresh()
        self.ctx.notify()
