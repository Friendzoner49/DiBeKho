import AppKit
import DiBeKhoCore
import GRDB
import SwiftUI

/// What "Cần xử lý" shows, read in one go (Python ui/pending_page.py refresh).
struct PendingData {
    var unplaced: [UnplacedOrder] = []
    var waiting: [WaitingNote] = []
    /// the distinct unknown lines in the order of the notes, and by key
    var unknownList: [UnknownLine] = []
    var unknown: [String: UnknownLine] = [:]
    /// the products offered for each unknown line (the three closest, the matcher's best guess first)
    var suggestions: [String: [Product]] = [:]
    var names: [Int64: String] = [:]
    var conflicts: [CountConflict] = []
    var files: [(file: PendingFile, otherOrder: Bool)] = []
    var inbox: [InboxItem] = []

    var isEmpty: Bool {
        unknownList.isEmpty && files.isEmpty && unplaced.isEmpty && conflicts.isEmpty && inbox.isEmpty
    }

    static func load(_ db: Database, _ folders: ShopFolders) throws -> PendingData {
        var data = PendingData()
        data.unplaced = try Deliveries.unplaced(db)
        data.unknownList = try Deliveries.unknownLines(db, folders)
        for u in data.unknownList {
            data.unknown[u.key] = u
            // 2-3 products that could be this line, then the matcher's own pick if it is not among them
            var offered = u.isFee ? [] : try Catalog.suggestProducts(db, name: u.rawName, spec: u.spec)
            if let s = u.suggestion, !offered.contains(where: { $0.id == s }), let p = try Catalog.product(db, id: s) {
                offered.insert(p, at: 0)
            }
            data.suggestions[u.key] = offered
        }
        data.waiting = try Deliveries.waitingNotes(db, folders)
        for p in try Catalog.products(db, includeInactive: true) { data.names[p.id] = p.longLabel }
        data.conflicts = try Deliveries.countConflicts(db)
        for file in try Deliveries.pendingFiles(db) where file.status != "needs_mapping" {
            let other = file.status == "changed" ? try Deliveries.looksLikeOtherOrder(db, folders, hash: file.hash) : false
            data.files.append((file, other))
        }
        data.inbox = try Inbox.items(db, folders)
        return data
    }
}

/// What the user chose for an unknown name (pending_page: a product, new, skip, other, later).
enum PendingChoice: Hashable {
    case product(Int64), new, skip, other, later
}

/// Cần xử lý (ui/pending_page.py): orders without a place, names the app does not know, orders read after a count,
/// files that need a look, and (owner's machine) the requests of the web and of the staff.
struct PendingPage: View {
    @ObservedObject var model: AppModel
    @ObservedObject var cloud: CloudRunner
    @State private var data = PendingData()

    init(model: AppModel) {
        self.model = model
        self.cloud = model.cloud
    }

    private var hasRequests: Bool { model.live && (!cloud.staffRequests.isEmpty || !cloud.webRequests.isEmpty) }
    @State private var choices: [String: PendingChoice] = [:]
    @State private var openings: [String: String] = [:]
    /// products picked with "Chọn mặt hàng khác…", shown on top of the choices of their line
    @State private var picked: [Int64: Product] = [:]
    @State private var places: [Int64: Int64] = [:]

    private let widths: [CGFloat] = [190, 100, 90, 55, 270, 90]

    var body: some View {
        _ = model.version
        return VStack(alignment: .leading, spacing: 6) {
            PageHeader(title: t("nav.pending"), hint: t("pending.hint"))
            ScrollView([.horizontal, .vertical]) {
                VStack(alignment: .leading, spacing: 10) {
                    // the order of pending_page.py: places, unknown names, counts, staff changes, web requests, files, inbox
                    if !data.unplaced.isEmpty { placesBox }
                    if !data.unknownList.isEmpty { unknownBox }
                    if !data.conflicts.isEmpty { countBox }
                    if model.live && !cloud.staffRequests.isEmpty { StaffRequestsBox(cloud: cloud) }
                    if model.live && !cloud.webRequests.isEmpty { WebRequestsBox(cloud: cloud) }
                    if !data.files.isEmpty { filesBox }
                    if !data.inbox.isEmpty { inboxBox }
                    if data.isEmpty && !hasRequests { Text(t("pending.empty")) }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .onAppear(perform: reload)
        .onChange(of: model.version) { _ in reload() }
    }

    private func reload() {
        guard let folders = model.folders else {
            data = PendingData()
            return
        }
        data = model.read { try PendingData.load($0, folders) } ?? PendingData()
        let keys = Set(data.unknownList.map(\.key))
        choices = choices.filter { keys.contains($0.key) }  // what the user already chose stays while the page refreshes
        openings = openings.filter { keys.contains($0.key) }
    }

    private func cell(_ text: String, _ width: CGFloat, bold: Bool = false, alignRight: Bool = false) -> some View {
        Text(text).bold(bold).lineLimit(2)
            .frame(width: width * UI.scale, alignment: alignRight ? .trailing : .leading)
    }

    private func box<Content: View>(_ title: String, @ViewBuilder _ content: () -> Content) -> some View {
        GroupBox(title) {
            VStack(alignment: .leading, spacing: 6) { content() }
                .frame(maxWidth: .infinity, alignment: .leading).padding(6)
        }
    }

    private func run(_ name: String, _ work: @escaping (Database) throws -> Void) {
        if model.write(name, work) != nil { model.rescan() }  // _run: do it, then read the folder again
    }

    // ---- orders waiting for their place

    private var placesBox: some View {
        box(t("pending.places_title")) {
            Hint(t("pending.places_hint")).frame(maxWidth: 1000 * UI.scale, alignment: .leading)
            HStack {
                cell(t("col.doc_code"), 90, bold: true); cell(t("col.date"), 90, bold: true)
                cell(t("col.customer"), 220, bold: true); cell(t("col.lines"), 60, bold: true)
                cell(t("col.total_qty"), 90, bold: true); cell(t("loc.taken_from"), 200, bold: true)
            }
            ForEach(data.unplaced, id: \.id) { d in
                HStack {
                    cell(d.code, 90); cell(dmy(d.docDate), 90); cell(d.customer, 220)
                    cell(String(d.lineCount), 60, alignRight: true); cell(Format.quantity(d.totalQty), 90, alignRight: true)
                    LocationPicker(selection: Binding(get: { places[d.id] ?? Ledger.main }, set: { places[d.id] = $0 }))
                }
            }
            Button { savePlaces() } label: { Text(t("pending.places_save")).bold() }
        }
    }

    private func savePlaces() {
        let list = data.unplaced
        guard !list.isEmpty else { return }
        let chosen = Dictionary(uniqueKeysWithValues: list.map { ($0.id, places[$0.id] ?? Ledger.main) })
        let done: ()? = model.write("places") { db in
            for d in list { try Ledger.setLocation(db, docId: d.id, locationId: chosen[d.id]!) }
        }
        guard done != nil else { return }
        ActivityLog.write("places", list.map { "\($0.code) → \(Ledger.locationCodes[chosen[$0.id]!] ?? "main")" }.joined(separator: ", "))
        places = [:]
        model.rescan()
    }

    // ---- names the app does not know, grouped by order

    private func choice(_ u: UnknownLine) -> PendingChoice {
        if let c = choices[u.key] { return c }
        if u.isFee { return .skip }
        if let s = u.suggestion { return .product(s) }
        return .later  // nothing close enough: the user decides, nothing is created by itself
    }

    private func binding(_ u: UnknownLine) -> Binding<PendingChoice> {
        Binding(get: { choice(u) }, set: { new in
            if new == .other {
                UI.later { pickOther(u) }  // the list opens after the menu has closed
            } else {
                choices[u.key] = new
            }
        })
    }

    private func pickOther(_ u: UnknownLine) {
        guard let id = Forms.pickProduct(model), let p = model.read({ try Catalog.product($0, id: id) }) ?? nil else { return }
        picked[id] = p
        choices[u.key] = .product(id)
    }

    private func options(_ u: UnknownLine) -> [Product] {
        var list = data.suggestions[u.key] ?? []
        if case let .product(id) = choice(u), !list.contains(where: { $0.id == id }) {
            if let p = picked[id] ?? model.read({ try Catalog.product($0, id: id) }) ?? nil { list.insert(p, at: 0) }
        }
        return list
    }

    /// "relPath#row" of the line that carries the opening-stock box of each unknown name: its first line in the notes,
    /// which are listed oldest first
    private func openingSlots() -> Set<String> {
        var seen = Set<String>(), slots = Set<String>()
        for note in data.waiting {
            for ln in note.lines where ln.productId == nil && !ln.ignored && data.unknown[ln.key] != nil {
                if seen.insert(ln.key).inserted { slots.insert("\(note.relPath)#\(ln.row)") }
            }
        }
        return slots
    }

    private var unknownBox: some View {
        let slots = openingSlots()
        return box(t("pending.unknown_title")) {
            Hint(t("pending.unknown_hint")).frame(maxWidth: 1000 * UI.scale, alignment: .leading)
            HStack {
                cell(t("pending.name_on_note"), widths[0], bold: true); cell(t("col.name_zh"), widths[1], bold: true)
                cell(t("col.spec"), widths[2], bold: true); cell(t("col.qty"), widths[3], bold: true, alignRight: true)
                cell(t("pending.map_to"), widths[4], bold: true); cell(t("pending.opening"), widths[5], bold: true)
            }
            ForEach(data.waiting, id: \.relPath) { note in
                Text(t("pending.order_title", ["code": note.code.isEmpty ? "—" : note.code,
                                               "customer": note.customer.isEmpty ? "—" : note.customer,
                                               "date": note.docDate.map(dmy) ?? "", "waiting": String(note.unknown.count)]))
                    .bold().help(note.relPath).padding(.top, 4)
                ForEach(note.lines, id: \.row) { ln in
                    if ln.productId == nil && !ln.ignored, let u = data.unknown[ln.key] {
                        unknownRow(ln, u, showOpening: slots.contains("\(note.relPath)#\(ln.row)"))
                    } else {
                        HStack {  // already known: shown to compare the whole order, not to change here
                            cell(ln.nameVi.isEmpty ? ln.rawName : ln.nameVi, widths[0]); cell(ln.nameZh, widths[1])
                            cell(ln.spec, widths[2]); cell(Format.quantity(ln.qty), widths[3], alignRight: true)
                            cell(ln.productId.map { "✓ " + (data.names[$0] ?? "") } ?? t("pending.skip_short"), widths[4])
                        }
                        .foregroundColor(.secondary)
                    }
                }
            }
            Button { apply() } label: { Text(t("pending.apply")).bold() }.padding(.top, 4)
        }
    }

    private func unknownRow(_ ln: NoteLineInfo, _ u: UnknownLine, showOpening: Bool) -> some View {
        let skip = choice(u) == .skip
        return HStack {
            Group {
                cell(ln.nameVi.isEmpty ? ln.rawName : ln.nameVi, widths[0]).help(ln.rawName)
                cell(ln.nameZh, widths[1]); cell(ln.spec, widths[2]); cell(Format.quantity(ln.qty), widths[3], alignRight: true)
            }
            .strikethrough(skip)
            .foregroundColor(skip ? .secondary : .primary)
            Picker("", selection: binding(u)) {
                ForEach(options(u), id: \.id) { p in Text(p.longLabel).tag(PendingChoice.product(p.id)) }
                if !options(u).isEmpty { Divider() }
                Text(t("pending.create_new")).tag(PendingChoice.new)
                Text(t("pending.skip")).tag(PendingChoice.skip)
                Text(t("pending.other")).tag(PendingChoice.other)
                Text(t("pending.later")).tag(PendingChoice.later)
            }
            .labelsHidden()
            .frame(width: widths[4] * UI.scale)
            if showOpening {  // once per name, on its earliest order; only a new product needs its stock before the note
                TextField(t("pending.opening_placeholder"), text: Binding(get: { openings[u.key] ?? "" }, set: { openings[u.key] = $0 }))
                    .multilineTextAlignment(.trailing)
                    .textFieldStyle(.roundedBorder)
                    .disabled(choice(u) != .new)
                    .help(t("pending.opening_tip"))
                    .frame(width: widths[5] * UI.scale)
            }
        }
    }

    private func apply() {
        let list = data.unknownList
        // a name about to become a new product that looks like one the shop already has: offer that one
        for u in list where choice(u) == .new {
            let dups = model.read {
                try Catalog.findPossibleDuplicates($0, nameVi: u.nameVi.isEmpty ? u.rawName : u.nameVi, nameZh: u.nameZh, spec: u.spec)
            } ?? []
            if let first = dups.first,
               UI.ask(t("pending.looks_duplicate", ["name": u.label, "code": first.code, "product": first.longLabel])) {
                picked[first.id] = first
                choices[u.key] = .product(first.id)
            }
        }
        var stock: [String: Double] = [:]
        for u in list where choice(u) == .new {
            let text = (openings[u.key] ?? "").trimmingCharacters(in: .whitespaces)
            if text.isEmpty { continue }
            guard let value = parseNumber(text) else {
                return UI.error(t("pending.opening_invalid", ["name": u.nameVi.isEmpty ? u.rawName : u.nameVi]))
            }
            stock[u.key] = value
        }
        var mapped = 0, created = 0, skipped = 0, later = 0
        for u in list {
            switch choice(u) {
            case .new: created += 1
            case .skip: skipped += 1
            case .later: later += 1
            default: mapped += 1
            }
        }
        guard UI.ask(t("pending.confirm_apply", ["mapped": String(mapped), "created": String(created),
                                                 "skipped": String(skipped), "later": String(later)])) else { return }
        let decided = list.map { ($0, choice($0)) }
        let codes = model.read { db in try Dictionary(uniqueKeysWithValues: Catalog.products(db, includeInactive: true).map { ($0.id, $0.code) }) } ?? [:]
        ActivityLog.write("apply", decided.map { u, c -> String in
            switch c {
            case .product(let id): return "\(u.label) → \(codes[id] ?? String(id))"
            case .new: return "\(u.label) → new"
            case .skip: return "\(u.label) → skip"
            default: return "\(u.label) → later"
            }
        }.joined(separator: "\n"))
        let done: ()? = model.write("apply") { db in
            for (u, c) in decided {
                switch c {
                case .new:
                    try Deliveries.createProduct(db, for: u, opening: stock[u.key],
                                                 note: t("pending.opening_note", ["name": u.nameVi.isEmpty ? u.rawName : u.nameVi]))
                case .skip: try Deliveries.ignoreUnknown(db, u)
                case .product(let id): try Deliveries.mapLine(db, key: u.key, productId: id, label: u.label)
                default: break
                }
            }
        }
        guard done != nil else { return }
        choices = [:]
        openings = [:]
        model.rescan(partial: true) { result in
            guard let result else { return }
            UI.info(t("pending.mapped", ["mapped": String(mapped), "created": String(created), "skipped": String(skipped),
                                         "count": String(result.imported.count)]))
        }
    }

    // ---- orders read after a stock count

    private var countBox: some View {
        box(t("pending.count_title")) {
            Hint(t("pending.count_hint")).frame(maxWidth: 1000 * UI.scale, alignment: .leading)
            HStack {
                cell(t("col.doc_code"), 90, bold: true); cell(t("col.date"), 90, bold: true)
                cell(t("col.customer"), 220, bold: true); cell(t("col.count_date"), 110, bold: true)
                cell(t("pending.actions"), 300, bold: true)
            }
            ForEach(data.conflicts, id: \.id) { c in
                HStack {
                    cell(c.code, 90); cell(dmy(c.docDate), 90); cell(c.customer, 220); cell(dmy(c.countDate), 110)
                    Button(t("btn.keep_counted")) { run("count_check") { try Deliveries.keepCounted($0, docId: c.id) } }
                    Button(t("btn.subtract_too")) { run("count_check") { try Deliveries.subtractToo($0, docId: c.id) } }
                }
            }
        }
    }

    // ---- files that need a look

    private func detail(_ f: PendingFile) -> String {
        switch f.status {
        case "missing": return t("file.missing_detail", ["code": f.docCode ?? ""])
        case "changed": return t("file.changed_detail", ["detail": f.message])
        default: return f.message
        }
    }

    private var filesBox: some View {
        box(t("pending.files_title")) {
            HStack {
                cell(t("col.status"), 150, bold: true); cell(t("col.file"), 260, bold: true)
                cell(t("pending.detail"), 360, bold: true); cell(t("pending.actions"), 300, bold: true)
            }
            ForEach(data.files, id: \.file.hash) { item in
                let f = item.file
                HStack(alignment: .top) {
                    cell(t("file.\(f.status)"), 150); cell(f.relPath, 260)
                    Text(detail(f)).frame(width: 360 * UI.scale, alignment: .leading).fixedSize(horizontal: false, vertical: true)
                    actions(f, otherOrder: item.otherOrder)
                }
            }
        }
    }

    @ViewBuilder private func actions(_ f: PendingFile, otherOrder: Bool) -> some View {
        let folders = model.folders
        HStack {
            switch f.status {
            case "changed":
                if otherOrder {  // another customer / a far date: a code that came back on another order
                    Button(t("btn.import_separate")) { if let fo = folders { run("file") { try Deliveries.importSeparately($0, fo, hash: f.hash) } } }
                }
                Button(t("btn.use_new")) { if let fo = folders { run("file") { try Deliveries.replaceChanged($0, fo, hash: f.hash) } } }
                Button(t("btn.keep_old")) { run("file") { try Deliveries.keepOld($0, hash: f.hash) } }
                openButton(f)
            case "missing":
                Button(t("btn.restore_file")) { if let fo = folders { run("file") { try Deliveries.restoreMissing($0, fo, hash: f.hash) } } }
                Button(t("btn.cancel_doc")) {
                    if UI.ask(t("doc.confirm_cancel")) { run("file") { try Deliveries.cancelMissing($0, hash: f.hash) } }
                }
                Button(t("btn.ignore")) { run("file") { try Deliveries.ignoreMissing($0, hash: f.hash) } }
            default:
                openButton(f)
                Button(t("btn.hide")) { run("file") { try Deliveries.dismissError($0, hash: f.hash) } }
            }
        }
    }

    private func openButton(_ f: PendingFile) -> some View {
        Button(t("btn.open_file")) {
            if let folders = model.folders, let url = Deliveries.notePath(folders, f.relPath),
               FileManager.default.fileExists(atPath: url.path) {
                UI.open(url)
            } else {
                UI.error(t("doc.original_missing"))
            }
        }
    }

    // ---- files of input/

    private func inboxDetail(_ item: InboxItem) -> String {
        switch item.kind {
        case .receipt:
            guard let receipt = item.receipt else { return item.message }
            return t("inbox.receipt_detail", ["date": dmy(receipt.date), "lines": String(item.resolved.count),
                                              "qty": Format.quantity(item.totalQty)])
        case .master:
            guard let m = item.master else { return item.message }
            return t("inbox.master_detail", ["products": String(m.products.count), "customers": String(m.customers.count),
                                             "stock": String(m.stock.count)])
        case .catalog:
            return t("inbox.catalog_detail", ["count": String(item.catalogCount)])
        case .package:
            guard let m = item.manifest else { return item.message }
            return t("inbox.package_detail", ["device": m.deviceName, "at": m.exportedAt.replacingOccurrences(of: "T", with: " "),
                                              "deliveries": String(m.deliveries)])
        case .error:
            return item.message
        }
    }

    private func inboxStatus(_ item: InboxItem) -> String {
        switch item.kind {
        case .receipt: return t("inbox.receipt")
        case .master: return t("inbox.master")
        case .catalog: return t("inbox.catalog")
        case .package: return t("inbox.package")
        case .error: return t("inbox.error")
        }
    }

    /// The import button of one kind of file; a used file leaves input/ only after it was imported.
    private func importButton(_ item: InboxItem) -> some View {
        Group {
            switch item.kind {
            case .receipt:
                Button(t("btn.view_import")) { UI.later { if ReceiptImport.review(model, item) { model.rescan() } } }
            case .master:
                Button(t("master.import")) { UI.later { finishImport(item, MasterDataScreen.importFile(model, item.url)) } }
            case .catalog:
                Button(t("catalog.import_btn")) { UI.later { finishImport(item, CatalogImport.importFile(model, item.url)) } }
            case .package:
                Hint(tr("Bản Mac chưa nhập được gói dữ liệu.", "The Mac app cannot import a data package yet.", "Mac 版暂时无法导入数据包。"))
            case .error:
                EmptyView()
            }
        }
    }

    private func finishImport(_ item: InboxItem, _ imported: Bool) {
        guard imported else { return }
        if let folders = model.folders { Inbox.done(folders, item.url) }  // a package is moved by its import already
        model.changed()
    }

    private var inboxBox: some View {
        box(t("pending.inbox_title")) {
            HStack {
                cell(t("col.status"), 150, bold: true); cell(t("col.file"), 260, bold: true)
                cell(t("pending.detail"), 420, bold: true); cell(t("pending.actions"), 260, bold: true)
            }
            ForEach(data.inbox, id: \.url) { item in
                HStack(alignment: .top) {
                    cell(inboxStatus(item), 150); cell(item.name, 260)
                    Text(inboxDetail(item)).frame(width: 420 * UI.scale, alignment: .leading).fixedSize(horizontal: false, vertical: true)
                    HStack {
                        if item.kind == .error {
                            // an unusable file is never moved: only hidden
                            Button(t("btn.open_file")) { UI.open(item.url) }
                            Button(t("btn.hide")) {
                                guard UI.ask(t("inbox.confirm_hide", ["name": item.name])) else { return }
                                run("inbox_hide") { try Inbox.hide($0, item) }
                            }
                        } else {
                            importButton(item)
                            Button(t("btn.discard")) {
                                guard let folders = model.folders, UI.ask(t("inbox.confirm_discard", ["name": item.name])) else { return }
                                Inbox.discard(folders, item)
                                model.changed()
                            }
                        }
                    }
                }
            }
            Button(t("receipts.open_input")) { if let f = model.inputFolder { UI.open(f) } }
        }
    }
}
