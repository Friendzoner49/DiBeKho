import Foundation
import GRDB

/// The cloud settings of this machine, kept in the Python app's config.json (cloud_url, cloud_key, cloud_user,
/// cloud_refresh_token, cloud_role) so that both apps share one sign-in. Only these keys are written; every other key
/// of the file stays as it is. Nothing is created when config.json is missing (the app then has no shared work folder).
/// The key and the refresh token never go to the repo, the log or an error text.
/// The shop's Cloud address put into the build (core/cloud/builtin.py): scripts/make_app.sh writes builtin.json into
/// the app's Resources from the repository's Actions secrets DIBEKHO_CLOUD_URL / DIBEKHO_CLOUD_KEY, never into the
/// repository. A build without it still works: the sign-in window then shows the address and key fields.
public enum CloudBuiltin {
    /// (project URL, publishable key) from builtin.json's bytes, or nil when either is missing
    public static func parse(_ data: Data) -> (String, String)? {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        let url = (object["url"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let key = (object["key"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return url.isEmpty || key.isEmpty ? nil : (url, key)
    }

    public static func address() -> (String, String)? {
        guard let file = Bundle.main.url(forResource: "builtin", withExtension: "json"),
              let data = try? Data(contentsOf: file) else { return nil }
        return parse(data)
    }

    /// has_builtin()
    public static var has: Bool { address() != nil }
}

public struct CloudConfig {
    public var url = ""
    public var key = ""
    public var user = ""
    public var refreshToken = ""
    public var role = ""
    public var deviceId = ""
    public var deviceName = ""
    /// Cài đặt → Cloud → Gửi nhật ký sử dụng (Config.send_logs, on unless switched off)
    public var sendLogs = true

    static var file: URL { Workspace.configFile }

    public static func load() -> CloudConfig? {
        guard let data = try? Data(contentsOf: file),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        func s(_ k: String) -> String { object[k] as? String ?? "" }
        var c = CloudConfig()
        c.url = s("cloud_url"); c.key = s("cloud_key"); c.user = s("cloud_user")
        if let builtin = CloudBuiltin.address() {  // apply_builtin: the address the build carries wins
            c.url = builtin.0; c.key = builtin.1
        }
        c.refreshToken = s("cloud_refresh_token"); c.role = s("cloud_role")
        c.deviceId = s("device_id"); c.deviceName = s("device_name")
        c.sendLogs = (object["send_logs"] as? Bool) ?? true
        if c.deviceId.isEmpty { c.deviceId = Workspace.device().id }
        if c.deviceName.isEmpty { c.deviceName = Workspace.device().name }
        return c
    }

    /// Read-modify-write of the cloud keys only.
    public func save() throws {
        let data = try Data(contentsOf: Self.file)
        guard var object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw CloudError("Không đọc được config.json.")
        }
        object["cloud_url"] = url; object["cloud_key"] = key; object["cloud_user"] = user
        object["cloud_refresh_token"] = refreshToken; object["cloud_role"] = role
        let out = try JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
        try out.write(to: Self.file, options: .atomic)
    }

    /// Only send_logs changes (the check box of Cài đặt → Cloud).
    public static func saveSendLogs(_ on: Bool) throws {
        let data = try Data(contentsOf: file)
        guard var object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw CloudError("Không đọc được config.json.")
        }
        object["send_logs"] = on
        let out = try JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
        try out.write(to: file, options: .atomic)
    }

    public var isStaff: Bool { role == CloudApproval.staff }
    public var hasSavedSession: Bool {
        !url.isEmpty && !key.isEmpty && !user.isEmpty && !refreshToken.isEmpty && [CloudApproval.owner, CloudApproval.staff].contains(role)
    }
}

public struct CloudSession {
    public let client: CloudClient
    public let token: String
    public let role: String
}

/// Refresh tokens rotate: two refreshes at once would invalidate it, so they go one at a time.
actor SessionGate {
    static let shared = SessionGate()

    func rotate(_ client: CloudClient) async throws -> CloudTokens {
        guard var cfg = CloudConfig.load() else { throw CloudError("Chưa đăng nhập trên máy này.", kind: .sessionExpired) }
        let tokens = try await client.refresh(cfg.refreshToken)
        cfg.refreshToken = tokens.refresh
        try cfg.save()
        return tokens
    }
}

/// Python core/cloud/account.py + sync.py (session). The account the app works with: 'desktop' (the owner) writes the
/// shared data, 'editor' (staff) works on its own copy and sends it for approval, 'viewer' or none is refused here:
/// the app has no view-only path by design (the same message as the Python app).
public enum CloudAccount {
    public enum Link { case uploaded, adopted, already, emptyCloud, refused }

    static let signInTimeout: TimeInterval = 20

    public static func roleOf(_ client: CloudClient, _ token: String) async throws -> String {
        (try await client.rpc("my_role", [:], token) as? String) ?? ""
    }

    static func allowed(_ role: String) throws -> String {
        if ![CloudApproval.owner, CloudApproval.staff].contains(role) {
            throw CloudError("Tài khoản này chỉ dùng để xem trên trang web, chưa được dùng app. "
                + "Nhờ chủ cấp vai trò Máy chính hoặc Nhân viên (trang web → Cài đặt → Tài khoản).", kind: .notForApp)
        }
        return role
    }

    /// Check the account with the cloud and remember the session. Throws CloudError (shown as it is).
    public static func signIn(username: String, password: String, url: String, key: String) async throws -> CloudSession {
        guard var cfg = CloudConfig.load() else { throw CloudError("Chưa có thư mục dữ liệu thật của DiBeKho (config.json) trên máy này.") }
        let user = username.trimmingCharacters(in: .whitespacesAndNewlines)
        let address = (url.isEmpty ? cfg.url : url).trimmingCharacters(in: .whitespacesAndNewlines)
        let publicKey = (key.isEmpty ? cfg.key : key).trimmingCharacters(in: .whitespacesAndNewlines)
        if address.isEmpty || publicKey.isEmpty { throw CloudError("Chưa có địa chỉ Cloud và mã kết nối.") }
        if user.isEmpty || password.isEmpty { throw CloudError("Hãy gõ tên đăng nhập và mật khẩu.") }
        let client = CloudClient(url: address, key: publicKey, timeout: signInTimeout)
        let tokens = try await client.signIn(username: user, password: password)
        let role = try allowed(try await roleOf(client, tokens.access))
        cfg.url = address; cfg.key = publicKey; cfg.user = user
        cfg.refreshToken = tokens.refresh; cfg.role = role
        try cfg.save()
        return CloudSession(client: client, token: tokens.access, role: role)
    }

    /// Client + access token from the saved refresh token (rotated and saved at once). Nil when the cloud is not set up.
    public static func session(timeout: TimeInterval? = nil) async throws -> (CloudClient, String)? {
        guard let cfg = CloudConfig.load(), !cfg.url.isEmpty, !cfg.key.isEmpty, !cfg.user.isEmpty, !cfg.refreshToken.isEmpty else { return nil }
        let client = CloudClient(url: cfg.url, key: cfg.key, timeout: timeout ?? CloudClient.timeout)
        return (client, try await SessionGate.shared.rotate(client).access)
    }

    /// The saved session, checked with the cloud. Throws SessionExpired (the password is needed again), NotForApp (the
    /// owner took the role away) or CloudError (no network).
    public static func resume(timeout: TimeInterval = 10) async throws -> CloudSession {
        guard let (client, token) = try await session(timeout: timeout) else {
            throw CloudError("Chưa đăng nhập trên máy này.", kind: .sessionExpired)
        }
        let role = try allowed(try await roleOf(client, token))
        try rememberRole(role)
        return CloudSession(client: client, token: token, role: role)
    }

    /// True when the role changed (the owner changed it on the web).
    @discardableResult
    public static func rememberRole(_ role: String) throws -> Bool {
        guard var cfg = CloudConfig.load(), cfg.role != role else { return false }
        cfg.role = role
        try cfg.save()
        return true
    }

    /// Forget the session on this machine; the next start asks for the account again.
    public static func signOut() throws {
        guard var cfg = CloudConfig.load() else { return }
        cfg.refreshToken = ""; cfg.role = ""
        try cfg.save()
    }

    static func hasLocalData(_ db: Database) throws -> Bool {
        for t in ["products", "documents", "customers"] {
            if try Int.fetchOne(db, sql: "SELECT 1 FROM \(t) LIMIT 1") != nil { return true }
        }
        return false
    }

    public static func fetch(_ client: CloudClient, _ token: String, after: Int) async throws -> Pulled {
        CloudJSON.pulled(try await client.rpc("sync_pull", ["p_after": after], token))
    }

    public static func send(_ client: CloudClient, _ token: String, device: String, expected: Int,
                            batch: [String: [CloudRow]]) async throws -> [String: Any] {
        let answer = try await client.rpc("sync_push", ["p_device": device, "p_expected": expected, "p_batch": CloudApproval.json(batch)], token)
        return (answer as? [String: Any]) ?? [:]
    }

    /// Join the shared data, once per machine (afterwards the background sync keeps it current).
    /// - the cloud is empty: the owner's machine becomes the shared data; a staff machine waits for the owner;
    /// - the cloud holds data: this machine takes it. When it has data of its own, `confirmAdopt` is asked first and the
    ///   file is backed up (sao-luu/, 'truoc-dung-du-lieu-cloud'): the web's data is the reference.
    public static func link(_ queue: DatabaseQueue, backups: URL, _ session: CloudSession,
                            confirmAdopt: @escaping () async -> Bool) async throws -> Link {
        if try await queue.read({ try Replica.enabled($0) }) { return .already }
        let pulled = try await fetch(session.client, session.token, after: 0)
        if TwoWay.cloudEmpty(pulled) {
            if session.role != CloudApproval.owner { return .emptyCloud }
            try await queue.write { try TwoWay.startFromThisMachine($0) }
            return .uploaded
        }
        if try await queue.read({ try hasLocalData($0) }) {
            if !(await confirmAdopt()) { return .refused }
            _ = try Backups.named(queue, folder: backups, label: "truoc-dung-du-lieu-cloud")
        }
        try await queue.write { try TwoWay.startFromCloud($0) }
        return .adopted
    }
}
