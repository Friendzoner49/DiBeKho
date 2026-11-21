import AppKit
import DiBeKhoCore
import GRDB
import SwiftUI

/// The page windows of the Python app (PageWindow): opened beside the main window from Tra cứu and Kiểm kê.
@MainActor
enum Screens {
    static func orders(_ model: AppModel) {
        Windows.show(t("nav.orders"), width: 1200, height: 760, modal: false) { _ in OrdersPage(model: model) }
    }

    static func customers(_ model: AppModel) {
        Windows.show(t("nav.customers"), width: 1200, height: 760, modal: false) { _ in CustomersPage(model: model) }
    }

    static func stats(_ model: AppModel) {
        Windows.show(t("nav.stats"), width: 1200, height: 760, modal: false) { _ in StatsPage(model: model) }
    }

    /// Phiếu chuyển hàng… / Phiếu dùng thử… / Phiếu kiểm kê… (OrdersPage(fixed_kind=…) of the Python app)
    static func history(_ kind: String, _ model: AppModel) {
        Windows.show(t("kind.\(kind)_plural"), width: 1200, height: 760, modal: false) { _ in
            OrdersPage(model: model, fixedKind: kind)
        }
    }

    static func detail(_ data: DetailData, _ model: AppModel) {
        Windows.show(data.title, width: 1100, height: 700, modal: false) { _ in DetailView(data: data, model: model) }
    }

    /// For the screenshots of the build workflow (DIBEKHO_WINDOW).
    static func open(_ name: String, _ model: AppModel) {
        switch name {
        case "orders": orders(model)
        case "customers": customers(model)
        case "stats": stats(model)
        case "transfers": history("transfer", model)
        case "transfer": Forms.transfer(model)
        case "trial": Forms.trial(model)
        case "receipt": ReceiptForm.open(model)
        case "issue": IssueForm.open(model)
        case "order": model.openOrder(2)
        case "customer": model.openCustomer(1)
        case "product": model.openProduct(1)
        case "trials": history("trial", model)
        default: break
        }
    }
}

// ---- Đơn hàng (ui/orders_page.OrdersPage); with a fixed kind also Phiếu chuyển hàng… / Phiếu dùng thử… /
// Phiếu kiểm kê… (OrdersPage(fixed_kind=…)): the same filters, minus the kind, customer and currency boxes

struct OrdersPage: View {
    @ObservedObject var model: AppModel
    let fixedKind: String?
    @State private var kind: String
    /// a transfer or a count is rare: don't hide one past 90 days (orders_page: all_time checked with a fixed kind)
    @State private var allTime: Bool
    @State private var from = Dates.iso(Calendar.current.date(byAdding: .day, value: -90, to: Date()) ?? Date())
    @State private var to = Dates.today
    @State private var customerId: Int64 = 0
    @State private var productId: Int64 = 0
    @State private var text = ""
    @State private var includeClosed = false
    @State private var currency = ""
    @State private var selected: Int?

    static let kinds = ["delivery", "receipt", "stock_count", "transfer", "trial"]

    init(model: AppModel, fixedKind: String? = nil) {
        self.model = model
        self.fixedKind = fixedKind
        _kind = State(initialValue: fixedKind ?? "delivery")
        _allTime = State(initialValue: fixedKind != nil)
    }

    /// Delivery: taken from; receipt: put in; transfer: from → to; '(?)' while a note waits for its place (_place)
    static func place(_ d: Row) -> String {
        let kind = Details.text(d, "kind")
        let location: Int64? = d["location_id"]
        if kind == "transfer" {
            let to: Int64? = d["to_location_id"]
            return "\(UI.locationName(location)) → \(UI.locationName(to))"
        }
        if kind == "delivery" && ((d["places"] as Int?) ?? 0) > 1 { return t("loc.both") }
        if kind == "delivery" || kind == "receipt" {
            return UI.locationName(location) + (((d["location_set"] as Int?) ?? 1) != 0 ? "" : " (?)")
        }
        if kind == "trial" { return UI.locationName(location) }
        return ""
    }

    private func load() -> [Row] {
        let k = kind
        let start: String? = allTime ? nil : from
        let end: String? = allTime ? nil : to
        let cid = customerId, pid = productId, closed = includeClosed
        let needle = text.trimmingCharacters(in: .whitespaces)
        let docs = model.read {
            try OrderQueries.documents($0, kind: k, from: start, to: end, customerId: cid, productId: pid,
                                       includeClosed: closed, text: needle)
        } ?? []
        let want = kind == "delivery" ? currency : ""
        if want.isEmpty { return docs }
        return docs.filter { (Details.text($0, "currency") == "CNY") == (want == "CNY") }
    }

    var body: some View {
        _ = model.version
        let docs = load()
        return VStack(alignment: .leading, spacing: 6) {
            PageHeader(title: fixedKind.map { t("kind.\($0)_plural") } ?? t("nav.orders"), hint: t("orders.hint"))
            OrdersFilterRows(model: model, fixedKind: fixedKind, kind: $kind, allTime: $allTime, from: $from, to: $to,
                             customerId: $customerId, productId: $productId, text: $text,
                             includeClosed: $includeClosed, currency: $currency)
            HStack {
                Text(t("orders.count", ["count": String(docs.count)]))
                Spacer()
                if fixedKind == "transfer" {
                    Button(t("transfer.edit_selected")) { editSelected(docs) }
                }
            }
            table(docs)
        }
    }

    private func editSelected(_ docs: [Row]) {
        guard let i = selected, i < docs.count else { return UI.error(t("orders.select_first")) }
        if Details.text(docs[i], "status") != "active" { return UI.error(t("orders.not_active")) }
        UI.later { _ = Forms.transfer(model, docId: docs[i]["id"]) }  // never inside the button's handling
    }

    private static func cells(_ d: Row, money: Bool) -> [String] {
        var cells = [Format.date(Details.text(d, "doc_date")), Details.text(d, "code"), Details.text(d, "customer_name"),
                     place(d), String((d["line_count"] as Int?) ?? 0), Format.quantity(Details.number(d, "total_qty"))]
        if money {
            let sale = Details.text(d, "kind") == "delivery"
            let cur = Details.text(d, "currency")
            let rate: Double? = d["fx_rate"]
            let goods: Double? = d["goods_amount"]
            let fees: Double? = d["fee_amount"]
            let yuan = cur == "CNY"
            let goodsText = sale ? Format.money(goods, currency: cur, rate: rate) : ""
            let feesText = sale && (fees ?? 0) != 0 ? Format.money(fees, currency: cur, rate: rate, approx: false) : ""
            cells += [yuan ? "" : goodsText, yuan ? goodsText : "", feesText]
        }
        cells += [t("status.\(Details.text(d, "status"))"), Details.text(d, "source_file")]
        return cells
    }

    private func table(_ docs: [Row]) -> some View {
        // the goods and fees columns are always blank outside delivery notes: hidden in the fixed-kind windows
        let money = fixedKind == nil
        var columns = [Column(title: t("col.date"), width: 90), Column(title: t("col.doc_code"), width: 80),
                       Column(title: t("col.customer"), width: 240), Column(title: t("col.place"), width: 150),
                       Column(title: t("col.lines"), width: 60, numeric: true),
                       Column(title: t("col.total_qty"), width: 90, numeric: true)]
        if money {
            columns += [Column(title: t("col.goods_vnd"), width: 120, numeric: true),
                        Column(title: t("col.goods_cny"), width: 120, numeric: true),
                        Column(title: t("col.fees"), width: 90, numeric: true)]
        }
        columns += [Column(title: t("col.status"), width: 110), Column(title: t("col.file"), width: 200)]
        let rows = docs.map { Self.cells($0, money: money) }
        let tones: [RowTone] = docs.map { Details.text($0, "status") == "active" ? .normal : .grey }
        return DataTable(
            columns: columns,
            rows: rows,
            tones: tones,
            onOpen: { i in model.openOrder(docs[i]["id"]) },
            onSelect: { selected = $0 },
            stretch: 2,
            rowMenu: { i in menu(docs[i]) })
    }

    /// Right click on a delivery note in force: Đọc lại cả phiếu (orders_page._context_menu)
    private func menu(_ d: Row) -> [(String, () -> Void)] {
        guard Details.text(d, "kind") == "delivery", Details.text(d, "status") == "active", model.writable else { return [] }
        let id: Int64 = d["id"]
        let model = self.model
        return [(t("btn.reread_doc"), { LearnedScreen.rereadOrder(model, docId: id) {} })]
    }
}

/// The filter boxes of the Đơn hàng window, in the three rows of orders_page.py's grid.
struct OrdersFilterRows: View {
    @ObservedObject var model: AppModel
    let fixedKind: String?
    @Binding var kind: String
    @Binding var allTime: Bool
    @Binding var from: String
    @Binding var to: String
    @Binding var customerId: Int64
    @Binding var productId: Int64
    @Binding var text: String
    @Binding var includeClosed: Bool
    @Binding var currency: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            periodRow
            whoRow
            textRow
        }
    }

    private var periodRow: some View {
        HStack {
            if fixedKind == nil {
                Text(t("orders.kind"))
                Picker("", selection: $kind) {
                    ForEach(OrdersPage.kinds, id: \.self) { k in Text(t("kind.\(k)_plural")).tag(k) }
                }
                .labelsHidden()
                .frame(width: 180 * UI.scale)
            }
            Text(t("filter.from"))
            DateBox(iso: $from).disabled(allTime)
            Text(t("filter.to"))
            DateBox(iso: $to).disabled(allTime)
            Toggle(t("filter.all_time"), isOn: $allTime)
            Spacer()
        }
    }

    private var customerChoices: [FilterChoice] {
        let rows = model.read { try Lookup.customers($0) } ?? []
        return rows.map { FilterChoice(id: $0["id"], name: Details.text($0, "name")) }
    }

    private var productChoices: [FilterChoice] {
        let products = model.read { try Catalog.products($0, includeInactive: true) } ?? []
        return products.map { FilterChoice(id: $0.id, name: $0.longLabel) }
    }

    private var whoRow: some View {
        let customers = customerChoices
        let products = productChoices
        return HStack {
            if fixedKind == nil {
                Text(t("col.customer"))
                Picker("", selection: $customerId) {
                    Text(t("filter.all")).tag(Int64(0))
                    ForEach(customers) { c in Text(c.name).tag(c.id) }
                }
                .labelsHidden()
                .frame(maxWidth: 360 * UI.scale)
            }
            Text(t("col.product"))
            Picker("", selection: $productId) {
                Text(t("filter.all")).tag(Int64(0))
                ForEach(products) { p in Text(p.name).tag(p.id) }
            }
            .labelsHidden()
            .frame(maxWidth: 360 * UI.scale)
            Toggle(t("orders.include_cancelled"), isOn: $includeClosed)
            Spacer()
        }
    }

    private var textRow: some View {
        HStack {
            ClearableField(placeholder: t("orders.text_filter"), text: $text)
            if fixedKind == nil {
                Text(t("col.currency"))
                Picker("", selection: $currency) {
                    Text(t("orders.currency_all")).tag("")
                    Text(t("orders.currency_vnd")).tag("VND")
                    Text(t("orders.currency_cny")).tag("CNY")
                }
                .labelsHidden()
                .frame(width: 160 * UI.scale)
            }
        }
    }
}

/// One customer or product of a filter box.
struct FilterChoice: Identifiable {
    let id: Int64
    let name: String
}

// ---- Khách hàng (ui/orders_page.CustomersPage)

struct CustomersPage: View {
    @ObservedObject var model: AppModel
    @State private var selected: [Int] = []

    var body: some View {
        let rows = model.customers
        VStack(alignment: .leading, spacing: 6) {
            PageHeader(title: t("nav.customers"), hint: t("customers.hint"))
            HStack {
                ClearableField(placeholder: t("customers.filter"), text: $model.customerFilter)
                Button(t("cust.merge_button")) {
                    let picked = selected.filter { $0 < rows.count }.map { i -> (id: Int64, name: String, orders: Int) in
                        (rows[i]["id"], Details.text(rows[i], "name"), (rows[i]["order_count"] as Int?) ?? 0)
                    }
                    UI.later { Forms.mergeCustomers(model, picked: picked) }
                }
                .help(t("cust.merge_tip"))
            }
            // columns in the order of orders_page.CustomersPage; Địa chỉ takes the room left (stretch=3)
            DataTable(
                columns: [Column(title: t("col.customer"), width: 240), Column(title: t("col.contact"), width: 120),
                          Column(title: t("col.phone"), width: 110), Column(title: t("col.address"), width: 200),
                          Column(title: t("col.orders"), width: 60, numeric: true),
                          Column(title: t("col.revenue"), width: 240, numeric: true),
                          Column(title: t("col.first_order"), width: 100), Column(title: t("col.last_order"), width: 100),
                          Column(title: t("col.tax_code"), width: 110), Column(title: t("col.email"), width: 170)],
                rows: rows.map { c in
                    [Details.text(c, "name"), Details.text(c, "contact"), Details.text(c, "phone"), Details.text(c, "address"),
                     String((c["order_count"] as Int?) ?? 0),
                     Format.both(Details.number(c, "revenue"), Details.number(c, "revenue_cny"),
                                 approx: Details.number(c, "revenue_approx")),
                     Format.date(Details.text(c, "first_order")), Format.date(Details.text(c, "last_order")),
                     Details.text(c, "tax_code"), Details.text(c, "email")]
                },
                onOpen: { i in model.openCustomer(rows[i]["id"]) },
                onSelectMany: { selected = $0 },
                stretch: 3)
        }
    }
}

// ---- Thống kê (ui/stats_page.py): the period and «Chia theo», the scope (Mặt hàng / Nhóm hàng / Khách hàng) with
// Xuất Excel…, the summary of every product, the most issued beside the chart

struct StatsPage: View {
    @ObservedObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            PageHeader(title: t("nav.stats"), hint: t("stats.hint"))
            StatsPeriodRow(model: model)
            HStack(spacing: 8) {
                ForEach([StatsScope.Kind.products, .categories, .customers], id: \.self) { kind in
                    Button(StatsScope.buttonText(model, kind)) { UI.later { StatsScope.pick(model, kind) } }
                }
                Spacer()
                Button(t("stats.export")) { UI.later { StatsExport.run(model) } }
            }
            Text(caption).fixedSize(horizontal: false, vertical: true)
            // the summary over the most issued and the chart, in splitters (stats_page.py: QSplitter)
            VSplitView {
                summaryTable.frame(minHeight: 150)
                HSplitView {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(t("stats.top_title"))
                        topTable
                    }
                    .frame(minWidth: 260)
                    StatsChart(daily: model.daily).frame(minWidth: 260)
                }
                .frame(minHeight: 160)
            }
        }
    }

    /// '11/2026 · 9 mặt hàng · nhập 0 · xuất 0' and the money line under it (StatsPage.run, common.money_text)
    private var caption: String {
        let rows = model.summary
        let totalIn = rows.reduce(0.0) { $0 + $1.qtyIn }, totalOut = rows.reduce(0.0) { $0 + $1.qtyOut }
        var text = t("stats.caption", ["period": StatsExport.periodLabel(model), "products": String(rows.count),
                                       "qty_in": Format.quantity(totalIn), "qty_out": Format.quantity(totalOut)])
        if let m = model.money { text += "\n" + Self.moneyText(m) }
        return text
    }

    static func moneyText(_ m: Stats.Money) -> String {
        let total = Format.both(m.total, m.totalCny, approx: m.approx)
        var text: String
        if m.fees == nil {
            text = t("stats.money_goods", ["goods": total, "orders": String(m.orders)])
        } else {
            text = t("stats.money", ["total": total, "goods": Format.both(m.goods, m.goodsCny, approx: nil, brackets: false),
                                     "fees": Format.both(m.fees, m.feesCny, approx: nil, brackets: false),
                                     "orders": String(m.orders)])
        }
        if m.returned != 0 || m.returnedCny != 0 {
            text += t("money.returned", ["returned": Format.both(m.returned, m.returnedCny, approx: nil, brackets: false)])
        }
        if m.unpriced > 0 { text += " · " + t("stats.unpriced", ["count": String(m.unpriced)]) }
        return text
    }

    /// num_item(x or None): nothing in the cell for 0
    private static func blankZero(_ v: Double) -> String { v == 0 ? "" : Format.quantity(v) }

    /// _revenue_item: blank when the product has no priced line
    private static func revenue(_ r: Stats.SummaryRow) -> String {
        r.revenue == nil && r.revenueCny == nil ? "" : Format.both(r.revenue, r.revenueCny, approx: r.revenueApprox)
    }

    /// Tồn đầu / cuối kỳ are left out when customers are chosen; «Chia theo» adds 'Nhập dd/MM', 'Xuất dd/MM'… (run)
    private var summaryColumns: [Column] {
        let stock = !model.statsFilters.customerFiltered
        var columns = [Column(title: t("col.code"), width: 70), Column(title: t("col.product"), width: 240),
                       Column(title: t("col.name_zh"), width: 130), Column(title: t("col.spec"), width: 100),
                       Column(title: t("col.variant"), width: 90), Column(title: t("col.unit"), width: 60)]
        if stock { columns.append(Column(title: t("col.opening"), width: 90, numeric: true)) }
        columns += [Column(title: t("col.in"), width: 70, numeric: true), Column(title: t("col.out"), width: 70, numeric: true),
                    Column(title: t("col.adjust"), width: 90, numeric: true)]
        if stock { columns.append(Column(title: t("col.closing"), width: 90, numeric: true)) }
        columns += [Column(title: t("col.revenue"), width: 200, numeric: true), Column(title: t("col.stock_note"), width: 150)]
        for label in bucketLabels {
            columns += [Column(title: "\(t("col.in")) \(label)", width: 80, numeric: true),
                        Column(title: "\(t("col.out")) \(label)", width: 80, numeric: true)]
        }
        return columns
    }

    private var bucketLabels: [String] {
        let (start, end) = model.periodRange
        return Stats.buckets(start: start, end: end, by: model.statsSplit).map(\.label)
    }

    private var summaryTable: some View {
        let rows = model.summary
        let columns = summaryColumns
        let stock = !model.statsFilters.customerFiltered
        let labels = bucketLabels
        let cells: [[String]] = rows.map { r in
            var c = [r.code, r.nameVi, r.nameZh, r.spec, r.variant, r.unit]
            if stock { c.append(Format.quantity(r.opening)) }
            c += [Self.blankZero(r.qtyIn), Self.blankZero(r.qtyOut), Self.blankZero(r.adjust)]
            if stock { c.append(Format.quantity(r.closing)) }
            c += [Self.revenue(r), r.stockNote]
            for label in labels {
                c += [Self.blankZero(r.perBucket[label]?.qtyIn ?? 0), Self.blankZero(r.perBucket[label]?.qtyOut ?? 0)]
            }
            return c
        }
        let tones: [RowTone] = rows.map { ($0.closing ?? 0) < 0 ? .negative : .normal }
        // the columns are made with the table: a new set of columns makes a new table
        return DataTable(columns: columns, rows: cells, tones: tones,
                         onOpen: { model.openProduct(rows[$0].productId) },
                         stretch: nil)
            .id(columns.map(\.title).joined(separator: "|"))
    }

    private var topTable: some View {
        let rows = Stats.topOut(model.summary)
        return DataTable(
            columns: [Column(title: t("col.rank"), width: 50, numeric: true), Column(title: t("col.product"), width: 240),
                      Column(title: t("col.name_zh"), width: 130), Column(title: t("col.spec"), width: 100),
                      Column(title: t("col.variant"), width: 90), Column(title: t("col.out"), width: 80, numeric: true),
                      Column(title: t("col.unit"), width: 60), Column(title: t("col.revenue"), width: 200, numeric: true)],
            rows: rows.enumerated().map { i, r in
                [String(i + 1), r.nameVi, r.nameZh, r.spec, r.variant, Format.quantity(r.qtyOut), r.unit, Self.revenue(r)]
            },
            onOpen: { model.openProduct(rows[$0].productId) })
    }
}

/// Kỳ: [Ngày | Tháng | Quý | Năm | Khoảng tự chọn] and the boxes of that period, «Chia theo» on the right.
struct StatsPeriodRow: View {
    @ObservedObject var model: AppModel

    static let splits = ["none", "day", "month"]

    var body: some View {
        HStack(spacing: 8) {
            Text(t("stats.period"))
            Picker("", selection: $model.periodKind) {
                ForEach(AppModel.PeriodKind.allCases) { k in Text(k.label).tag(k) }
            }
            .labelsHidden()
            .frame(width: 170 * UI.scale)
            inputs
            Spacer()
            Text(t("stats.split"))
            Picker("", selection: $model.statsSplit) {
                ForEach(Self.splits, id: \.self) { s in Text(t("split.\(s)")).tag(s) }
            }
            .labelsHidden()
            .frame(width: 150 * UI.scale)
        }
    }

    @ViewBuilder private var inputs: some View {
        switch model.periodKind {
        case .day:
            DateBox(iso: $model.statsDay)
        case .month:
            Picker("", selection: $model.month) {
                ForEach(1...12, id: \.self) { n in Text(t("stats.month_n", ["n": String(n)])).tag(n) }
            }
            .labelsHidden()
            .frame(width: 130 * UI.scale)
            yearBox
        case .quarter:
            Picker("", selection: $model.quarter) {
                ForEach(1...4, id: \.self) { n in Text(t("stats.quarter_n", ["n": String(n)])).tag(n) }
            }
            .labelsHidden()
            .frame(width: 110 * UI.scale)
            yearBox
        case .year:
            yearBox
        case .range:
            Text(t("filter.from"))
            DateBox(iso: $model.rangeFrom)
            Text(t("filter.to"))
            DateBox(iso: $model.rangeTo)
        }
    }

    /// the year as a number with ▲▼ (QSpinBox)
    private var yearBox: some View {
        Stepper(value: $model.year, in: 2000...2100) {
            Text(String(model.year)).monospacedDigit()
        }
    }
}

// ---- Kiểm kê (ui/count_page.CountPage)

struct CountPage: View {
    @ObservedObject var model: AppModel
    @State private var date = Dates.today
    @State private var note = ""
    /// typed counts, by product and place
    @State private var counted: [Ledger.PlaceKey: String] = [:]

    static let countMain = 9, countOffice = 10, noteCol = 12

    var body: some View {
        _ = model.version
        let products = model.read { try Catalog.products($0) } ?? []
        let levels = model.read { try Ledger.levelsByPlace($0, asOf: date) } ?? [:]
        var red: Set<[Int]> = []
        let rows: [[String]] = products.enumerated().map { i, p in
            let main = levels[.init(p.id, Ledger.main)] ?? 0, office = levels[.init(p.id, Ledger.office)] ?? 0
            let cm = counted[.init(p.id, Ledger.main)] ?? "", co = counted[.init(p.id, Ledger.office)] ?? ""
            var diff = 0.0, any = false
            for (text, had) in [(cm, main), (co, office)] {
                if let v = parseNumber(text) {
                    diff += v - had
                    any = true
                }
            }
            if any && abs(diff) > 1e-9 { red.insert([i, 11]) }
            let diffText = any ? (diff > 0 ? "+" : "") + Format.quantity(diff) : ""
            return [p.code, p.nameVi, p.nameZh, p.spec, p.variant, p.unit, Format.quantity(main), Format.quantity(office),
                    Format.quantity(main + office), cm, co, diffText, p.stockNote]
        }
        let typed = Set(counted.filter { parseNumber($0.value) != nil }.keys.map(\.productId))
        return VStack(alignment: .leading, spacing: 6) {
            PageHeader(title: t("nav.count"), hint: t("count.hint"))
                .onAppear { model.rescan(quiet: true) }  // notes dated before the count must be in first
            HStack {
                Text(t("count.date"))
                DateBox(iso: $date)
                Text(t("col.note"))
                TextField("", text: $note).textFieldStyle(.roundedBorder)
                Button(t("transfer.button")) { UI.later { _ = Forms.transfer(model) } }.help(t("transfer.tip"))
                Button(t("trial.button")) { UI.later { _ = Forms.trial(model) } }.help(t("trial.tip"))
            }
            HStack {
                Button(t("count.transfers_btn")) { Screens.history("transfer", model) }
                Button(t("count.trials_btn")) { Screens.history("trial", model) }
                Button(t("count.counts_btn")) { Screens.history("stock_count", model) }
                Spacer()
            }
            let main = UI.locationName(Ledger.main), office = UI.locationName(Ledger.office)
            DataTable(
                columns: [Column(title: t("col.code"), width: 70), Column(title: t("col.product"), width: 200),
                          Column(title: t("col.name_zh"), width: 130), Column(title: t("col.spec"), width: 100),
                          Column(title: t("col.variant"), width: 90), Column(title: t("col.unit"), width: 60),
                          Column(title: t("count.in_app_at", ["place": main]).replacingOccurrences(of: "\n", with: " "), width: 110, numeric: true),
                          Column(title: t("count.in_app_at", ["place": office]).replacingOccurrences(of: "\n", with: " "), width: 110, numeric: true),
                          Column(title: t("count.in_app"), width: 90, numeric: true),
                          Column(title: t("count.counted_at", ["place": main]).replacingOccurrences(of: "\n", with: " "), width: 120, numeric: true, editable: true),
                          Column(title: t("count.counted_at", ["place": office]).replacingOccurrences(of: "\n", with: " "), width: 120, numeric: true, editable: true),
                          Column(title: t("col.difference"), width: 90, numeric: true),
                          Column(title: t("col.stock_note"), width: 180, editable: true)],
                rows: rows,
                onEdit: { row, col, text in
                    let p = products[row]
                    if col == Self.noteCol {
                        model.write("stock_note") { try Catalog.saveStockNote($0, productId: p.id, text: text) }
                        return
                    }
                    let place = col == Self.countMain ? Ledger.main : Ledger.office
                    let clean = text.trimmingCharacters(in: .whitespaces)
                    counted[.init(p.id, place)] = clean.isEmpty || parseNumber(clean) != nil ? clean : ""
                },
                redCells: red,
                // count_page.py: columns as wide as their contents, Mặt hàng takes the room left, the table scrolls
                // sideways (no pinned or squeezed columns there, unlike Chuyển hàng / Dùng thử)
                fitWidth: false,
                sortable: false)
            HStack {
                Text(t("count.summary", ["counted": String(typed.count), "total": String(products.count)]))
                Spacer()
                Button(t("count.save")) { save(products) }
            }
        }
    }

    private func save(_ products: [Product]) {
        var lines: [Ledger.Counted] = []
        for p in products {
            for place in Ledger.locations {
                if let v = counted[.init(p.id, place)].flatMap(parseNumber) { lines.append(.init(p.id, place, v)) }
            }
        }
        if lines.isEmpty { return UI.error(t("count.nothing")) }
        let count = Set(lines.map(\.productId)).count
        guard UI.ask(t("count.confirm", ["count": String(count), "date": dmy(date)])) else { return }
        let day = date, text = note.trimmingCharacters(in: .whitespaces)
        if model.write("stock_count", { try Ledger.stockCount($0, date: day, counted: lines, note: text) }) != nil {
            counted = [:]
            note = ""
            UI.info(t("count.saved"))
        }
    }
}
