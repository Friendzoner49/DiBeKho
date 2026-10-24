"""'Cần xử lý': unknown product names, edited/deleted/invalid files, and input/ items."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dibekho import __version__, db
from dibekho.core import activity, backup, catalog, deliveries, inbox, transfer
from dibekho.core.stock import set_location
from dibekho.core.text import fmt_qty, parse_number, unaccent
from dibekho.i18n import t
from dibekho.ui.common import (
    GREY,
    NoWheelCombo,
    ask,
    error,
    fill_table,
    fit_window,
    fmt_date,
    hint_label,
    info,
    location_combo,
    make_table,
    open_path,
)
from dibekho.ui.catalog_import import import_catalog_file
from dibekho.ui.page import Page
from dibekho.ui.receipt_page import review_receipt
from dibekho.ui.transfer_page import import_master_file

NEW, LATER, SKIP, OTHER = "new", "later", "skip", "other"
NAME, NAME_ZH, SPEC, QTY, CHOICE, OPENING = range(6)


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

        # recorded delivery notes waiting for their place: goods already taken from Kho tổng meanwhile
        self.places_box = QGroupBox(t("pending.places_title"))
        lay = QVBoxLayout(self.places_box)
        lay.addWidget(hint_label(t("pending.places_hint")))
        self.places = make_table([t("col.doc_code"), t("col.date"), t("col.customer"), t("col.lines"),
                                  t("col.total_qty"), t("loc.taken_from")], stretch=2)
        lay.addWidget(self.places)
        row = QHBoxLayout()
        places_btn = QPushButton(t("pending.places_save"))
        places_btn.clicked.connect(self.save_places)
        font = places_btn.font()
        font.setBold(True)
        places_btn.setFont(font)
        row.addWidget(places_btn)
        row.addStretch()
        lay.addLayout(row)
        self.layout_.addWidget(self.places_box, 2)

        self.unknown_box = QGroupBox(t("pending.unknown_title"))
        lay = QVBoxLayout(self.unknown_box)
        lay.addWidget(hint_label(t("pending.unknown_hint")))
        # one group per delivery note with all its lines, so a whole order is checked against the paper
        self.unknown = QTreeWidget()
        self.unknown.setColumnCount(6)
        self.unknown.setHeaderLabels([t("pending.name_on_note"), t("col.name_zh"), t("col.spec"), t("col.qty"),
                                      t("pending.map_to"), t("pending.opening")])
        self.unknown.setAlternatingRowColors(True)
        self.unknown.setSelectionMode(QAbstractItemView.NoSelection)
        self.unknown.header().setSectionResizeMode(QHeaderView.Interactive)
        self.unknown.header().setStretchLastSection(False)
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
        self._fill_places(conn)
        self._fill_unknown(conn, ws)

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

        self.empty.setVisible(not (self._unknown or rows or self._items or self._unplaced))

    # ---- delivery notes waiting for their place ----------------------------------

    def _fill_places(self, conn):
        self._unplaced = deliveries.unplaced(conn)
        fill_table(self.places, [[d["code"], fmt_date(d["doc_date"]), d["customer"], str(d["line_count"]),
                                  fmt_qty(d["total_qty"]), ""] for d in self._unplaced],
                   ids=[d["id"] for d in self._unplaced])
        self._place_combos = []
        for i, d in enumerate(self._unplaced):
            combo = location_combo()
            self.places.setCellWidget(i, 5, combo)
            self._place_combos.append(combo)
        self.places.resizeColumnsToContents()
        self.places_box.setVisible(bool(self._unplaced))

    def save_places(self):
        if not self._unplaced:
            return
        self.ctx.undo_point("places")
        with db.transaction(self.ctx.conn):
            for d, combo in zip(self._unplaced, self._place_combos):
                set_location(self.ctx.conn, d["id"], combo.currentData())
        activity.log("places", ", ".join(f"{d['code']} → {c.currentData()}"
                                         for d, c in zip(self._unplaced, self._place_combos)))
        self.ctx.notify()
        self.rescan()

    # ---- unknown lines, grouped by order ---------------------------------------

    def _fill_unknown(self, conn, ws):
        self._unknown = {u.key: u for u in deliveries.unknown_lines(conn, ws)}  # one decision per name
        self._combos: dict[str, list] = {}
        self._rows: dict[str, list] = {}  # tree rows of each unknown name (one per order it is in)
        self._openings: dict[str, QLineEdit] = {}
        self._syncing = False
        names = {p["id"]: catalog.long_label(p) for p in catalog.products(conn, include_inactive=True)}
        self.unknown.clear()
        for note in deliveries.waiting_notes(conn, ws):
            head = QTreeWidgetItem([t("pending.order_title", code=note.code or "—", customer=note.customer or "—",
                                      date=fmt_date(note.doc_date), waiting=len(note.unknown))])
            head.setToolTip(0, note.rel_path)
            font = head.font(0)
            font.setBold(True)
            head.setFont(0, font)
            self.unknown.addTopLevelItem(head)
            head.setFirstColumnSpanned(True)
            for ln in note.lines:
                item = QTreeWidgetItem([ln.name_vi or ln.raw_name, ln.name_zh, ln.spec, fmt_qty(ln.qty), "", ""])
                item.setToolTip(NAME, ln.raw_name)
                item.setTextAlignment(QTY, Qt.AlignRight | Qt.AlignVCenter)
                head.addChild(item)
                u = self._unknown.get(ln.key) if ln.product_id is None and not ln.ignored else None
                if u is None:  # already known: shown to compare the whole order, not to change here
                    item.setText(CHOICE, "✓ " + names.get(ln.product_id, "") if ln.product_id
                                 else t("pending.skip_short"))
                    for c in range(6):
                        item.setForeground(c, GREY)
                    continue
                self._rows.setdefault(ln.key, []).append(item)
                combo = self._choice_combo(u)
                self._combos.setdefault(ln.key, []).append(combo)
                self.unknown.setItemWidget(item, CHOICE, combo)
                if ln.key not in self._openings:  # once per name, on its earliest order
                    opening = QLineEdit()
                    opening.setPlaceholderText(t("pending.opening_placeholder"))
                    opening.setToolTip(t("pending.opening_tip"))
                    opening.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self._openings[ln.key] = opening
                    self.unknown.setItemWidget(item, OPENING, opening)
            head.setExpanded(True)
        for key in self._combos:
            self._restyle(key)
        for col, width in ((NAME, 220), (NAME_ZH, 120), (SPEC, 100), (QTY, 75), (CHOICE, 300), (OPENING, 100)):
            self.unknown.setColumnWidth(col, width)
        self.unknown_box.setVisible(bool(self._unknown))

    def _default_choice(self, u):
        if u.is_fee:
            return SKIP
        return u.suggestion or LATER  # nothing close enough: the user decides, nothing is created by itself

    def _choice_combo(self, u) -> QComboBox:
        """2-3 products with the same name first, then: new product, not goods, another product…, decide later.
        Not editable and deaf to the mouse wheel, so scrolling never changes a choice."""
        combo = NoWheelCombo()
        suggestions = [] if u.is_fee else catalog.suggest_products(self.ctx.conn, u.raw_name, u.spec)
        if u.suggestion and u.suggestion not in [p["id"] for p in suggestions]:
            suggestions.insert(0, self.ctx.conn.execute("SELECT * FROM products WHERE id = ?",
                                                        (u.suggestion,)).fetchone())
        for p in suggestions:
            combo.addItem(catalog.long_label(p), p["id"])
        if suggestions:
            combo.insertSeparator(combo.count())
        combo.addItem(t("pending.create_new"), NEW)
        combo.addItem(t("pending.skip"), SKIP)
        combo.addItem(t("pending.other"), OTHER)
        combo.addItem(t("pending.later"), LATER)
        combo.setCurrentIndex(combo.findData(self._default_choice(u)))
        combo.setProperty("previous", combo.currentIndex())
        widest = max(combo.fontMetrics().horizontalAdvance(combo.itemText(i)) for i in range(combo.count()))
        combo.view().setMinimumWidth(widest + 40)  # every name readable in full in the drop-down list
        combo.setToolTip(combo.currentText())
        combo.currentIndexChanged.connect(lambda _=0, c=combo, key=u.key: self._choice_changed(key, c))
        return combo

    def _choice_changed(self, key, combo):
        if self._syncing:
            return
        data = combo.currentData()
        if data == OTHER:  # pick any product from the whole catalog
            picked = ProductPicker(self.ctx, self).choose()
            if picked is None:
                self._syncing = True
                combo.setCurrentIndex(combo.property("previous"))
                self._syncing = False
                return
            data = picked
        self.set_choice(key, data)

    def set_choice(self, key, data):
        """Same decision for every row of this name (it may be in several orders)."""
        self._syncing = True
        for combo in self._combos[key]:
            idx = combo.findData(data)
            if idx < 0:  # a product picked from the whole list: add it on top
                p = self.ctx.conn.execute("SELECT * FROM products WHERE id = ?", (data,)).fetchone()
                combo.insertItem(0, catalog.long_label(p), data)
                idx = 0
            combo.setCurrentIndex(idx)
            combo.setProperty("previous", idx)
            combo.setToolTip(combo.currentText())
        self._syncing = False
        self._restyle(key)

    def choice(self, key):
        return self._combos[key][0].currentData()

    def _restyle(self, key):
        """Lines marked 'not goods' are greyed and struck through, like deleted."""
        skip = self.choice(key) == SKIP
        for item in self._rows[key]:
            for c in (NAME, NAME_ZH, SPEC, QTY):
                font = item.font(c)
                font.setStrikeOut(skip)
                item.setFont(c, font)
                item.setForeground(c, GREY if skip else self.palette().text().color())
        if key in self._openings:  # only a new product needs its stock before the note; others have a history
            self._openings[key].setEnabled(self.choice(key) == NEW)

    def _opening(self, key) -> float | None:
        text = self._openings[key].text().strip() if key in self._openings else ""
        if not text:
            return None
        return parse_number(text)

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
                (t("btn.open_file"), lambda: open_path(deliveries.note_path(ws, r["rel_path"]))),
            )
        if r["status"] == "missing":
            return _buttons(
                (t("btn.restore_file"), lambda: self._run(lambda: deliveries.restore_missing(conn, ws, h))),
                (t("btn.cancel_doc"), lambda: ask(self, t("doc.confirm_cancel"))
                 and self._run(lambda: deliveries.cancel_missing(conn, h))),
                (t("btn.ignore"), lambda: self._run(lambda: deliveries.ignore_missing(conn, h))),
            )
        return _buttons(
            (t("btn.open_file"), lambda: open_path(deliveries.note_path(ws, r["rel_path"]))),
            (t("btn.hide"), lambda: self._run(lambda: deliveries.dismiss_error(conn, h))),
        )

    def _inbox_message(self, it) -> str:
        if it.kind == "receipt":
            total = sum(ln.qty for ln, _ in it.resolved)
            return t("inbox.receipt_detail", date=fmt_date(it.receipt.doc_date), lines=len(it.resolved),
                     qty=fmt_qty(total))
        if it.kind == "catalog":
            return t("inbox.catalog_detail", count=len(it.catalog))
        if it.kind == "master":
            products, customers, stock = it.master
            return t("inbox.master_detail", products=len(products), customers=len(customers), stock=len(stock))
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
        if it.kind == "master":
            return _buttons((t("master.import"), lambda: self.import_master(it)),
                            (t("btn.discard"), lambda: self.discard(it)))
        # unusable file: never moved, only hidden
        return _buttons((t("btn.open_file"), lambda: open_path(it.path)),
                        (t("btn.hide"), lambda: self.hide(it)))

    # ---- actions -----------------------------------------------------------

    def _run(self, action, undo_action="file"):
        self.ctx.undo_point(undo_action)
        try:
            action()
        except Exception as exc:  # show the reason instead of failing silently
            error(self, str(exc))
        self.rescan()

    def apply_mapping(self, confirm=True):
        conn = self.ctx.conn
        choices = [(u, self.choice(key)) for key, u in self._unknown.items()]
        openings = {}
        for u, choice in choices:
            if choice != NEW:
                continue
            try:
                openings[u.key] = self._opening(u.key)
            except ValueError:
                error(self, t("pending.opening_invalid", name=u.name_vi or u.raw_name))
                self._openings[u.key].setFocus()
                return
        counts = {NEW: 0, SKIP: 0, LATER: 0, "map": 0}
        for _, choice in choices:
            counts[choice if choice in (NEW, SKIP, LATER) else "map"] += 1
        if confirm and not ask(self, t("pending.confirm_apply", mapped=counts["map"], created=counts[NEW],
                                       skipped=counts[SKIP], later=counts[LATER])):
            return
        self.ctx.undo_point("apply")
        codes = dict(conn.execute("SELECT id, code FROM products"))
        activity.log("apply", "\n".join(
            f"{deliveries.line_label(u)} → {codes.get(c, c) if c not in (NEW, SKIP, LATER) else c}"
            for u, c in choices))
        for u, choice in choices:
            if choice == NEW:
                deliveries.create_product_for_line(conn, u, opening=openings.get(u.key),
                                                   note=t("pending.opening_note", name=u.name_vi or u.raw_name))
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

    def import_master(self, it):
        if import_master_file(self.ctx, self, it.path, it.master):
            inbox.done(self.ctx.ws, it.path)
            self.rescan()

    def hide(self, it):
        if ask(self, t("inbox.confirm_hide", name=it.path.name)):
            inbox.hide(self.ctx.conn, it)
            self.rescan()

    def import_package(self, it):
        m = it.manifest
        text = t("transfer.confirm_import", device=m.device_name, at=m.exported_at.replace("T", " "),
                 deliveries=m.deliveries, products=m.products)
        if transfer.is_older(m):
            text += "\n\n" + t("transfer.older_version", version=m.app_version or "?", current=__version__)
        if not ask(self, text):
            return
        if transfer.has_unsent_changes(self.ctx.conn) and not ask(self, t("transfer.unsent_warning")):
            return
        try:
            backup.named_backup(self.ctx.conn, self.ctx.ws, "truoc-nhap-du-lieu")
            self.ctx.undo_point("package")
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


class ProductPicker(QDialog):
    """'Chọn mặt hàng khác…': the whole catalog with a search box (Vietnamese, Chinese, code, no accents)."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("pending.other_title"))
        fit_window(self, 760, 560)
        lay = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText(t("pending.other_search"))
        lay.addWidget(self.search)
        self.list = QListWidget()
        for p in sorted(catalog.products(ctx.conn), key=lambda p: (len(p["code"]), p["code"])):
            item = QListWidgetItem(catalog.long_label(p))
            item.setData(Qt.UserRole, p["id"])
            item.setData(Qt.UserRole + 1, unaccent(f"{catalog.long_label(p)} {p['name_zh']}"))
            self.list.addItem(item)
        lay.addWidget(self.list)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.search.textChanged.connect(self._filter)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        self.search.setFocus()

    def _filter(self, text):
        needle = unaccent(text)
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(needle not in item.data(Qt.UserRole + 1))

    def choose(self) -> int | None:
        if self.exec() != QDialog.Accepted or self.list.currentItem() is None:
            return None
        return self.list.currentItem().data(Qt.UserRole)
