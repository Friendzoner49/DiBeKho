import Foundation

public struct CloudTokens {
    public let access: String
    public let refresh: String
}

/// Python core/cloud/client.py: Supabase over plain HTTPS (GoTrue sign-in, PostgREST RPC, Storage). The project URL and
/// the publishable key are public by design; the service-role key never appears here. The error texts are the Python
/// app's, word for word. ⚠ Not run against a real Cloud yet.
public final class CloudClient {
    public static let bucket = "backups"
    public static let emailDomain = "dibekho.local"
    public static let timeout: TimeInterval = 40

    let base: String
    let key: String
    let timeout: TimeInterval

    public init(url: String, key: String, timeout: TimeInterval = CloudClient.timeout) {
        var base = url.trimmingCharacters(in: .whitespacesAndNewlines)
        while base.hasSuffix("/") { base.removeLast() }
        for suffix in ["/rest/v1", "/auth/v1"] where base.hasSuffix(suffix) {  // the user may paste the REST endpoint
            base = String(base.dropLast(suffix.count))
        }
        self.base = base
        self.key = key.trimmingCharacters(in: .whitespacesAndNewlines)
        self.timeout = timeout
    }

    public static func fullEmail(_ username: String) -> String {
        let name = username.trimmingCharacters(in: .whitespacesAndNewlines)
        return name.contains("@") ? name : "\(name)@\(emailDomain)"
    }

    /// '2026-11-11T09:36:52.9+00:00' (the cloud keeps UTC) -> '2026-11-11 12:36' in this machine's time zone.
    public static func localTime(_ iso: String?) -> String {
        let text = iso ?? ""
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let plain = ISO8601DateFormatter()
        if let date = formatter.date(from: text) ?? plain.date(from: text) {
            let out = DateFormatter()
            out.locale = Locale(identifier: "en_US_POSIX")
            out.dateFormat = "yyyy-MM-dd HH:mm"
            return out.string(from: date)
        }
        return String(text.prefix(16)).replacingOccurrences(of: "T", with: " ")
    }

    // ---- account

    public func signIn(username: String, password: String) async throws -> CloudTokens {
        try tokens(await post("/auth/v1/token?grant_type=password", ["email": Self.fullEmail(username), "password": password]))
    }

    /// Refresh tokens rotate: the caller must store the new refresh token.
    public func refresh(_ token: String) async throws -> CloudTokens {
        do {
            return try tokens(await post("/auth/v1/token?grant_type=refresh_token", ["refresh_token": token]))
        } catch let error as CloudError where error.message.lowercased().contains("refresh token") {
            throw CloudError("Phiên đăng nhập Cloud của máy này đã hết (có thể do bấm Đăng xuất trên web). "
                + "Vào Cài đặt → Cloud, gõ mật khẩu rồi bấm Đồng bộ ngay.", kind: .sessionExpired)
        }
    }

    public func rpc(_ name: String, _ args: [String: Any], _ token: String) async throws -> Any? {
        try await post("/rest/v1/rpc/\(name)", args, token)
    }

    public func get(_ path: String, _ token: String) async throws -> Any? { try await request("GET", path, nil, token) }

    public func patch(_ path: String, _ body: [String: Any], _ token: String) async throws -> Any? {
        try await request("PATCH", path, body, token)
    }

    private func tokens(_ data: Any?) throws -> CloudTokens {
        guard let object = data as? [String: Any], let access = object["access_token"] as? String, !access.isEmpty,
              let refresh = object["refresh_token"] as? String, !refresh.isEmpty
        else { throw CloudError("Cloud trả về dữ liệu đăng nhập không hiểu được.") }
        return CloudTokens(access: access, refresh: refresh)
    }

    // ---- Storage (private buckets: 'backups', 'inbox-files')

    static func quote(_ name: String) -> String {
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "_.-~/")
        return name.addingPercentEncoding(withAllowedCharacters: allowed) ?? name
    }

    public func storageUpload(_ name: String, _ data: Data, _ token: String, bucket: String = CloudClient.bucket) async throws {
        _ = try await raw("POST", "/storage/v1/object/\(bucket)/\(Self.quote(name))", data, token, "application/octet-stream")
    }

    public func storageList(_ token: String, bucket: String = CloudClient.bucket, prefix: String = "", limit: Int = 200,
                            offset: Int = 0) async throws -> [[String: Any]] {
        let rows = try await request("POST", "/storage/v1/object/list/\(bucket)",
                                     ["prefix": prefix, "limit": limit, "offset": offset,
                                      "sortBy": ["column": "name", "order": "desc"]], token)
        return (rows as? [[String: Any]]) ?? []
    }

    public func storageDownload(_ name: String, _ token: String, bucket: String = CloudClient.bucket) async throws -> Data {
        try await raw("GET", "/storage/v1/object/authenticated/\(bucket)/\(Self.quote(name))", nil, token)
    }

    public func storageDelete(_ names: [String], _ token: String, bucket: String = CloudClient.bucket) async throws {
        _ = try await request("DELETE", "/storage/v1/object/\(bucket)", ["prefixes": names], token)
    }

    // ---- plumbing

    private func post(_ path: String, _ body: [String: Any], _ token: String? = nil) async throws -> Any? {
        try await request("POST", path, body, token)
    }

    func raw(_ method: String, _ path: String, _ data: Data?, _ token: String?, _ contentType: String = "application/json") async throws -> Data {
        if base.isEmpty || key.isEmpty { throw CloudError("Chưa điền địa chỉ Cloud hoặc mã kết nối.") }
        guard let url = URL(string: base + path) else { throw CloudError("Chưa điền địa chỉ Cloud hoặc mã kết nối.") }
        var req = URLRequest(url: url, timeoutInterval: timeout)
        req.httpMethod = method
        req.httpBody = data
        req.setValue(key, forHTTPHeaderField: "apikey")
        req.setValue("Bearer \(token ?? key)", forHTTPHeaderField: "Authorization")
        req.setValue(contentType, forHTTPHeaderField: "Content-Type")
        do {
            let (body, response) = try await URLSession.shared.data(for: req)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                throw CloudError(Self.httpMessage(http.statusCode, body))
            }
            return body
        } catch let error as CloudError {
            throw error
        } catch {
            ActivityLog.write("error", "network \(method) \(path.components(separatedBy: "?")[0]): \(error)")  // the real cause
            throw CloudError("Không kết nối được Cloud. Kiểm tra mạng rồi thử lại.")
        }
    }

    private func request(_ method: String, _ path: String, _ body: [String: Any]?, _ token: String?) async throws -> Any? {
        let data = try body.map { try JSONSerialization.data(withJSONObject: $0) }
        let reply = try await raw(method, path, data, token)
        if reply.isEmpty { return nil }
        guard let object = try? JSONSerialization.jsonObject(with: reply, options: [.fragmentsAllowed]) else {
            throw CloudError("Cloud trả về dữ liệu không hiểu được.")
        }
        return object
    }

    /// A short Vietnamese line; the server's own words are appended for troubleshooting (never a token).
    static func httpMessage(_ code: Int, _ body: Data) -> String {
        var detail = ""
        if let object = (try? JSONSerialization.jsonObject(with: body)) as? [String: Any] {
            for k in ["error_description", "message", "msg", "error"] {
                if let v = object[k], !(v is NSNull), "\(v)" != "" { detail = "\(v)"; break }
            }
        }
        if detail.lowercased().contains("invalid login credentials") || ((code == 400 || code == 401) && detail.lowercased().contains("grant")) {
            return "Sai tên đăng nhập hoặc mật khẩu."
        }
        if code == 401 || code == 403 {
            return "Cloud từ chối truy cập (\(detail.isEmpty ? String(code) : detail)). Kiểm tra tài khoản và vai trò."
        }
        return "Cloud báo lỗi \(code): \(detail.isEmpty ? "không rõ" : detail)"
    }
}
