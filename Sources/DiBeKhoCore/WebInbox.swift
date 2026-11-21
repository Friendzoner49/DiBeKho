import CryptoKit
import Foundation
import GRDB
import ZIPFoundation

/// Python core/cloud/inbox.py: requests staff send from the web page, pulled by the desktop and approved by the owner.
/// Three kinds: a goods-in slip (`receipt`), an Excel delivery note (`delivery_file`, only put in phieu-giao-hang/ so the
/// normal scan reads it) and a physical count (`stock_count`, recorded as of the moment it was SENT). Nothing reaches the
/// books before the owner approves. The link request -> document lives in meta, so it travels with data packages.
/// ⚠ No golden: the checks and the error texts are the Python ones word for word, the network was never run for real.
public struct WebRequest {
    public let id: String
    public let kind: String
    public let createdAt: String
    public let createdBy: String
    public let payload: [String: Any]
    public var sender = ""
    public var senderRole = ""

    public init?(_ json: [String: Any]) {
        guard let id = json["id"] as? String, let kind = json["kind"] as? String else { return nil }
        self.id = id
        self.kind = kind
        createdAt = (json["created_at"] as? String) ?? ""
        createdBy = (json["created_by"] as? String) ?? ""
        payload = (json["payload"] as? [String: Any]) ?? [:]
    }

    /// When the request reached the cloud, as this machine's local time (like the database's created_at).
    public var sentAt: Date { WebInbox.parseTime(createdAt) ?? Date() }
}

public struct CountLine: Equatable {
    public let productId: Int64
    public let code: String
    public let name: String
    public let counted: Double
    public let system: Double  // what the app knew at the moment the request was sent
    public var diff: Double { counted - system }
}

public enum WebInbox {
    public static let receipt = "receipt", deliveryFile = "delivery_file", stockCount = "stock_count"
    public static let kinds = [receipt, deliveryFile, stockCount]
    public static let filesBucket = "inbox-files"
    public static let maxFile = 2 * 1024 * 1024
    public static let maxUnzipped = 50 * 1024 * 1024
    static let metaKey = "cloud_inbox_applied"  // {"<request uuid>": document id}

    // ---- the link request -> document

    public static func appliedMap(_ db: Database) throws -> [String: Int64] {
        let text = try Meta.get(db, metaKey, "{}")
        let object = try? JSONSerialization.jsonObject(with: Data(text.utf8))
        var out: [String: Int64] = [:]
        for (k, v) in (object as? [String: Any]) ?? [:] { if let n = v as? NSNumber { out[k] = n.int64Value } }
        return out
    }

    static func storeApplied(_ db: Database, _ map: [String: Int64]) throws {
        let data = try JSONSerialization.data(withJSONObject: map, options: [.sortedKeys])
        try Meta.set(db, metaKey, String(decoding: data, as: UTF8.self))
    }

    static func remember(_ db: Database, _ item: WebRequest, doc: Int64) throws {
        var m = try appliedMap(db)
        m[item.id] = doc
        try storeApplied(db, m)
        try Meta.log(db, "web_inbox_applied", "\(item.id.prefix(8)) -> #\(doc)")
    }

    // ---- small readers of the JSON the web sends (Python float(), int(), date.fromisoformat())

    static func parseTime(_ iso: String) -> Date? {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: iso) { return d }
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: iso)
    }

    /// 'YYYY-MM-DD HH:MM:SS' in this machine's local time (the form of documents.created_at).
    static func stamp(_ date: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return f.string(from: date)
    }

    static func day(_ any: Any?) -> String? {
        guard let s = any as? String, s.count == 10 else { return nil }
        let parts = s.split(separator: "-", omittingEmptySubsequences: false).map(String.init)
        guard parts.count == 3, parts[0].count == 4, parts[1].count == 2, parts[2].count == 2,
              let y = Int(parts[0]), let m = Int(parts[1]), let d = Int(parts[2]) else { return nil }
        var c = DateComponents()
        c.year = y; c.month = m; c.day = d
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0) ?? .current
        guard let date = calendar.date(from: c), calendar.dateComponents([.year, .month, .day], from: date) == c
        else { return nil }
        return s
    }

    static func double(_ any: Any?) -> Double? {
        switch any {
        case let n as NSNumber:
            if CFGetTypeID(n) == CFBooleanGetTypeID() { return nil }
            return n.doubleValue
        case let s as String:
            return Double(s.trimmingCharacters(in: .whitespaces))
        default: return nil
        }
    }

    static func integer(_ any: Any?) -> Int64? {
        guard let n = any as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID() else { return nil }
        let d = n.doubleValue
        return d == d.rounded() ? n.int64Value : nil
    }

    static func text(_ any: Any?) -> String {
        switch any {
        case nil, is NSNull: return ""
        case let s as String: return s
        case let n as NSNumber: return CFGetTypeID(n) == CFBooleanGetTypeID() ? (n.boolValue ? "True" : "False") : "\(n)"
        default: return "\(any!)"
        }
    }

    struct Unreadable: Error {}

    /// An id the web sent: the shared data's uuid or this database's own number. Unknown uuid gives -1; neither throws.
    static func localId(_ db: Database, _ table: String, _ value: Any?) throws -> Int64 {
        let t = text(value)
        if t.contains("-") { return try Replica.localFor(db, table, t) ?? -1 }
        guard let n = Int64(t.trimmingCharacters(in: .whitespaces)) else { throw Unreadable() }
        return n
    }

    // ---- pulling

    public static func fetchPending(_ client: CloudClient, _ token: String, seen: [String: Int64]) async throws -> [WebRequest] {
        let rows = (try await client.get("/rest/v1/web_inbox?status=eq.pending&order=created_at", token) as? [[String: Any]]) ?? []
        var items = rows.compactMap { WebRequest($0) }.filter { seen[$0.id] == nil && kinds.contains($0.kind) }
        if !items.isEmpty {
            let who = await senderInfo(client, token)
            for i in items.indices {
                let known = who[items[i].createdBy]
                items[i].sender = known?.name ?? ""
                items[i].senderRole = known?.role ?? ""
            }
        }
        return items
    }

    /// {user id: (name, role)}; empty when the profiles cannot be read (then no one is treated as the owner).
    static func senderInfo(_ client: CloudClient, _ token: String) async -> [String: (name: String, role: String)] {
        guard let rows = (try? await client.get("/rest/v1/profiles?select=user_id,display_name,role", token)) as? [[String: Any]]
        else { return [:] }
        var out: [String: (name: String, role: String)] = [:]
        for r in rows {
            if let id = r["user_id"] as? String, !id.isEmpty {
                out[id] = ((r["display_name"] as? String) ?? "", (r["role"] as? String) ?? "")
            }
        }
        return out
    }

    // ---- receipt

    public static func receiptInput(_ db: Database, _ p: [String: Any]) throws -> (Receipts.Input, [String]) {
        var errors: [String] = []
        var docDate = Dates.today
        if let given = day(p["doc_date"]) { docDate = given } else { errors.append("Ngày không hợp lệ.") }
        let wanted = integer(p["location_id"])
        let location = wanted.flatMap { Ledger.locations.contains($0) ? $0 : nil } ?? Ledger.main
        var lines: [Receipts.LineInput] = []
        var unpriced: [Int] = []
        for case let raw as [String: Any] in (p["lines"] as? [Any]) ?? [] {
            guard let productId = try? localId(db, "products", raw["product_id"]), let qty = double(raw["qty"]), qty.isFinite
            else {
                errors.append("Có dòng hàng không đọc được.")
                continue
            }
            let code = text(raw["code"])
            guard let row = try Row.fetchOne(db, sql: "SELECT code, active FROM products WHERE id = ?", arguments: [productId])
            else {
                let shown = code.isEmpty ? "#" + text(raw["product_id"]) : code
                errors.append("Mặt hàng \(shown) không còn trong danh mục (đã xoá hoặc gộp).")
                continue
            }
            let have: String = row["code"]
            if !code.isEmpty && code != have {  // the web sends the code it saw: the id may mean another product now
                errors.append("Mặt hàng \(code) đã thay đổi trên máy chính (có thể đã Hoàn tác). Hãy tải lại trang web.")
                continue
            }
            if qty <= 0 {
                errors.append("Số lượng của \(have) phải lớn hơn 0.")
                continue
            }
            var line = Receipts.LineInput(qty, productId, note: TextRules.clean(text(raw["note"])))
            if raw.keys.contains("unit_price") {  // a return typed on the web carries its price
                let value = raw["unit_price"]
                let price = (value is NSNull || text(value).isEmpty) ? nil : double(value)
                line.unitPrice = (price ?? 0) < 0 ? nil : price
            } else {
                unpriced.append(lines.count)  // an older page: priced below like the app's own form does
            }
            lines.append(line)
        }
        if lines.isEmpty { errors.append("Phiếu không có dòng hàng nào dùng được.") }
        let asked = text(p["source"])
        let source = Receipts.sources.contains(asked) ? asked : Receipts.supplier
        var customerId: Int64?
        var customerName = ""
        if source == Receipts.customerReturn {  // goods a customer sent back
            if let raw = p["customer_id"], !(raw is NSNull) {
                let cid = (try? localId(db, "customers", raw)) ?? -1
                if let found = try Int64.fetchOne(db, sql: "SELECT id FROM customers WHERE id = ?", arguments: [cid]) {
                    customerId = found
                } else {
                    errors.append("Khách hàng không còn trong danh sách (có thể đã gộp).")
                }
            }
            customerName = TextRules.clean(text(p["customer_name"]))
            if customerId == nil && customerName.isEmpty { errors.append("Hãy chọn khách hàng trả lại hàng.") }
            for i in unpriced {
                lines[i].unitPrice = try Receipts.returnPrice(db, customerId: customerId, productId: lines[i].productId,
                                                              refCode: TextRules.clean(text(p["ref_code"])), on: docDate)
            }
        }
        var supplier = ""
        if Receipts.named.contains(source) {
            let name = TextRules.clean(text(p["supplier_name"]))
            supplier = name.isEmpty ? "Web" : name
        }
        let data = Receipts.Input(
            date: docDate, source: source, supplierName: supplier, customerName: customerName, customerId: customerId,
            refCode: source == Receipts.customerReturn ? TextRules.clean(text(p["ref_code"])) : "",
            note: TextRules.clean(text(p["note"])), lines: lines, locationId: location)
        if errors.isEmpty && !Receipts.problems(data).isEmpty {
            errors.append("Phiếu hàng về chưa đủ thông tin (kiểm tra mặt hàng bị lặp hoặc thiếu nguồn hàng).")
        }
        return (data, errors)
    }

    /// One line per goods line, for the confirm dialog.
    public static func describe(_ db: Database, _ item: WebRequest) throws -> String {
        let (data, _) = try receiptInput(db, item.payload)
        var out: [String] = []
        for ln in data.lines {
            let row = try ln.productId.flatMap {
                try Row.fetchOne(db, sql: "SELECT code, name_vi, spec FROM products WHERE id = ?", arguments: [$0])
            }
            var label = "#\(ln.productId ?? 0)"
            if let row {
                let (code, name, spec): (String, String, String) = (row["code"], row["name_vi"], row["spec"])
                label = "\(code) \(name) \(spec)".trimmingCharacters(in: .whitespaces)
            }
            var money = ""
            if data.source == Receipts.customerReturn, let price = ln.unitPrice {  // money off the revenue: seen before approving
                money = " × \(Format.showMoney(price)) = \(Format.showMoney(Receipts.lineAmount(ln.qty, price)))"
            }
            out.append("• \(label): \(String(format: "%g", ln.qty))\(money)")
        }
        return out.joined(separator: "\n")
    }

    /// Record the receipt through the normal business path, then remember request -> document. The Excel file is made
    /// after (a file open in Excel is no reason to lose the receipt); its failure is returned, not thrown.
    public static func applyReceipt(_ queue: DatabaseQueue, _ folders: ShopFolders, _ item: WebRequest) throws -> (doc: Int64, file: URL?) {
        let doc = try queue.write { db -> Int64 in
            let (data, errors) = try receiptInput(db, item.payload)
            if !errors.isEmpty { throw WriteError(errors.joined(separator: " ")) }
            let id = try Receipts.save(db, data, outputFolder: folders.output)
            try remember(db, item, doc: id)
            return id
        }
        let file = try? queue.write { try Receipts.exportFile($0, folders, docId: doc) }
        return (doc, file)
    }

    // ---- delivery note file

    static let storagePath = try! NSRegularExpression(pattern: "^[0-9a-fA-F-]{36}/[^/\\\\]{1,200}$")

    static func matches(_ regex: NSRegularExpression, _ s: String) -> Bool {
        regex.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) != nil
    }

    /// The uploader's file name, made safe to put in the delivery folder (no path, no odd characters).
    public static func safeFileName(_ name: String) -> String {
        let base = (name as NSString).lastPathComponent
        let replaced = String(base.unicodeScalars.map { s -> Character in
            let bad = s.value < 0x20 || "<>:\"/\\|?*".unicodeScalars.contains(s)
            return bad ? "_" : Character(s)
        })
        let trimmed = replaced.trimmingCharacters(in: CharacterSet(charactersIn: " ."))
        let stem = trimmed.lowercased().hasSuffix(".xlsx") ? String(trimmed.dropLast(5)) : trimmed
        return (stem.isEmpty ? "phieu-web" : stem) + ".xlsx"
    }

    public static func checkDelivery(_ item: WebRequest) -> [String] {
        let p = item.payload
        var errors: [String] = []
        if !matches(storagePath, text(p["file_path"])) { errors.append("Đường dẫn file trên Cloud không hợp lệ.") }
        if !text(p["file_name"]).lowercased().hasSuffix(".xlsx") { errors.append("Chỉ nhận file Excel .xlsx.") }
        if let size = integer(p["size"]), size > 0, size <= Int64(maxFile) {} else {
            errors.append("Kích thước file không hợp lệ (tối đa 2 MB).")
        }
        let sha = text(p["sha256"])
        if !sha.isEmpty && !(sha.count == 64 && sha.lowercased().allSatisfy { $0.isHexDigit }) {
            errors.append("Mã kiểm tra của file không hợp lệ.")
        }
        return errors
    }

    static func knownHash(_ queue: DatabaseQueue, _ digest: String) throws -> String? {
        try queue.read { try String.fetchOne($0, sql: "SELECT status FROM scanned_files WHERE hash = ?", arguments: [digest]) }
    }

    static func freePath(_ folder: URL, _ name: String) -> URL {
        var target = folder.appendingPathComponent(name)
        let stem = (name as NSString).deletingPathExtension
        var n = 2
        while FileManager.default.fileExists(atPath: target.path) {
            target = folder.appendingPathComponent("\(stem) (\(n)).xlsx")
            n += 1
        }
        return target
    }

    static func checkXlsx(_ data: Data) throws {
        let bad = WriteError("File không phải Excel .xlsx hợp lệ.")
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent("dibekho-\(UUID().uuidString).zip")
        defer { try? FileManager.default.removeItem(at: temp) }
        do { try data.write(to: temp) } catch { throw bad }
        guard let archive = try? Archive(url: temp, accessMode: .read) else { throw bad }
        var hasWorkbook = false
        var total: UInt64 = 0
        for entry in archive {
            if entry.path == "xl/workbook.xml" { hasWorkbook = true }
            total += UInt64(entry.uncompressedSize)
        }
        if !hasWorkbook { throw bad }
        if total > UInt64(maxUnzipped) { throw WriteError("File Excel giải nén ra quá lớn, không nhận.") }
    }

    /// Now with this machine's offset (Python datetime.now().astimezone().isoformat): the cloud column is a timestamptz.
    static func nowIso() -> String {
        let f = ISO8601DateFormatter()
        f.timeZone = .current
        f.formatOptions = [.withInternetDateTime]
        return f.string(from: Date())
    }

    /// Mark the request applied and drop the uploaded copy. Best effort: the file is already safe in the delivery folder.
    static func confirmFile(_ client: CloudClient, _ token: String, _ item: WebRequest, _ result: [String: Any]) async {
        do {
            _ = try await client.patch("/rest/v1/web_inbox?id=eq.\(item.id)",
                                       ["status": "applied", "result": result, "applied_at": nowIso()], token)
            try await client.storageDelete([text(item.payload["file_path"])], token, bucket: filesBucket)
        } catch {
            ActivityLog.write("error", "cloud inbox confirm file: \(error.localizedDescription)")
        }
    }

    /// Put the uploaded note into phieu-giao-hang/ (the caller then scans). placed is nil, with the status, when the app
    /// already has a note with this content.
    public static func applyDelivery(_ queue: DatabaseQueue, _ folders: ShopFolders, _ client: CloudClient, _ token: String,
                                     _ item: WebRequest) async throws -> (placed: URL?, status: String?) {
        let errors = checkDelivery(item)
        if !errors.isEmpty { throw WriteError(errors.joined(separator: " ")) }
        let p = item.payload
        let want = text(p["sha256"]).lowercased()
        if !want.isEmpty, let status = try knownHash(queue, want) {
            await confirmFile(client, token, item, ["already": true, "hash": want, "status": status])
            return (nil, status)
        }
        let data = try await client.storageDownload(text(p["file_path"]), token, bucket: filesBucket)
        if data.count > maxFile { throw WriteError("File quá lớn (tối đa 2 MB).") }
        let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        if !want.isEmpty && digest != want {
            throw WriteError("File tải về bị lỗi (mã kiểm tra không khớp). Hãy nhờ nhân viên gửi lại.")
        }
        try checkXlsx(data)
        if let status = try knownHash(queue, digest) {
            await confirmFile(client, token, item, ["already": true, "hash": digest, "status": status])
            return (nil, status)
        }
        try FileManager.default.createDirectory(at: folders.deliveries, withIntermediateDirectories: true)
        let target = freePath(folders.deliveries, safeFileName(text(p["file_name"])))
        try data.write(to: target)
        await confirmFile(client, token, item, ["file": target.lastPathComponent, "hash": digest])
        return (target, nil)
    }

    // ---- stock count

    /// (count date, place, [(product, counted)], reasons it cannot be applied)
    public static func checkCount(_ db: Database, _ item: WebRequest) throws -> (String, Int64, [(Int64, Double)], [String]) {
        let p = item.payload
        var errors: [String] = []
        let sentDay = String(stamp(item.sentAt).prefix(10))
        var countDay = day(p["count_date"]) ?? ""
        if countDay.isEmpty {
            errors.append("Ngày kiểm kê không hợp lệ.")
            countDay = sentDay
        }
        if countDay > sentDay { errors.append("Ngày kiểm kê ở tương lai.") }
        var location = Ledger.main
        if let l = integer(p["location_id"]), Ledger.locations.contains(l) {
            location = l
        } else {
            errors.append("Nơi kiểm kê không hợp lệ.")
        }
        var lines: [(Int64, Double)] = []
        var seen = Set<Int64>()
        for case let raw as [String: Any] in (p["lines"] as? [Any]) ?? [] {
            guard let productId = try? localId(db, "products", raw["product_id"]), let qty = double(raw["qty"]) else {
                errors.append("Có dòng kiểm kê không đọc được.")
                continue
            }
            let code = text(raw["code"])
            if let have = try String.fetchOne(db, sql: "SELECT code FROM products WHERE id = ?", arguments: [productId]) {
                if !code.isEmpty && code != have {
                    errors.append("Mặt hàng \(code) đã thay đổi trên máy chính (có thể đã Hoàn tác). Hãy tải lại trang web.")
                } else if qty < 0 || qty.isNaN {
                    errors.append("Số đếm của \(have) không được âm.")
                } else if seen.contains(productId) {
                    errors.append("Mặt hàng \(have) xuất hiện hai lần.")
                } else {
                    seen.insert(productId)
                    lines.append((productId, qty))
                }
            } else {
                let shown = code.isEmpty ? "#" + text(raw["product_id"]) : code
                errors.append("Mặt hàng \(shown) không còn trong danh mục (đã xoá hoặc gộp).")
            }
        }
        if lines.isEmpty { errors.append("Phiếu kiểm kê không có dòng nào dùng được.") }
        return (countDay, location, lines, errors)
    }

    /// Counted vs the system's stock at the moment of sending, product by product.
    public static func countPreview(_ db: Database, _ item: WebRequest) throws -> [CountLine] {
        let (countDay, location, lines, _) = try checkCount(db, item)
        let levels = try Ledger.levelsByPlace(db, asOf: countDay, createdUntil: stamp(item.sentAt))
        var out: [CountLine] = []
        for (productId, qty) in lines {
            guard let p = try Row.fetchOne(db, sql: "SELECT code, name_vi, spec, variant FROM products WHERE id = ?",
                                           arguments: [productId]) else { continue }
            let parts = [p["name_vi"] as String, p["spec"] as String, p["variant"] as String].filter { !$0.isEmpty }
            out.append(CountLine(productId: productId, code: p["code"], name: parts.joined(separator: " · "), counted: qty,
                                 system: levels[Ledger.PlaceKey(productId, location)] ?? 0))
        }
        return out
    }

    public static func applyCount(_ queue: DatabaseQueue, _ item: WebRequest) throws -> Int64 {
        try queue.write { db in
            let (countDay, location, lines, errors) = try checkCount(db, item)
            if !errors.isEmpty { throw WriteError(errors.joined(separator: " ")) }
            let who = TextRules.clean(item.sender)
            let note = TextRules.clean("Kiểm kê từ web (\(who.isEmpty ? "nhân viên" : who)). \(text(item.payload["note"]))")
            let id = try Ledger.stockCount(db, date: countDay, counted: lines.map { Ledger.Counted($0.0, location, $0.1) },
                                           note: note, at: stamp(item.sentAt))
            try remember(db, item, doc: id)
            return id
        }
    }

    // ---- rejecting, confirming

    public static func reject(_ client: CloudClient, _ token: String, _ item: WebRequest, reason: String = "") async throws {
        _ = try await client.patch("/rest/v1/web_inbox?id=eq.\(item.id)",
                                   ["status": "rejected", "result": ["reason": reason], "applied_at": nowIso()], token)
        let path = text(item.payload["file_path"])
        if item.kind == deliveryFile && !path.isEmpty && matches(storagePath, path) {
            do {
                try await client.storageDelete([path], token, bucket: filesBucket)
            } catch {
                ActivityLog.write("error", "cloud inbox drop rejected file: \(error.localizedDescription)")
            }
        }
    }

    /// Once the approved documents are on the cloud: confirm each locally applied request whose document still exists;
    /// one undone in the meantime is forgotten here and comes back as pending on the next pull. Progress is saved per request.
    @discardableResult
    public static func finishApplied(_ queue: DatabaseQueue, _ client: CloudClient, _ token: String) async throws -> Int {
        var confirmed = 0
        let map = try await queue.read { try appliedMap($0) }
        for (itemId, docId) in map {
            let row = try await queue.read { try Row.fetchOne($0, sql: "SELECT kind, code, created_at FROM documents WHERE id = ?", arguments: [docId]) }
            if let row {
                let kind: String = row["kind"]
                let result: [String: Any] = kind == "receipt" ? ["doc_id": docId, "code": row["code"] as String? ?? ""]
                    : ["doc_id": docId, "stamp": row["created_at"] as String? ?? ""]  // a count has no code: its time identifies it
                _ = try await client.patch("/rest/v1/web_inbox?id=eq.\(itemId)",
                                           ["status": "applied", "result": result, "applied_at": nowIso()], token)
                confirmed += 1
            }
            try await queue.write { db in
                var m = try appliedMap(db)
                m.removeValue(forKey: itemId)
                try storeApplied(db, m)
            }
        }
        return confirmed
    }

    /// Requests shown as recorded whose document is no longer in this database (an Undo, a restore or a package replaced
    /// the data) go back to pending. Delivery files are not reconciled: the scan reads the file again on its own.
    @discardableResult
    public static func reconcileApplied(_ queue: DatabaseQueue, _ client: CloudClient, _ token: String, limit: Int = 50) async throws -> Int {
        let rows = (try await client.get("/rest/v1/web_inbox?status=eq.applied&order=applied_at.desc&limit=\(limit)", token) as? [[String: Any]]) ?? []
        var back = 0
        for row in rows {
            let result = (row["result"] as? [String: Any]) ?? [:]
            let exists: Bool
            if (row["kind"] as? String) == stockCount, let at = result["stamp"] as? String, !at.isEmpty {
                // by its time only: doc_id is the approving machine's own number
                exists = try await queue.read { try Row.fetchOne($0, sql: "SELECT 1 FROM documents WHERE kind = 'stock_count' AND created_at = ?", arguments: [at]) != nil }
            } else if let code = result["code"] as? String, !code.isEmpty {
                exists = try await queue.read { try Row.fetchOne($0, sql: "SELECT 1 FROM documents WHERE kind = 'receipt' AND code = ?", arguments: [code]) != nil }
            } else {
                continue
            }
            if !exists, let id = row["id"] as? String {
                _ = try await client.patch("/rest/v1/web_inbox?id=eq.\(id)",
                                           ["status": "pending", "result": NSNull(), "applied_at": NSNull()], token)
                back += 1
            }
        }
        return back
    }
}
