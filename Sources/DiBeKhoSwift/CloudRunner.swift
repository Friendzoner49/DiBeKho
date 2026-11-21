import AppKit
import DiBeKhoCore
import Foundation
import GRDB

/// Python ui/sync_runner.py: two-way sync in the background while the app is open. A round = pull (network) → merge
/// (database, only at a safe moment) → push (network). A staff account never pushes: it takes the answer about its
/// request, merges, and sends its queue for the owner's approval when it changed. The window never waits on the network.
/// Cloud stays OFF until the user signs in or presses "Đồng bộ ngay" once (`allowed`), and never runs on the practice
/// copy. ⚠ Not compiled and not run against a real Cloud yet.
@MainActor
final class CloudRunner: ObservableObject {
    static let period: TimeInterval = 60      // between rounds when nothing happens here
    static let afterChange: TimeInterval = 5  // several quick edits travel together
    static let retryUnsafe: TimeInterval = 15 // the user was busy on a page
    static let originalsSeconds: TimeInterval = 90

    @Published private(set) var statusText = ""
    @Published private(set) var conflicts: [CloudConflict] = []
    @Published private(set) var staffRequests: [[String: Any]] = [] { didSet { model?.updateBadge() } }
    @Published private(set) var webRequests: [WebRequest] = [] { didSet { model?.updateBadge() } }
    @Published private(set) var lastBackup = ""
    @Published private(set) var busy = false
    /// changes of this machine not on the cloud yet (Bỏ thay đổi chưa duyệt… shows only when there are some)
    @Published private(set) var queued = 0

    weak var model: AppModel?
    private var lastOk: Date?
    private var lastError = ""
    /// the saved session ended (password changed, signed out on the web): the status button asks for the password again
    @Published private(set) var signedOut = false
    /// core/cloud/logs.LogUploader: this machine's app.log, anonymized, every 10 minutes at most
    private let logs = CloudLogs.Uploader()
    /// what the log rows on the cloud carry as the app version (the Python app sends its own number)
    static var version: String {
        "swift-" + (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0")
    }
    private var timer: Timer?
    private var soon: Timer?

    /// Set once the user signs in (or presses "Đồng bộ ngay"); without it nothing here touches the network.
    static var allowed: Bool {
        get { UserDefaults.standard.bool(forKey: "cloudAllowed") }
        set { UserDefaults.standard.set(newValue, forKey: "cloudAllowed") }
    }

    func start() {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: Self.period, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.round() }
        }
        Task { await refreshState() }
        schedule(after: 3)
    }

    func stop() { timer?.invalidate(); timer = nil; soon?.invalidate(); soon = nil }

    func schedule(after seconds: TimeInterval) {
        soon?.invalidate()
        soon = Timer.scheduledTimer(withTimeInterval: seconds, repeats: false) { [weak self] _ in
            Task { @MainActor in self?.round() }
        }
    }

    /// Called after every change made here.
    func changedHere() {
        guard Self.allowed, !busy, model?.live == true else { return }
        schedule(after: Self.afterChange)
    }

    // ---- what the screens show

    /// May rows change under the user now? Not while a dialog is open or on a page where they type.
    private var safe: Bool {
        guard let model else { return false }
        return NSApp.modalWindow == nil && model.page != .count && model.page != .pending
    }

    func refreshState() async {
        guard let queue = model?.queue, model?.live == true else { statusText = ""; conflicts = []; return }
        let cfg = CloudConfig.load()
        let info: (Bool, [CloudConflict], Int, String, [String: Any], String)? = try? await queue.read { db in
            let enabled = try Replica.enabled(db)
            return (enabled, try TwoWay.conflicts(db), try TwoWay.queuedCount(db),
                    try Meta.get(db, "cloud_last_push_at", ""), try CloudApproval.state(db), "")
        }
        guard let (enabled, found, queued, push, state, _) = info, enabled else { statusText = ""; conflicts = []; return }
        conflicts = found
        self.queued = queued
        lastBackup = push
        var parts: [String] = []
        if !found.isEmpty { parts.append(t("sync.conflicts", ["n": String(found.count)])) }
        let at = lastOk.map { Self.clock($0) } ?? ""
        if cfg?.isStaff == true && !signedOut && lastError.isEmpty {
            switch state["status"] as? String ?? "" {
            case "rejected": parts.append(t("staff.status_rejected", ["reason": (state["reason"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "—"]))
            case "pending" where queued > 0: parts.append(t("staff.status_pending", ["n": String(queued)]))
            default:
                if queued > 0 { parts.append(t("staff.status_unsent", ["n": String(queued)])) }
                else if lastOk != nil { parts.append(t("sync.ok", ["at": at])) }
                else { parts.append(t("sync.waiting")) }
            }
        } else if signedOut {
            parts.append(t("sync.signed_out", ["n": String(queued)]))
        } else if !lastError.isEmpty {
            parts.append(t("sync.offline", ["n": String(queued)]))
        } else if lastOk != nil {
            parts.append(t("sync.ok", ["at": at]) + (queued > 0 ? " · " + t("sync.queued", ["n": String(queued)]) : ""))
        } else {
            parts.append(t("sync.waiting"))
        }
        statusText = parts.joined(separator: " · ")
    }

    private static func clock(_ date: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        return f.string(from: date)
    }

    // ---- a round

    func round(tries: Int = 3) {
        Task { await run(tries: tries) }
    }

    private func failed(_ error: Error) async {
        busy = false
        let text = (error as? CloudError)?.message ?? "\(error)"
        if text != lastError { ActivityLog.write("error", "cloud sync: \(text)") }  // offline for hours: one line, not one a minute
        lastError = text
        signedOut = (error as? CloudError)?.kind == .sessionExpired
        await refreshState()
    }

    private func run(tries: Int) async {
        guard Self.allowed, !busy, let model, model.live, let queue = model.queue else { return }
        guard let cfg = CloudConfig.load(), cfg.hasSavedSession else { return }
        busy = true
        let staff = cfg.isStaff
        do {
            guard try await queue.read({ try Replica.enabled($0) }) else { busy = false; return }
            let after = try await queue.read { try TwoWay.cursor($0) }
            guard let (client, token) = try await CloudAccount.session(timeout: 15) else { busy = false; return }
            var request: [String: Any]?
            if staff { request = try await CloudApproval.mine(client, token, device: cfg.deviceId) }
            let pulled = try await CloudAccount.fetch(client, token, after: after)
            await logs.maybeUpload(logFile: ActivityLog.file, deviceName: cfg.deviceName, deviceId: cfg.deviceId,
                                   version: Self.version, sendLogs: cfg.sendLogs, client, token)
            // the data was replaced meanwhile (restore, reset): this pull is stale
            guard model.queue === queue, try await queue.read({ try TwoWay.cursor($0) }) == after else { busy = false; return }
            if !safe && !TwoWay.nothingNew(pulled) {  // rows from elsewhere wait until the user is not typing
                busy = false
                schedule(after: Self.retryUnsafe)
                return
            }
            let folders = model.folders
            let (merged, answered): (Merged, Bool) = try await queue.write { db in
                var answered = false
                if staff { answered = try CloudApproval.takeAnswer(db, request) }
                let merged = try TwoWay.merge(db, pulled)
                if let folders { try TwoWay.exportRenamed(db, folders, merged) }
                return (merged, answered)
            }
            tell(merged)
            if merged.applied > 0 || !merged.renamed.isEmpty || answered { model.changed() }
            let (batch, seq, hold) = try await queue.write { try TwoWay.prepare($0) }
            if staff {
                try await sendForApproval(queue, client, token, batch: batch, seq: seq, device: cfg.deviceId)
            } else if TwoWay.isEmpty(batch) {
                try await ownerExtras(client, token)
            } else {
                let expected = try await queue.read { try TwoWay.cursor($0) }
                let answer = try await CloudAccount.send(client, token, device: cfg.deviceId, expected: expected, batch: batch)
                if (answer["ok"] as? Bool) == true {
                    let rev = (answer["max_rev"] as? NSNumber)?.intValue ?? expected
                    try await queue.write { try TwoWay.finish($0, seq: seq, maxRev: rev, hold: hold) }
                    try await ownerExtras(client, token)
                } else {  // someone wrote in between: pull again
                    busy = false
                    if tries > 1 { await run(tries: tries - 1) }
                    return
                }
            }
            await finished()
        } catch {
            await failed(error)
        }
    }

    private func sendForApproval(_ queue: DatabaseQueue, _ client: CloudClient, _ token: String,
                                 batch: [String: [CloudRow]], seq: Int, device: String) async throws {
        try await queue.write { try CloudApproval.forgetAnswerIfIdle($0) }
        guard try await queue.read({ try CloudApproval.needsSending($0, batch) }) else { return }
        let (base, summary): (Int, [[String: Any]]) = try await queue.read { (try TwoWay.cursor($0), try CloudApproval.summarize($0, batch)) }
        let answer = try await CloudApproval.send(client, token, device: device, baseRev: base, batch: batch, summary: summary)
        try await queue.write { try CloudApproval.sent($0, batch: batch, seq: seq, answer: answer) }
    }

    /// The owner's machine, after a round: the web requests whose documents are now on the cloud are confirmed (or
    /// forgotten when undone), the ones recorded and then lost go back to pending, then the staff and web requests waiting.
    private func ownerExtras(_ client: CloudClient, _ token: String) async throws {
        if let queue = model?.queue {
            do {
                try await WebInbox.finishApplied(queue, client, token)
                try await WebInbox.reconcileApplied(queue, client, token)
            } catch {
                ActivityLog.write("error", "web requests confirm: \(error)")
            }
        }
        do {
            staffRequests = try await CloudApproval.pending(client, token)
        } catch {
            ActivityLog.write("error", "staff requests: \(error)")
        }
        await fetchWeb(client, token)
    }

    private func fetchWeb(_ client: CloudClient, _ token: String) async {
        guard let queue = model?.queue else { return }
        do {
            let seen = try await queue.read { try WebInbox.appliedMap($0) }
            webRequests = try await WebInbox.fetchPending(client, token, seen: seen)
        } catch {
            ActivityLog.write("error", "web requests: \(error)")
        }
    }

    private func finished() async {
        busy = false
        lastOk = Date()
        lastError = ""
        signedOut = false
        await refreshState()
    }

    private func tell(_ merged: Merged) {
        var lines = merged.renamed.map { t("sync.renamed", ["old": $0.old, "new": $0.new]) }
        lines += merged.separated.map { t("sync.separated", ["code": $0]) }
        if merged.duplicates > 0 { lines.append(t("sync.duplicates", ["n": String(merged.duplicates)])) }
        if !merged.conflicts.isEmpty { lines.append(t("sync.new_conflicts", ["n": String(merged.conflicts.count)])) }
        if !lines.isEmpty {
            ActivityLog.write("cloud", lines.joined(separator: "; "))
            model?.errorText = lines.joined(separator: "\n")
        }
    }

    // ---- the buttons of the Cloud tab

    /// "Đồng bộ ngay": a round now; on the owner's machine also the full backup (and kept notes) in Storage.
    func syncNow() async {
        guard let model, model.live, let queue = model.queue else { UI.error(Texts.noLive); return }
        guard let cfg = CloudConfig.load(), cfg.hasSavedSession else { UI.error(t("cloud.need_password")); return }
        Self.allowed = true
        if timer == nil { start() }
        let first = await linkIfNeeded(queue, cfg)
        if !first { return }
        await run(tries: 3)
        if cfg.isStaff { UI.info(t("cloud.sync_started")); return }
        do {
            guard let (client, token) = try await CloudAccount.session(timeout: 30) else { return }
            let name = try await CloudBackup.uploadSnapshot(queue, deviceName: cfg.deviceName, client, token)
            try await queue.write { db in
                try Meta.set(db, "cloud_last_push_at", Self.iso(Date()))
                try Meta.log(db, "cloud_backup", name)
            }
            if let originals = model.folders?.originals {
                let (sent, left) = try await CloudBackup.uploadOriginals(originals, client, token, maxSeconds: Self.originalsSeconds)
                if sent > 0 || left > 0 { ActivityLog.write("cloud", "originals: \(sent) uploaded, \(left) left for next time") }
            }
            await refreshState()
            UI.info(t("cloud.push_ok"))
        } catch {
            UI.error(t("cloud.backup_failed", ["reason": (error as? CloudError)?.message ?? "\(error)"]))
        }
    }

    nonisolated static func iso(_ date: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f.string(from: date)
    }

    /// Join the shared data once per machine. False when the user declined or nothing could be joined.
    private func linkIfNeeded(_ queue: DatabaseQueue, _ cfg: CloudConfig) async -> Bool {
        do {
            let session = try await CloudAccount.resume(timeout: 20)
            guard let backups = model?.workFolder?.backups else { return false }
            let result = try await CloudAccount.link(queue, backups: backups, session) {
                await MainActor.run { UI.ask(t("login.confirm_adopt")) }
            }
            switch result {
            case .refused: return false
            case .emptyCloud: UI.info(t("login.empty_cloud")); return false
            default: model?.changed(); return true
            }
        } catch {
            UI.error((error as? CloudError)?.message ?? "\(error)")
            return false
        }
    }

    /// Sign in with the account (the login window), then join (first time) and run a round. Returns the reason the
    /// account was refused, shown in red in the window as login_dialog.py does; nil when signed in.
    func signIn(user: String, password: String, url: String, key: String) async -> String? {
        guard let model, model.live, let queue = model.queue, let backups = model.workFolder?.backups else { return Texts.noLive }
        // read before signing in, which writes the new account into config.json (app.sign_in_and_link)
        let previousUser = CloudConfig.load()?.user ?? ""
        let queuedBefore: Int = (try? await queue.read { db -> Int in
            guard try Replica.enabled(db) else { return 0 }
            return try TwoWay.queuedCount(db)
        }) ?? 0
        let session: CloudSession
        do {
            session = try await CloudAccount.signIn(username: user, password: password, url: url, key: key)
        } catch {
            return (error as? CloudError)?.message ?? "\(error)"
        }
        let current = CloudConfig.load()?.user ?? user
        ActivityLog.write("start", "signed in as \(current) (\(session.role))")
        if queuedBefore > 0 && !previousUser.isEmpty && previousUser != current {
            // another account worked here and left changes not on the cloud: never send them under this account
            let text = t("login.other_queue", ["n": String(queuedBefore), "user": previousUser])
            guard Self.dropOtherQueue(text) else {
                try? CloudAccount.signOut()
                return text
            }
            do {
                _ = try Backups.named(queue, folder: backups, label: "truoc-bo-thay-doi-tai-khoan-khac")
                try await queue.write { try CloudApproval.discard($0) }
            } catch {
                try? CloudAccount.signOut()
                return UI.message(error)
            }
            model.changed()
        }
        Self.allowed = true
        signedOut = false
        lastError = ""
        if timer == nil { start() }
        do {
            let result = try await CloudAccount.link(queue, backups: backups, session) {
                await MainActor.run { UI.ask(t("login.confirm_adopt")) }
            }
            if result == .emptyCloud { UI.info(t("login.empty_cloud")) }
            if result == .refused { UI.info(t("login.refused")) }
            if result != .refused && result != .emptyCloud { model.changed(); await run(tries: 3) }
        } catch {
            UI.error((error as? CloudError)?.message ?? "\(error)")
        }
        await refreshState()
        return nil
    }

    func signOut() {
        guard let model, let queue = model.queue else { return }
        let queued = (try? queue.read { try TwoWay.queuedCount($0) }) ?? 0
        let extra = queued > 0 ? t("login.queued_warning", ["n": String(queued)]) : ""
        if !UI.ask(t("login.confirm_sign_out", ["queued": extra])) { return }
        do { try CloudAccount.signOut() } catch { UI.error((error as? CloudError)?.message ?? "\(error)"); return }
        Self.allowed = false
        UI.info(t("login.signed_out"))
        Task { await refreshState() }
    }

    /// login.other_queue: true when the user chose «Bỏ các thay đổi đó»; the safe answer is the default one.
    private static func dropOtherQueue(_ text: String) -> Bool {
        let alert = NSAlert()
        alert.messageText = t("app.name")
        alert.informativeText = text
        alert.alertStyle = .warning
        alert.addButton(withTitle: t("btn.cancel"))
        alert.addButton(withTitle: t("login.other_queue_drop"))
        let drop = alert.runModal() == .alertSecondButtonReturn
        ActivityLog.write("ask", "other account's changes → \(drop ? "drop" : "keep")")
        return drop
    }

    /// Cài đặt → Cloud → Gửi nhật ký sử dụng (cloud_tab.set_send_logs)
    func setSendLogs(_ on: Bool) {
        ActivityLog.write("click", "send_logs \(on ? "on" : "off")")
        do { try CloudConfig.saveSendLogs(on) } catch { UI.error(UI.message(error)) }
    }

    static func shown(_ date: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "dd/MM/yyyy HH:mm"
        return f.string(from: date)
    }

    private static func text(_ error: Error) -> String {
        if let e = error as? CloudError { return e.message }
        if let e = error as? CloudAdmin.NotReady { return e.message }
        return UI.message(error)
    }

    /// Cài đặt → Cloud → Khôi phục từ Cloud… (cloud_tab.restore_from_cloud): the owner picks a full backup kept on the
    /// cloud; it is downloaded and checked, the current data is backed up, then
    /// - shared data (shared_admin.replace_shared_data): asked once more, the cloud takes the backup first in one push,
    ///   only then is the file on this computer replaced;
    /// - data of this machine only: the file is replaced, as restoring a local backup.
    /// Afterwards the kept delivery notes this machine lacks are downloaded. ⚠ Not run against a real Cloud yet.
    func restoreFromCloud() async {
        ActivityLog.write("click", "cloud_restore")
        guard let model, model.live, let queue = model.queue, let backups = model.workFolder?.backups,
              let cfg = CloudConfig.load() else { UI.error(Texts.noLive); return }
        if cfg.isStaff { UI.error(t("staff.not_for_staff")); return }
        let client: CloudClient, token: String
        do {
            guard let pair = try await CloudAccount.session(timeout: 30) else { UI.error(t("admin.need_cloud")); return }
            client = pair.0
            token = pair.1
        } catch {
            UI.error(Self.text(error))
            return
        }
        let items: [CloudBackupItem]
        do { items = try await CloudBackup.listBackups(client, token) } catch { UI.error(Self.text(error)); return }
        if items.isEmpty { UI.info(t("cloud.restore_none")); return }
        guard let chosen = CloudScreens.pickBackup(items) else { return }
        if !UI.ask(t("cloud.restore_confirm", ["device": chosen.device, "at": Self.shown(chosen.at)])) { return }
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("dibekho-cloud-restore-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: tmp) }
        let shared = (try? await queue.read { try Replica.enabled($0) }) ?? false
        if shared {
            guard await replaceShared(model, queue, cfg, backups, chosen, into: tmp) else { return }
        } else {
            do {
                let unpushed: Bool = try await queue.read { db in
                    let changed = try Meta.get(db, "last_change_at")
                    let pushed = try Meta.get(db, "cloud_last_push_at")
                    return !changed.isEmpty && changed > pushed
                }
                if unpushed && !UI.ask(t("cloud.restore_unpushed")) { return }
                let path = try await CloudBackup.fetch(client, token, name: chosen.name, into: tmp)
                _ = try Backups.named(queue, folder: backups, label: "truoc-khoi-phuc-cloud")
                ActivityLog.write("data", "restore")
                try Reset.restore(queue, from: path)
                try await queue.write { try CloudBackup.afterRestore($0, deviceName: cfg.deviceName, chosen) }
            } catch {
                UI.error(Self.text(error))
                return
            }
        }
        model.changed()
        await refreshState()
        // the kept delivery notes come back too (Mở file gốc / Khôi phục file); one that fails is only reported
        var failed = 0
        if let originals = model.folders?.originals {
            let (got, missed) = await CloudBackup.fetchOriginals(originals, client, token)
            if got > 0 { ActivityLog.write("cloud", "originals downloaded after restore: \(got)") }
            failed = missed
        }
        UI.info(t("cloud.restored") + (failed > 0 ? "\n\n" + t("cloud.originals_failed", ["n": String(failed)]) : ""))
    }

    /// shared_admin.replace_shared_data with the cloud backup as the new data. True when the shared data was replaced
    /// (also when only the file on this computer could not be replaced: the next sync brings the cloud's data here).
    private func replaceShared(_ model: AppModel, _ queue: DatabaseQueue, _ cfg: CloudConfig, _ backups: URL,
                               _ chosen: CloudBackupItem, into tmp: URL) async -> Bool {
        if !UI.ask(t("admin.confirm", ["what": t("admin.what_restore")])) { return false }
        if busy { UI.error(t("admin.busy")); return false }
        busy = true  // no background round meanwhile
        defer { busy = false }
        var onCloud = false
        do {
            try await queue.read { try CloudAdmin.checkReady($0) }
            guard let (client, token) = try await CloudAccount.session(timeout: 30) else {
                UI.error(t("admin.need_cloud"))
                return false
            }
            _ = try Backups.named(queue, folder: backups, label: "truoc-thay-du-lieu-chung")
            let path = try await CloudBackup.fetch(client, token, name: chosen.name, into: tmp)
            let new = try DatabaseQueue(path: path.path, configuration: Store.configuration())
            try await new.write { try CloudBackup.afterRestore($0, deviceName: cfg.deviceName, chosen) }
            try new.close()
            try await CloudAdmin.replaceShared(queue, newPath: path, client, token, device: cfg.deviceId)
            onCloud = true
            ActivityLog.write("data", "shared data replaced: \(t("admin.what_restore"))")
            try Reset.restore(queue, from: path)
        } catch let error as CloudAdmin.NotReady {
            UI.error(error.message)
            return false
        } catch let error as CloudError where !onCloud {
            UI.error(error.message)
            return false
        } catch {
            // a broken backup: the cloud and this computer are unchanged; once the cloud holds the new data, the next
            // sync brings it here even if replacing the file failed
            ActivityLog.write("error", "replacing shared data: \(error)")
            UI.error(t(onCloud ? "admin.local_failed" : "admin.failed", ["error": Self.text(error)]))
            return onCloud
        }
        return true
    }

    func resolve(_ conflict: CloudConflict, keepMine: Bool) async {
        guard let queue = model?.queue else { return }
        do {
            try await queue.write { try TwoWay.resolve($0, conflict, keepMine: keepMine) }
            model?.changed()
            if keepMine { schedule(after: 1) }
            await refreshState()
        } catch { UI.error(UI.message(error)) }
    }

    /// A staff machine gives its unapproved changes up and takes the shared data again.
    func discard() async {
        guard let model, let queue = model.queue, let backups = model.workFolder?.backups else { return }
        let n = (try? await queue.read { try TwoWay.queuedCount($0) }) ?? 0
        if n == 0 || !UI.ask(t("staff.confirm_discard", ["n": String(n)])) { return }
        if busy { UI.error(t("admin.busy")); return }
        do {
            _ = try Backups.named(queue, folder: backups, label: "truoc-bo-thay-doi-chua-duyet")
            try await queue.write { try CloudApproval.discard($0) }
            if let cfg = CloudConfig.load(), let (client, token) = try? await CloudAccount.session(timeout: 15) {
                try? await CloudApproval.cancel(client, token, device: cfg.deviceId)
            }
            model.changed()
            round()
        } catch { UI.error(UI.message(error)) }
    }

    /// The owner approves or refuses a staff request (the owner's machine). The documents arrive through the next round.
    func decide(_ item: [String: Any], approve: Bool, reason: String = "") async {
        guard let id = item["id"] as? String else { return }
        do {
            guard let (client, token) = try await CloudAccount.session(timeout: 30) else { return }
            let answer = try await CloudApproval.decide(client, token, id: id, approve: approve, reason: reason)
            if (answer["ok"] as? Bool) != true {
                UI.info(t((answer["reason"] as? String) == "stale" ? "staff.stale" : "staff.gone"))
            } else if approve {
                UI.info(t("staff.approved"))
            }
            staffRequests = try await CloudApproval.pending(client, token)
            round()
        } catch { UI.error((error as? CloudError)?.message ?? "\(error)") }
    }

    // ---- web requests (the owner's machine): the screens ask first, these do the work

    private func forget(_ item: WebRequest) { webRequests.removeAll { $0.id == item.id } }

    /// What the owner reads before approving a receipt; the reasons it cannot be applied come back as the failure.
    func webReceiptText(_ item: WebRequest) -> Result<String, WriteError> {
        let read = model?.read { db -> (String, [String], String, String) in
            let (data, errors) = try WebInbox.receiptInput(db, item.payload)
            var source = data.supplierName
            if data.source == Receipts.customerReturn {  // goods a customer sent back: say who
                var name = data.customerName
                if name.isEmpty, let id = data.customerId {
                    name = try String.fetchOne(db, sql: "SELECT name FROM customers WHERE id = ?", arguments: [id]) ?? ""
                }
                let order = data.refCode.isEmpty ? "" : " · \(t("receipt_form.order")) \(data.refCode)"
                source = t("receipt_form.source_return") + ": " + name + order
            }
            let lines = try WebInbox.describe(db, item)
            return (data.date, errors, source, lines)
        }
        guard let r = read else { return .failure(WriteError(Texts.noLive)) }
        if !r.1.isEmpty { return .failure(WriteError(r.1.joined(separator: " "))) }
        return .success(t("pending.web_confirm", ["date": Format.date(r.0), "source": r.2, "lines": r.3]))
    }

    func webCount(_ item: WebRequest) -> (day: String, place: Int64, problems: [String], rows: [CountLine])? {
        model?.read { db -> (day: String, place: Int64, problems: [String], rows: [CountLine]) in
            let (day, place, _, problems) = try WebInbox.checkCount(db, item)
            let rows = try WebInbox.countPreview(db, item)
            return (day, place, problems, rows)
        }
    }

    func approveWeb(_ item: WebRequest) async {
        guard let model, let queue = model.queue, let folders = model.folders, model.writable else { UI.error(Texts.readOnly); return }
        ActivityLog.write("click", "web_request \(item.kind)")
        do {
            switch item.kind {
            case WebInbox.receipt:
                _ = try WebInbox.applyReceipt(queue, folders, item)
            case WebInbox.deliveryFile:
                guard let (client, token) = try await CloudAccount.session(timeout: 30) else { UI.error(t("cloud.need_password")); return }
                let result = try await WebInbox.applyDelivery(queue, folders, client, token, item)
                if result.placed == nil { UI.info(t("web.file_already", ["status": result.status ?? ""])) }
            default:
                _ = try WebInbox.applyCount(queue, item)
            }
            forget(item)
            model.changed()
            if item.kind == WebInbox.deliveryFile { model.rescan(quiet: true) }
        } catch { UI.error(UI.message(error)) }
    }

    /// End of day: every receipt and delivery file in one go (counts are approved one by one).
    func approveAllWeb() async {
        guard let model, let queue = model.queue, let folders = model.folders, model.writable else { UI.error(Texts.readOnly); return }
        let todo = webRequests.filter { $0.kind != WebInbox.stockCount }
        var failed: [String] = []
        var session: (CloudClient, String)?
        for item in todo {
            do {
                if item.kind == WebInbox.receipt {
                    _ = try WebInbox.applyReceipt(queue, folders, item)
                } else {
                    if session == nil { session = try await CloudAccount.session(timeout: 30) }
                    guard let (client, token) = session else { throw CloudError(t("cloud.need_password")) }
                    _ = try await WebInbox.applyDelivery(queue, folders, client, token, item)
                }
                forget(item)
            } catch {
                failed.append("• \(Self.webKind(item.kind)) · \(Self.webDetail(item)): \(UI.message(error))")
            }
        }
        model.changed()
        model.rescan(quiet: true)
        if !failed.isEmpty { UI.error(t("web.apply_all_failed", ["n": String(failed.count), "list": failed.joined(separator: "\n")])) }
    }

    func rejectWeb(_ item: WebRequest) async {
        do {
            guard let (client, token) = try await CloudAccount.session(timeout: 30) else { UI.error(t("cloud.need_password")); return }
            try await WebInbox.reject(client, token, item)
            ActivityLog.write("action", "web_inbox_rejected")
            forget(item)
        } catch { UI.error(UI.message(error)) }
    }

    /// web.kind_receipt / web.kind_delivery_file / web.kind_stock_count
    static func webKind(_ kind: String) -> String { t("web.kind_\(kind)") }

    /// web_requests.WebRequestsPanel.detail
    static func webDetail(_ item: WebRequest) -> String {
        let p = item.payload
        func text(_ k: String) -> String { (p[k] as? String) ?? "" }
        let n = String(((p["lines"] as? [Any]) ?? []).count)
        switch item.kind {
        case WebInbox.receipt:
            return t("web.detail_receipt", ["date": Format.date(text("doc_date")), "source": text("supplier_name"), "n": n])
        case WebInbox.deliveryFile:
            let size = (p["size"] as? NSNumber)?.intValue ?? 0
            return t("web.detail_file", ["name": text("file_name"), "kb": String(max(1, Int((Double(size) / 1024).rounded())))])
        default:
            let place = UI.locationName((p["location_id"] as? NSNumber)?.int64Value)
            return t("web.detail_count", ["date": Format.date(text("count_date")), "place": place, "n": n])
        }
    }
}
