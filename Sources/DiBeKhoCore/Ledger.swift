import Foundation
import GRDB

/// A write refused for a reason the user can act on; the message is the Python app's, word for word.
public struct WriteError: Error, LocalizedError, Equatable {
    public let message: String
    public init(_ message: String) { self.message = message }
    public var errorDescription: String? { message }
}

/// Python db.get_meta / set_meta / touch / log.
public enum Meta {
    public static func get(_ db: Database, _ key: String, _ fallback: String = "") throws -> String {
        try String.fetchOne(db, sql: "SELECT value FROM meta WHERE key = ?", arguments: [key]) ?? fallback
    }

    public static func set(_ db: Database, _ key: String, _ value: String) throws {
        try db.execute(sql: """
            INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, arguments: [key, value])
    }

    /// Local time as Python's datetime.now().isoformat(timespec="seconds"): 2026-11-17T09:05:00.
    static func isoNow() -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f.string(from: Date())
    }

    /// Local data changed (used to warn before a data package overwrites it).
    public static func touch(_ db: Database) throws {
        try set(db, "last_change_at", isoNow())
    }

    public static func log(_ db: Database, _ action: String, _ detail: String = "") throws {
        try db.execute(sql: "INSERT INTO app_log(action, detail) VALUES(?, ?)", arguments: [action, detail])
        ActivityLog.write("data", "\(action) \(detail)".trimmingCharacters(in: .whitespaces))
    }
}

/// One line of a document to record (Python core/stock.Line).
public struct LedgerLine: Equatable {
    public var productId: Int64
    public var qty: Double
    public var rawName = ""
    public var rawSpec = ""
    public var note = ""
    public var lineNo: Int?
    public var unitPrice: Double?
    public var amount: Double?
    public var locationId: Int64?
    /// a stock issue note line taken from both places: (location, qty) adding up to qty; empty = one place
    public var places: [(Int64, Double)] = []

    public init(_ productId: Int64, _ qty: Double, note: String = "", unitPrice: Double? = nil, amount: Double? = nil) {
        self.productId = productId
        self.qty = qty
        self.note = note
        self.unitPrice = unitPrice
        self.amount = amount
    }

    public static func == (a: LedgerLine, b: LedgerLine) -> Bool {
        a.productId == b.productId && a.qty == b.qty && a.note == b.note && a.unitPrice == b.unitPrice
            && a.amount == b.amount && a.locationId == b.locationId && a.lineNo == b.lineNo
    }
}

/// Python core/stock: every change is a stock_movements row, stock = SUM(qty). Every function that writes expects
/// to run inside one write transaction (queue.write).
public enum Ledger {
    public static let main: Int64 = 1
    public static let office: Int64 = 2
    public static let locations: [Int64] = [main, office]
    static let locationCodes: [Int64: String] = [main: "main", office: "office"]

    static let forward: [String: (String, Double)] = ["delivery": ("delivery_out", -1), "receipt": ("receipt_in", 1)]
    static let reverse: [String: String] = ["delivery": "delivery_reverse", "receipt": "receipt_reverse",
                                            "stock_count": "count_reverse", "transfer": "transfer_reverse",
                                            "trial": "trial_reverse"]

    static func iso(_ day: Date) -> String { Dates.iso(day) }

    @discardableResult
    public static func insertDocument(_ db: Database, kind: String, date: String, lines: [LedgerLine], code: String = "",
                                      codeNorm: String = "", customerId: Int64? = nil, note: String = "",
                                      sourceFile: String = "", sourceHash: String = "", locationId: Int64 = main,
                                      locationSet: Bool = true) throws -> Int64 {
        guard let (movement, sign) = forward[kind] else { throw WriteError(kind) }
        try db.execute(sql: """
            INSERT INTO documents(kind, code, code_norm, doc_date, customer_id, note, source_file, source_hash,
            location_id, location_set) VALUES(?,?,?,?,?,?,?,?,?,?)
            """, arguments: [kind, code, codeNorm, date, customerId, note, sourceFile, sourceHash, locationId,
                             locationSet ? 1 : 0])
        let docId = db.lastInsertedRowID
        try insertLines(db, docId, lines, movement, sign, date, locationId)
        return docId
    }

    /// Lines added to an active delivery/receipt (a partly approved note getting its remaining lines).
    public static func addLines(_ db: Database, docId: Int64, lines: [LedgerLine]) throws {
        guard let doc = try Row.fetchOne(db, sql: "SELECT * FROM documents WHERE id = ?", arguments: [docId]),
              doc["status"] as String == "active", let (movement, sign) = forward[doc["kind"] as String] else {
            throw WriteError("Phiếu không tồn tại hoặc đã huỷ.")
        }
        try insertLines(db, docId, lines, movement, sign, doc["doc_date"], doc["location_id"])
    }

    static func insertLines(_ db: Database, _ docId: Int64, _ lines: [LedgerLine], _ movement: String, _ sign: Double,
                            _ occurredOn: String, _ locationId: Int64) throws {
        for (i, line) in lines.enumerated() {
            let several = line.places.count > 1
            try db.execute(sql: """
                INSERT INTO document_lines(document_id, line_no, product_id, qty, raw_name, raw_spec, note, unit_price,
                amount, location_id) VALUES(?,?,?,?,?,?,?,?,?,?)
                """, arguments: [docId, line.lineNo ?? (i + 1), line.productId, line.qty, line.rawName, line.rawSpec,
                                 line.note, line.unitPrice, line.amount, several ? nil : line.locationId])
            let moves = several ? line.places : [(line.locationId ?? locationId, line.qty)]
            for (place, qty) in moves {
                try move(db, line.productId, sign * qty, docId, movement, occurredOn, place)
            }
        }
        try Meta.touch(db)
    }

    /// Cancel (or mark replaced) a document by adding reverse movements. Nothing is deleted.
    public static func close(_ db: Database, docId: Int64, status: String = "cancelled") throws {
        guard let doc = try Row.fetchOne(db, sql: "SELECT * FROM documents WHERE id = ?", arguments: [docId]),
              doc["status"] as String == "active" else {
            throw WriteError("Phiếu không tồn tại hoặc đã huỷ.")
        }
        let kind: String = doc["kind"]
        let rows = try Row.fetchAll(db, sql: """
            SELECT product_id, location_id, SUM(qty) AS qty FROM stock_movements WHERE document_id = ?
            GROUP BY product_id, location_id
            """, arguments: [docId])
        for r in rows {
            let qty: Double = r["qty"] ?? 0
            if qty != 0 {
                // dated like the original so period reports stay consistent
                try move(db, r["product_id"], -qty, docId, reverse[kind] ?? "", doc["doc_date"], r["location_id"])
            }
        }
        try db.execute(sql: "UPDATE documents SET status = ?, closed_at = datetime('now', 'localtime') WHERE id = ?",
                       arguments: [status, docId])
        try Meta.touch(db)
        let code: String = doc["code"] ?? ""
        try Meta.log(db, "document_\(status)", "\(kind) \(code) #\(docId)")
    }

    /// One counted quantity: a place (locationId) or the total (nil: the difference goes to Kho tổng).
    public struct Counted {
        public var productId: Int64
        public var locationId: Int64?
        public var qty: Double
        public init(_ productId: Int64, _ locationId: Int64?, _ qty: Double) {
            self.productId = productId
            self.locationId = locationId
            self.qty = qty
        }
    }

    /// A physical count: movement = counted - stock as of countDate (inclusive). Delivery notes dated on or before
    /// it must be read first. at: the moment of a count recorded later ('YYYY-MM-DD HH:MM:SS').
    @discardableResult
    public static func stockCount(_ db: Database, date: String, counted: [Counted], note: String = "",
                                  at stamp: String? = nil) throws -> Int64 {
        try db.execute(sql: """
            INSERT INTO documents(kind, doc_date, note, created_at)
            VALUES('stock_count', ?, ?, COALESCE(?, datetime('now', 'localtime')))
            """, arguments: [date, note, stamp])
        let docId = db.lastInsertedRowID
        let total = try levels(db, asOf: date, createdUntil: stamp)
        let placed = try levelsByPlace(db, asOf: date, createdUntil: stamp)
        for (i, c) in counted.enumerated() {
            try db.execute(sql: "INSERT INTO document_lines(document_id, line_no, product_id, qty, location_id) VALUES(?,?,?,?,?)",
                           arguments: [docId, i + 1, c.productId, c.qty, c.locationId])
            let had = c.locationId.map { placed[PlaceKey(c.productId, $0)] ?? 0 } ?? (total[c.productId] ?? 0)
            let diff = c.qty - had
            if abs(diff) > 1e-9 {
                try move(db, c.productId, diff, docId, "count_adjust", date, c.locationId ?? main, stamp)
            }
        }
        try Meta.touch(db)
        try Meta.log(db, "stock_count", "#\(docId) \(date)")
        return docId
    }

    public struct PlaceKey: Hashable, Comparable {
        public let productId: Int64
        public let locationId: Int64
        public init(_ productId: Int64, _ locationId: Int64) {
            self.productId = productId
            self.locationId = locationId
        }
        public static func < (a: PlaceKey, b: PlaceKey) -> Bool {
            (a.productId, a.locationId) < (b.productId, b.locationId)
        }
    }

    static func whereClause(_ asOf: String?, _ createdUntil: String?) -> (String, StatementArguments) {
        var clauses: [String] = []
        var args: StatementArguments = []
        if let asOf {
            clauses.append("occurred_on <= ?")
            args += [asOf]
        }
        if let createdUntil {
            clauses.append("created_at <= ?")
            args += [createdUntil]
        }
        return (clauses.isEmpty ? "" : "WHERE " + clauses.joined(separator: " AND "), args)
    }

    /// {product: stock} (Python stock_levels).
    public static func levels(_ db: Database, asOf: String? = nil, createdUntil: String? = nil) throws -> [Int64: Double] {
        let (clause, args) = whereClause(asOf, createdUntil)
        var out: [Int64: Double] = [:]
        for r in try Row.fetchAll(db, sql: "SELECT product_id, SUM(qty) FROM stock_movements \(clause) GROUP BY product_id",
                                  arguments: args) {
            out[r[0]] = (r[1] as Double?) ?? 0
        }
        return out
    }

    /// {(product, place): stock} (Python stock_levels(by_location=True)).
    public static func levelsByPlace(_ db: Database, asOf: String? = nil, createdUntil: String? = nil) throws -> [PlaceKey: Double] {
        let (clause, args) = whereClause(asOf, createdUntil)
        var out: [PlaceKey: Double] = [:]
        for r in try Row.fetchAll(db, sql: """
            SELECT product_id, location_id, SUM(qty) FROM stock_movements \(clause) GROUP BY product_id, location_id
            """, arguments: args) {
            out[PlaceKey(r[0], r[1])] = (r[2] as Double?) ?? 0
        }
        return out
    }

    /// CH001, CH002…: the highest number in use + 1 (an edited transfer keeps its code on a new row).
    public static func nextTransferCode(_ db: Database) throws -> String {
        try nextCode(db, kind: "transfer", prefix: "CH")
    }

    /// DT001, DT002… (dùng thử), same rule.
    public static func nextTrialCode(_ db: Database) throws -> String {
        try nextCode(db, kind: "trial", prefix: "DT")
    }

    static func nextCode(_ db: Database, kind: String, prefix: String) throws -> String {
        let highest = try Int.fetchOne(db, sql: """
            SELECT MAX(CAST(SUBSTR(code, 3) AS INTEGER)) FROM documents WHERE kind = ? AND code GLOB '\(prefix)[0-9]*'
            """, arguments: [kind]) ?? 0
        return prefix + String(format: "%03d", highest + 1)
    }

    /// Goods moved from one place to the other (the total does not change). replaces: the transfer being edited.
    @discardableResult
    public static func transfer(_ db: Database, date: String, from: Int64, to: Int64, lines: [LedgerLine],
                                note: String = "", replaces: Int64? = nil) throws -> Int64 {
        if from == to || !locations.contains(from) || !locations.contains(to) {
            throw WriteError("Nơi chuyển đi và nơi nhận phải khác nhau.")
        }
        if lines.isEmpty { throw WriteError("Phiếu chuyển hàng chưa có dòng nào.") }
        var code = try nextTransferCode(db)
        if let replaces {
            guard let old = try Row.fetchOne(db, sql: "SELECT code, kind FROM documents WHERE id = ?", arguments: [replaces]),
                  old["kind"] as String == "transfer" else {
                throw WriteError("Chỉ sửa được phiếu chuyển hàng.")
            }
            try close(db, docId: replaces, status: "replaced")
            let oldCode: String = old["code"] ?? ""
            if !oldCode.isEmpty { code = oldCode }
        }
        try db.execute(sql: """
            INSERT INTO documents(kind, code, code_norm, doc_date, note, location_id, to_location_id)
            VALUES('transfer', ?, ?, ?, ?, ?, ?)
            """, arguments: [code, code, date, note, from, to])
        let docId = db.lastInsertedRowID
        for (i, line) in lines.enumerated() {
            try db.execute(sql: "INSERT INTO document_lines(document_id, line_no, product_id, qty, note) VALUES(?,?,?,?,?)",
                           arguments: [docId, i + 1, line.productId, line.qty, line.note])
            try move(db, line.productId, -line.qty, docId, "transfer_out", date, from)
            try move(db, line.productId, line.qty, docId, "transfer_in", date, to)
        }
        try Meta.touch(db)
        try Meta.log(db, replaces == nil ? "transfer" : "transfer_edited",
                     "\(code) \(locationCodes[from]!)->\(locationCodes[to]!)")
        return docId
    }

    /// Goods taken out for internal trial use, no customer. A mistake is cancelled and typed again.
    @discardableResult
    public static func trialUse(_ db: Database, date: String, locationId: Int64, lines: [LedgerLine],
                                note: String = "") throws -> Int64 {
        if !locations.contains(locationId) { throw WriteError("Nơi xuất dùng thử không hợp lệ.") }
        if lines.isEmpty { throw WriteError("Phiếu dùng thử chưa có dòng nào.") }
        let code = try nextTrialCode(db)
        try db.execute(sql: "INSERT INTO documents(kind, code, code_norm, doc_date, note, location_id) VALUES('trial', ?, ?, ?, ?, ?)",
                       arguments: [code, code, date, note, locationId])
        let docId = db.lastInsertedRowID
        for (i, line) in lines.enumerated() {
            try db.execute(sql: "INSERT INTO document_lines(document_id, line_no, product_id, qty, note) VALUES(?,?,?,?,?)",
                           arguments: [docId, i + 1, line.productId, line.qty, line.note])
            try move(db, line.productId, -line.qty, docId, "trial_out", date, locationId)
        }
        try Meta.touch(db)
        try Meta.log(db, "trial_use", "\(code) \(locationCodes[locationId]!)")
        return docId
    }

    /// Where the goods of a delivery note were taken from (or a receipt put in); the total does not change.
    public static func setLocation(_ db: Database, docId: Int64, locationId: Int64) throws {
        guard let doc = try Row.fetchOne(db, sql: "SELECT * FROM documents WHERE id = ?", arguments: [docId]),
              forward[doc["kind"] as String] != nil, locations.contains(locationId) else {
            throw WriteError("Không đổi được nơi lấy hàng của phiếu này.")
        }
        if try isMixed(db, docId) {
            throw WriteError("Phiếu này lấy hàng ở cả Kho tổng và Văn phòng: không đổi chung một nơi được. "
                             + "Muốn đổi, hãy huỷ phiếu rồi tạo lại phiếu xuất kho.")
        }
        try db.execute(sql: "UPDATE stock_movements SET location_id = ? WHERE document_id = ?", arguments: [locationId, docId])
        try db.execute(sql: "UPDATE document_lines SET location_id = ? WHERE document_id = ? AND location_id IS NOT NULL",
                       arguments: [locationId, docId])
        try db.execute(sql: "UPDATE documents SET location_id = ?, location_set = 1 WHERE id = ?", arguments: [locationId, docId])
        try Meta.touch(db)
        let kind: String = doc["kind"]
        let code: String = doc["code"] ?? ""
        try Meta.log(db, "document_location", "\(kind) \(code) #\(docId) -> \(locationCodes[locationId]!)")
    }

    /// Goods of this document taken from both places (a stock issue note).
    public static func isMixed(_ db: Database, _ docId: Int64) throws -> Bool {
        try Int.fetchOne(db, sql: "SELECT COUNT(DISTINCT location_id) FROM stock_movements WHERE document_id = ?",
                         arguments: [docId]) ?? 0 > 1
    }

    static func move(_ db: Database, _ productId: Int64, _ qty: Double, _ docId: Int64, _ kind: String,
                     _ occurredOn: String, _ locationId: Int64, _ createdAt: String? = nil) throws {
        try db.execute(sql: """
            INSERT INTO stock_movements(product_id, qty, document_id, kind, occurred_on, location_id, created_at)
            VALUES(?,?,?,?,?,?,COALESCE(?, datetime('now', 'localtime')))
            """, arguments: [productId, qty, docId, kind, occurredOn, locationId, createdAt])
    }
}

/// Dates as the database keeps them (ISO, local calendar).
public enum Dates {
    static let formatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.calendar = Calendar(identifier: .gregorian)
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    public static func iso(_ day: Date) -> String { formatter.string(from: day) }
    public static func parse(_ iso: String) -> Date? { formatter.date(from: iso) }
    public static var today: String { iso(Date()) }
}

/// Python round(x, 2): to the nearest of the exact binary value, a true tie to the even digit (printf does the same).
public func pythonRound2(_ value: Double) -> Double {
    Double(String(format: "%.2f", value)) ?? value
}
