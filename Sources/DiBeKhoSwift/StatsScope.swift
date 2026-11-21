import Charts
import DiBeKhoCore
import SwiftUI

/// The scope of Thống kê (ui/stats_page.ScopeButton / PickDialog): «Mặt hàng: Tất cả» / «Mặt hàng: 3 đã chọn»; a
/// click opens a list to tick, with a filter box. Nothing ticked = all.
@MainActor
enum StatsScope {
    enum Kind { case products, categories, customers }

    static func labelKey(_ kind: Kind) -> String {
        switch kind {
        case .products: return "col.product"
        case .categories: return "col.category"
        case .customers: return "col.customer"
        }
    }

    /// (text, value) of each choice, as _product_items / _category_items / _customer_items
    static func items(_ model: AppModel, _ kind: Kind) -> [PickItem] {
        switch kind {
        case .products:
            let products = model.read { try Catalog.products($0, includeInactive: true) } ?? []
            return products.map { PickItem(text: $0.longLabel, value: String($0.id)) }
        case .categories:
            let names = model.read { try Catalog.categories($0) } ?? []
            return names.map { PickItem(text: $0, value: $0) }
        case .customers:
            let rows = model.read { try Lookup.customers($0) } ?? []
            return rows.map { PickItem(text: Details.text($0, "name"), value: String($0["id"] as Int64)) }
        }
    }

    static func selected(_ model: AppModel, _ kind: Kind) -> [String] {
        switch kind {
        case .products: return model.statsFilters.productIds.map(String.init)
        case .categories: return model.statsFilters.categories
        case .customers: return model.statsFilters.customerIds.map(String.init)
        }
    }

    static func set(_ model: AppModel, _ kind: Kind, _ values: [String]) {
        var f = model.statsFilters
        switch kind {
        case .products: f.productIds = values.compactMap { Int64($0) }
        case .categories: f.categories = values
        case .customers: f.customerIds = values.compactMap { Int64($0) }
        }
        model.statsFilters = f
    }

    /// 'Mặt hàng: Tất cả' or 'Mặt hàng: 3 đã chọn' (the button)
    static func buttonText(_ model: AppModel, _ kind: Kind) -> String {
        let chosen = selected(model, kind)
        let what = chosen.isEmpty ? t("filter.all") : t("stats.n_selected", ["count": String(chosen.count)])
        return "\(t(labelKey(kind))): \(what)"
    }

    /// 'Mặt hàng: A, B, C …' (the Excel file's scope line; ScopeButton.describe)
    static func describe(_ model: AppModel, _ kind: Kind) -> String {
        let chosen = Set(selected(model, kind))
        guard !chosen.isEmpty else { return "\(t(labelKey(kind))): \(t("filter.all"))" }
        let names = items(model, kind).filter { chosen.contains($0.value) }.map(\.text)
        return "\(t(labelKey(kind))): " + names.prefix(5).joined(separator: ", ") + (names.count > 5 ? " …" : "")
    }

    static func scopeLabel(_ model: AppModel) -> String {
        [Kind.products, .categories, .customers].map { describe(model, $0) }.joined(separator: " · ")
    }

    static func pick(_ model: AppModel, _ kind: Kind) {
        var result: [String]?
        let all = items(model, kind)
        let now = selected(model, kind)
        Windows.show(t(labelKey(kind)), width: 520, height: 560, modal: true) { _ in
            PickListView(items: all, selected: Set(now)) { result = $0 }
        }
        if let result { set(model, kind, result) }
    }
}

struct PickItem: Identifiable {
    let text: String
    let value: String
    var id: String { value }
}

/// A list to tick with a filter box (stats_page.PickDialog); OK hands over the values ticked, in the list's order.
struct PickListView: View {
    let items: [PickItem]
    @State var selected: Set<String>
    let done: ([String]) -> Void
    @EnvironmentObject var box: WindowBox
    @State private var filter = ""

    var body: some View {
        let shown = items.filter { filter.isEmpty || TextRules.matchesWords(filter, $0.text) }
        VStack(alignment: .leading, spacing: 8) {
            ClearableField(placeholder: t("stock.filter"), text: $filter)
            List(shown) { item in
                Toggle(item.text, isOn: Binding(get: { selected.contains(item.value) },
                                                set: { if $0 { selected.insert(item.value) } else { selected.remove(item.value) } }))
            }
            HStack {
                Button(t("stats.pick_all")) { selected = [] }
                Spacer()
            }
            Text(t("stats.pick_hint"))
            HStack {
                Spacer()
                Button(t("btn.ok")) {
                    done(items.map(\.value).filter { selected.contains($0) })
                    box.close(accepted: true)
                }
                .keyboardShortcut(.defaultAction)
                Button(t("btn.cancel")) { box.close() }
            }
        }
    }
}

/// «Số lượng xuất theo thời gian» (stats_page._draw_chart): a bar per day, a bar per month over 62 days; day numbers
/// for one month, dd/MM otherwise; only some labels under many bars.
struct StatsChart: View {
    let daily: [(day: String, qty: Double)]

    struct Bar: Identifiable {
        let id: Int
        let label: String
        let qty: Double
    }

    private var bars: [Bar] {
        guard let first = daily.first?.day, let last = daily.last?.day else { return [] }
        if daily.count > 63 {
            var keys: [String] = [], sums: [String: Double] = [:]
            for d in daily {
                let p = d.day.split(separator: "-")
                let key = "\(p[1])/\(p[0].suffix(2))"
                if sums[key] == nil { keys.append(key) }
                sums[key, default: 0] += d.qty
            }
            return keys.enumerated().map { Bar(id: $0.offset, label: $0.element, qty: sums[$0.element] ?? 0) }
        }
        let oneMonth = first.prefix(7) == last.prefix(7)
        return daily.enumerated().map { i, d in
            let p = d.day.split(separator: "-")
            return Bar(id: i, label: oneMonth ? String(Int(p[2]) ?? 0) : "\(p[2])/\(p[1])", qty: d.qty)
        }
    }

    /// the first label and every 5th (7th for dd/MM) once there are more than 12 bars (_x_axis)
    private func shownLabels(_ bars: [Bar]) -> [String] {
        guard bars.count > 12 else { return bars.map(\.label) }
        let step = (bars.first?.label.count ?? 0) <= 2 ? 5 : 7
        return bars.filter { $0.id == 0 || ($0.id + 1) % step == 0 }.map(\.label)
    }

    var body: some View {
        let bars = self.bars
        VStack(spacing: 4) {
            Text(t("stats.chart_title")).font(.system(size: UI.baseSize))
            Chart(bars) { bar in
                BarMark(x: .value("x", bar.label), y: .value(t("col.out"), bar.qty))
            }
            .chartXAxis { AxisMarks(values: shownLabels(bars)) }
        }
        .padding(8)
        .background(SoftRect().fill(Color(nsColor: .textBackgroundColor)))
    }
}
