"""'Thống kê': period + scope selection, summary table, top list, chart, Excel export."""

from datetime import date, datetime

from PySide6.QtCharts import QBarSeries, QBarSet, QCategoryAxis, QChart, QChartView, QValueAxis
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from dibekho.core import catalog, queries, stats
from dibekho.core.text import unaccent
from dibekho.excel import report
from dibekho.i18n import t
from dibekho.ui.common import (
    RED,
    ask,
    error,
    fill_table,
    fit_window,
    from_qdate,
    make_table,
    num_item,
    open_path,
    row_id,
    to_qdate,
)
from dibekho.ui.details import ProductDialog
from dibekho.ui.page import Page

PERIODS = ("day", "month", "quarter", "year", "range")
SPLITS = ("none", "day", "month")


def _x_axis(labels: list[str]) -> QCategoryAxis:
    """Bar positions 0..n-1. With many bars only the first and every 5th (7th for dd/mm) label is shown,
    otherwise Qt shortens them all to '...'."""
    axis = QCategoryAxis()
    axis.setLabelsPosition(QCategoryAxis.AxisLabelsPositionOnValue)
    axis.setRange(-0.5, max(len(labels), 1) - 0.5)
    step = 1 if len(labels) <= 12 else (5 if len(labels[0]) <= 2 else 7)
    for i, lab in enumerate(labels):
        if i == 0 or (i + 1) % step == 0:
            axis.append(lab, i)
    axis.setGridLineVisible(False)
    return axis


class PickDialog(QDialog):
    """Check-list with a filter box. Nothing checked = all."""

    def __init__(self, title: str, items: list[tuple[str, object]], selected: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        fit_window(self, 520, 560)
        lay = QVBoxLayout(self)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(t("stock.filter"))
        self.filter.textChanged.connect(self._filter)
        lay.addWidget(self.filter)
        self.list = QListWidget()
        for text, value in items:
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, value)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if value in selected else Qt.Unchecked)
            self.list.addItem(it)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        clear = QPushButton(t("stats.pick_all"))
        clear.clicked.connect(lambda: [self.list.item(i).setCheckState(Qt.Unchecked)
                                       for i in range(self.list.count())])
        row.addWidget(clear)
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(QLabel(t("stats.pick_hint")))
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText(t("btn.ok"))
        box.button(QDialogButtonBox.Cancel).setText(t("btn.cancel"))
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def _filter(self, text):
        needle = unaccent(text)
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(needle) and needle not in unaccent(it.text()))

    def selected(self) -> list:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]


class ScopeButton(QPushButton):
    """'Mặt hàng: Tất cả' / 'Mặt hàng: 3 đã chọn'."""

    def __init__(self, label_key: str, items_fn, parent):
        super().__init__()
        self.label_key, self.items_fn, self.parent_ = label_key, items_fn, parent
        self.values: list = []
        self.clicked.connect(self.pick)
        self._update()

    def _update(self):
        what = t("filter.all") if not self.values else t("stats.n_selected", count=len(self.values))
        self.setText(f"{t(self.label_key)}: {what}")

    def pick(self):
        dlg = PickDialog(t(self.label_key), self.items_fn(), self.values, self.parent_)
        if dlg.exec() == QDialog.Accepted:
            self.values = dlg.selected()
            self._update()
            self.parent_.run()

    def describe(self, items) -> str:
        if not self.values:
            return f"{t(self.label_key)}: {t('filter.all')}"
        names = [text for text, value in items if value in self.values]
        return f"{t(self.label_key)}: " + ", ".join(names[:5]) + (" …" if len(names) > 5 else "")


class StatsPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, t("nav.stats"), t("stats.hint"))
        today = date.today()

        bar = QHBoxLayout()
        self.period = QComboBox()
        for p in PERIODS:
            self.period.addItem(t(f"period.{p}"), p)
        self.period.setCurrentIndex(1)
        bar.addWidget(QLabel(t("stats.period")))
        bar.addWidget(self.period)

        self.inputs = QStackedWidget()
        self.day = self._date_edit(today)
        self.month = QComboBox()
        for m in range(1, 13):
            self.month.addItem(t("stats.month_n", n=m), m)
        self.month.setCurrentIndex(today.month - 1)
        self.quarter = QComboBox()
        for q in range(1, 5):
            self.quarter.addItem(t("stats.quarter_n", n=q), q)
        self.quarter.setCurrentIndex((today.month - 1) // 3)
        self.year_m, self.year_q, self.year_y = (self._year(today.year) for _ in range(3))
        self.range_from = self._date_edit(date(today.year, today.month, 1))
        self.range_to = self._date_edit(today)
        for widgets in ([self.day], [self.month, self.year_m], [self.quarter, self.year_q], [self.year_y],
                        [QLabel(t("filter.from")), self.range_from, QLabel(t("filter.to")), self.range_to]):
            page = QWidget()
            lay = QHBoxLayout(page)
            lay.setContentsMargins(0, 0, 0, 0)
            for w in widgets:
                lay.addWidget(w)
            lay.addStretch()
            self.inputs.addWidget(page)
        self.inputs.setCurrentIndex(1)
        self.inputs.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        bar.addWidget(self.inputs, 1)

        self.split = QComboBox()
        for s in SPLITS:
            self.split.addItem(t(f"split.{s}"), s)
        bar.addWidget(QLabel(t("stats.split")))
        bar.addWidget(self.split)
        self.layout_.addLayout(bar)

        scope = QHBoxLayout()
        self.products = ScopeButton("col.product", self._product_items, self)
        self.categories = ScopeButton("col.category", self._category_items, self)
        self.customers = ScopeButton("col.customer", self._customer_items, self)
        for b in (self.products, self.categories, self.customers):
            scope.addWidget(b)
        scope.addStretch()
        export = QPushButton(t("stats.export"))
        export.clicked.connect(self.export)
        scope.addWidget(export)
        self.layout_.addLayout(scope)
        self.caption = QLabel()
        self.layout_.addWidget(self.caption)

        split = QSplitter(Qt.Vertical)
        self.table = make_table([], stretch=None)
        self.table.doubleClicked.connect(
            lambda idx: ProductDialog(self.ctx, row_id(self.table, idx.row()), self).exec())
        split.addWidget(self.table)
        bottom = QSplitter(Qt.Horizontal)
        top_box = QWidget()
        top_lay = QVBoxLayout(top_box)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.addWidget(QLabel(t("stats.top_title")))
        self.top = make_table([t("col.rank"), t("col.product"), t("col.spec"), t("col.variant"), t("col.out"),
                               t("col.unit")], stretch=1)
        top_lay.addWidget(self.top)
        bottom.addWidget(top_box)
        self.chart = QChartView()
        self.chart.setRenderHint(QPainter.Antialiasing)
        self.chart.setMinimumHeight(220)
        bottom.addWidget(self.chart)
        bottom.setSizes([400, 600])
        split.addWidget(bottom)
        split.setSizes([500, 260])
        self.layout_.addWidget(split)

        self.period.currentIndexChanged.connect(lambda i: (self.inputs.setCurrentIndex(i), self.run()))
        for w in (self.day, self.range_from, self.range_to):
            w.dateChanged.connect(self.run)
        for w in (self.month, self.quarter, self.split):
            w.currentIndexChanged.connect(self.run)
        for w in (self.year_m, self.year_q, self.year_y):
            w.valueChanged.connect(self.run)

    @staticmethod
    def _date_edit(d: date) -> QDateEdit:
        w = QDateEdit()
        w.setCalendarPopup(True)
        w.setDisplayFormat("dd/MM/yyyy")
        w.setDate(to_qdate(d))
        return w

    @staticmethod
    def _year(y: int) -> QSpinBox:
        w = QSpinBox()
        w.setRange(2000, 2100)
        w.setValue(y)
        return w

    def _product_items(self):
        return [(catalog.label(p), p["id"]) for p in catalog.products(self.ctx.conn, True)]

    def _category_items(self):
        return [(c, c) for c in catalog.categories(self.ctx.conn)]

    def _customer_items(self):
        return [(c["name"], c["id"]) for c in queries.customers(self.ctx.conn)]

    # ---- period ------------------------------------------------------------

    def period_range(self) -> tuple[date, date, str]:
        kind = self.period.currentData()
        if kind == "day":
            d = from_qdate(self.day.date())
            return d, d, d.strftime("%d/%m/%Y")
        if kind == "month":
            y, m = self.year_m.value(), self.month.currentData()
            s, e = stats.month_range(y, m)
            return s, e, f"{m:02d}/{y}"
        if kind == "quarter":
            y, q = self.year_q.value(), self.quarter.currentData()
            s, e = stats.quarter_range(y, q)
            return s, e, t("stats.quarter_label", q=q, y=y)
        if kind == "year":
            y = self.year_y.value()
            s, e = stats.year_range(y)
            return s, e, str(y)
        s, e = from_qdate(self.range_from.date()), from_qdate(self.range_to.date())
        if e < s:
            s, e = e, s
        return s, e, f"{s:%d/%m/%Y} – {e:%d/%m/%Y}"

    def filters(self) -> stats.Filters:
        return stats.Filters(self.products.values or None, self.categories.values or None,
                             self.customers.values or None)

    def scope_label(self) -> str:
        return " · ".join([self.products.describe(self._product_items()),
                           self.categories.describe(self._category_items()),
                           self.customers.describe(self._customer_items())])

    # ---- display -----------------------------------------------------------

    def refresh(self):
        self.run()

    def run(self):
        start, end, label = self.period_range()
        f = self.filters()
        by = self.split.currentData()
        rows = stats.summary(self.ctx.conn, start, end, f, by)
        customer_filtered = bool(f.customer_ids)
        labels = [b.label for b in stats.buckets(start, end, by)] if by != "none" else []

        headers = [t("col.code"), t("col.product"), t("col.spec"), t("col.variant"), t("col.unit")]
        if not customer_filtered:
            headers.append(t("col.opening"))
        headers += [t("col.in"), t("col.out"), t("col.adjust")]
        if not customer_filtered:
            headers.append(t("col.closing"))
        for lb in labels:
            headers += [f"{t('col.in')} {lb}", f"{t('col.out')} {lb}"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)

        table_rows, colors = [], []
        for r in rows:
            cells = [r.code, r.name_vi, r.spec, r.variant, r.unit]
            if not customer_filtered:
                cells.append(num_item(r.opening))
            cells += [num_item(r.qty_in or None), num_item(r.qty_out or None), num_item(r.adjust or None)]
            if not customer_filtered:
                cells.append(num_item(r.closing))
            for lb in labels:
                qin, qout = r.per_bucket.get(lb, (0, 0))
                cells += [num_item(qin or None), num_item(qout or None)]
            table_rows.append(cells)
            colors.append(RED if (r.closing is not None and r.closing < 0) else None)
        fill_table(self.table, table_rows, ids=[r.product_id for r in rows], colors=colors)

        total_out = sum(r.qty_out for r in rows)
        total_in = sum(r.qty_in for r in rows)
        self.caption.setText(t("stats.caption", period=label, products=len(rows),
                               qty_in=num_item(total_in).text(), qty_out=num_item(total_out).text()))

        top = sorted((r for r in rows if r.qty_out > 0), key=lambda r: r.qty_out, reverse=True)[:10]
        fill_table(self.top, [[i, r.name_vi, r.spec, r.variant, num_item(r.qty_out), r.unit] for i, r in enumerate(top, 1)],
                   ids=None)
        self._draw_chart(start, end, f)

    def _draw_chart(self, start: date, end: date, f: stats.Filters):
        data = stats.daily_out(self.ctx.conn, start, end, f)
        if (end - start).days > 62:  # long periods: one bar per month
            monthly: dict[str, float] = {}
            for d, q in data:
                key = f"{d.month:02d}/{d.year % 100:02d}"
                monthly[key] = monthly.get(key, 0) + q
            labels, values = list(monthly), list(monthly.values())
        elif start.month == end.month and start.year == end.year:  # one month: day numbers fit without rotating
            labels, values = [str(d.day) for d, _ in data], [q for _, q in data]
        else:
            labels, values = [d.strftime("%d/%m") for d, _ in data], [q for _, q in data]
        bar_set = QBarSet(t("col.out"))
        bar_set.append(values)
        series = QBarSeries()
        series.append(bar_set)
        chart = QChart()
        chart.addSeries(series)
        chart.setTitle(t("stats.chart_title"))
        chart.legend().hide()
        axis_x = _x_axis(labels)
        font = axis_x.labelsFont()
        font.setPointSize(max(font.pointSize() - 2, 7))
        axis_x.setLabelsFont(font)
        series.setBarWidth(0.8)
        chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)
        axis_y = QValueAxis()
        axis_y.setRange(0, max(values + [1]) * 1.1)
        axis_y.setLabelFormat("%d")
        chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_y)
        self.chart.setChart(chart)

    # ---- export ------------------------------------------------------------

    def export(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(t("stats.export"))
        lay = QVBoxLayout(dlg)
        start, end, label = self.period_range()
        lay.addWidget(QLabel(t("report.period", period=label)))
        scope = QLabel(t("report.scope", scope=self.scope_label()))
        scope.setWordWrap(True)
        lay.addWidget(scope)
        lay.addWidget(QLabel(t("stats.export_sheets")))
        boxes = {}
        for key in report.SHEETS:
            cb = QCheckBox(t(f"sheet.{key}"))
            cb.setChecked(True)
            lay.addWidget(cb)
            boxes[key] = cb
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(t("stats.export_do"))
        bb.button(QDialogButtonBox.Cancel).setText(t("btn.cancel"))
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        sheets = {k for k, cb in boxes.items() if cb.isChecked()}
        if not sheets:
            error(self, t("stats.export_none"))
            return
        safe_label = "".join(ch if ch.isalnum() else "-" for ch in label).strip("-")
        path = self.ctx.ws.output / f"ThongKe_{safe_label}_{datetime.now():%Y%m%d-%H%M%S}.xlsx"
        try:
            report.export(path, self.ctx.conn, start, end, self.filters(), self.split.currentData(), sheets,
                          label, self.scope_label())
        except PermissionError:
            error(self, t("stats.export_locked"))
            return
        if ask(self, t("stats.exported", path=str(path))):
            open_path(path)
