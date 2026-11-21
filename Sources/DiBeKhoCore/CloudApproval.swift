import CryptoKit
import Foundation
import GRDB

/// Python core/cloud/approval.py: a staff account ('editor') never writes the shared data; it sends its whole queue as one
/// request with a summary, and the owner ('desktop') approves or refuses it. The network calls touch no database.
public enum CloudApproval {
    public static let owner = "desktop", staff = "editor"
    static let sentKey = "staff_sent_hash"  // per machine: the queue as it was last sent for approval
    static let stateKey = "staff_request"  // per machine: JSON of the newest request's state, for the screens
    static let docKinds = ["delivery", "receipt", "stock_count", "transfer", "trial"]
    public static let stale = "__stale__"

    // ---- the staff machine

    static func json(_ batch: [String: [CloudRow]]) -> [String: Any] {
        var out: [String: Any] = [:]
        for (name, rows) in batch { out[name] = rows.map { CloudJSON.any($0) } }
        return out
    }

    public static func batchHash(_ batch: [String: [CloudRow]]) -> String {
        let data = (try? JSONSerialization.data(withJSONObject: json(batch), options: [.sortedKeys, .withoutEscapingSlashes])) ?? Data()
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    /// What the owner reads before approving: the documents, products and customers added or changed, and how many other rows.
    public static func summarize(_ db: Database, _ batch: [String: [CloudRow]]) throws -> [[String: Any]] {
        func deleted(_ r: CloudRow) -> Bool { r["deleted"]?.isTrue ?? false }
        var out: [[String: Any]] = []
        var customers: [String: String] = [:]  // id -> name
        var customerOrder: [String] = []
        for r in batch["customers"] ?? [] where !deleted(r) {
            let id = r["id"]?.string ?? ""
            if customers[id] == nil { customerOrder.append(id) }
            customers[id] = r["name"]?.string ?? ""
        }
        var lines: [String: Int] = [:]
        for r in batch["document_lines"] ?? [] where !deleted(r) {
            if let d = r["document_id"]?.string, !d.isEmpty { lines[d, default: 0] += 1 }
        }
        for r in batch["documents"] ?? [] {
            if deleted(r) { out.append(["t": "doc_deleted"]); continue }
            var name = customers[r["customer_id"]?.string ?? ""]
            if name == nil, let c = r["customer_id"]?.string, !c.isEmpty {
                if let local = try Replica.localFor(db, "customers", c) {
                    name = try String.fetchOne(db, sql: "SELECT name FROM customers WHERE id = ?", arguments: [local]) ?? ""
                } else { name = "" }
            }
            let kind = r["kind"]?.string ?? ""
            out.append(["t": "doc", "kind": docKinds.contains(kind) ? kind : "", "code": r["code"]?.string ?? "",
                        "date": String((r["doc_date"]?.string ?? "").prefix(10)), "customer": name ?? "",
                        "status": r["status"]?.string ?? "", "lines": lines[r["id"]?.string ?? ""] ?? 0])
        }
        for r in batch["products"] ?? [] {
            if deleted(r) { out.append(["t": "product_deleted"]); continue }
            let parts = [r["name_vi"]?.string, r["variant"]?.string].compactMap { $0 }.filter { !$0.isEmpty }
            out.append(["t": "product", "code": r["code"]?.string ?? "",
                        "name": parts.isEmpty ? (r["name_zh"]?.string ?? "") : parts.joined(separator: " ")])
        }
        for id in customerOrder { out.append(["t": "customer", "name": customers[id] ?? ""]) }
        var rest = ["suppliers", "product_aliases", "ignored_lines", "meta"].reduce(0) { $0 + (batch[$1]?.count ?? 0) }
        rest += (batch["customers"] ?? []).filter { deleted($0) }.count
        if rest > 0 { out.append(["t": "other", "n": rest]) }
        return out
    }

    public static func state(_ db: Database) throws -> [String: Any] { try object(db, stateKey) }

    static func object(_ db: Database, _ key: String) throws -> [String: Any] {
        let text = try Meta.get(db, key, "")
        guard !text.isEmpty, let data = text.data(using: .utf8),
              let any = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [:] }
        return any
    }

    static func setState(_ db: Database, status: String, reason: String, at: String) throws {
        let data = try JSONSerialization.data(withJSONObject: ["status": status, "reason": reason, "at": at])
        try Meta.set(db, stateKey, String(decoding: data, as: UTF8.self))
    }

    /// {"hash", "seq", "id"} of the request last sent from here ({} = none waiting).
    static func sentInfo(_ db: Database) throws -> [String: Any] { try object(db, sentKey) }

    /// The queue differs from what was last sent (a refused request is not sent again unchanged).
    public static func needsSending(_ db: Database, _ batch: [String: [CloudRow]]) throws -> Bool {
        if TwoWay.isEmpty(batch) { return false }
        let last = try sentInfo(db)["hash"] as? String
        return last != batchHash(batch)
    }

    public static func send(_ client: CloudClient, _ token: String, device: String, baseRev: Int,
                            batch: [String: [CloudRow]], summary: [[String: Any]]) async throws -> Any? {
        try await client.rpc("push_request_send", ["p_device": device, "p_base": baseRev, "p_batch": json(batch), "p_summary": summary], token)
    }

    /// This machine's newest request on the cloud, or nil.
    public static func mine(_ client: CloudClient, _ token: String, device: String) async throws -> [String: Any]? {
        try await client.rpc("push_request_mine", ["p_device": device], token) as? [String: Any]
    }

    /// After send(): remember which queue entries (up to seq) the request carries.
    public static func sent(_ db: Database, batch: [String: [CloudRow]], seq: Int, answer: Any?) throws {
        let id = (answer as? [String: Any])?["id"] ?? NSNull()
        let data = try JSONSerialization.data(withJSONObject: ["hash": batchHash(batch), "seq": seq, "id": id])
        try Meta.set(db, sentKey, String(decoding: data, as: UTF8.self))
        try setState(db, status: "pending", reason: "", at: "")
    }

    /// What the cloud says about this machine's newest request, taken BEFORE merging the pull of the same round.
    /// Returns true when what the screens show changed.
    public static func takeAnswer(_ db: Database, _ request: [String: Any]?) throws -> Bool {
        let before = try state(db), info = try sentInfo(db)
        let infoId = info["id"] as? String ?? ""
        let mineNow = request != nil && !infoId.isEmpty && (request?["id"] as? String) == infoId
        var status = mineNow ? "\(request?["status"] ?? "")" : ""
        var reason = mineNow ? "\(request?["reason"] ?? "")" : ""
        if status == "<null>" { status = "" }
        if reason == "<null>" { reason = "" }
        if mineNow && status == "approved" {
            try Replica.clearOutbox(db, upTo: (info["seq"] as? NSNumber)?.intValue ?? 0, keep: try TwoWay.held(db))
            try Meta.set(db, sentKey, "")
            status = ""
        } else if mineNow && status == "rejected" && reason == stale {
            try Meta.set(db, sentKey, "")
            status = ""; reason = ""
        } else if !mineNow && !infoId.isEmpty && request == nil {
            try Meta.set(db, sentKey, "")  // the request is gone (deleted on the cloud): send again
        }
        var at = ""
        if mineNow { at = "\(request?["decided_at"] ?? request?["created_at"] ?? "")" }
        let changed = (before["status"] as? String ?? "") != status || (before["reason"] as? String ?? "") != reason
        if changed { try setState(db, status: status, reason: reason, at: at) }
        return changed
    }

    /// Nothing queued here any more: no request is waiting.
    public static func forgetAnswerIfIdle(_ db: Database) throws {
        let status = try state(db)["status"] as? String ?? ""
        let info = try sentInfo(db)
        let queued = try TwoWay.queuedCount(db)
        if queued == 0 && (!status.isEmpty || !info.isEmpty) {
            try Meta.set(db, sentKey, "")
            try setState(db, status: "", reason: "", at: "")
        }
    }

    /// Give up everything this machine did that the owner has not approved (the caller backed the file up first).
    public static func discard(_ db: Database) throws {
        try TwoWay.startFromCloud(db)
        try Meta.set(db, sentKey, "")
        try setState(db, status: "", reason: "", at: "")
    }

    public static func cancel(_ client: CloudClient, _ token: String, device: String) async throws {
        _ = try await client.rpc("push_request_cancel", ["p_device": device], token)
    }

    // ---- the owner

    /// Requests waiting for the owner, oldest first: {id, sender, device, summary, created_at}.
    public static func pending(_ client: CloudClient, _ token: String) async throws -> [[String: Any]] {
        let rows = try await client.rpc("push_requests_pending", [:], token)
        return ((rows as? [Any]) ?? []).compactMap { $0 as? [String: Any] }
    }

    /// -> ["ok": true] | ["ok": false, "reason": "gone" | "stale"]
    public static func decide(_ client: CloudClient, _ token: String, id: String, approve: Bool, reason: String = "") async throws -> [String: Any] {
        let answer = try await client.rpc("push_request_decide", ["p_id": id, "p_approve": approve, "p_reason": reason], token)
        return (answer as? [String: Any]) ?? ["ok": false, "reason": "gone"]
    }
}
