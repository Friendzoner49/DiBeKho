import Foundation
import GRDB

/// One product as the write screens list it (Python catalog.products rows).
public struct Product: Equatable, Identifiable {
    public let id: Int64
    public let code: String
    public let nameVi: String
    public let nameZh: String
    public let spec: String
    public let variant: String
    public let unit: String
    public let category: String
    public let stockNote: String
    public let active: Bool

    init(_ row: Row) {
        id = row["id"]
        code = row["code"] ?? ""
        nameVi = row["name_vi"] ?? ""
        nameZh = row["name_zh"] ?? ""
        spec = row["spec"] ?? ""
        variant = row["variant"] ?? ""
        unit = row["unit"] ?? ""
        category = row["category"] ?? ""
        stockNote = row["stock_note"] ?? ""
        active = (row["active"] as Int?) ?? 1 != 0
    }

    /// 'SP003 · Sơn FS-101 · 10KG · Xám nhạt' (Python catalog.label).
    public var label: String { [code, nameVi, spec, variant].filter { !$0.isEmpty }.joined(separator: " · ") }

    /// label plus the Chinese name (Python catalog.long_label).
    public var longLabel: String { label + (!nameZh.isEmpty && nameZh != nameVi ? " · \(nameZh)" : "") }

    /// What the product picker searches in (Python ProductPicker).
    public var haystack: String { [code, nameVi, spec, variant, nameZh, category].joined(separator: " ") }
}

extension Catalog {
    /// Active products (or all), ordered as in the Python app: category, name, packing, type.
    public static func products(_ db: Database, includeInactive: Bool = false) throws -> [Product] {
        try Row.fetchAll(db, sql: "SELECT * FROM products" + (includeInactive ? "" : " WHERE active = 1")
                         + " ORDER BY category, name_vi, spec, variant").map(Product.init)
    }

    public static func product(_ db: Database, id: Int64) throws -> Product? {
        try Row.fetchOne(db, sql: "SELECT * FROM products WHERE id = ?", arguments: [id]).map(Product.init)
    }

    public static func categories(_ db: Database) throws -> [String] {
        try String.fetchAll(db, sql: "SELECT DISTINCT category FROM products WHERE category <> '' ORDER BY category")
    }

    /// Same name + packing + type (and category, when given), ignoring accents (Python catalog.find_same).
    public static func findSame(_ db: Database, nameVi: String, spec: String, variant: String,
                                category: String? = nil) throws -> Product? {
        var sql = "SELECT * FROM products WHERE unaccent(name_vi) = ? AND unaccent(spec) = ? AND unaccent(variant) = ?"
        var args: StatementArguments = [TextRules.unaccent(TextRules.clean(nameVi)), TextRules.unaccent(TextRules.clean(spec)),
                                        TextRules.unaccent(TextRules.clean(variant))]
        if let category {
            sql += " AND unaccent(category) = ?"
            args += [TextRules.unaccent(TextRules.clean(category))]
        }
        return try Row.fetchOne(db, sql: sql, arguments: args).map(Product.init)
    }

    /// The note kept with a product's stock (Tồn kho and Kiểm kê). Returns true when it changed.
    @discardableResult
    public static func saveStockNote(_ db: Database, productId: Int64, text: String) throws -> Bool {
        let text = TextRules.clean(text)
        guard let row = try Row.fetchOne(db, sql: "SELECT code, stock_note FROM products WHERE id = ?", arguments: [productId]),
              (row["stock_note"] as String?) != text else { return false }
        try db.execute(sql: "UPDATE products SET stock_note = ? WHERE id = ?", arguments: [text, productId])
        try Meta.touch(db)
        try Meta.log(db, "stock_note", row["code"] ?? "")
        return true
    }
}

/// Python core/text.parse_number: '12', '12,5', '１２' or '１２，５' typed with a Chinese input method. nil = not a number.
public func parseNumber(_ text: String) -> Double? {
    var s = text.precomposedStringWithCompatibilityMapping.trimmingCharacters(in: .whitespacesAndNewlines)
    s = s.replacingOccurrences(of: " ", with: "").replacingOccurrences(of: ",", with: ".").replacingOccurrences(of: "。", with: ".")
    guard !s.isEmpty, let value = Double(s), value.isFinite else { return nil }
    return value
}

extension OrderQueries {
    /// Documents of one kind, newest first, as Python queries.documents (the Đơn hàng window and its fixed-kind
    /// copies): only those in force unless includeClosed; from / to are ISO days (nil: no limit); a customer, a
    /// product on one of the lines, a text in the code or the customer's name (076 = 76).
    public static func documents(_ db: Database, kind: String, from: String? = nil, to: String? = nil,
                                 customerId: Int64? = nil, productId: Int64? = nil, includeClosed: Bool = false,
                                 text: String = "") throws -> [Row] {
        var conditions = ["d.kind = ?"]
        var arguments: [DatabaseValueConvertible?] = [kind]
        if !includeClosed { conditions.append("d.status = 'active'") }
        if let from, !from.isEmpty {
            conditions.append("d.doc_date >= ?")
            arguments.append(from)
        }
        if let to, !to.isEmpty {
            conditions.append("d.doc_date <= ?")
            arguments.append(to)
        }
        if let customerId, customerId != 0 {
            conditions.append("d.customer_id = ?")
            arguments.append(customerId)
        }
        if let productId, productId != 0 {
            conditions.append("EXISTS (SELECT 1 FROM document_lines x WHERE x.document_id = d.id AND x.product_id = ?)")
            arguments.append(productId)
        }
        if !text.isEmpty {
            conditions.append("(unaccent(d.code) LIKE ? OR unaccent(COALESCE(c.name, '')) LIKE ? OR d.code_norm = ?)")
            let like = "%\(TextRules.unaccent(text))%"
            arguments += [like, like, Lookup.normalizeCode(text)]
        }
        return try Row.fetchAll(db, sql: """
            SELECT d.*, c.name AS customer_name, s.name AS supplier_name,
                   COUNT(l.id) AS line_count, COALESCE(SUM(l.qty), 0) AS total_qty,
                   (SELECT SUM(x.amount) FROM document_lines x WHERE x.document_id = d.id) AS goods_amount,
                   (SELECT COUNT(DISTINCT m.location_id) FROM stock_movements m WHERE m.document_id = d.id) AS places
            FROM documents d
            LEFT JOIN customers c ON c.id = d.customer_id
            LEFT JOIN suppliers s ON s.id = d.supplier_id
            LEFT JOIN document_lines l ON l.document_id = d.id
            WHERE \(conditions.joined(separator: " AND "))
            GROUP BY d.id
            ORDER BY d.doc_date DESC, d.id DESC
            """, arguments: StatementArguments(arguments))
    }

    /// The lines of a document with their products (to edit a transfer).
    public static func lines(_ db: Database, docId: Int64) throws -> [Row] {
        try Row.fetchAll(db, sql: "SELECT * FROM document_lines WHERE document_id = ? ORDER BY line_no", arguments: [docId])
    }
}

extension Workspace {
    /// The language the user chose in the Python app (config.json, only read): vi, en or zh.
    public static func language() -> String? {
        guard let data = try? Data(contentsOf: configFile),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let lang = object["language"] as? String, L10n.languages.contains(lang) else { return nil }
        return lang
    }

    /// The size of letters and buttons chosen in the Python app (config.json ui_scale, 1.0–1.5).
    public static func uiScale() -> Double? {
        guard let data = try? Data(contentsOf: configFile),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let scale = object["ui_scale"] as? Double, scale >= 1, scale <= 1.5 else { return nil }
        return scale
    }
}

/// The practice work folder of phase 3 (BẢN THỬ): a full copy of the shop's data where the Swift app writes, so the
/// real data and the cloud never change until the Swift app can sync (phase 4). It stays from one run to the next.
public enum Practice {
    /// tests put the practice folder somewhere else (never the user's own)
    public static var folderOverride: URL?

    public static var folder: URL {
        folderOverride ?? FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/DiBeKhoSwift/BanThu", isDirectory: true)
    }

    public static var database: URL { folder.appendingPathComponent("data/kho.sqlite") }
    public static var exists: Bool { FileManager.default.fileExists(atPath: database.path) }
    public static var deliveries: URL { folder.appendingPathComponent("phieu-giao-hang", isDirectory: true) }
    public static var input: URL { folder.appendingPathComponent("input", isDirectory: true) }
    public static var output: URL { folder.appendingPathComponent("output", isDirectory: true) }

    /// What the copy was made from and when (shown on the banner).
    public static var origin: String {
        (try? String(contentsOf: folder.appendingPathComponent("BAN-THU.txt"), encoding: .utf8))?
            .split(separator: "\n").last.map(String.init) ?? ""
    }

    /// A fresh practice folder from a kho.sqlite (the original is only read, with SQLite's backup), with the
    /// delivery notes and stored originals of its work folder when they are there. The old practice folder goes.
    public static func make(from source: URL) throws {
        var readOnly = Configuration()
        readOnly.readonly = true
        let original = try DatabaseQueue(path: source.path, configuration: readOnly)
        defer { try? original.close() }
        try original.read { try Store.check($0) }

        let fm = FileManager.default
        try? fm.removeItem(at: folder)
        for sub in ["data", "phieu-giao-hang", "input", "output", "sao-luu"] {
            try fm.createDirectory(at: folder.appendingPathComponent(sub), withIntermediateDirectories: true)
        }
        let copy = try DatabaseQueue(path: database.path, configuration: Store.configuration())
        try original.backup(to: copy)
        try copy.close()
        let work = source.deletingLastPathComponent().deletingLastPathComponent()
        for (from, to) in [("data/phieu-goc", "data/phieu-goc"), ("phieu-giao-hang", "phieu-giao-hang")] {
            let src = work.appendingPathComponent(from)
            if fm.fileExists(atPath: src.path) {
                let dst = folder.appendingPathComponent(to)
                try? fm.removeItem(at: dst)
                try fm.copyItem(at: src, to: dst)
            }
        }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "dd/MM/yyyy HH:mm"
        let text = """
            BẢN THỬ của DiBeKho Swift: bản sao dữ liệu để thử ghi (hàng về, kiểm kê, chuyển hàng…).
            Không phải dữ liệu thật, không đồng bộ lên Cloud. Xoá thư mục này là mất các thao tác đã thử, dữ liệu thật không sao.
            Chép từ \(source.path) lúc \(f.string(from: Date()))
            """
        try text.write(to: folder.appendingPathComponent("BAN-THU.txt"), atomically: true, encoding: .utf8)
    }

    /// The practice database, brought to the current schema, with the Python app's sync triggers.
    public static func open() throws -> DatabaseQueue {
        let queue = try DatabaseQueue(path: database.path, configuration: Store.configuration())
        try queue.read { try Store.check($0) }
        try Schema.migrate(queue)
        try queue.write { try Sync.ensureTriggers($0) }
        ActivityLog.setup(folder.appendingPathComponent("data/app.log"))
        return queue
    }
}
