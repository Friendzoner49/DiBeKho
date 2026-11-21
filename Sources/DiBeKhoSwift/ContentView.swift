import AppKit
import DiBeKhoCore
import GRDB
import SwiftUI

/// The main window as ui/main_window.py: the navigation list on the left (Tồn kho · Cần xử lý · Tra cứu · Hàng về ·
/// Kiểm kê · Cài đặt), the shared buttons on top (Quét lại phiếu, Mở thư mục phiếu giao hàng, Phiếu xuất kho…),
/// the page under them.
struct ContentView: View {
    @StateObject private var model = AppModel()
    @StateObject private var currency = CurrencyModel()

    var body: some View {
        Group {
            switch model.stage {
            case .ready: main
            case .firstRun: FirstRunSheet(model: model).frame(maxWidth: .infinity, maxHeight: .infinity)
            case .login(let problem): LoginScreen(model: model, problem: problem).id(problem)
            case .starting: StartingScreen()
            }
        }
        .font(.system(size: UI.baseSize))
        .buttonStyle(AppButtonStyle())
        .frame(minWidth: 900, idealWidth: 1280 * UI.scale, minHeight: 600, idealHeight: 800 * UI.scale)
        .onAppear {
            NSApplication.shared.setActivationPolicy(.regular)
            NSApplication.shared.activate(ignoringOtherApps: true)
            currency.changed = { [model] in model.changed() }
            Updater.checkOnStart()
        }
    }

    private var main: some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                ForEach(AppModel.Page.allCases) { page in
                    Button { model.page = page } label: {
                        Text(t(page.key) + (page == .pending && model.pendingTotal > 0 ? "  (\(model.pendingTotal))" : ""))
                            .font(.system(size: UI.baseSize + 1))
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.vertical, 7 * UI.scale)
                            .padding(.horizontal, 10)
                            .background(RoundedRectangle(cornerRadius: 6)
                                .fill(model.page == page ? Color.primary.opacity(0.14) : Color.clear))
                            .foregroundColor(page == .pending && model.pendingTotal > 0 ? .red : .primary)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
                Spacer()
                CurrencySwitch(currency: currency).padding(.bottom, 4)
            }
            .padding(6)
            .frame(width: 200)
            .background(SoftRect().fill(Color(nsColor: .controlBackgroundColor)))

            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    Button(t("main.rescan")) { model.rescan(); currency.refreshIfShown() }
                        .help("F5")
                        .keyboardShortcut(KeyEquivalent(Character(UnicodeScalar(NSF5FunctionKey)!)), modifiers: [])
                        .disabled(model.scanning)
                    Button(t("main.open_deliveries")) {
                        if let folder = model.notesFolder { UI.open(folder) }
                    }
                    Button(t("issue.button")) { IssueForm.open(model) }
                    // ⌘F: go to Tra cứu and type (ui/main_window.py, Ctrl+F)
                    Button("") { model.page = .search; model.searchFocus += 1 }
                        .keyboardShortcut("f", modifiers: .command)
                        .opacity(0).frame(width: 0, height: 0).accessibilityHidden(true)
                    // «Lần quét gần nhất…» beside the buttons (main_window.py: top.addWidget(self.status, 1))
                    Text(model.status).lineLimit(1).truncationMode(.tail).frame(maxWidth: .infinity, alignment: .leading)
                    CloudStatusBadge(model: model, cloud: model.cloud)
                }
                if let error = model.errorText {
                    Text(error).foregroundColor(.red)
                }
                page
            }
        }
        .padding(10)
        .groupBoxStyle(SoftGroupBoxStyle())
    }

    @ViewBuilder private var page: some View {
        switch model.page {
        case .stock: StockPage(model: model)
        case .pending: PendingPage(model: model)
        case .search: SearchPage(model: model)
        case .receipts: ReceiptPage(model: model)
        case .count: CountPage(model: model)
        case .settings: SettingsPage(model: model)
        }
    }
}

/// The Cloud line at the top right (ui/main_window.py): what the sync says; a click asks for the password again when the
/// session ended, opens the conflicts when there are some, else syncs now (CloudScreens.statusClicked).
struct CloudStatusBadge: View {
    @ObservedObject var model: AppModel
    @ObservedObject var cloud: CloudRunner

    var body: some View {
        let text = cloud.statusText.isEmpty ? tr("Cloud: chưa đăng nhập", "Cloud: not signed in", "Cloud：未登录") : cloud.statusText
        Button { CloudScreens.statusClicked(model) } label: {
            Text(text).font(.system(size: UI.baseSize))
                .padding(.horizontal, 10).padding(.vertical, 5)
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.primary.opacity(0.25)))
        }
        .buttonStyle(.plain)
    }
}

// ---- Tồn kho (ui/stock_page.py)

struct StockPage: View {
    @ObservedObject var model: AppModel
    @State private var category = ""
    @State private var onlyLow = false

    var body: some View {
        let level = model.lowLevel
        let needle = model.filter.trimmingCharacters(in: .whitespaces)
        let rows = model.stock.filter { r in
            (category.isEmpty || r.category == category)
                && (needle.isEmpty || TextRules.matchesWords(needle, r.haystack))
                && (!onlyLow || r.stock < 0 || StockQueries.isLow(r.stock, level))
        }
        let low = rows.filter { $0.stock >= 0 && StockQueries.isLow($0.stock, level) }.count
        let negative = rows.filter { $0.stock < 0 }.count
        let categories = Array(Set(model.stock.map(\.category).filter { !$0.isEmpty })).sorted()
        return VStack(alignment: .leading, spacing: 6) {
            PageHeader(title: t("nav.stock"), hint: t("stock.hint"))
            HStack {
                TextField(t("stock.filter"), text: $model.filter).textFieldStyle(.roundedBorder)
                Text(t("col.category") + ":")
                Picker("", selection: $category) {
                    Text(t("filter.all")).tag("")
                    ForEach(categories, id: \.self) { Text($0).tag($0) }
                }
                .labelsHidden()
                .frame(width: 180 * UI.scale)
                Toggle(t("stock.only_low"), isOn: $onlyLow)
            }
            if model.queue != nil && model.stock.isEmpty {
                Text(t("stock.empty_hint")).padding(8).frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 6).fill(UI.banner))
            }
            if low > 0 {
                Text(t("stock.alarm_banner", ["count": String(low), "level": Format.quantity(level)]))
                    .bold().foregroundColor(UI.warn).padding(6).frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 6).fill(Color(nsColor: UI.orange)))
            }
            Text(t("stock.summary", ["count": String(rows.count), "low": String(low), "negative": String(negative)]))
            DataTable(
                // capped as stock_page: real (long) names don't push Tồn out of sight; the note column always 160
                columns: [Column(title: t("col.code"), width: 70), Column(title: t("col.product"), width: 180, cap: 180),
                          Column(title: t("col.name_zh"), width: 150, cap: 150), Column(title: t("col.spec"), width: 100, cap: 100),
                          Column(title: t("col.variant"), width: 90, cap: 90), Column(title: t("col.category"), width: 110, cap: 110),
                          Column(title: t("col.unit"), width: 60, cap: 60), Column(title: t("col.stock"), width: 80, numeric: true, bold: true),
                          Column(title: t("col.stock_note"), width: 160, editable: true, fixed: true),
                          Column(title: t("loc.main"), width: 80, numeric: true),
                          Column(title: t("loc.office"), width: 80, numeric: true),
                          Column(title: t("col.last_out"), width: 100)],
                rows: rows.map { r in
                    [r.code, r.nameVi, r.nameZh, r.spec, r.variant, r.category, r.unit, Format.quantity(r.stock),
                     r.stockNote, Format.quantity(r.stockMain), Format.quantity(r.stockOffice), Format.date(r.lastOut)]
                },
                tones: rows.map { r in r.stock < 0 ? .negative : StockQueries.isLow(r.stock, level) ? .low : .normal },
                onOpen: { model.openProduct(rows[$0].id) },
                onEdit: { row, _, text in
                    let id = rows[row].id
                    model.write("stock_note") { try Catalog.saveStockNote($0, productId: id, text: text) }
                },
                fitWidth: false)
        }
    }
}

// ---- Tra cứu (ui/search_page.py)

struct SearchPage: View {
    @ObservedObject var model: AppModel
    @FocusState private var searchFocused: Bool
    /// 0 Tra cứu, 1 Danh mục mặt hàng (moved here from Cài đặt so the list gets the whole page: the owner, 21/11/2026)
    @State private var tab = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            PageHeader(title: t("nav.search"), hint: tab == 0 ? t("search.hint") : t("settings.products_hint"))
            TabBar(titles: [t("nav.search"), t("settings.products")], selection: $tab)
            if tab == 0 {
                lookup
            } else {
                CatalogPage(model: model, showsHint: false)
            }
        }
        .onChange(of: model.searchFocus) { _ in tab = 0 }  // ⌘F: back to the search box
    }

    @ViewBuilder private var lookup: some View {
            let found = model.found
            TextField(t("search.placeholder"), text: $model.searchText)
                .textFieldStyle(.roundedBorder)
                .font(.system(size: UI.baseSize + 3))
                .focused($searchFocused)
                .onAppear { searchFocused = true }
                .onChange(of: model.searchFocus) { _ in searchFocused = true }
                .overlay(alignment: .trailing) {
                    // the round ✕ of the Python box (setClearButtonEnabled)
                    if !model.searchText.isEmpty {
                        Button { model.searchText = "" } label: {
                            Image(systemName: "xmark.circle.fill").foregroundColor(.secondary)
                        }
                        .buttonStyle(.plain)
                        .padding(.trailing, 6)
                    }
                }
            HStack {
                Text(t("search.more"))
                Button(t("search.orders_btn")) { Screens.orders(model) }
                Button(t("search.customers_btn")) { Screens.customers(model) }
                Button(t("search.stats_btn")) { Screens.stats(model) }
                Spacer()
            }
            // three boxes in a splitter that fills the page (search_page.py: QSplitter(Qt.Vertical))
            VSplitView {
                productsBox(found)
                customersBox(found)
                documentsBox(found)
            }
    }

    private func productsBox(_ found: Lookup.Found) -> some View {
            GroupBox(t("search.products", ["count": String(found.products.count)])) {
                DataTable(
                    columns: [Column(title: t("col.code"), width: 70), Column(title: t("col.product"), width: 260),
                              Column(title: t("col.name_zh"), width: 140), Column(title: t("col.spec"), width: 110),
                              Column(title: t("col.variant"), width: 90), Column(title: t("col.stock"), width: 80, numeric: true),
                              Column(title: t("col.unit"), width: 60)],
                    rows: found.products.map { p in
                        [Details.text(p, "code"), Details.text(p, "name_vi"), Details.text(p, "name_zh"), Details.text(p, "spec"),
                         Details.text(p, "variant"), Format.quantity(Details.number(p, "stock")), Details.text(p, "unit")]
                    },
                    onOpen: { i in model.openProduct(found.products[i]["id"]) })
            }
            .frame(minHeight: 90)  // 3 boxes + the tab bar still fit a small window (CI 1024×768)
    }

    private func customersBox(_ found: Lookup.Found) -> some View {
            GroupBox(t("search.customers", ["count": String(found.customers.count)])) {
                DataTable(
                    columns: [Column(title: t("col.customer"), width: 260), Column(title: t("col.contact"), width: 140),
                              Column(title: t("col.phone"), width: 120), Column(title: t("col.address"), width: 300),
                              Column(title: t("col.tax_code"), width: 110), Column(title: t("col.email"), width: 170)],
                    rows: found.customers.map { c in
                        [Details.text(c, "name"), Details.text(c, "contact"), Details.text(c, "phone"), Details.text(c, "address"),
                         Details.text(c, "tax_code"), Details.text(c, "email")]
                    },
                    onOpen: { i in model.openCustomer(found.customers[i]["id"]) },
                    stretch: 3)
            }
            .frame(minHeight: 90)  // 3 boxes + the tab bar still fit a small window (CI 1024×768)
    }

    private func documentsBox(_ found: Lookup.Found) -> some View {
            GroupBox(t("search.documents", ["count": String(found.documents.count)])) {
                DataTable(
                    columns: [Column(title: t("col.date"), width: 90), Column(title: t("orders.kind"), width: 130),
                              Column(title: t("col.doc_code"), width: 80), Column(title: t("col.customer"), width: 240),
                              Column(title: t("col.status"), width: 110), Column(title: t("col.file"), width: 200)],
                    rows: found.documents.map { d in
                        [Format.date(Details.text(d, "doc_date")), t("kind.\(Details.text(d, "kind"))"), Details.text(d, "code"),
                         Details.text(d, "customer_name"), t("status.\(Details.text(d, "status"))"), Details.text(d, "source_file")]
                    },
                    onOpen: { i in model.openOrder(found.documents[i]["id"]) },
                    stretch: 3)
            }
            .frame(minHeight: 90)  // 3 boxes + the tab bar still fit a small window (CI 1024×768)
    }
}

// ---- Hàng về (ui/receipt_page.py)

struct ReceiptPage: View {
    @ObservedObject var model: AppModel
    @State private var selected: Int?

    static func sourceText(_ d: Row) -> String {
        let source = Details.text(d, "receipt_source")
        return source.isEmpty ? "" : t("receipt_form.source_short_\(source)")
    }

    static func fromText(_ d: Row) -> String {
        if Details.text(d, "receipt_source") == "return" {
            let ref = Details.text(d, "ref_code")
            return [Details.text(d, "customer_name"), ref.isEmpty ? "" : t("receipt_form.order") + " " + ref]
                .filter { !$0.isEmpty }.joined(separator: " · ")
        }
        return Details.text(d, "supplier_name")
    }

    var body: some View {
        let docs = model.read { try OrderQueries.documents($0, kind: "receipt") } ?? []
        _ = model.version
        return VStack(alignment: .leading, spacing: 8) {
            PageHeader(title: t("nav.receipts"), hint: t("receipts.steps"))
            HStack {
                Button { ReceiptForm.open(model) } label: {
                    Text(t("receipts.new")).font(.system(size: UI.baseSize + 2, weight: .bold))
                        .frame(minHeight: 40 * UI.scale).padding(.horizontal, 10)
                }
                Spacer()
            }
            HStack {
                Button(t("receipts.pick_file")) { ReceiptImport.pickFile(model) }.help(t("receipts.pick_file_tip"))
                Button(t("receipts.open_input")) { if let f = model.inputFolder { UI.open(f) } }
                Button(t("receipts.check_input")) { model.page = .pending }
                Spacer()
            }
            HStack {
                Text(t("receipts.history"))
                Spacer()
                Button(t("receipts.edit_selected")) {
                    guard let i = selected, i < docs.count else { return UI.error(t("receipts.select_first")) }
                    if Details.text(docs[i], "status") != "active" { return UI.error(t("receipts.not_active")) }
                    ReceiptForm.open(model, docId: docs[i]["id"])
                }
            }
            DataTable(
                columns: [Column(title: t("col.doc_code"), width: 80), Column(title: t("col.date"), width: 90),
                          Column(title: t("receipt_form.source"), width: 170), Column(title: t("receipt_form.from"), width: 260),
                          Column(title: t("col.lines"), width: 60, numeric: true),
                          Column(title: t("col.total_qty"), width: 100, numeric: true),
                          Column(title: t("col.note"), width: 200), Column(title: t("col.status"), width: 110)],
                rows: docs.map { d in
                    [Details.text(d, "code"), Format.date(Details.text(d, "doc_date")), Self.sourceText(d), Self.fromText(d),
                     String((d["line_count"] as Int?) ?? 0), Format.quantity(Details.number(d, "total_qty")),
                     Details.text(d, "note"), t("status.\(Details.text(d, "status"))")]
                },
                onOpen: { i in model.openOrder(docs[i]["id"]) },
                onSelect: { selected = $0 })
        }
    }
}

// ---- Cài đặt (ui/settings_page.py): for now where the data is opened (phase 5 brings the rest)

struct SettingsPage: View {
    @ObservedObject var model: AppModel

    // DIBEKHO_SETTINGS_TAB: the tab shown first, for the screenshots of the build workflow
    @State private var tab = Int(ProcessInfo.processInfo.environment["DIBEKHO_SETTINGS_TAB"] ?? "") ?? 0

    /// Four tabs as in the Python app: Chung, Mặt hàng, Chuyển dữ liệu, Cloud
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            PageHeader(title: t("nav.settings"))
            TabBar(titles: [t("settings.tab_general"), t("settings.learned_title"), t("settings.tab_transfer"),
                            t("settings.tab_cloud")], selection: $tab)
            switch tab {
            case 0: tabPage { general }
            case 1: productsTab.padding(8)
            case 2: tabPage { transferTab }
            default: tabPage { cloudTab }
            }
        }
    }

    private func tabPage<C: View>(@ViewBuilder _ content: () -> C) -> some View {
        ScrollView { VStack(alignment: .leading, spacing: 10) { content() }.padding(8) }
    }

    @ViewBuilder private var general: some View {
        GeneralBox(model: model)
        UninstallBox()
    }

    @ViewBuilder private var cloudTab: some View {
        CloudBox(model: model)
    }

    /// The learned names fill the tab; the product list moved to Tra cứu → Danh mục mặt hàng (the owner, 21/11/2026:
    /// in a box here it showed two rows only)
    private var productsTab: some View {
        GroupBox(t("settings.learned_title")) { LearnedPage(model: model).padding(6) }
            .frame(maxHeight: .infinity)
    }

    /// the three boxes of the Python tab, then where the data of this Mac is
    @ViewBuilder private var transferTab: some View {
            TransferTab(model: model)
            GroupBox(tr("Dữ liệu đang dùng", "Live data", "正在使用的数据")) {
                VStack(alignment: .leading, spacing: 8) {
                    Hint(tr("Thư mục làm việc của DiBeKho trên máy này. Mỗi ngày mở app có một bản sao lưu trong sao-luu/. Dữ liệu luôn đồng bộ với Cloud.", "The DiBeKho work folder on this computer. A backup is made in sao-luu/ the first time the app opens each day. The data is always synced with the Cloud.", "本机上的 DiBeKho 工作文件夹。每天首次打开应用时会在 sao-luu/ 中生成一份备份。数据始终与 Cloud 同步。"))
                    if let root = WorkFolder.configured {
                        Text(root.path).font(.caption).foregroundColor(.secondary)
                    }
                    HStack {
                        if let folder = model.workFolder {
                            Button(tr("Mở thư mục làm việc", "Open the work folder", "打开工作文件夹")) { UI.open(folder.root) }
                            Button(tr("Mở thư mục sao lưu", "Open the backup folder", "打开备份文件夹")) { UI.open(folder.backups) }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(6)
            }
    }
}

/// A detail window as ui/details.py: the title (a customer's has 'Sửa thông tin khách hàng…' beside it), the
/// label/value pairs, a customer's date filter with Xuất Excel…, the tables (boxed for a customer or a product), the
/// lines under them, a document's buttons (Mở file gốc, Đọc lại cả phiếu, Sửa…, Huỷ phiếu) and Đóng at the bottom right.
struct DetailView: View {
    let data: DetailData
    @ObservedObject var model: AppModel
    @EnvironmentObject var box: WindowBox
    @State private var place: Int64 = Ledger.main
    /// customer window's date filter (ui/details.CustomerDialog): everything or from–to; `filtered` replaces `data` while on
    @State private var allTime = true
    @State private var from = Dates.iso(Calendar.current.date(from: DateComponents(year: Calendar.current.component(.year, from: Date()), month: 1, day: 1)) ?? Date())
    @State private var to = Dates.today
    @State private var filtered: DetailData?

    private var shown: DetailData { filtered ?? data }
    private var range: (start: String?, end: String?) { allTime ? (nil, nil) : (from, to) }

    /// Read the customer again for the chosen period
    private func reload() {
        guard let cid = data.customerId else { return }
        let r = range
        if let got = model.read({ try Details.customer($0, id: cid, start: r.start, end: r.end) }), let d = got { filtered = d }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            titleRow
            infoGrid
            ForEach(Array(shown.infoHints.enumerated()), id: \.offset) { _, hint in Hint(hint) }
            filterBar
            tablesView
            ForEach(Array(shown.footer.enumerated()), id: \.offset) { _, line in
                if line.1 { Hint(line.0) } else { RichText(text: line.0) }
            }
            if data.docId != nil { documentButtons }
            HStack {
                Spacer()
                Button(t("btn.close")) { box.close() }.keyboardShortcut(.cancelAction)
            }
        }
        .onAppear { place = data.docLocation ?? Ledger.main }
    }

    private var titleRow: some View {
        HStack {
            Text(data.title).font(.system(size: UI.baseSize + 5, weight: .bold))
            Spacer()
            if let cid = data.customerId, model.writable {
                Button(t("cust.edit_button")) {
                    if Forms.editCustomer(model, id: cid) {
                        box.close()
                        model.openCustomer(cid)
                    }
                }
                .help(t("cust.edit_tip"))
            }
        }
    }

    private var infoGrid: some View {
        Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 4) {
            ForEach(Array(shown.info.enumerated()), id: \.offset) { i, pair in
                GridRow {
                    Text(pair.0 + ":")
                    infoValue(i, pair.1)
                }
            }
        }
    }

    @ViewBuilder private func infoValue(_ i: Int, _ value: String) -> some View {
        if value == DetailData.placeMarker {
            placePicker
        } else if let link = shown.customerLink, link.row == i {
            Button { model.openCustomer(link.id) } label: { Text(value).underline().foregroundColor(.accentColor) }
                .buttonStyle(.plain)
        } else {
            switch shown.emphasis[i] {
            case .alert: Text(value).bold().foregroundColor(.red)
            case .big: Text(value).font(.system(size: UI.baseSize + 3, weight: .bold))
            case .warn: Text(value).bold().foregroundColor(UI.warn).textSelection(.enabled)
            case nil: RichText(text: value.isEmpty ? "—" : value).textSelection(.enabled)
            }
        }
    }

    /// Lấy hàng từ: the place the goods of a delivery note were taken from (details.change_location)
    private var placePicker: some View {
        HStack {
            Picker("", selection: Binding(get: { place }, set: { changePlace($0) })) {
                ForEach(Ledger.locations, id: \.self) { Text(UI.locationName($0)).tag($0) }
            }
            .labelsHidden()
            .frame(width: 200 * UI.scale)
            .disabled(data.docStatus != "active" || !model.writable)
            Hint(t(!data.docLocationSet && data.docStatus == "active" ? "doc.location_unset" : "doc.location_change_hint"))
                .frame(maxWidth: 420 * UI.scale, alignment: .leading)
        }
    }

    @ViewBuilder private var filterBar: some View {
        if let cid = data.customerId {
            HStack {
                Toggle(t("filter.all_time"), isOn: $allTime).onChange(of: allTime) { _ in reload() }
                Text(t("filter.from"))
                DateBox(iso: $from).disabled(allTime).onChange(of: from) { _ in if !allTime { reload() } }
                Text(t("filter.to"))
                DateBox(iso: $to).disabled(allTime).onChange(of: to) { _ in if !allTime { reload() } }
                Spacer()
                Button(t("cust.export")) { CustomerExport.run(model, id: cid, start: range.start, end: range.end) }
                    .help(t("cust.export_tip"))
            }
        }
    }

    private var tablesView: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(shown.tables.enumerated()), id: \.offset) { _, table in
                if table.boxed {
                    GroupBox(table.title) { tableView(table) }
                } else {
                    if !table.title.isEmpty { Text(table.title).bold() }
                    tableView(table)
                }
            }
        }
    }

    private func tableView(_ table: DetailData.Table) -> some View {
        DataTable(columns: table.columns, rows: table.rows, tones: table.tones,
                  onOpen: { i in open(table, i) },
                  sortable: table.sortable, stretch: table.stretch)
            .frame(minHeight: 120, maxHeight: .infinity)
    }

    /// A double click: the product of a line, the document of a movement or an order, the customer
    private func open(_ table: DetailData.Table, _ row: Int) {
        guard row < table.ids.count, let id = table.ids[row] else { return }
        switch table.opens {
        case .product: model.openProduct(id)
        case .document: model.openOrder(id)
        case .customer: model.openCustomer(id)
        case .none: break
        }
    }

    /// The buttons of a document (DocumentDialog), in the Python order
    private var documentButtons: some View {
        HStack {
            if let id = data.docId, data.docKind == "delivery", !data.sourceHash.isEmpty {
                Button(t("btn.open_original")) { openOriginal() }
                if data.docStatus == "active", model.writable {
                    Button(t("btn.reread_doc")) { reread(id) }.help(t("doc.reread_tip"))
                }
            }
            if data.docKind == "receipt", let folders = model.folders,
               let file = Receipts.exportedFile(folders, name: data.sourceFile) {
                Button(t("receipt_form.open_file")) { UI.open(file) }
            }
            if let id = data.docId, data.docStatus == "active", model.writable {
                if data.docKind == "receipt" {
                    Button(t("receipts.edit")) {
                        box.close()
                        ReceiptForm.open(model, docId: id)
                    }
                    .help(t("receipts.edit_tip"))
                }
                if data.docKind == "transfer" {
                    Button(t("transfer.edit")) {
                        box.close()
                        Forms.transfer(model, docId: id)
                    }
                    .help(t("transfer.edit_tip"))
                }
                if Issues.canEdit(kind: data.docKind, status: data.docStatus, code: data.docCode) {
                    Button(t("issue.edit_btn")) {
                        box.close()
                        IssueForm.open(model, docId: id)
                    }
                    .help(t("issue.edit_tip"))
                }
                Button(t("btn.cancel_doc")) { cancel(id) }
            }
            Spacer()
        }
    }

    private func cancel(_ id: Int64) {
        guard UI.ask(t("doc.confirm_cancel")) else { return }
        let delivery = data.docKind == "delivery"
        // a stock issue note may be deleted entirely: a wrong note leaves no hole in the shop's numbers
        if delivery, Issues.isIssueCode(data.docCode), let folders = model.folders,
           UI.ask(t("doc.ask_delete_issue", ["code": data.docCode])) {
            if model.write("delete_issue", { try Issues.delete($0, folders, docId: id) }) != nil { box.close() }
            return
        }
        let done = model.write("cancel_doc") { db -> Bool in
            try Ledger.close(db, docId: id)
            if delivery {
                // the file stays in the folder; don't warn about it later
                try db.execute(sql: "UPDATE scanned_files SET status = 'imported' WHERE document_id = ? AND status = 'missing'",
                               arguments: [id])
            }
            return true
        }
        if done != nil { box.close() }
    }

    private func changePlace(_ new: Int64) {
        guard let id = data.docId, new != place else { return }
        if model.write("places", { try Ledger.setLocation($0, docId: id, locationId: new) }) != nil { place = new }
    }

    /// Mở file gốc: a read-only copy of the stored original in the temp folder, never the stored file itself
    /// A copy this Mac lacks (signed in for the first time, or the app was removed) is downloaded from the cloud first.
    private func openOriginal() {
        guard let folders = model.folders else { return UI.error(t("doc.original_missing")) }
        let hash = data.sourceHash, name = data.sourceFile
        if let copy = Deliveries.viewingCopy(folders, hash: hash, name: name) { return UI.open(copy) }
        Task { @MainActor in
            let fetched = await model.cloud.fetchOriginal(hash: hash)
            if fetched == true, let copy = Deliveries.viewingCopy(folders, hash: hash, name: name) { return UI.open(copy) }
            UI.error(t(fetched == false ? "doc.original_not_fetched" : "doc.original_missing"))
        }
    }

    /// Đọc lại cả phiếu (common.reread_whole_note)
    private func reread(_ id: Int64) {
        LearnedScreen.rereadOrder(model, docId: id) { box.close() }
    }
}

/// A line of text where <b>…</b> parts are bold (the Python labels are rich text).
struct RichText: View {
    let text: String

    var body: some View {
        var result = Text("")
        var rest = Substring(text)
        while let open = rest.range(of: "<b>") {
            result = result + Text(String(rest[..<open.lowerBound]))
            rest = rest[open.upperBound...]
            if let close = rest.range(of: "</b>") {
                result = result + Text(String(rest[..<close.lowerBound])).bold()
                rest = rest[close.upperBound...]
            } else {
                result = result + Text(String(rest)).bold()
                rest = ""
            }
        }
        return result + Text(String(rest))
    }
}
