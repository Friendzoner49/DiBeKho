"""'Cần xử lý': unknown product names, edited/deleted/invalid files, and input/ items."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dibekho import db
from dibekho.core import backup, catalog, deliveries, inbox, transfer
from dibekho.core.text import fmt_qty
from dibekho.i18n import t
from dibekho.ui.common import (
    GREY,
    ask,
    error,
    fill_table,
    fmt_date,
    hint_label,
    info,
    make_table,
    open_path,
)
from dibekho.ui.catalog_import import import_catalog_file
from dibekho.ui.page import Page
from dibekho.ui.receipt_page import review_receipt

NEW, LATER, SKIP = "new", "later", "skip"
NAME, NAME_ZH, SPEC, ORDERS, CHOICE, DROP = range(6)


def _buttons(*specs) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(2, 0, 2, 0)
    for text, slot in specs:
        b = QPushButton(text)
        b.clicked.connect(slot)
        lay.addWidget(b)
    return w


class PendingPage(Page):
    def __init__(self, ctx, rescan):
        super().__init__(ctx, t("nav.pending"), t("pending.hint"))
        self.rescan = rescan  # callable from the main window: scan + notify

        self.unknown_box = QGroupBox(t("pending.unknown_title"))
        lay = QVBoxLayout(self.unknown_box)
        lay.addWidget(hint_label(t("pending.unknown_hint")))
        self.unknown = make_table([t("pending.name_on_note"), t("col.name_zh"), t("col.spec"), t("pending.in_orders"),
                                   t("pending.map_to"), ""], stretch=CHOICE)
        self.unknown.setWordWrap(False)  # long names are cut; the full text is in the tooltip
        lay.addWidget(self.unknown)
        row = QHBoxLayout()
        apply_btn = QPushButton(t("pending.apply"))
        apply_btn.clicked.connect(self.apply_mapping)
        font = apply_btn.font()
        font.setBold(True)
        apply_btn.setFont(font)
        row.addWidget(apply_btn)
        row.addStretch()
        lay.addLayout(row)
        self.layout_.addWidget(self.unknown_box, 3)

        self.files_box = QGroupBox(t("pending.files_title"))
        lay = QVBoxLayout(self.files_box)
        self.files = make_table([t("col.status"), t("col.file"), t("pending.detail"), t("pending.actions")], stretch=2)
        lay.addWidget(self.files)
        self.layout_.addWidget(self.files_box, 2)

        self.inbox_box = QGroupBox(t("pending.inbox_title"))
        lay = QVBoxLayout(self.inbox_box)
        self.inbox = make_table([t("pending.type"), t("col.file"), t("pending.detail"), t("pending.actions")],
                                stretch=2)
        lay.addWidget(self.inbox)
        self.layout_.addWidget(self.inbox_box, 2)

        self.empty = QLabel(t("pending.empty"))
        self.layout_.addWidget(self.empty)
        self.layout_.addStretch()  # keeps title and hint at the top when every box is hidden

    # ---- refresh -----------------------------------------------------------

    def refresh(self):
        conn, ws = self.ctx.conn, self.ctx.ws
        self._unknown = deliveries.unknown_lines(conn, ws)
        products = catalog.products(conn)
        fill_table(self.unknown, [[u.name_vi, u.name_zh, u.spec, "; ".join(u.orders), "", ""]
                                  for u in self._unknown])
        self.unknown.setSortingEnabled(False)  # row r must stay self._unknown[r]
        for r, u in enumerate(self._unknown):
            self.unknown.setCellWidget(r, CHOICE, self._choice_combo(r, u, products))
            drop = QPushButton()
            drop.clicked.connect(lambda _=False, row=r: self._toggle_drop(row))
            self.unknown.setCellWidget(r, DROP, drop)
            self._restyle(r)
            for c in (NAME, ORDERS):
                self.unknown.item(r, c).setToolTip(self.unknown.item(r, c).text().replace("; ", chr(10)))
        # long product names: fixed widths instead of fitting the (very wide) contents
        for col, width in ((NAME, 240), (NAME_ZH, 130), (SPEC, 110), (ORDERS, 160), (DROP, 110), (CHOICE, 240)):
            self.unknown.setColumnWidth(col, width)
        self.unknown.natural = 240  # takes the spare width; the drop-down list itself is as wide as the longest name
        self.unknown.fill_spare()
        self.unknown_box.setVisible(bool(self._unknown))

        rows = [r for r in deliveries.pending_files(conn) if r["status"] != "needs_mapping"]
        fill_table(self.files, [[t(f"file.{r['status']}"), r["rel_path"], self._file_message(r), ""] for r in rows])
        for i, r in enumerate(rows):
            self.files.setCellWidget(i, 3, self._file_actions(r))
        self.files.resizeColumnsToContents()
        self.files_box.setVisible(bool(rows))

        self._items = inbox.items(conn, ws)
        fill_table(self.inbox, [[t(f"inbox.{it.kind}"), it.path.name, self._inbox_message(it), ""]
                                for it in self._items])
        for i, it in enumerate(self._items):
            self.inbox.setCellWidget(i, 3, self._inbox_actions(it))
        self.inbox.resizeColumnsToContents()
        self.inbox_box.setVisible(bool(self._items))

        self.empty.setVisible(not (self._unknown or rows or self._items))

    # ---- unknown lines -----------------------------------------------------

    def _default_choice(self, u):
        if u.is_fee:
            return SKIP
        return u.suggestion or NEW

    def _choice_combo(self, r, u, products) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)  # type a few letters (Vietnamese or Chinese) to find the product
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.completer().setFilterMode(Qt.MatchContains)
        combo.completer().setCompletionMode(QCompleter.PopupCompletion)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(32)
        combo.addItem(t("pending.create_new"), NEW)
        combo.addItem(t("pending.skip"), SKIP)
        combo.addItem(t("pending.later"), LATER)
        for p in products:
            combo.addItem(catalog.long_label(p), p["id"])
        combo.setCurrentIndex(combo.findData(self._default_choice(u)))
        combo.lineEdit().setCursorPosition(0)  # show the start of the long label (code, name)
        # the drop-down list is as wide as the longest name, so every product name can be read in full
        metrics = combo.fontMetrics()
        widest = max(metrics.horizontalAdvance(combo.itemText(i)) for i in range(combo.count()))
        combo.view().setMinimumWidth(widest + 40)
        combo.setToolTip(combo.currentText())
        combo.currentIndexChanged.connect(lambda _=0, row=r: self._restyle(row))
        combo.currentIndexChanged.connect(lambda _=0, c=combo: c.lineEdit().setCursorPosition(0))
        combo.currentTextChanged.connect(combo.setToolTip)
        return combo

    def _choice(self, r):
        combo = self.unknown.cellWidget(r, CHOICE)
        idx = combo.findText(combo.currentText())  # typed text that matches nothing -> decide later
        return combo.itemData(idx) if idx >= 0 else LATER

    def _toggle_drop(self, r):
        combo = self.unknown.cellWidget(r, CHOICE)
        if self._choice(r) == SKIP:
            default = self._default_choice(self._unknown[r])
            combo.setCurrentIndex(combo.findData(NEW if default == SKIP else default))
        else:
            combo.setCurrentIndex(combo.findData(SKIP))

    def _restyle(self, r):
        """Lines marked 'not goods' are greyed and struck through, like deleted."""
        skip = self._choice(r) == SKIP
        for c in (NAME, NAME_ZH, SPEC, ORDERS):
            item = self.unknown.item(r, c)
            font = item.font()
            font.setStrikeOut(skip)
            item.setFont(font)
            item.setForeground(GREY if skip else self.palette().text().color())
        self.unknown.cellWidget(r, DROP).setText(t("pending.keep_line") if skip else t("pending.drop_line"))

    def _file_message(self, r) -> str:
        if r["status"] == "missing":
            return t("file.missing_detail", code=r["doc_code"] or "")
        if r["status"] == "changed":
            return t("file.changed_detail", detail=r["message"])
        return r["message"]

    def _file_actions(self, r) -> QWidget:
        h, conn, ws = r["hash"], self.ctx.conn, self.ctx.ws
        if r["status"] == "changed":
            return _buttons(
                (t("btn.use_new"), lambda: self._run(lambda: deliveries.replace_changed(conn, ws, h))),
                (t("btn.keep_old"), lambda: self._run(lambda: deliveries.keep_old(conn, h))),
                (t("btn.open_file"), lambda: open_path(ws.deliveries / r["rel_path"])),
            )
        if r["status"] == "missing":
            return _buttons(
                (t("btn.restore_file"), lambda: self._run(lambda: deliveries.restore_missing(conn, ws, h))),
                (t("btn.cancel_doc"), lambda: ask(self, t("doc.confirm_cancel"))
                 and self._run(lambda: deliveries.cancel_missing(conn, h))),
                (t("btn.ignore"), lambda: self._run(lambda: deliveries.ignore_missing(conn, h))),
            )
        return _buttons(
            (t("btn.open_file"), lambda: open_path(ws.deliveries / r["rel_path"])),
            (t("btn.hide"), lambda: self._run(lambda: deliveries.dismiss_error(conn, h))),
        )

    def _inbox_message(self, it) -> str:
        if it.kind == "receipt":
            total = sum(ln.qty for ln, _ in it.resolved)
            return t("inbox.receipt_detail", date=fmt_date(it.receipt.doc_date), lines=len(it.resolved),
                     qty=fmt_qty(total))
        if it.kind == "catalog":
            return t("inbox.catalog_detail", count=len(it.catalog))
        if it.kind == "package":
            m = it.manifest
            return t("inbox.package_detail", device=m.device_name, at=m.exported_at.replace("T", " "),
                     deliveries=m.deliveries)
        return it.error

    def _inbox_actions(self, it) -> QWidget:
        if it.kind == "receipt":
            return _buttons((t("btn.view_import"), lambda: self.import_receipt(it)),
                            (t("btn.discard"), lambda: self.discard(it)))
        if it.kind == "package":
            return _buttons((t("btn.import_data"), lambda: self.import_package(it)),
                            (t("btn.discard"), lambda: self.discard(it)))
        if it.kind == "catalog":
            return _buttons((t("catalog.import_btn"), lambda: self.import_catalog(it)),
                            (t("btn.discard"), lambda: self.discard(it)))
        # unusable file: never moved, only hidden
        return _buttons((t("btn.open_file"), lambda: open_path(it.path)),
                        (t("btn.hide"), lambda: self.hide(it)))

    # ---- actions -----------------------------------------------------------

    def _run(self, action):
        try:
            action()
        except Exception as exc:  # show the reason instead of failing silently
            error(self, str(exc))
        self.rescan()

    def apply_mapping(self, confirm=True):
        conn = self.ctx.conn
        choices = [(u, self._choice(r)) for r, u in enumerate(self._unknown)]
        counts = {NEW: 0, SKIP: 0, LATER: 0, "map": 0}
        for _, choice in choices:
            counts[choice if choice in (NEW, SKIP, LATER) else "map"] += 1
        if confirm and not ask(self, t("pending.confirm_apply", mapped=counts["map"], created=counts[NEW],
                                       skipped=counts[SKIP], later=counts[LATER])):
            return
        for u, choice in choices:
            if choice == NEW:
                deliveries.create_product_for_line(conn, u)
            elif choice == SKIP:
                deliveries.ignore_unknown(conn, u)
            elif choice != LATER:
                deliveries.map_line(conn, u.key, choice, deliveries.line_label(u))
        result = self.rescan(allow_partial=True)
        if result is not None:
            info(self, t("pending.mapped", mapped=counts["map"], created=counts[NEW], skipped=counts[SKIP],
                         count=len(result.imported)))

    def discard(self, it):
        if ask(self, t("inbox.confirm_discard", name=it.path.name)):
            inbox.discard(self.ctx.ws, it)
            self.refresh()

    def import_receipt(self, it):
        review_receipt(self.ctx, self, it)

    def import_catalog(self, it):
        if import_catalog_file(self.ctx, self, it.path, it.catalog):
            inbox.done(self.ctx.ws, it.path)
            self.ctx.notify()

    def hide(self, it):
        if ask(self, t("inbox.confirm_hide", name=it.path.name)):
            inbox.hide(self.ctx.conn, it)
            self.rescan()

    def import_package(self, it):
        m = it.manifest
        text = t("transfer.confirm_import", device=m.device_name, at=m.exported_at.replace("T", " "),
                 deliveries=m.deliveries, products=m.products)
        if not ask(self, text):
            return
        if transfer.has_unsent_changes(self.ctx.conn) and not ask(self, t("transfer.unsent_warning")):
            return
        try:
            backup.named_backup(self.ctx.conn, self.ctx.ws, "truoc-nhap-du-lieu")
            self.ctx.close()
            manifest = transfer.import_package(self.ctx.ws, it.path)
            self.ctx.reopen()
            with db.transaction(self.ctx.conn):
                transfer.after_import(self.ctx.conn, manifest)
            transfer.move_to_processed(self.ctx.ws, it.path)
        except Exception as exc:
            try:
                self.ctx.reopen()
            except Exception:
                pass
            error(self, t("transfer.import_failed", error=str(exc)))
            return
        self.rescan()
        info(self, t("transfer.imported", device=m.device_name))
