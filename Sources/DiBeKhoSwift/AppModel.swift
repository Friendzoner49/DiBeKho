import AppKit
import DiBeKhoCore
import Foundation
import GRDB

/// The app's state. As the Python app (app.py): the work folder of this Mac, opened only after the account signed in
/// and the machine joined the shared data on the Cloud; the window then works on it and syncs in the background.
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
    /// app.py before the main window: the first-start box, the login (with the reason in red), then the window
    enum Stage: Equatable { case starting, firstRun, login(String), ready }
    @Published private(set) var stage: Stage = .starting
    /// the build workflow's screenshots only: a made-up shop in a temporary folder (DemoShop), no login, no Cloud
    @Published private(set) var demo = false
    /// the shop's own work folder (config.json of the Python app), written for real, with the shared lock
    @Published private(set) var workFolder: WorkFolder?
    var live: Bool { workFolder != nil }
    var writable: Bool { demo || live }
    var outputFolder: URL? { workFolder?.output ?? (demo ? DemoShop.output : nil) }
    var inputFolder: URL? { workFolder?.input ?? (demo ? DemoShop.input : nil) }
    /// the folders the delivery notes are scanned in (the open work folder; nil before it is open)
    var folders: ShopFolders? {
        if let workFolder { return ShopFolders(root: workFolder.root) }
        return demo ? ShopFolders(root: DemoShop.folder) : nil
    }
    /// true while the delivery notes folder is being scanned
    @Published private(set) var scanning = false
    /// the line under the pages: the last scan and what waits ("Lần quét gần nhất: 2 phiếu mới · 3 việc cần xử lý")
    @Published private(set) var status = ""
    /// what waits in "Cần xử lý": files, orders without a place, orders read after a count, files in input/
    @Published private(set) var pendingTotal = 0
    private var lastScan: ScanResult?
    private var queued: QueuedScan?
    /// changes after every write: the pages read again
    @Published private(set) var version = 0
    @Published var errorText: String?
    /// Hàng về: a new receipt closed without saving is kept for the next '＋ Nhập hàng về…'
    var receiptDraft: Receipts.Input?

    private(set) var queue: DatabaseQueue?

    /// Background sync with the Cloud, from the moment the window opens
    let cloud = CloudRunner()

    init() {
        let today = Calendar(identifier: .gregorian).dateComponents([.year, .month], from: Date())
        year = today.year ?? 2026
        month = today.month ?? 1
        quarter = ((today.month ?? 1) - 1) / 3 + 1
        // Vietnamese unless Cài đặt → Chung chose another language.
        L10n.language = GeneralSettings.savedLanguage()
        NotificationCenter.default.addObserver(forName: NSApplication.willTerminateNotification, object: nil,
                                               queue: .main) { [weak self] _ in
            Store.removeCopies()
            MainActor.assumeIsolated { self?.closeWorkFolder() }  // the shared lock goes with the app
        }
        let env = ProcessInfo.processInfo.environment
        if let path = env["DIBEKHO_OPEN"] {
            // the build workflow's screenshots: a made-up shop, a page, a window
            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                self.openDemo(URL(fileURLWithPath: path))
                if let name = env["DIBEKHO_PAGE"], let page = Page(rawValue: name) { self.page = page }
                if let folder = env["DIBEKHO_SCAN_NOTES"], !folder.isEmpty, let to = self.folders?.deliveries {
                    // a few made-up notes dropped into the shop's folder, then read: "Cần xử lý" has something to show
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
        } else {
            DispatchQueue.main.async { [weak self] in self?.openAtStart() }
        }
    }

    // ---- opening (app.main and app.sign_in_and_link)

    /// No work folder yet: the first-start box. Otherwise the work folder opens (refused while another DiBeKho holds
    /// it: the app quits), then the saved session is used without asking, or the login shows.
    func openAtStart() {
        guard WorkFolder.configured != nil else {
            stage = .firstRun
            return
        }
        guard openLive() else {
            NSApp.terminate(nil)
            return
        }
        Task { await resume() }
    }

    /// A machine already signed in opens without asking, also offline once it has joined the shared data (it syncs
    /// when the line is back). An expired session, a role taken away or no line before joining: the login, with why.
    private func resume() async {
        guard CloudConfig.load()?.hasSavedSession == true else {
            stage = .login("")
            return
        }
        do {
            let session = try await CloudAccount.resume(timeout: 6)
            joined(await cloud.join(session, previousUser: CloudConfig.load()?.user ?? "", queuedBefore: 0))
        } catch let error as CloudError where error.kind == .notForApp {
            try? CloudAccount.signOut()
            stage = .login(error.message)
        } catch let error as CloudError where error.kind == .sessionExpired {
            stage = .login(t("login.again"))
        } catch {
            if (try? queue?.read { try Replica.enabled($0) }) == true {
                ActivityLog.write("cloud", "offline at start: working on the local copy")
                begin()
            } else {
                stage = .login(t("login.offline"))
            }
        }
    }

    /// What the login (or the saved session) led to: the login again with the reason, the app quits, or the window
    /// opens (after the first round when the machine has just joined the shared data).
    func joined(_ outcome: CloudRunner.Joined) {
        switch outcome {
        case .problem(let text):
            stage = .login(text)
        case .quit:
            NSApp.terminate(nil)
        case .ready(let first):
            Task {
                if first, let reason = await cloud.firstRound() {
                    UI.error(reason)
                    NSApp.terminate(nil)
                    return
                }
                begin()
            }
        }
    }

    /// The window opens: the background sync starts, the pages read, the notes folder is scanned (window.rescan()).
    private func begin() {
        stage = .ready
        cloud.start()
        changed()
        rescan(quiet: true)
    }

    /// The shop's work folder (config.json); refused while another DiBeKho has it open.
    @discardableResult
    func openLive() -> Bool {
        guard let root = WorkFolder.configured else {
            UI.error(Texts.noLive)
            return false
        }
        closeWorkFolder()
        do {
            let folder = try WorkFolder(root: root)
            workFolder = folder
            queue = folder.queue
            demo = false
            errorText = nil
            ActivityLog.write("start", "DiBeKho Swift \(GeneralSettings.version()) · \(ProcessInfo.processInfo.operatingSystemVersionString)")
            cloud.model = self
            return true
        } catch {
            queue = nil
            report(error)
            UI.error(UI.message(error))
            return false
        }
    }

    func closeWorkFolder() {
        guard let folder = workFolder else { return }
        cloud.stop()
        if queue === folder.queue { queue = nil }
        folder.close()
        workFolder = nil
    }

    /// The build workflow's screenshots (DIBEKHO_OPEN): a made-up shop copied into a temporary folder, opened without
    /// the login and never synced.
    private func openDemo(_ url: URL) {
        do {
            try DemoShop.make(from: url)
            queue = try DemoShop.open()
            demo = true
            stage = .ready
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

    /// One write transaction; the user sees the Python app's message if it is refused.
    /// `failed`: the screen's own message around the reason (issue.failed: "Không lưu được phiếu xuất kho…{error}").
    @discardableResult
    func write<T>(_ action: String, failed: ((String) -> String)? = nil, _ work: (Database) throws -> T) -> T? {
        guard let queue, writable else {
            UI.error(Texts.notOpen)
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
            if !quiet { UI.error(Texts.notOpen) }
            then?(nil)
            return
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

    var notesFolder: URL? { workFolder?.deliveries ?? (demo ? DemoShop.deliveries : nil) }

    // ---- the detail windows (double click)

    func openOrder(_ id: Int64) { showDetail { try Details.order($0, id: id) } }
    func openCustomer(_ id: Int64) { showDetail { try Details.customer($0, id: id) } }
    func openProduct(_ id: Int64) { showDetail { try Details.product($0, id: id) } }

    private func showDetail(_ make: (Database) throws -> DetailData?) {
        if let data = read(make) ?? nil { Screens.detail(data, self) }
    }
}

/// Texts of the Swift app that the Python app does not have.
enum Texts {
    static var noLive: String { tr("Không thấy thư mục làm việc của DiBeKho trên máy này (app chưa được thiết lập).", "No DiBeKho work folder was found on this computer (the app has not been set up yet).", "本机上没有找到 DiBeKho 工作文件夹（应用尚未设置）。") }
    static var notOpen: String { tr("Chưa mở dữ liệu của cửa hàng nên chưa ghi được.", "The shop's data is not open yet: nothing can be written.", "尚未打开店铺数据，无法写入。") }
    static var scanning: String { tr("Đang quét thư mục phiếu giao hàng…", "Scanning the delivery notes folder…", "正在扫描送货单文件夹…") }
}
