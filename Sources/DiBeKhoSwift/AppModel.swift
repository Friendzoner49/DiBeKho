import AppKit
import DiBeKhoCore
import Foundation
import GRDB

/// The app's state. Phase 3 writes only to the practice folder (DiBeKhoCore.Practice, BẢN THỬ): the shop's real data
/// and the cloud never change until the Swift app can sync (phase 4). A kho.sqlite chosen by hand is opened as a
/// read-only copy, as in phases 0-2.
@MainActor
final class AppModel: ObservableObject {
    /// The navigation list of the Python app, in its order (ui/main_window.py).
    enum Page: String, CaseIterable, Identifiable {
        case stock, pending, search, receipts, count, settings
        var id: String { rawValue }
        var key: String {
            switch self {
            case .stock: return "nav.stock"
            case .pending: return "nav.pending"
            case .search: return "nav.search"
            case .receipts: return "nav.receipts"
            case .count: return "nav.count"
            case .settings: return "nav.settings"
            }
        }
    }

    /// stats_page.PERIODS: a day, a month, a quarter, a year or a range of days chosen
    enum PeriodKind: String, CaseIterable, Identifiable {
        case day, month, quarter, year, range
        var id: String { rawValue }
        var label: String { t("period.\(rawValue)") }
    }

    @Published var page: Page = .stock { didSet { ActivityLog.write("page", t(page.key)) } }
    @Published var filter = ""
    /// Raised by ⌘F: the Tra cứu page takes the keyboard focus.
    @Published var searchFocus = 0
    @Published var customerFilter = "" { didSet { reloadCustomers() } }
    @Published var searchText = "" { didSet { reloadSearch() } }
    @Published var periodKind: PeriodKind = .month { didSet { reloadStats() } }
    @Published var year: Int { didSet { reloadStats() } }
    @Published var month: Int { didSet { reloadStats() } }
    @Published var quarter: Int { didSet { reloadStats() } }
    @Published var statsDay = Dates.today { didSet { reloadStats() } }
    @Published var rangeFrom = Dates.iso(Calendar.current.date(byAdding: .day, value: -30, to: Date()) ?? Date()) { didSet { reloadStats() } }
    @Published var rangeTo = Dates.today { didSet { reloadStats() } }
    /// Thống kê: Mặt hàng / Nhóm hàng / Khách hàng (nothing chosen = all) and «Chia theo» (none, day, month)
    @Published var statsFilters = Stats.Filters() { didSet { reloadStats() } }
    @Published var statsSplit = "none" { didSet { reloadStats() } }

    @Published private(set) var stock: [StockRow] = []
    @Published private(set) var customers: [Row] = []
    @Published private(set) var found = Lookup.Found()
    @Published private(set) var summary: [Stats.SummaryRow] = []
    @Published private(set) var money: Stats.Money?
    /// the outgoing quantity of each day of the period (the chart)
    @Published private(set) var daily: [(day: String, qty: Double)] = []
    @Published private(set) var lowLevel: Double = 30
    @Published private(set) var source: String = ""
    /// true while the practice folder is open (writing allowed, only into the copy)
    @Published private(set) var practice = false
    /// the shop's own work folder (config.json of the Python app), written for real, with the shared lock
    @Published private(set) var workFolder: WorkFolder?
    var live: Bool { workFolder != nil }
    var writable: Bool { practice || live }
    var outputFolder: URL? { workFolder?.output ?? (practice ? Practice.output : nil) }
    var inputFolder: URL? { workFolder?.input ?? (practice ? Practice.input : nil) }
    /// the folders the delivery notes are scanned in (the open work folder or the practice folder; nil when the data is
    /// a read-only copy: nothing is read from or moved in a folder then)
    var folders: ShopFolders? {
        if let workFolder { return ShopFolders(root: workFolder.root) }
        return practice ? ShopFolders(root: Practice.folder) : nil
    }
    /// true while the delivery notes folder is being scanned
    @Published private(set) var scanning = false
    /// the line under the pages: the last scan and what waits ("Lần quét gần nhất: 2 phiếu mới · 3 việc cần xử lý")
    @Published private(set) var status = ""
    /// what waits in "Cần xử lý": files, orders without a place, orders read after a count, files in input/
    @Published private(set) var pendingTotal = 0
    private var lastScan: ScanResult?
    private var queued: QueuedScan?
    /// the build workflow's screenshots must not scan (they show the made-up shop as it is)
    private var autoScan = true
    /// changes after every write: the pages read again
    @Published private(set) var version = 0
    @Published var errorText: String?
    /// A Mac with no config.json and no practice copy: the first-start box asks for a language and a folder
    @Published var firstRun = false
    @Published private(set) var noteResults: [NoteResult] = []
    /// Hàng về: a new receipt closed without saving is kept for the next '＋ Nhập hàng về…'
    var receiptDraft: Receipts.Input?

    struct NoteResult {
        let file: URL
        let note: DeliveryNote?
        let error: String?
    }

    private(set) var queue: DatabaseQueue?

    let liveDatabase = Workspace.liveDatabase()
    /// Background sync with the Cloud: off until the user signs in; never on the practice copy
    let cloud = CloudRunner()

    init() {
        let today = Calendar(identifier: .gregorian).dateComponents([.year, .month], from: Date())
        year = today.year ?? 2026
        month = today.month ?? 1
        quarter = ((today.month ?? 1) - 1) / 3 + 1
        // Vietnamese unless Cài đặt → Chung chose another language. ⚠ Some texts of the Swift app (detail windows, the
        // practice banner, parts of Cài đặt) are not in i18n and stay Vietnamese in en and zh.
        L10n.language = GeneralSettings.savedLanguage()
        NotificationCenter.default.addObserver(forName: NSApplication.willTerminateNotification, object: nil,
                                               queue: .main) { [weak self] _ in
            Store.removeCopies()
            MainActor.assumeIsolated { self?.closeWorkFolder() }  // the shared lock goes with the app
        }
        let env = ProcessInfo.processInfo.environment
        if let path = env["DIBEKHO_OPEN"] {
            // the build workflow's screenshots: a made-up shop as the practice folder, a page, a window
            autoScan = false
            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                self.makePractice(from: URL(fileURLWithPath: path), ask: false)
                if let name = env["DIBEKHO_PAGE"], let page = Page(rawValue: name) { self.page = page }
                if let notes = env["DIBEKHO_NOTES"] { self.readNotes([URL(fileURLWithPath: notes)]) }
                if let folder = env["DIBEKHO_SCAN_NOTES"], !folder.isEmpty, let to = self.folders?.deliveries {
                    // a few made-up notes dropped into the practice folder, then read: "Cần xử lý" has something to show
                    for name in ["n202", "n203", "n76", "n77", "n155"] {
                        try? FileManager.default.copyItem(at: URL(fileURLWithPath: folder).appendingPathComponent("\(name).xlsx"),
                                                          to: to.appendingPathComponent("\(name).xlsx"))
                    }
                    // and two goods-receipt files typed by hand in input/ (one usable, one with a code the shop does not have)
                    if let input = self.folders?.input {
                        try? FileManager.default.createDirectory(at: input, withIntermediateDirectories: true)
                        let files = URL(fileURLWithPath: folder).deletingLastPathComponent().appendingPathComponent("InboxFiles")
                        for name in ["hangve-dien", "hangve-ma-la"] {
                            try? FileManager.default.copyItem(at: files.appendingPathComponent("\(name).xlsx"),
                                                              to: input.appendingPathComponent("\(name).xlsx"))
                        }
                    }
                    self.rescan()
                }
                if let window = env["DIBEKHO_WINDOW"] { Screens.open(window, self) }
            }
        } else if WorkFolder.configured != nil {
            DispatchQueue.main.async { [weak self] in self?.openLive() }
        } else if Practice.exists {
            DispatchQueue.main.async { [weak self] in self?.openPractice() }
        } else {
            firstRun = FirstRun.needed
        }
    }

    // ---- opening

    /// The shop's own data (the Python app's work folder), written for real; refused while the Python app is open.
    func openLive() {
        guard let root = WorkFolder.configured else { return UI.error(Texts.noLive) }
        closeWorkFolder()
        do {
            let folder = try WorkFolder(root: root)
            workFolder = folder
            queue = folder.queue
            practice = false
            source = root.path
            errorText = nil
            ActivityLog.write("start", "DiBeKho Swift · \(ProcessInfo.processInfo.operatingSystemVersionString)")
            cloud.model = self
            if autoScan && CloudRunner.allowed { cloud.start() }
            changed()
            if autoScan {  // as the Python app does when it opens, once the user has agreed to it
                askToScanOnce()
                rescan(quiet: true)
            }
        } catch {
            queue = nil
            report(error)
            UI.error(UI.message(error))
        }
    }

    func closeWorkFolder() {
        guard let folder = workFolder else { return }
        cloud.stop()
        if queue === folder.queue { queue = nil }
        folder.close()
        workFolder = nil
    }

    func makePractice(from url: URL, ask: Bool = true) {
        if ask && Practice.exists && !UI.ask(Texts.remakePractice) { return }
        closeWorkFolder()
        do {
            queue = nil
            try Practice.make(from: url)
            openPractice()
        } catch {
            report(error)
        }
    }

    func makePracticeFromLive() {
        if let liveDatabase { makePractice(from: liveDatabase) }
    }

    func choosePracticeSource() {
        let panel = NSOpenPanel()
        panel.title = Texts.chooseSource
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        if panel.runModal() == .OK, let url = panel.url { makePractice(from: url) }
    }

    func openPractice() {
        closeWorkFolder()
        do {
            let opened = try Practice.open()
            queue = opened
            practice = true
            source = Practice.origin
            errorText = nil
            ActivityLog.write("start", "DiBeKho Swift (bản thử)")
            changed()
            if autoScan { rescan(quiet: true) }
        } catch {
            report(error)
        }
    }

    /// A kho.sqlite looked at without writing (phases 0-2): a private copy, removed on quit.
    func openReadOnly() {
        let panel = NSOpenPanel()
        panel.title = Texts.chooseReadOnly
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        closeWorkFolder()
        do {
            let opened = try Store.openCopy(of: url)
            queue = opened.queue
            practice = false
            source = url.path
            errorText = nil
            ActivityLog.file = nil
            changed()
        } catch {
            report(error)
        }
    }

    // ---- reading and writing

    func read<T>(_ work: (Database) throws -> T) -> T? {
        guard let queue else { return nil }
        do {
            return try queue.read(work)
        } catch {
            report(error)
            return nil
        }
    }

    /// One write transaction on the practice folder; the user sees the Python app's message if it is refused.
    /// `failed`: the screen's own message around the reason (issue.failed: "Không lưu được phiếu xuất kho…{error}").
    @discardableResult
    func write<T>(_ action: String, failed: ((String) -> String)? = nil, _ work: (Database) throws -> T) -> T? {
        guard let queue, writable else {
            UI.error(Texts.readOnly)
            return nil
        }
        ActivityLog.write("action", action)  // ctx.log_action
        do {
            let value = try queue.write(work)
            changed()
            return value
        } catch {
            UI.error(failed?(UI.message(error)) ?? UI.message(error))
            return nil
        }
    }

    /// Data changed: every page reads again.
    func changed() {
        guard let queue else { return }
        do {
            let rows = try queue.read { try StockQueries.table($0) }
            stock = rows
            lowLevel = (try? queue.read { try StockQueries.lowStockDefault($0) }) ?? 30
        } catch {
            report(error)
        }
        reloadCustomers()
        reloadSearch()
        reloadStats()
        updateBadge()
        version += 1
        cloud.changedHere()
    }

    // ---- the delivery notes folder (Quét lại phiếu, F5)

    /// Scans phieu-giao-hang/ in the background and shows what came in. quiet: the pages are refreshed only when a
    /// note came in (the scan at opening, and the one before a stock count). partial: right after "Áp dụng", the
    /// waiting notes are imported with the lines that were decided. `then` gets the result (nil when it failed).
    func rescan(quiet: Bool = false, partial: Bool = false, then: ((ScanResult?) -> Void)? = nil) {
        guard let queue, let folders, writable else {
            if !quiet { UI.error(Texts.readOnly) }
            then?(nil)
            return
        }
        // a scan nobody asked for (at opening, before a count) never touches the shop's own folder before the user
        // has agreed once; pressing Quét lại is an agreement
        if live && !scanAllowed {
            if quiet {
                then?(nil)
                return
            }
            scanAllowed = true
        }
        if scanning {
            // asked while another scan runs: one more scan follows it, with every wish and every callback kept
            // (an "Áp dụng" must still import the notes it decided, a reread must still say it is done)
            var next = queued ?? QueuedScan(quiet: quiet, partial: partial, callbacks: [])
            next.quiet = next.quiet && quiet
            next.partial = next.partial || partial
            if let then { next.callbacks.append(then) }
            queued = next
            return
        }
        scanning = true
        status = Texts.scanning
        Task {
            var outcome: ScanResult?
            do {
                let result = try await Task.detached(priority: .userInitiated) {
                    try Deliveries.scan(queue, folders, allowPartial: partial)
                }.value
                scanning = false
                lastScan = result
                outcome = result
                if !result.imported.isEmpty || result.pending > 0 {
                    ActivityLog.write("scan", result.imported.isEmpty
                        ? "waiting \(result.pending)"
                        : "read \(result.imported.count): \(result.imported.joined(separator: ", ")) · waiting \(result.pending)")
                }
                if !result.imported.isEmpty || !quiet { changed() } else { updateBadge() }
            } catch {
                scanning = false
                updateBadge()
                UI.error(t("main.scan_failed", ["error": UI.message(error)]))
            }
            then?(outcome)
            if let next = queued {
                queued = nil
                rescan(quiet: next.quiet, partial: next.partial) { result in next.callbacks.forEach { $0(result) } }
            }
        }
    }

    private struct QueuedScan {
        var quiet: Bool
        var partial: Bool
        var callbacks: [(ScanResult?) -> Void]
    }

    /// The user agreed (once) that the shop's own delivery notes folder is read by this app: asked at the first
    /// opening on the shop's data, answer kept. Until then only Quét lại phiếu reads it.
    private var scanAllowed: Bool {
        get { UserDefaults.standard.bool(forKey: "scanAllowed") }
        set { UserDefaults.standard.set(newValue, forKey: "scanAllowed") }
    }

    /// Opening on the shop's own data: the first time, ask before the folder of delivery notes is read (the notes
    /// are imported and moved into da-xu-ly/). tr("Để sau", "Later", "稍后") is the default: nothing is read until Quét lại phiếu.
    private func askToScanOnce() {
        if scanAllowed { return }
        let alert = NSAlert()
        alert.messageText = t("app.name")
        alert.informativeText = Texts.firstScan
        alert.addButton(withTitle: Texts.later)
        alert.addButton(withTitle: Texts.scanNow)
        scanAllowed = alert.runModal() == .alertSecondButtonReturn
        ActivityLog.write("ask", "first scan → \(scanAllowed ? "yes" : "later")")
    }

    /// "Cần xử lý (3)" in the list and the line under the pages.
    func updateBadge() {
        guard let queue, let folders else {
            pendingTotal = 0
            status = ""
            return
        }
        let local = (try? queue.read { db -> Int in
            try Deliveries.pendingCount(db) + Deliveries.unplaced(db).count + Deliveries.countConflicts(db).count
                + Deliveries.inboxCount(db, folders)
        }) ?? 0
        // staff changes and web requests wait here too, on the owner's machine (Python: pending_page)
        let total = local + cloud.staffRequests.count + cloud.webRequests.count
        pendingTotal = total
        var parts: [String] = []
        if let result = lastScan {
            parts.append(t("main.scan_result", ["count": String(result.imported.count)]))
            if !result.copies.isEmpty { parts.append(t("main.scan_copies", ["count": String(result.copies.count)])) }
        }
        if total > 0 { parts.append(t("main.pending", ["count": String(total)])) }
        status = parts.joined(separator: " · ")
    }

    func report(_ error: Error) { errorText = UI.message(error) }

    private func reloadCustomers() {
        guard let queue else { return }
        let text = customerFilter.trimmingCharacters(in: .whitespaces)
        customers = (try? queue.read { try Lookup.customers($0, text: text) }) ?? []
    }

    private func reloadSearch() {
        guard let queue else { return }
        let text = searchText
        found = (try? queue.read { try Lookup.search($0, text: text) }) ?? Lookup.Found()
    }

    private func reloadStats() {
        guard let queue else { return }
        let (start, end) = periodRange
        let filters = statsFilters, by = statsSplit
        do {
            let result = try queue.read { db -> ([Stats.SummaryRow], Stats.Money, [(day: String, qty: Double)]) in
                let rows = try Stats.summary(db, start: start, end: end, filters: filters, by: by)
                let money = try Stats.money(db, start: start, end: end, filters: filters)
                let daily = try Stats.dailyOut(db, start: start, end: end, filters: filters)
                return (rows, money, daily)
            }
            summary = result.0
            money = result.1
            daily = result.2
        } catch {
            report(error)
        }
    }

    var periodRange: (String, String) {
        switch periodKind {
        case .day: return (statsDay, statsDay)
        case .month: return Stats.monthRange(year, month)
        case .quarter: return Stats.quarterRange(year, quarter)
        case .year: return Stats.yearRange(year)
        case .range: return rangeFrom <= rangeTo ? (rangeFrom, rangeTo) : (rangeTo, rangeFrom)  // swapped as Python
        }
    }

    // ---- Đọc phiếu (phase 2, read only): the Swift reader on chosen notes

    var notesFolder: URL? {
        if let workFolder { return workFolder.deliveries }
        if practice { return Practice.deliveries }
        guard let db = liveDatabase else { return nil }
        let folder = db.deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("phieu-giao-hang")
        return FileManager.default.fileExists(atPath: folder.path) ? folder : nil
    }

    func chooseNotes() {
        let panel = NSOpenPanel()
        panel.title = Texts.chooseNotes
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = true
        if panel.runModal() == .OK { readNotes(panel.urls) }
    }

    func readNotes(_ picked: [URL]) {
        var files: [URL] = []
        for url in picked {
            var isFolder: ObjCBool = false
            if FileManager.default.fileExists(atPath: url.path, isDirectory: &isFolder), isFolder.boolValue {
                let walker = FileManager.default.enumerator(at: url, includingPropertiesForKeys: nil)
                while let item = walker?.nextObject() as? URL {
                    if item.pathExtension.lowercased() == "xlsx" && !item.lastPathComponent.hasPrefix("~$") { files.append(item) }
                }
            } else {
                files.append(url)
            }
        }
        noteResults = files.sorted { $0.path < $1.path }.map { file -> NoteResult in
            var note: DeliveryNote?
            var problem: String?
            do {
                note = try DeliveryNoteReader.read(file)
            } catch {
                problem = UI.message(error)
            }
            return NoteResult(file: file, note: note, error: problem)
        }
    }

    // ---- the detail windows (double click)

    func openOrder(_ id: Int64) { showDetail { try Details.order($0, id: id) } }
    func openCustomer(_ id: Int64) { showDetail { try Details.customer($0, id: id) } }
    func openProduct(_ id: Int64) { showDetail { try Details.product($0, id: id) } }
    func openNote(_ result: NoteResult) {
        Screens.detail(Details.note(result.note, error: result.error, file: result.file), self)
    }

    private func showDetail(_ make: (Database) throws -> DetailData?) {
        if let data = read(make) ?? nil { Screens.detail(data, self) }
    }
}

/// Texts of the Swift app that the Python app does not have (the practice folder, the read-only copy).
enum Texts {
    static var practiceBanner: String { tr("BẢN THỬ — mọi thao tác chỉ ghi vào bản sao này, không đổi dữ liệu thật, không lên Cloud.", "PRACTICE COPY — everything is written to this copy only; the real data and the Cloud are not touched.", "试用版 — 所有操作只写入这份副本，不会改动真实数据，也不会上传到 Cloud。") }
    static var readOnlyBanner: String { tr("CHỈ XEM — bản sao tạm của file đã chọn, không ghi được.", "VIEW ONLY — a temporary copy of the chosen file; nothing can be written.", "仅查看 — 所选文件的临时副本，无法写入。") }
    static var noLive: String { tr("Không thấy thư mục làm việc của DiBeKho trên máy này (app chưa được thiết lập).", "No DiBeKho work folder was found on this computer (the app has not been set up yet).", "本机上没有找到 DiBeKho 工作文件夹（应用尚未设置）。") }
    static var noData: String { tr("Chưa mở dữ liệu. Vào Cài đặt để mở dữ liệu đang dùng, hoặc tạo bản thử.", "No data is open. Open the live data or make a practice copy in Settings.", "尚未打开数据。请在 设置 中打开正在使用的数据，或创建试用版。") }
    static var remakePractice: String { tr("Tạo lại bản thử? Những gì đã thử ghi trong bản thử hiện tại sẽ mất (dữ liệu thật không sao).", "Make the practice copy again? What was tried in the current practice copy is lost (the real data is safe).", "重新创建试用版？当前试用版中试过的内容将丢失（真实数据不受影响）。") }
    static var chooseSource: String { tr("Chọn file kho.sqlite để làm bản thử (app chỉ đọc file này, ghi vào bản sao)", "Choose a kho.sqlite file for the practice copy (the app only reads it and writes to a copy)", "选择 kho.sqlite 文件作为试用版（应用只读取该文件，写入副本）") }
    static var chooseReadOnly: String { tr("Chọn file kho.sqlite để xem (app chỉ đọc một bản sao, không ghi)", "Choose a kho.sqlite file to look at (the app reads a copy and never writes)", "选择要查看的 kho.sqlite 文件（应用只读取副本，不写入）") }
    static var chooseNotes: String { tr("Chọn file phiếu .xlsx hoặc một thư mục phiếu (app chỉ đọc, không sửa, không chuyển file)", "Choose a note .xlsx file or a folder of notes (read only: nothing is changed or moved)", "选择单据 .xlsx 文件或单据文件夹（只读，不修改、不移动文件）") }
    static var readOnly: String { tr("Đang xem bản sao chỉ đọc: không ghi được. Vào Cài đặt → Bản thử để thử ghi.", "This is a read-only copy: nothing can be written. Use Settings → Practice copy to try writing.", "当前是只读副本，无法写入。请在 设置 → 试用版 中试用写入。") }
    static var scanning: String { tr("Đang quét thư mục phiếu giao hàng…", "Scanning the delivery notes folder…", "正在扫描送货单文件夹…") }
    static var firstScan: String { tr("Bản Swift sắp đọc các phiếu giao hàng MỚI trong thư mục phiếu giao hàng và ghi vào dữ liệu đang dùng (phiếu đọc xong được chuyển vào da-xu-ly). Hôm nay đã có bản sao lưu trong sao-luu.\n\nNên thử trước trên bản thử (Cài đặt → Tạo bản thử). Quét ngay bây giờ?", "The app is about to read the NEW delivery notes in the delivery notes folder and write them into the live data (notes that are read are moved to da-xu-ly). Today's backup is already in sao-luu.\n\nIt is best to try on a practice copy first (Settings → Make a practice copy). Scan now?", "应用即将读取送货单文件夹中的新单据并写入正在使用的数据（读完的单据会移到 da-xu-ly）。今天的备份已在 sao-luu 中。\n\n建议先在试用版上试一试（设置 → 创建试用版）。现在扫描吗？") }
    static var later: String { tr("Để sau", "Later", "稍后") }
    static var scanNow: String { tr("Quét ngay (và đừng hỏi lại)", "Scan now (and do not ask again)", "立即扫描（不再询问）") }
}
