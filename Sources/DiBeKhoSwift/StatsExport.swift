import DiBeKhoCore
import GRDB
import SwiftUI

/// ui/stats_page.export: choose the sheets, write ThongKe_<period>_<time>.xlsx into the output folder, offer to open it.
/// The file is always in dong, whatever the ₫ | ¥ switch shows.
@MainActor
enum StatsExport {
    static func run(_ model: AppModel) {
        guard let folders = model.folders, let queue = model.queue else { return UI.error(t("stats.export_none")) }
        let (start, end) = model.periodRange
        let label = periodLabel(model)
        let scope = StatsScope.scopeLabel(model)
        let filters = model.statsFilters, by = model.statsSplit
        var chosen: Set<String>?
        Windows.show(t("stats.export"), width: 380, height: 300, modal: true) { _ in
            StatsExportView(period: t("report.period", ["period": label]), scope: t("report.scope", ["scope": scope])) { chosen = $0 }
        }
        guard let sheets = chosen else { return }
        if sheets.isEmpty { return UI.error(t("stats.export_none")) }
        let url = folders.output.appendingPathComponent(Report.fileName(label: label))
        do {
            _ = try queue.read { db in
                try Report.export(db, to: url, start: start, end: end, filters: filters, by: by, sheets: sheets,
                                  periodLabel: label, scopeLabel: scope)
            }
        } catch {
            let locked = (error as NSError).domain == NSCocoaErrorDomain
            return UI.error(locked ? t("stats.export_locked") : UI.message(error))
        }
        if UI.ask(t("stats.exported", ["path": url.path])) { UI.open(url) }
    }

    /// Python period_range's label: 20/11/2026, 11/2026, Quý 4/2026, 2026, 01/11/2026 – 20/11/2026
    static func periodLabel(_ model: AppModel) -> String {
        switch model.periodKind {
        case .day: return Format.date(model.statsDay)
        case .month: return String(format: "%02d/%d", model.month, model.year)
        case .quarter: return t("stats.quarter_label", ["q": String(model.quarter), "y": String(model.year)])
        case .year: return String(model.year)
        case .range:
            let (start, end) = model.periodRange
            return "\(Format.date(start)) – \(Format.date(end))"
        }
    }
}

private struct StatsExportView: View {
    let period: String
    let scope: String
    let done: (Set<String>) -> Void
    @EnvironmentObject var box: WindowBox
    @State private var on = Set(Report.sheetKeys)

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(period)
            Text(scope).fixedSize(horizontal: false, vertical: true)
            Text(t("stats.export_sheets")).padding(.top, 4)
            ForEach(Report.sheetKeys, id: \.self) { key in
                Toggle(t("sheet.\(key)"), isOn: Binding(get: { on.contains(key) },
                                                         set: { if $0 { on.insert(key) } else { on.remove(key) } }))
            }
            Spacer()
            HStack {
                Spacer()
                Button(t("stats.export_do")) {
                    done(on)
                    box.close(accepted: true)
                }.keyboardShortcut(.defaultAction)
                Button(t("btn.cancel")) { box.close() }
            }
        }
    }
}

/// details.CustomerDialog.export: the orders and products of one customer (all time) to output/KhachHang_<name>_<time>.xlsx.
@MainActor
enum CustomerExport {
    static func run(_ model: AppModel, id: Int64, start: String? = nil, end: String? = nil) {
        guard let folders = model.folders, let queue = model.queue else { return UI.error(t("stats.export_none")) }
        let label = start == nil && end == nil ? t("filter.all_time") : "\(Format.date(start ?? "")) – \(Format.date(end ?? ""))"
        guard let name = model.read({ db in try String.fetchOne(db, sql: "SELECT name FROM customers WHERE id = ?", arguments: [id]) }) ?? nil
        else { return }
        let safe = String(String(name.map { $0.isLetter || $0.isNumber ? $0 : "-" }).trimmingCharacters(in: CharacterSet(charactersIn: "-")).prefix(80))
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyyMMdd-HHmmss"
        let url = folders.output.appendingPathComponent("KhachHang_\(safe)_\(label.map { $0.isLetter || $0.isNumber ? String($0) : "-" }.joined().trimmingCharacters(in: CharacterSet(charactersIn: "-")))_\(f.string(from: Date())).xlsx")
        do {
            _ = try queue.read { try Report.exportCustomer($0, to: url, customerId: id, start: start, end: end, periodLabel: label) }
        } catch {
            let locked = (error as NSError).domain == NSCocoaErrorDomain
            return UI.error(locked ? t("stats.export_locked") : UI.message(error))
        }
        ActivityLog.write("export", url.lastPathComponent)
        if UI.ask(t("stats.exported", ["path": url.path])) { UI.open(url) }
    }
}
