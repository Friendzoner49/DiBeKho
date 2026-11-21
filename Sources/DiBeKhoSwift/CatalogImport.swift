import AppKit
import DiBeKhoCore
import GRDB
import SwiftUI
import UniformTypeIdentifiers

/// Settings → Nhập danh mục từ Excel…: the customer's monthly stock sheet, an editable preview, import
/// (ui/catalog_import.py).
@MainActor
enum CatalogImport {
    static func start(_ model: AppModel) {
        guard model.writable else { return UI.error(Texts.readOnly) }
        let panel = NSOpenPanel()
        panel.title = t("catalog.pick_file")
        panel.allowedContentTypes = [UTType(filenameExtension: "xlsx") ?? .data]
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = model.folders?.input
        guard panel.runModal() == .OK, let url = panel.url else { return }
        importFile(model, url)
    }

    /// True when the user imported (the Inbox then moves the file).
    @discardableResult
    static func importFile(_ model: AppModel, _ url: URL) -> Bool {
        let items: [CatalogSheet.Item]
        do {
            let found = try CatalogSheet.columns(url)
            if found.stockCol == nil {
                guard let (goOn, col) = askStockColumn(url, found.columns), goOn else { return false }
                items = try CatalogSheet.read(url, stockCol: col)
            } else {
                items = try CatalogSheet.read(url)
            }
        } catch let e as CatalogSheet.NotCatalogSheet {
            return fail(t("catalog.not_sheet", ["error": e.reason]))
        } catch {
            return fail(t("catalog.not_sheet", ["error": error.localizedDescription]))
        }
        if items.isEmpty { return fail(t("catalog.not_sheet", ["error": "0"])) }
        let exists = model.read { db in try items.map { try Catalog.findSame(db, nameVi: $0.nameVi, spec: $0.spec, variant: $0.variant) != nil } } ?? []
        guard exists.count == items.count else { return false }
        return Windows.show(t("catalog.title", ["file": url.lastPathComponent]), width: 1200, height: 720, modal: true) { _ in
            CatalogImportView(model: model, file: url.lastPathComponent, items: items, exists: exists)
        }
    }

    private static func fail(_ text: String) -> Bool {
        UI.error(text)
        return false
    }

    /// (go on?, the chosen column or nil = no stock); nil when the dialog could not be built.
    private static func askStockColumn(_ url: URL, _ columns: [CatalogSheet.Column]) -> (Bool, Int?)? {
        var picked: Int?? = nil
        Windows.show(t("catalog.pick_stock_title"), width: 640, height: 460, modal: true) { _ in
            StockColumnView(file: url.lastPathComponent, columns: columns) { picked = .some($0) }
        }
        guard let choice = picked else { return (false, nil) }
        return (true, choice)
    }
}

struct StockColumnView: View {
    let file: String
    let columns: [CatalogSheet.Column]
    let done: (Int?) -> Void
    @EnvironmentObject var box: WindowBox
    @State private var choice = -1  // -1 = no stock

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(t("catalog.pick_stock_hint", ["file": file]))
            List(selection: Binding<Int?>(get: { choice }, set: { choice = $0 ?? -1 })) {
                Text(t("catalog.pick_stock_none")).tag(-1)
                ForEach(columns, id: \.col) { c in
                    let samples = c.samples.filter { !$0.isEmpty }.joined(separator: ", ")
                    Text(t("catalog.pick_stock_column", ["letter": c.letter, "label": c.label.isEmpty ? "—" : c.label])
                         + (samples.isEmpty ? "" : "   " + t("catalog.pick_stock_samples", ["samples": samples])))
                        .tag(c.col)
                }
            }
            HStack {
                Spacer()
                Button(t("catalog.pick_stock_continue")) {
                    done(choice < 0 ? nil : choice)
                    box.close(accepted: true)
                }
                .keyboardShortcut(.defaultAction)
                Button(t("btn.cancel")) { box.close() }
            }
        }
    }
}

struct CatalogImportView: View {
    @ObservedObject var model: AppModel
    let file: String
    @State var items: [CatalogSheet.Item]
    let exists: [Bool]
    @EnvironmentObject var box: WindowBox
    @State private var checked: [Bool]
    @State private var stockText: [String]
    @State private var useStock: Bool
    @State private var date = Dates.iso(Date())
    private let hasStock: Bool

    init(model: AppModel, file: String, items: [CatalogSheet.Item], exists: [Bool]) {
        self.model = model
        self.file = file
        _items = State(initialValue: items)
        self.exists = exists
        _checked = State(initialValue: exists.map { !$0 })
        _stockText = State(initialValue: items.map { $0.stock.map { Format.quantity($0) } ?? "" })
        hasStock = items.contains { $0.stock != nil }
        _useStock = State(initialValue: items.contains { $0.stock != nil })
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Hint(t("catalog.hint"))
            DataTable(
                columns: [Column(title: t("catalog.row"), width: 80), Column(title: t("col.product"), width: 330, editable: true),
                          Column(title: t("col.name_zh"), width: 230, editable: true), Column(title: t("col.spec"), width: 110, editable: true),
                          Column(title: t("col.variant"), width: 120, editable: true), Column(title: t("col.unit"), width: 70, editable: true),
                          Column(title: t("col.category"), width: 140, editable: true),
                          Column(title: t("catalog.col_stock"), width: 100, numeric: true, editable: true),
                          Column(title: t("col.status"), width: 70)],
                rows: items.indices.map { i in
                    let it = items[i]
                    return [(checked[i] ? "☑ " : "☐ ") + String(it.row), it.nameVi, it.nameZh, it.spec, it.variant, it.unit,
                            it.category, stockText[i], t(exists[i] ? "catalog.exists" : "catalog.new")]
                },
                tones: exists.map { $0 ? .grey : .normal },
                onOpen: { i in checked[i].toggle() },
                onEdit: { r, c, text in edit(r, c, text) },
                fitWidth: false, sortable: false)
            HStack {
                Button(t("catalog.check_all")) { checked = checked.map { _ in true } }
                Button(t("catalog.check_none")) { checked = checked.map { _ in false } }
                Spacer()
            }
            HStack {
                Toggle(t("catalog.use_stock"), isOn: $useStock).disabled(!hasStock)
                DateBox(iso: $date).disabled(!useStock)
                Spacer()
            }
            Hint(t("catalog.stock_hint"))
            HStack {
                Spacer()
                Button(t("catalog.import_do")) { doImport() }.keyboardShortcut(.defaultAction)
                Button(t("btn.cancel")) { box.close() }
            }
        }
    }

    private func edit(_ r: Int, _ c: Int, _ text: String) {
        let v = TextRules.clean(text)
        switch c {
        case 1: items[r].nameVi = v
        case 2: items[r].nameZh = v
        case 3: items[r].spec = v
        case 4: items[r].variant = v
        case 5: items[r].unit = v
        case 6: items[r].category = v
        case 7: stockText[r] = v
        default: break
        }
    }

    private func stock(_ i: Int) -> Double? {
        let s = stockText[i].trimmingCharacters(in: .whitespaces)
        return s.isEmpty ? nil : parseNumber(s)
    }

    private func doImport() {
        let picked = items.indices.filter { checked[$0] && !items[$0].nameVi.isEmpty }
        guard !picked.isEmpty else { return UI.error(t("catalog.nothing")) }
        let list = picked.map { i -> Catalog.CatalogItem in
            let it = items[i]
            return Catalog.CatalogItem(nameVi: it.nameVi, nameZh: it.nameZh, spec: it.spec, unit: it.unit,
                                       category: it.category, variant: it.variant, stock: stock(i))
        }
        let stockDate = useStock ? date : nil
        let note = t("catalog.stock_note", ["file": file])
        // notes up to that date must be in the ledger first, or they would be subtracted from the count later
        if stockDate != nil, let queue = model.queue, let folders = model.folders {
            _ = try? Deliveries.scan(queue, folders)
        }
        guard let r = model.write("catalog", { try Catalog.importCatalog($0, list, stockDate: stockDate, note: note) }) else { return }
        var text = t("catalog.done", ["created": String(r.created), "skipped": String(r.skipped)])
        if r.counted > 0 { text += "\n\n" + t("catalog.stock_done", ["count": String(r.counted), "date": dmy(date)]) }
        UI.info(text)
        box.close(accepted: true)
    }
}
