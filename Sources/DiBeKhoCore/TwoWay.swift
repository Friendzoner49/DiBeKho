import Foundation
import GRDB

/// A row changed on both sides: neither is applied nor pushed until the user chooses.
public struct CloudConflict {
    public let table: String
    public let uid: String
    public let local: CloudRow
    public let cloud: CloudRow
}

/// What one merge did (core/cloud/twoway.py Merged).
public struct Merged {
    public var applied = 0
    public var renamed: [(table: String, old: String, new: String)] = []
    public var duplicates = 0
    public var separated: [String] = []
    public var conflicts: [CloudConflict] = []
    public var receiptsToExport: [Int64] = []
    public var receiptFiles: [(id: Int64, file: String)] = []
    public init() {}
}

/// Two-way sync with the cloud's tables: PULL everything newer than this machine saw, MERGE here (the business rules are
/// this app's), PUSH this machine's queued changes. Python core/cloud/twoway.py, rule by rule; the network is elsewhere.
public enum TwoWay {
    static let cursorKey = "sync_cursor"  // per machine: the highest cloud rev merged here
    static let conflictsKey = "sync_conflicts"  // per machine: JSON list of unresolved conflicts
    static let clockKey = "clock_offset_min"
    static let prefixes: [(kind: String, prefix: String)] = [("receipt", "HV"), ("transfer", "CH"), ("trial", "DT")]

    /// This machine's clock, minutes from UTC (Vietnam: 420); the tests fix it.
    static var clockOffset: () -> Int = { TimeZone.current.secondsFromGMT() / 60 }

    // ---- small state

    public static func cursor(_ db: Database) throws -> Int { Int(try Meta.get(db, cursorKey, "0")) ?? 0 }

    public static func conflicts(_ db: Database) throws -> [CloudConflict] {
        let text = try Meta.get(db, conflictsKey, "[]")
        guard let data = text.data(using: .utf8), let list = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else { return [] }
        return list.map {
            CloudConflict(table: $0["table"] as? String ?? "", uid: $0["uid"] as? String ?? "",
                          local: CloudJSON.row($0["local"]), cloud: CloudJSON.row($0["cloud"]))
        }
    }

    static func saveConflicts(_ db: Database, _ items: [CloudConflict]) throws {
        let list: [[String: Any]] = items.map {
            ["table": $0.table, "uid": $0.uid, "local": CloudJSON.any($0.local), "cloud": CloudJSON.any($0.cloud)]
        }
        let data = try JSONSerialization.data(withJSONObject: list)
        try Meta.set(db, conflictsKey, String(decoding: data, as: UTF8.self))
    }

    /// (table, local id or key) of rows in conflict: not pushed until resolved.
    static func held(_ db: Database) throws -> Set<RowKey> {
        var out: Set<RowKey> = []
        for c in try conflicts(db) {
            let t = try Replica.table(c.table)
            if t.natural { out.insert(RowKey(table: c.table, id: c.uid)) }
            else { out.insert(RowKey(table: c.table, id: (try Replica.localFor(db, c.table, c.uid)).map(String.init) ?? "nil")) }
        }
        return out
    }

    // ---- merge

    static func queuedKeys(_ db: Database) throws -> Set<RowKey> {
        Set(try Row.fetchAll(db, sql: "SELECT tbl, local_id FROM sync_outbox").map { RowKey(table: $0["tbl"], id: $0["local_id"]) })
    }

    /// Equal as values (the cloud writes timestamps as 2026-11-02T10:00:00, numbers may come back as int).
    static func same(_ t: SyncTable, _ local: CloudRow, _ cloud: CloudRow) -> Bool {
        func norm(_ col: String, _ v: CloudValue?) -> CloudValue {
            guard let v = v else { return .null }
            if t.timestamps.contains(col), let s = v.string { return .text(String(s.prefix(19)).replacingOccurrences(of: "T", with: " ")) }
            return v
        }
        let keys = Set(local.keys).union(cloud.keys).subtracting(["rev", "deleted"])
        return keys.allSatisfy { norm($0, local[$0]).same(norm($0, cloud[$0])) }
            && (local["deleted"]?.isTrue ?? false) == (cloud["deleted"]?.isTrue ?? false)
    }

    static func mergeMeta(_ key: String, mine: String, theirs: String) -> String {
        func split(_ s: String) -> [String] { s.split(separator: ",").map(String.init) }
        func unique(_ items: [String]) -> [String] {
            var seen: Set<String> = []
            return items.filter { seen.insert($0).inserted }
        }
        switch key {
        case "count_checked": return unique(split(theirs) + split(mine)).joined(separator: ",")
        case "freed_codes":  // a code reused on either side must not be handed out again: keep what both still free
            let both = Set(split(theirs))
            return split(mine).filter { both.contains($0) }.joined(separator: ",")
        case "product_code_max": return String(max(Int(mine) ?? 0, Int(theirs) ?? 0))
        default: return mine  // last writer wins: ours is pushed right after
        }
    }

    static func nextNumber(_ codes: Set<String>, _ prefix: String) -> Int {
        var best = 0
        for code in codes where code.hasPrefix(prefix) {
            let rest = code.dropFirst(prefix.count)
            if !rest.isEmpty, rest.allSatisfy({ $0.isASCII && $0.isNumber }), let n = Int(rest) { best = max(best, n) }
        }
        return best + 1
    }

    static func live(_ rows: [CloudRow]) -> [CloudRow] { rows.filter { !($0["deleted"]?.isTrue ?? false) } }

    /// Merge what was pulled into this database (inside the caller's write transaction).
    public static func merge(_ db: Database, _ pulled: Pulled) throws -> Merged {
        var tables: [String: [CloudRow]] = [:]
        for t in SyncSchema.tables { tables[t.name] = pulled.tables[t.name] ?? [] }
        var out = Merged()
        let queued = try queuedKeys(db)
        let openConflicts = try conflicts(db)
        try conflictsAndEchoes(db, &tables, queued, &out)
        try mergeSharedMeta(db, &tables, queued)
        try renumberProducts(db, tables, &out)
        try renumberDocuments(db, tables, &out)
        let dupHashes = try deliveries(db, tables, &out)
        try forgetScansOfDeleted(db, tables)
        try Replica.apply(db, tables)
        // a receipt entered on the web names the Excel file the app writes for it (cloud 009: no file hash yet)
        for r in live(tables["documents"] ?? []) where r["kind"]?.string == "receipt" && r["status"]?.string == "active" {
            let file = r["source_file"]?.string ?? ""
            if !file.isEmpty, (r["source_hash"]?.string ?? "").isEmpty, let uid = r["id"]?.string,
               let local = try Replica.localFor(db, "documents", uid) {
                out.receiptFiles.append((local, file))
            }
        }
        for h in dupHashes {  // the scan record of a note read on both machines points at the cloud's document now
            if let doc = try Int64.fetchOne(db, sql: "SELECT id FROM documents WHERE kind = 'delivery' AND source_hash = ? AND status = 'active'", arguments: [h]) {
                try db.execute(sql: "UPDATE scanned_files SET document_id = ? WHERE hash = ?", arguments: [doc, h])
            }
        }
        if !out.conflicts.isEmpty {  // a row already in conflict that changed again keeps only its newest cloud version
            let fresh = Set(out.conflicts.map { RowKey(table: $0.table, id: $0.uid) })
            let kept = openConflicts.filter { !fresh.contains(RowKey(table: $0.table, id: $0.uid)) }
            try saveConflicts(db, kept + out.conflicts)
        }
        try Meta.set(db, cursorKey, String(max(try cursor(db), pulled.maxRev)))
        out.applied = tables.values.reduce(0) { $0 + $1.count }
        return out
    }

    private static func conflictsAndEchoes(_ db: Database, _ tables: inout [String: [CloudRow]], _ queued: Set<RowKey>, _ out: inout Merged) throws {
        let deletedHere = Set(try String.fetchAll(db, sql: "SELECT uid FROM sync_outbox WHERE op = 'D' AND uid IS NOT NULL"))
        for t in SyncSchema.tables {
            var keep: [CloudRow] = []
            for r in tables[t.name] ?? [] {
                let localId: String?
                if t.natural { localId = r[t.key]?.string }
                else { localId = try Replica.localFor(db, t.name, r["id"]?.string ?? "").map(String.init) }
                let uid = (t.natural ? r["key"]?.string : r["id"]?.string) ?? ""
                if localId == nil, deletedHere.contains(uid) {  // deleted here, not pushed yet: our delete wins
                    if r["deleted"]?.isTrue ?? false {  // ...and it is already gone there (our push, reply lost)
                        try db.execute(sql: "DELETE FROM sync_outbox WHERE op = 'D' AND uid = ?", arguments: [uid])
                    }
                    continue
                }
                guard let id = localId, queued.contains(RowKey(table: t.name, id: id)), t.name != "meta" else { keep.append(r); continue }
                let rowid = t.key == "rowid" ? "rowid AS _rowid, " : ""
                guard let row = try Row.fetchOne(db, sql: "SELECT \(rowid)* FROM \(t.name) WHERE \(Replica.keyColumn(t)) = ?", arguments: [id])
                else { continue }  // gone here since it was queued: its delete decides
                let mine = try Replica.toCloud(db, t, row)
                if same(t, mine, r) {  // our own push, its reply lost: it is on the cloud already
                    try db.execute(sql: "DELETE FROM sync_outbox WHERE tbl = ? AND local_id = ?", arguments: [t.name, id])
                    continue
                }
                if t.natural { continue }  // names learned / lines ignored: ours wins, it is pushed right after
                out.conflicts.append(CloudConflict(table: t.name, uid: r["id"]?.string ?? "", local: mine, cloud: r))
            }
            tables[t.name] = keep
        }
    }

    private static func mergeSharedMeta(_ db: Database, _ tables: inout [String: [CloudRow]], _ queued: Set<RowKey>) throws {
        var keep: [CloudRow] = []
        for r in tables["meta"] ?? [] {
            let key = r["key"]?.string ?? ""
            if queued.contains(RowKey(table: "meta", id: key)), !(r["deleted"]?.isTrue ?? false) {
                let mine = try Meta.get(db, key, "")
                try Meta.set(db, key, mergeMeta(key, mine: mine, theirs: r["value"]?.string ?? ""))  // queued again: pushed merged
                continue
            }
            keep.append(r)
        }
        tables["meta"] = keep
    }

    private static func renumberProducts(_ db: Database, _ tables: [String: [CloudRow]], _ out: inout Merged) throws {
        var order: [String] = []
        var pulled: [String: String] = [:]  // code -> uid (the last one wins, the first position stays, as a Python dict)
        for r in live(tables["products"] ?? []) {
            let code = r["code"]?.string ?? ""
            if pulled[code] == nil { order.append(code) }
            pulled[code] = r["id"]?.string ?? ""
        }
        let going = Set((tables["products"] ?? []).filter { $0["deleted"]?.isTrue ?? false }.compactMap { $0["id"]?.string })
        var allCodes = Set(order).union(try String.fetchAll(db, sql: "SELECT code FROM products"))
        for code in order {
            let uid = pulled[code] ?? ""
            guard let id = try Int64.fetchOne(db, sql: "SELECT id FROM products WHERE code = ?", arguments: [code]) else { continue }
            let mine = try Replica.uidFor(db, "products", String(id), create: false)
            if mine == uid || (mine != nil && going.contains(mine!)) { continue }
            let used = Int(try Meta.get(db, Catalog.codeMaxKey, "0")) ?? 0
            let new = "SP" + String(format: "%03d", max(nextNumber(allCodes, "SP"), used + 1))
            try db.execute(sql: "UPDATE products SET code = ? WHERE id = ?", arguments: [new, id])
            try Meta.set(db, Catalog.codeMaxKey, String(Int(new.dropFirst(2)) ?? 0))
            allCodes.insert(new)
            out.renamed.append(("products", code, new))
        }
    }

    private static func renumberDocuments(_ db: Database, _ tables: [String: [CloudRow]], _ out: inout Merged) throws {
        let docs = tables["documents"] ?? []
        for (kind, prefix) in prefixes {
            var pulledSet: Set<[String]> = []
            for r in live(docs) where r["kind"]?.string == kind && r["status"]?.string != "replaced" {
                if let code = r["code"]?.string, !code.isEmpty { pulledSet.insert([code, r["id"]?.string ?? ""]) }
            }
            let pulledUids = Set(docs.filter { $0["kind"]?.string == kind }.compactMap { $0["id"]?.string })
            var codes = Set(docs.filter { $0["kind"]?.string == kind }.compactMap { $0["code"]?.string })
            codes.formUnion(try String.fetchAll(db, sql: "SELECT code FROM documents WHERE kind = ?", arguments: [kind]))
            let ordered = pulledSet.sorted { ($0[0], $0[1]) < ($1[0], $1[1]) }
            for pair in ordered {
                let code = pair[0]
                guard let mine = try Int64.fetchOne(db, sql: "SELECT id FROM documents WHERE kind = ? AND code = ? AND status <> 'replaced'", arguments: [kind, code])
                else { continue }
                if let u = try Replica.uidFor(db, "documents", String(mine), create: false), pulledUids.contains(u) { continue }
                let new = prefix + String(format: "%03d", nextNumber(codes, prefix))
                var ids: [Int64] = []
                for id in try Int64.fetchAll(db, sql: "SELECT id FROM documents WHERE kind = ? AND code = ?", arguments: [kind, code]) {
                    let u = try Replica.uidFor(db, "documents", String(id), create: false)
                    if u == nil || !pulledUids.contains(u!) { ids.append(id) }
                }
                for id in ids {  // every version of it (an edited receipt keeps its code on the replaced one)
                    try db.execute(sql: "UPDATE documents SET code = ?, code_norm = ? WHERE id = ?", arguments: [new, new, id])
                }
                codes.insert(new)
                out.renamed.append(("documents", code, new))
                if kind == "receipt" {
                    for id in ids {
                        let status = try String.fetchOne(db, sql: "SELECT status FROM documents WHERE id = ?", arguments: [id])
                        if status == "active" { out.receiptsToExport.append(id) }
                    }
                }
            }
        }
    }

    private static func deliveries(_ db: Database, _ tables: [String: [CloudRow]], _ out: inout Merged) throws -> [String] {
        var dupHashes: [String] = []
        for r in live(tables["documents"] ?? []) where r["kind"]?.string == "delivery" && r["status"]?.string == "active" {
            let codeNorm = r["code_norm"]?.string ?? ""
            guard let mine = try Row.fetchOne(db, sql: "SELECT id, source_hash FROM documents WHERE kind = 'delivery' AND status = 'active' AND code_norm = ?", arguments: [codeNorm])
            else { continue }
            let mineId: Int64 = mine["id"]
            if try Replica.uidFor(db, "documents", String(mineId), create: false) == r["id"]?.string { continue }
            let mineHash: String = mine["source_hash"] ?? ""
            if !mineHash.isEmpty, mineHash == (r["source_hash"]?.string ?? "") {
                // the same note read here too and not pushed yet: the cloud's copy stays, ours goes (never pushed)
                for table in ["stock_movements", "document_lines", "document_skipped_lines"] {
                    try db.execute(sql: "DELETE FROM \(table) WHERE document_id = ?", arguments: [mineId])
                }
                try db.execute(sql: "UPDATE scanned_files SET document_id = NULL WHERE document_id = ?", arguments: [mineId])
                try db.execute(sql: "DELETE FROM documents WHERE id = ?", arguments: [mineId])
                dupHashes.append(mineHash)
                out.duplicates += 1
                continue
            }
            var n = 2
            while try Int.fetchOne(db, sql: "SELECT 1 FROM documents WHERE kind = 'delivery' AND code_norm = ?", arguments: ["\(codeNorm)#\(n)"]) != nil { n += 1 }
            try db.execute(sql: "UPDATE documents SET code_norm = ? WHERE id = ?", arguments: ["\(codeNorm)#\(n)", mineId])
            out.separated.append(r["code"]?.string ?? "")
        }
        return dupHashes
    }

    private static func forgetScansOfDeleted(_ db: Database, _ tables: [String: [CloudRow]]) throws {
        for r in tables["documents"] ?? [] where r["deleted"]?.isTrue ?? false {
            if let uid = r["id"]?.string, let local = try Replica.localFor(db, "documents", uid) {
                try db.execute(sql: "DELETE FROM scanned_files WHERE document_id = ?", arguments: [local])
            }
        }
    }

    // ---- push

    /// The shared data's clock, set once by the first machine that syncs.
    static func stampClock(_ db: Database) throws {
        if try Meta.get(db, clockKey, "").isEmpty { try Meta.set(db, clockKey, String(clockOffset())) }
    }

    /// (batch, last outbox seq in it, rows held back by conflicts).
    public static func prepare(_ db: Database) throws -> (batch: [String: [CloudRow]], seq: Int, hold: Set<RowKey>) {
        try stampClock(db)
        let hold = try held(db)
        let (batch, seq) = try Replica.pending(db, exclude: hold)
        return (batch, seq, hold)
    }

    /// A receipt renumbered by a merge: its Excel file follows the new code (the old file would carry a code that now
    /// belongs to another machine's receipt). Receipts entered on the web only get their file. Python export_renamed.
    /// ⚠ No golden: it only writes files.
    public static func exportRenamed(_ db: Database, _ folders: ShopFolders, _ merged: Merged) throws {
        for (docId, name) in merged.receiptFiles where Receipts.exportedFile(folders, name: name) == nil {
            _ = try? Receipts.writeFile(db, folders, docId: docId, name: name)  // the folder may not be writable now
        }
        for docId in merged.receiptsToExport {
            guard let old = try String.fetchOne(db, sql: "SELECT source_file FROM documents WHERE id = ?", arguments: [docId]) else { continue }
            let oldFile = Receipts.exportedFile(folders, name: old)
            _ = try Receipts.exportFile(db, folders, docId: docId)
            if let oldFile { try? FileManager.default.removeItem(at: oldFile) }  // open in Excel: the new file exists anyway
        }
    }

    public static func finish(_ db: Database, seq: Int, maxRev: Int, hold: Set<RowKey>) throws {
        try Replica.clearOutbox(db, upTo: seq, keep: hold)
        try Meta.set(db, cursorKey, String(maxRev))
    }

    public static func isEmpty(_ batch: [String: [CloudRow]]) -> Bool { !batch.values.contains { !$0.isEmpty } }

    /// The pull brought no row from elsewhere: merging changes nothing on screen.
    public static func nothingNew(_ pulled: Pulled) -> Bool { !pulled.tables.values.contains { !$0.isEmpty } }

    public static func cloudEmpty(_ pulled: Pulled) -> Bool { nothingNew(pulled) }

    // ---- resolving a conflict

    /// keepMine: this machine's version is pushed (overwrites the cloud's). Otherwise the cloud's is written here.
    public static func resolve(_ db: Database, _ conflict: CloudConflict, keepMine: Bool) throws {
        let rest = try conflicts(db).filter { !($0.table == conflict.table && $0.uid == conflict.uid) }
        if keepMine { try saveConflicts(db, rest); return }
        let local = try Replica.localFor(db, conflict.table, conflict.uid)
        try Replica.apply(db, [conflict.table: [conflict.cloud]])
        if let local = local {
            try db.execute(sql: "DELETE FROM sync_outbox WHERE tbl = ? AND local_id = ?", arguments: [conflict.table, String(local)])
        }
        try saveConflicts(db, rest)
    }

    // ---- turning cloud mode on

    /// The cloud holds nothing yet: this machine's data becomes the shared data (everything queued for the push).
    public static func startFromThisMachine(_ db: Database) throws {
        try Replica.queueAll(db)
        try Replica.setEnabled(db, true)
    }

    /// The cloud already holds the shared data: this machine's own copy is put aside (the caller backed it up) and the
    /// next round pulls everything.
    public static func startFromCloud(_ db: Database) throws {
        try Replica.setEnabled(db, false)  // clearing is not a change to send
        for t in SyncSchema.tables.reversed() {
            if t.name == "documents" { try db.execute(sql: "DELETE FROM scanned_files") }
            let only = t.onlyKeys.isEmpty ? "" : " WHERE key IN (\(t.onlyKeys.map { _ in "?" }.joined(separator: ", ")))"
            try db.execute(sql: "DELETE FROM \(t.name)\(only)", arguments: StatementArguments(t.onlyKeys))
        }
        try db.execute(sql: "DELETE FROM sync_map")
        try db.execute(sql: "DELETE FROM sync_outbox")
        try Meta.set(db, cursorKey, "0")
        try Meta.set(db, conflictsKey, "[]")
        try Replica.setEnabled(db, true)
    }

    /// Back to working alone. Queued changes stay queued.
    public static func stop(_ db: Database) throws { try Replica.setEnabled(db, false) }

    public static func queuedCount(_ db: Database) throws -> Int {
        try Int.fetchOne(db, sql: "SELECT COUNT(DISTINCT tbl || ':' || local_id) FROM sync_outbox") ?? 0
    }
}
