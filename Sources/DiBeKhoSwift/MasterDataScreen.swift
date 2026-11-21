import AppKit
import DiBeKhoCore
import GRDB
import SwiftUI
import UniformTypeIdentifiers

/// Cài đặt → «Xuất / Nhập dữ liệu gốc…» (ui/transfer_page.py export_master, import_master_file, StockMatchDialog):
/// the catalog, the customers and the stock as one Excel file, and back.
@MainActor
enum MasterDataScreen {
    static func export(_ model: AppModel) {
        guard let folders = model.folders, model.queue != nil else { return }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd_HHmm"
        let url = folders.output.appendingPathComponent("DiBeKho_DuLieuGoc_\(f.string(from: Date())).xlsx")
        do {
            guard let queue = model.queue else { return }
            _ = try queue.read { try MasterData.export($0, to: url) }
        } catch {
            let locked = (error as NSError).domain == NSCocoaErrorDomain
            return UI.error(locked ? t("stats.export_locked") + "\n" + error.localizedDescription : UI.message(error))
        }
        if UI.ask(t("master.exported", ["path": url.path])) { UI.open(url) }
    }

    static func start(_ model: AppModel) {
        guard model.writable else { return UI.error(Texts.notOpen) }
        let panel = NSOpenPanel()
        panel.title = t("master.import")
        panel.allowedContentTypes = [UTType(filenameExtension: "xlsx") ?? .data]
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = model.folders?.input
        guard panel.runModal() == .OK, let url = panel.url else { return }
        _ = importFile(model, url)
    }

    /// Reads the workbook and imports it after the questions. True when imported (the Inbox then moves the file).
    static func importFile(_ model: AppModel, _ url: URL) -> Bool {
        guard model.writable, let queue = model.queue, let folders = model.folders else {
            UI.error(Texts.notOpen)
            return false
        }
        let data: MasterData.Contents
        do { data = try MasterData.read(url) } catch {
            UI.error(t("master.not_master_file", ["error": UI.message(error)]))
            return false
        }
        var stock = data.stock
        if !stock.isEmpty && MasterData.needsCheck(stock) {
            var checked: [MasterData.Stock]?
            Windows.show(t("master.preview_title"), width: 1250, height: 640, modal: true) { box in
                StockMatchView(products: data.products, stock: data.stock, box: box) { checked = $0 }
            }
            guard let result = checked else { return false }
            stock = result
        }
        var text = t("master.confirm_import", ["products": String(data.products.count), "customers": String(data.customers.count)])
        if !stock.isEmpty {
            let extra = t("master.confirm_stock", ["count": String(stock.count)])
            if let gap = text.range(of: "\n\n") { text.replaceSubrange(gap, with: "\n\n" + extra + "\n\n") }
        }
        guard UI.ask(text) else { return false }
        do {
            try Backups.named(queue, folder: folders.root.appendingPathComponent("sao-luu", isDirectory: true), label: "truoc-nhap-du-lieu-goc")
        } catch {
            UI.error(UI.message(error))
            return false
        }
        ActivityLog.write("action", "master")
        // notes up to today must be in the ledger first, or they would be subtracted from the count
        if !stock.isEmpty { _ = try? Deliveries.scan(queue, folders) }
        let today = Dates.iso(Date())
        let done = stock
        guard let r = model.write("master_import", { db in
            try MasterData.importMaster(db, products: data.products, customers: data.customers, stock: done,
                                        stockDate: today, note: t("master.stock_note"))
        }) else { return false }
        UI.info(summary(r))
        return true
    }

    private static func summary(_ r: MasterData.Outcome) -> String {
        var text = t("master.imported", ["products_new": String(r.productsNew), "products_updated": String(r.productsUpdated),
                                         "customers_new": String(r.customersNew), "customers_updated": String(r.customersUpdated)])
        if r.stockCounted > 0 { text += "\n" + t("master.imported_stock", ["count": String(r.stockCounted)]) }
        if !r.labelsUpdated.isEmpty { text += "\n" + t("master.imported_labels", ["count": String(r.labelsUpdated.count)]) }
        if !r.renumbered.isEmpty {
            let lines = r.renumbered.map { t("master.renumbered_row", ["row": String($0.row), "code": $0.code, "new": $0.new]) }
            text += "\n\n" + t("master.renumbered") + "\n" + lines.joined(separator: "\n")
        }
        if !r.skipped.isEmpty {
            let lines = r.skipped.map { t("master.skipped_row", ["row": String($0.row), "code": $0.code.isEmpty ? "—" : $0.code, "existing": $0.existing]) }
            text += "\n\n" + t("master.skipped") + "\n" + lines.joined(separator: "\n")
        }
        if !r.stockSkipped.isEmpty {
            let lines = r.stockSkipped.map { t("master.stock_skipped_row", ["row": String($0.row), "name": $0.name]) }
            text += "\n\n" + t("master.stock_skipped") + "\n" + lines.joined(separator: "\n")
        }
        return text
    }
}

/// Which product each row of the «Tồn kho» sheet goes to, when they are not tied by code (files without the code column).
/// Rows whose name/category/type differ from the product are yellow; the user can pick another product for any row.
private struct StockMatchView: View {
    let products: [MasterData.Product]
    let stock: [MasterData.Stock]
    let box: WindowBox
    let done: ([MasterData.Stock]) -> Void
    private let same: [Int: [Int]]
    private let byRow: [Int: MasterData.Product]
    @State private var chosen: [Int?]

    init(products: [MasterData.Product], stock: [MasterData.Stock], box: WindowBox, done: @escaping ([MasterData.Stock]) -> Void) {
        self.products = products
        self.stock = stock
        self.box = box
        self.done = done
        same = MasterData.sameRows(stock)
        byRow = Dictionary(products.map { ($0.row, $0) }, uniquingKeysWith: { first, _ in first })
        _chosen = State(initialValue: stock.map { $0.productRow })
    }

    private func label(_ p: MasterData.Product) -> String {
        [p.code.isEmpty ? "—" : p.code, p.spec, p.category, p.variant, p.nameVi].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private func inFile(_ st: MasterData.Stock) -> String {
        [st.category, st.variant, st.name.replacingOccurrences(of: "\n", with: " / ")].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    /// (problems that make the row yellow, the change the import will make)
    private func problems(_ i: Int, _ users: [Int: [Int]]) -> ([String], String) {
        let st = stock[i]
        var list: [String] = []
        if let rows = same[st.row] { list.append(t("master.problem_same", ["rows": rows.map(String.init).joined(separator: ", ")])) }
        guard let pr = chosen[i], let p = byRow[pr] else { return (list + [t("master.problem_unassigned")], "") }
        if MasterData.stockDiffers(st, p) { list.append(t("master.problem_name")) }
        let others = (users[pr] ?? []).filter { $0 != i }.map { String(stock[$0].row) }
        if !others.isEmpty { list.append(t("master.problem_twice", ["rows": others.joined(separator: ", ")])) }
        var change = ""
        if let c = MasterData.labelChange(st, p) {
            change = t("master.change_labels", ["code": p.code.isEmpty ? "—" : p.code, "old": c.old, "new": c.new])
        }
        return (list, change)
    }

    private var users: [Int: [Int]] {
        var out: [Int: [Int]] = [:]
        for (i, c) in chosen.enumerated() { if let c { out[c, default: []].append(i) } }
        return out
    }

    var body: some View {
        let used = users
        let report = stock.indices.map { problems($0, used) }
        let differing = report.filter { !$0.0.isEmpty }.count
        return VStack(alignment: .leading, spacing: 8) {
            Hint(t("master.preview_hint"))
            Text(differing > 0 ? t("master.preview_warn", ["count": String(differing)]) : t("master.preview_ok"))
            // a table with its column titles, as transfer_page.StockMatchDialog
            VStack(spacing: 0) {
                TableHeader(cells: [(t("master.col_stock_row"), 50), (t("col.stock"), 70), (t("master.col_in_file"), 300),
                                    (t("master.col_assign"), 330), (t("master.col_problem"), nil)])
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(stock.indices, id: \.self) { i in
                            row(i, report[i])
                            Divider().opacity(0.4)
                        }
                    }
                }
            }
            .tableBox()
            HStack {
                Spacer()
                Button(t("master.preview_continue")) { accept(used) }.keyboardShortcut(.defaultAction)
                Button(t("btn.cancel")) { box.close() }
            }
        }
    }

    private func row(_ i: Int, _ report: ([String], String)) -> some View {
        let st = stock[i]
        let bad = !report.0.isEmpty
        let problem = (report.0 + (report.1.isEmpty ? [] : [report.1])).joined(separator: "; ")
        return HStack(alignment: .top, spacing: 8) {
            Text(String(st.row)).frame(width: 50, alignment: .trailing)
            Text(Format.quantity(st.stock ?? 0)).frame(width: 70, alignment: .trailing)
            Text(inFile(st)).frame(width: 300, alignment: .leading).help(inFile(st))
            Picker("", selection: Binding(get: { chosen[i] }, set: { chosen[i] = $0 })) {
                Text(t("master.no_assign")).tag(Int?.none)
                ForEach(products, id: \.row) { p in Text(label(p)).tag(Int?.some(p.row)) }
            }
            .labelsHidden()
            .frame(width: 330)
            Text((bad ? "⚠ " : "") + problem).frame(maxWidth: .infinity, alignment: .leading).help(problem)
        }
        .lineLimit(2)
        .padding(.vertical, 3)
        .background(bad ? Color.yellow.opacity(0.25) : Color.clear)
    }

    private func accept(_ used: [Int: [Int]]) {
        if let twice = used.first(where: { $0.value.count > 1 }), let p = byRow[twice.key] {
            let rows = twice.value.map { String(stock[$0].row) }.joined(separator: ", ")
            return UI.error(t("master.preview_twice", ["product": label(p), "rows": rows]))
        }
        var result = stock
        for i in result.indices { result[i].productRow = chosen[i] }
        done(result)
        box.close(accepted: true)
    }
}
