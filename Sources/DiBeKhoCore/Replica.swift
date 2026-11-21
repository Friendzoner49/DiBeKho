import Foundation
import GRDB

/// One value of a cloud row (core/cloud/replica.py): the same columns as the SQLite row, references turned into uuids,
/// 0/1 into booleans.
public enum CloudValue: Equatable {
    case null
    case bool(Bool)
    case int(Int64)
    case double(Double)
    case text(String)

    var number: Double? {
        switch self {
        case .int(let i): return Double(i)
        case .double(let d): return d
        case .bool(let b): return b ? 1 : 0
        default: return nil
        }
    }

    var string: String? { if case .text(let s) = self { return s }; return nil }

    /// For the screens (conflict list): "∅" for null.
    public var shown: String {
        switch self {
        case .null: return "∅"
        case .bool(let b): return b ? "true" : "false"
        case .int(let i): return String(i)
        case .double(let d): return String(d)
        case .text(let s): return s
        }
    }

    var isTrue: Bool {
        switch self {
        case .null: return false
        case .bool(let b): return b
        case .int(let i): return i != 0
        case .double(let d): return d != 0
        case .text(let s): return !s.isEmpty
        }
    }

    var database: DatabaseValue {
        switch self {
        case .null: return .null
        case .bool(let b): return (b ? 1 : 0).databaseValue
        case .int(let i): return i.databaseValue
        case .double(let d): return d.databaseValue
        case .text(let s): return s.databaseValue
        }
    }

    /// Python's `==` between two cloud values (1 == 1.0 == True).
    func same(_ other: CloudValue) -> Bool {
        if case .null = self { if case .null = other { return true }; return false }
        if case .null = other { return false }
        if let a = number, let b = other.number { return a == b }
        return self == other
    }
}

public typealias CloudRow = [String: CloudValue]

/// What sync_pull gave: the rows per table and the highest rev among them.
public struct Pulled {
    public var tables: [String: [CloudRow]]
    public var maxRev: Int
    public init(tables: [String: [CloudRow]] = [:], maxRev: Int = 0) { self.tables = tables; self.maxRev = maxRev }
}

/// Python CloudError (shown to the user as it is) and its two sub-kinds.
public struct CloudError: LocalizedError {
    public enum Kind { case plain, sessionExpired, notForApp }
    public let message: String
    public let kind: Kind
    public init(_ message: String, kind: Kind = .plain) { self.message = message; self.kind = kind }
    public var errorDescription: String? { message }
}

/// A JSON object <-> cloud values.
public enum CloudJSON {
    public static func value(_ any: Any?) -> CloudValue {
        switch any {
        case nil, is NSNull: return .null
        case let n as NSNumber:
            if CFGetTypeID(n) == CFBooleanGetTypeID() { return .bool(n.boolValue) }
            let type = String(cString: n.objCType)
            if type == "d" || type == "f" { return .double(n.doubleValue) }
            return .int(n.int64Value)
        case let s as String: return .text(s)
        default: return .null
        }
    }

    public static func row(_ any: Any?) -> CloudRow {
        var out: CloudRow = [:]
        for (k, v) in (any as? [String: Any]) ?? [:] { out[k] = value(v) }
        return out
    }

    public static func any(_ v: CloudValue) -> Any {
        switch v {
        case .null: return NSNull()
        case .bool(let b): return b
        case .int(let i): return i
        case .double(let d): return d
        case .text(let s): return s
        }
    }

    public static func any(_ row: CloudRow) -> [String: Any] { row.mapValues { any($0) } }

    /// The body of an RPC answer {"tables": {...}, "max_rev": n}.
    public static func pulled(_ any: Any?) -> Pulled {
        let object = (any as? [String: Any]) ?? [:]
        var tables: [String: [CloudRow]] = [:]
        for (name, rows) in (object["tables"] as? [String: Any]) ?? [:] {
            tables[name] = ((rows as? [Any]) ?? []).map { row($0) }
        }
        return Pulled(tables: tables, maxRev: Int((object["max_rev"] as? NSNumber)?.int64Value ?? 0))
    }
}

/// (table, local id or key): one queued or held row.
public struct RowKey: Hashable {
    public let table: String
    public let id: String
}

/// Rows between the local database and the cloud's tables (core/cloud/replica.py). The local database keeps its integer
/// ids; the cloud keys rows by uuid; sync_map links the two.
public enum Replica {
    /// Python's uuid.uuid4(); the tests count instead so that the ids are the same as in the Python golden.
    static var newUID: () -> String = { UUID().uuidString.lowercased() }

    static func setEnabled(_ db: Database, _ on: Bool) throws {
        try db.execute(sql: "UPDATE sync_flags SET value = ? WHERE key = 'enabled'", arguments: [on ? "1" : "0"])
    }

    public static func enabled(_ db: Database) throws -> Bool {
        try String.fetchOne(db, sql: "SELECT value FROM sync_flags WHERE key = 'enabled'") == "1"
    }

    static func columns(_ db: Database, _ t: SyncTable) throws -> [String] {
        try Row.fetchAll(db, sql: "PRAGMA table_info(\(t.name))").map { $0["name"] as String }
    }

    static func table(_ name: String) throws -> SyncTable {
        guard let t = SyncSchema.tables.first(where: { $0.name == name }) else { throw CloudError("Bảng \(name) không được đồng bộ.") }
        return t
    }

    static func keyColumn(_ t: SyncTable) -> String { t.key == "rowid" ? "rowid" : t.key }

    // ---- ids

    static func uidFor(_ db: Database, _ table: String, _ localId: String, create: Bool = true) throws -> String? {
        if let uid = try String.fetchOne(db, sql: "SELECT uid FROM sync_map WHERE tbl = ? AND local_id = ?", arguments: [table, localId]) {
            return uid
        }
        if !create { return nil }
        let uid = newUID()
        try db.execute(sql: "INSERT INTO sync_map(tbl, local_id, uid) VALUES (?, ?, ?)", arguments: [table, localId, uid])
        return uid
    }

    static func localFor(_ db: Database, _ table: String, _ uid: String) throws -> Int64? {
        guard let text = try String.fetchOne(db, sql: "SELECT local_id FROM sync_map WHERE tbl = ? AND uid = ?", arguments: [table, uid])
        else { return nil }
        return Int64(text)
    }

    // ---- local -> cloud

    static func select(_ t: SyncTable) -> String {
        let rowid = t.key == "rowid" ? "rowid AS _rowid, " : ""
        let only = t.onlyKeys.isEmpty ? "" : " WHERE key IN (\(t.onlyKeys.map { _ in "?" }.joined(separator: ", ")))"
        return "SELECT \(rowid)* FROM \(t.name)\(only)"
    }

    static func text(_ v: DatabaseValue) -> String {
        switch v.storage {
        case .int64(let i): return String(i)
        case .double(let d): return d == d.rounded() && abs(d) < 1e15 ? String(Int64(d)) : String(d)
        case .string(let s): return s
        default: return ""
        }
    }

    static func toCloud(_ db: Database, _ t: SyncTable, _ row: Row) throws -> CloudRow {
        var out: CloudRow = [:]
        for col in try columns(db, t) {
            let v: DatabaseValue = row[col]
            switch v.storage {
            case .null: out[col] = .null
            case .int64(let i):
                if let target = t.refs[col] { out[col] = .text(try uidFor(db, target, String(i)) ?? "") }
                else if t.booleans.contains(col) { out[col] = .bool(i != 0) }
                else { out[col] = .int(i) }
            case .double(let d):
                if let target = t.refs[col] { out[col] = .text(try uidFor(db, target, text(v)) ?? "") }
                else if t.booleans.contains(col) { out[col] = .bool(d != 0) }
                else { out[col] = .double(d) }
            case .string(let s):
                if let target = t.refs[col] { out[col] = .text(try uidFor(db, target, s) ?? "") }
                else if t.booleans.contains(col) { out[col] = .bool(!s.isEmpty) }
                else { out[col] = .text(s) }
            case .blob: out[col] = .null
            }
        }
        if !t.natural {
            let local: String = t.key == "rowid" ? text(row["_rowid"]) : text(row[t.key])
            out["id"] = .text(try uidFor(db, t.name, local) ?? "")
        }
        out["deleted"] = .bool(false)
        return out
    }

    /// What changed since the last push, as cloud rows (deleted ones carry only their id/key) + the last outbox seq
    /// included. A row changed several times travels once. `exclude`: rows held back (in conflict).
    static func pending(_ db: Database, exclude: Set<RowKey> = []) throws -> (batch: [String: [CloudRow]], last: Int) {
        let last = try Int.fetchOne(db, sql: "SELECT MAX(seq) FROM sync_outbox") ?? 0
        var out: [String: [CloudRow]] = [:]
        for t in SyncSchema.tables { out[t.name] = [] }
        // Deletes first and each on its own: SQLite may give a deleted id to a new row. A delete without uuid was never
        // pushed: nothing to tell the cloud.
        for r in try Row.fetchAll(db, sql: "SELECT DISTINCT tbl, uid FROM sync_outbox WHERE op = 'D' AND uid IS NOT NULL ORDER BY seq") {
            let tbl: String = r["tbl"]
            let uid: String = r["uid"]
            let t = try table(tbl)
            out[tbl, default: []].append([t.natural ? t.key : "id": .text(uid), "deleted": .bool(true)])
        }
        let changed = try Row.fetchAll(db, sql: "SELECT tbl, local_id FROM sync_outbox WHERE op = 'U' GROUP BY tbl, local_id ORDER BY MIN(seq)")
        for r in changed {
            let tbl: String = r["tbl"]
            let localId: String = r["local_id"]
            if exclude.contains(RowKey(table: tbl, id: localId)) { continue }
            let t = try table(tbl)
            let base = select(t).components(separatedBy: " WHERE").first ?? select(t)
            guard let row = try Row.fetchOne(db, sql: "\(base) WHERE \(keyColumn(t)) = ?", arguments: [localId]) else { continue }  // deleted since
            if t.natural {  // deleted then written again: the write wins
                out[tbl] = (out[tbl] ?? []).filter { $0[t.key] != CloudValue.text(localId) }
            }
            out[tbl, default: []].append(try toCloud(db, t, row))
        }
        return (out, last)
    }

    /// Every synced row as cloud rows (replica.snapshot: replacing the shared data). Writes sync_map for rows that had
    /// no uuid yet, so it runs inside a write.
    static func snapshot(_ db: Database) throws -> [String: [CloudRow]] {
        var out: [String: [CloudRow]] = [:]
        for t in SyncSchema.tables {
            let rows = try Row.fetchAll(db, sql: select(t), arguments: StatementArguments(t.onlyKeys))
            out[t.name] = try rows.map { try toCloud(db, t, $0) }
        }
        return out
    }

    /// Queue every synced row (the first push of a database that already holds data).
    static func queueAll(_ db: Database) throws {
        for t in SyncSchema.tables {
            let only = t.onlyKeys.isEmpty ? "" : " WHERE key IN (\(t.onlyKeys.map { _ in "?" }.joined(separator: ", ")))"
            try db.execute(sql: "INSERT INTO sync_outbox(tbl, local_id, op) SELECT '\(t.name)', \(keyColumn(t)), 'U' FROM \(t.name)\(only)",
                           arguments: StatementArguments(t.onlyKeys))
        }
    }

    /// Forget what the cloud now has; rows in `keep` (held back) stay queued.
    static func clearOutbox(_ db: Database, upTo seq: Int, keep: Set<RowKey> = []) throws {
        for r in try Row.fetchAll(db, sql: "SELECT DISTINCT tbl, local_id FROM sync_outbox WHERE seq <= ?", arguments: [seq]) {
            let tbl: String = r["tbl"]
            let id: String = r["local_id"]
            if !keep.contains(RowKey(table: tbl, id: id)) {
                try db.execute(sql: "DELETE FROM sync_outbox WHERE tbl = ? AND local_id = ? AND seq <= ?", arguments: [tbl, id, seq])
            }
        }
    }

    // ---- cloud -> local

    static func localValue(_ db: Database, _ t: SyncTable, _ col: String, _ value: CloudValue) throws -> DatabaseValue {
        if case .null = value { return .null }
        if let target = t.refs[col] {
            guard let uid = value.string, let local = try localFor(db, target, uid) else {
                throw CloudError("\(t.name).\(col): \(target) \(value.string ?? "") is not here")
            }
            return local.databaseValue
        }
        if t.booleans.contains(col) { return (value.isTrue ? 1 : 0).databaseValue }
        if t.timestamps.contains(col), let s = value.string {  // Postgres JSON writes 2026-11-02T10:00:00
            return String(s.prefix(19)).replacingOccurrences(of: "T", with: " ").databaseValue
        }
        return value.database
    }

    /// Write rows pulled from the cloud into this database without queueing them again. Parents first; deletions
    /// children first. Runs inside the caller's transaction.
    static func apply(_ db: Database, _ rows: [String: [CloudRow]]) throws {
        try db.execute(sql: "PRAGMA defer_foreign_keys = ON")  // checked at commit: a merge elsewhere deletes before it re-points
        try db.execute(sql: "UPDATE sync_flags SET value = '1' WHERE key = 'applying'")
        for t in SyncSchema.tables.reversed() {
            for r in rows[t.name] ?? [] where r["deleted"]?.isTrue ?? false { try delete(db, t, r) }
        }
        for t in SyncSchema.tables {
            for r in rows[t.name] ?? [] where !(r["deleted"]?.isTrue ?? false) { try upsert(db, t, r) }
        }
        try db.execute(sql: "UPDATE sync_flags SET value = '0' WHERE key = 'applying'")
    }

    private static func delete(_ db: Database, _ t: SyncTable, _ r: CloudRow) throws {
        if t.natural {
            try db.execute(sql: "DELETE FROM \(t.name) WHERE \(t.key) = ?", arguments: [r[t.key]?.database ?? .null])
            return
        }
        if let uid = r["id"]?.string, let local = try localFor(db, t.name, uid) {
            try db.execute(sql: "DELETE FROM \(t.name) WHERE \(keyColumn(t)) = ?", arguments: [local])
        }
    }

    private static func upsert(_ db: Database, _ t: SyncTable, _ r: CloudRow) throws {
        if !t.onlyKeys.isEmpty, !t.onlyKeys.contains(r["key"]?.string ?? "") { return }
        let cols = try columns(db, t).filter { r[$0] != nil && !(!t.natural && $0 == t.key) }
        var values: [DatabaseValue] = []
        for c in cols { values.append(try localValue(db, t, c, r[c] ?? .null)) }
        let marks = cols.map { _ in "?" }.joined(separator: ", ")
        if t.natural {
            let sets = cols.filter { $0 != t.key }.map { "\($0) = excluded.\($0)" }.joined(separator: ", ")
            try db.execute(sql: "INSERT INTO \(t.name)(\(cols.joined(separator: ", "))) VALUES (\(marks)) ON CONFLICT(\(t.key)) DO UPDATE SET \(sets)",
                           arguments: StatementArguments(values))
            return
        }
        let uid = r["id"]?.string ?? ""
        if let local = try localFor(db, t.name, uid) {
            try db.execute(sql: "UPDATE \(t.name) SET \(cols.map { "\($0) = ?" }.joined(separator: ", ")) WHERE \(keyColumn(t)) = ?",
                           arguments: StatementArguments(values + [local.databaseValue]))
            return
        }
        try db.execute(sql: "INSERT INTO \(t.name)(\(cols.joined(separator: ", "))) VALUES (\(marks))", arguments: StatementArguments(values))
        try db.execute(sql: "INSERT INTO sync_map(tbl, local_id, uid) VALUES (?, ?, ?)", arguments: [t.name, String(db.lastInsertedRowID), uid])
    }
}
