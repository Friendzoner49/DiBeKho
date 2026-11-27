import DiBeKhoCore
import SwiftUI

/// Cài đặt → Cloud (Python ui/cloud_tab.py): one box with the hint, who is signed in and Đăng xuất, a row of buttons
/// (Đồng bộ ngay; the owner's Khôi phục từ Cloud…; Xem các thay đổi trùng when there are some; a staff machine's Bỏ thay
/// đổi chưa duyệt… when it has some), the sync status and the last full backup, then «Gửi nhật ký sử dụng».
/// Signing in is the login of login_dialog.py, before the main window (LoginScreen); Đăng xuất quits the app.
/// ⚠ Not run against a real Cloud yet.
struct CloudBox: View {
    @ObservedObject var model: AppModel
    @ObservedObject var cloud: CloudRunner
    @State private var config = CloudConfig.load()
    @State private var working = false
    @State private var sendLogs = CloudConfig.load()?.sendLogs ?? true

    init(model: AppModel) {
        self.model = model
        self.cloud = model.cloud
    }

    private var signedIn: Bool { config?.hasSavedSession == true }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            GroupBox(t("cloud.title")) {
                VStack(alignment: .leading, spacing: 8) {
                    Hint(t("sync.mode_hint"))
                    if model.live && signedIn { signedInView }
                }
                .frame(maxWidth: .infinity, alignment: .leading).padding(6)
            }
            if model.live && signedIn && config?.isStaff != true
                && (!cloud.staffRequests.isEmpty || !cloud.webRequests.isEmpty) {
                Hint(tr("Có yêu cầu của nhân viên đang chờ bạn duyệt: xem ở mục «Cần xử lý».", "Staff requests are waiting for you: see “To do”.", "有员工的请求等待您审批：请看“待处理”。"))
            }
        }
        .onAppear { reload() }
    }

    private func reload() {
        config = CloudConfig.load()
        sendLogs = config?.sendLogs ?? true
        Task { await cloud.refreshState() }
    }

    @ViewBuilder private var signedInView: some View {
        let role = config?.role ?? ""
        let staff = config?.isStaff == true
        HStack {
            Text(t("login.who", ["user": config?.user ?? "—", "role": t("login.role_\(role)")]))
            Spacer()
            Button(t("login.sign_out")) { cloud.signOut() }
        }
        HStack {
            Button(t("cloud.sync_now")) {
                working = true
                Task {
                    await cloud.syncNow()
                    working = false
                    reload()
                }
            }
            .disabled(working || cloud.busy)
            if !staff {
                Button(t("cloud.restore_btn")) {
                    working = true
                    Task {
                        await cloud.restoreFromCloud()
                        working = false
                        reload()
                    }
                }
                .disabled(working || cloud.busy)
            }
            if !cloud.conflicts.isEmpty {
                Button(t("sync.show_conflicts")) { CloudScreens.conflicts(model) }
            }
            if staff && cloud.queued > 0 {
                Button(t("staff.discard")) { Task { await cloud.discard() } }
            }
            if working || cloud.busy { ProgressView().controlSize(.small) }
            Spacer()
        }
        VStack(alignment: .leading, spacing: 2) {
            if !cloud.statusText.isEmpty { Text(cloud.statusText) }
            if !staff {
                Text(t("cloud.last_push", ["when": cloud.lastBackup.isEmpty ? t("cloud.never") : String(cloud.lastBackup.replacingOccurrences(of: "T", with: " ").prefix(16))]))
            }
        }
        .fixedSize(horizontal: false, vertical: true)
        Toggle(t("cloud.send_logs"), isOn: Binding(get: { sendLogs }, set: { on in
            sendLogs = on
            cloud.setSendLogs(on)
        }))
        Hint(t("cloud.send_logs_hint"))
    }
}

/// The Cloud windows: sign in (login_dialog.py), the conflicts (conflict_dialog.py), the cloud backups to restore
/// (cloud_tab.CloudRestoreDialog).
@MainActor
enum CloudScreens {
    static func signIn(_ model: AppModel, message: String = "", done: @escaping () -> Void = {}) {
        guard model.live else { return UI.error(Texts.noLive) }
        Windows.show(t("app.name"), width: 560, height: CloudBuiltin.has ? 290 : 360, modal: false) { _ in
            LoginView(model: model, problem: message, done: done)
        }
    }

    static func conflicts(_ model: AppModel) {
        Windows.show(t("sync.conflict_title"), width: 900, height: 480, modal: false) { _ in
            ConflictsView(model: model, cloud: model.cloud)
        }
    }

    /// The backup picked, or nil when cancelled.
    static func pickBackup(_ items: [CloudBackupItem]) -> CloudBackupItem? {
        var picked: Int?
        let ok = Windows.show(t("cloud.restore_title"), width: 760, height: 460, modal: true) { _ in
            CloudRestoreView(items: items) { picked = $0 }
        }
        guard ok, let picked, picked < items.count else { return nil }
        return items[picked]
    }

    /// The Cloud button at the top right (main_window._sync_clicked): the session ended -> the login again; conflicts ->
    /// the conflicts window; otherwise a sync round now.
    static func statusClicked(_ model: AppModel) {
        let cloud = model.cloud
        guard model.live else { return }
        if cloud.signedOut {
            signIn(model, message: t("login.again"))
        } else if !cloud.conflicts.isEmpty {
            conflicts(model)
        } else {
            cloud.round()
        }
    }
}

/// login_dialog.LoginDialog: the title, the hint, the address and key (only in a build that carries none), the account
/// and the password; a refused sign-in is said in red here, the password emptied. `cancelTitle` (Thoát at the start,
/// Huỷ bỏ inside the app), then Đăng nhập (default). `joined`: the app quits or opens.
struct LoginForm: View {
    @ObservedObject var cloud: CloudRunner
    @State var problem: String
    let cancelTitle: String
    let cancel: () -> Void
    let joined: (CloudRunner.Joined) -> Void
    @State private var url = CloudConfig.load()?.url ?? ""
    @State private var key = CloudConfig.load()?.key ?? ""
    @State private var user = CloudConfig.load()?.user ?? ""
    @State private var password = ""
    @State private var working = false
    @FocusState private var focus: Field?
    private let builtin = CloudBuiltin.has

    enum Field { case user, password }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(t("login.title")).font(.system(size: UI.baseSize + 5, weight: .bold))
            Hint(t("login.hint"))
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 6) {
                if !builtin {  // a build that carries no Cloud address (CloudBuiltin): asked here, as the Python app
                    GridRow {
                        Text(t("cloud.url") + ":")
                        TextField("", text: $url).textFieldStyle(.roundedBorder)
                    }
                    GridRow {
                        Text(t("cloud.key") + ":")
                        TextField("", text: $key).textFieldStyle(.roundedBorder)
                    }
                }
                GridRow {
                    Text(t("cloud.user") + ":")
                    TextField("", text: $user).textFieldStyle(.roundedBorder).focused($focus, equals: .user)
                }
                GridRow {
                    Text(t("cloud.password") + ":")
                    SecureField("", text: $password).textFieldStyle(.roundedBorder).focused($focus, equals: .password)
                        .onSubmit { signIn() }
                }
            }
            if !problem.isEmpty {
                Text(problem).foregroundColor(Color(nsColor: .systemRed)).fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
            HStack {
                Spacer()
                if working { ProgressView().controlSize(.small) }
                Button(cancelTitle) { cancel() }
                Button(t("login.sign_in")) { signIn() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(working)
            }
        }
        .onAppear { focus = user.isEmpty ? .user : .password }
    }

    private func signIn() {
        guard !working else { return }
        ActivityLog.write("click", "sign_in")
        working = true
        let typed = password
        Task {
            let outcome = await cloud.signIn(user: user, password: typed, url: builtin ? "" : url, key: builtin ? "" : key)
            working = false
            password = ""
            if case .problem(let text) = outcome {
                problem = text
                focus = .password
            } else {
                joined(outcome)
            }
        }
    }
}

/// The login asked again inside the running app when the saved session ended (login_dialog.sign_in_again).
struct LoginView: View {
    @ObservedObject var model: AppModel
    let problem: String
    let done: () -> Void
    @EnvironmentObject var box: WindowBox

    var body: some View {
        LoginForm(cloud: model.cloud, problem: problem, cancelTitle: t("btn.cancel"), cancel: { box.close() }) { outcome in
            if outcome == .quit {
                UI.quit()
                return
            }
            box.close(accepted: true)
            model.cloud.round()
            done()
        }
    }
}

/// The first window of the app (app.sign_in_and_link), inside the main window before anything else: the logo, then the
/// account and the password; Thoát quits. Every start after Đăng xuất opens here.
struct LoginScreen: View {
    @ObservedObject var model: AppModel
    let problem: String

    var body: some View {
        VStack(spacing: 14) {
            Spacer()
            AppLogo(size: 120)
            Text(t("app.name")).font(.system(size: UI.baseSize + 12, weight: .bold))
            LoginForm(cloud: model.cloud, problem: problem, cancelTitle: t("app.quit"), cancel: { UI.quit() }) {
                model.joined($0)
            }
            .padding(20)
            .frame(width: 540)
            .fixedSize(horizontal: false, vertical: true)
            .background(SoftRect().fill(Color(nsColor: .controlBackgroundColor)))
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// While the work folder opens and the saved session is checked (a slow line: the app shows it is opening).
struct StartingScreen: View {
    var body: some View {
        VStack(spacing: 14) {
            AppLogo(size: 120)
            ProgressView().controlSize(.small)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// The app's own icon (yellow tile, blue warehouse) as the logo of the first windows.
struct AppLogo: View {
    let size: CGFloat

    var body: some View {
        Image(nsImage: NSApp.applicationIconImage)
            .resizable()
            .interpolation(.high)
            .frame(width: size, height: size)
    }
}

/// conflict_dialog.ConflictDialog: rows edited differently here and on the cloud; pick a row, then which version stays.
struct ConflictsView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var cloud: CloudRunner
    @EnvironmentObject var box: WindowBox
    @State private var selected: Int?

    static let hidden: Set<String> = ["id", "deleted", "rev", "created_at", "code_norm", "phone_norm"]

    static func text(_ v: CloudValue?) -> String {
        switch v {
        case .none, .some(.null): return ""
        case .some(.bool(let b)): return b ? "True" : "False"
        case .some(.int(let i)): return String(i)
        case .some(.double(let d)): return String(d)
        case .some(.text(let s)): return s
        }
    }

    static func label(_ key: String, fallback: String) -> String { L10n.has(key) ? t(key) : fallback }

    /// conflict_dialog._what: the table, then the code or name of the row
    static func what(_ c: CloudConflict) -> String {
        let row = c.cloud.isEmpty ? c.local : c.cloud
        let name = ["code", "name", "name_vi", "key"].map { text(row[$0]) }.first { !$0.isEmpty } ?? ""
        let extra = !text(row["code"]).isEmpty ? text(row["name_vi"]) : ""
        return [label("sync.table.\(c.table)", fallback: c.table), name, extra].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    /// conflict_dialog._differences: each column whose values differ, mine against the cloud's
    static func differences(_ c: CloudConflict) -> [String] {
        Set(c.local.keys).union(c.cloud.keys).sorted().compactMap { col in
            if hidden.contains(col) || c.local[col] == c.cloud[col] { return nil }
            return t("sync.diff", ["col": label("sync.col.\(col)", fallback: col), "mine": text(c.local[col]),
                                   "theirs": text(c.cloud[col])])
        }
    }

    var body: some View {
        let items = cloud.conflicts
        VStack(alignment: .leading, spacing: 8) {
            Hint(t("sync.conflict_hint"))
            DataTable(columns: [Column(title: t("sync.conflict_what"), width: 280),
                                Column(title: t("sync.conflict_diff"), width: 520)],
                      rows: items.map { [Self.what($0), Self.differences($0).joined(separator: " · ")] },
                      onSelect: { selected = $0 }, sortable: false)
            // the whole differences of the row picked (the Python table shows them on several lines)
            if let i = selected, i < items.count {
                Text(Self.differences(items[i]).joined(separator: "\n"))
                    .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
            HStack {
                Button(t("sync.keep_mine")) { choose(keepMine: true) }
                Button(t("sync.keep_cloud")) { choose(keepMine: false) }
                Spacer()
                Button(t("btn.close")) { box.close() }
            }
        }
    }

    private func choose(keepMine: Bool) {
        let items = cloud.conflicts
        guard let i = selected, i < items.count else { return UI.error(t("sync.pick_first")) }
        let c = items[i]
        ActivityLog.write("click", "conflict \(c.table) \(keepMine ? "mine" : "cloud")")
        Task {
            await cloud.resolve(c, keepMine: keepMine)
            cloud.round()
            selected = nil
            if cloud.conflicts.isEmpty { box.close(accepted: true) }
        }
    }
}

/// cloud_tab.CloudRestoreDialog: the full backups kept on the cloud, newest first; double-click or Khôi phục bản này.
struct CloudRestoreView: View {
    let items: [CloudBackupItem]
    let picked: (Int) -> Void
    @EnvironmentObject var box: WindowBox
    @State private var selected: Int?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Hint(t("cloud.restore_hint"))
            DataTable(columns: [Column(title: t("cloud.col_at"), width: 170), Column(title: t("cloud.col_device"), width: 260),
                                Column(title: t("cloud.col_size"), width: 110, numeric: true)],
                      rows: items.map { [CloudRunner.shown($0.at), $0.device, "\(max(1, Int((Double($0.size) / 1024).rounded()))) KB"] },
                      onOpen: { i in
                          picked(i)
                          box.close(accepted: true)
                      },
                      onSelect: { selected = $0 }, sortable: false)
            HStack {
                Spacer()
                Button(t("cloud.restore_go")) {
                    guard let i = selected else { return UI.error(t("cloud.restore_pick")) }
                    picked(i)
                    box.close(accepted: true)
                }
                Button(t("btn.cancel")) { box.close() }
            }
        }
    }
}
