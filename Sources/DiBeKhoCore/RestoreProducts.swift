import Foundation
import GRDB

/// Python core/catalog «Khôi phục mặt hàng đã xoá»: products found in a backup but missing from the catalog now,
/// brought back with their old code, and the check for a copy made after the mistaken delete.
public struct DeletedProduct: Equatable {
    public var code: String
    public var nameVi: String
    public var nameZh: String
    public var spec: String
    public var unit: String
    public var category: String
    public var minStock: Double
    public var variant: String
    public var stockNote: String
    public var backupAt: Date  // of the newest backup that still has it
    public var aliasKeys: [String]  // delivery-note names it used to be recognised by, read from that same backup

    public init(code: String, nameVi: String, nameZh: String = "", spec: String = "", unit: String = "", category: String = "",
                minStock: Double = 0, variant: String = "", stockNote: String = "", backupAt: Date = Date(), aliasKeys: [String] = []) {
        self.code = code; self.nameVi = nameVi; self.nameZh = nameZh; self.spec = spec; self.unit = unit
        self.category = category; self.minStock = minStock; self.variant = variant; self.stockNote = stockNote
        self.backupAt = backupAt; self.aliasKeys = aliasKeys
    }
}

extension Catalog {
    private static let productColumns = ["code", "name_vi", "name_zh", "spec", "unit", "category", "min_stock", "variant", "stock_note"]

    /// Every backup that might still have a deleted product's row, oldest first (so the newest one read for a code wins):
    /// the backups of sao-luu/ and the snapshots older versions kept in sao-luu/hoan-tac/ (still read, never written).
    public static func backupFilesForRestore(_ backups: URL) -> [URL] {
        func sqlite(_ folder: URL) -> [URL] {
            ((try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? [])
                .filter { $0.pathExtension == "sqlite" }
        }
        func date(_ u: URL) -> Date { (try? u.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate ?? .distantPast }
        let all = sqlite(backups) + sqlite(backups.appendingPathComponent("hoan-tac", isDirectory: true))
        return all.sorted { date($0) < date($1) }
    }

    /// Products found in some backup but missing from the catalog now. A code waiting in the freed pool (merged away on
    /// purpose) is not offered again. A backup is only opened read-only; one that cannot be read, or whose schema is
    /// too old to have the product table, is skipped.
    public static func deletedProducts(_ db: Database, backups: URL) throws -> [DeletedProduct] {
        let current = Set(try String.fetchAll(db, sql: "SELECT code FROM products")).union(try freedCodes(db))
        var found: [String: DeletedProduct] = [:]
        for file in backupFilesForRestore(backups) {
            guard let queue = try? DatabaseQueue(path: file.path, configuration: Store.configuration(readonly: true)) else { continue }
            defer { try? queue.close() }
            let at = (try? file.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate ?? Date()
            let rows: [DeletedProduct]? = try? queue.read { b in
                let cols = Set(try Row.fetchAll(b, sql: "PRAGMA table_info(products)").map { $0["name"] as String })
                let present = productColumns.filter { cols.contains($0) }
                guard present.contains("code"), present.contains("name_vi") else { return [] }
                let hasAliases = try Int.fetchOne(b, sql: "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'product_aliases'") != nil
                var list: [DeletedProduct] = []
                for r in try Row.fetchAll(b, sql: "SELECT id, \(present.joined(separator: ", ")) FROM products") {
                    let code: String = r["code"] ?? ""
                    if current.contains(code) { continue }
                    let id: Int64 = r["id"]
                    let keys = try hasAliases ? String.fetchAll(b, sql: "SELECT key FROM product_aliases WHERE product_id = ?", arguments: [id]) : []
                    func text(_ c: String) -> String { cols.contains(c) ? (r[c] as String? ?? "") : "" }
                    list.append(DeletedProduct(code: code, nameVi: text("name_vi"), nameZh: text("name_zh"), spec: text("spec"),
                                               unit: text("unit"), category: text("category"),
                                               minStock: cols.contains("min_stock") ? (r["min_stock"] as Double? ?? 0) : 0,
                                               variant: text("variant"), stockNote: text("stock_note"), backupAt: at, aliasKeys: keys))
                }
                return list
            }
            for p in rows ?? [] { found[p.code] = p }
        }
        return found.values.sorted { $0.code < $1.code }
    }

    /// Re-create a deleted product with its old code (freed by deleteProduct so nothing else took it). It has no stock
    /// movements: a product can only be deleted when no document uses it. Returns the new id.
    @discardableResult
    public static func restoreProduct(_ db: Database, _ data: DeletedProduct) throws -> Int64 {
        try db.execute(sql: """
            INSERT INTO products(code, name_vi, name_zh, spec, unit, category, min_stock, variant, stock_note)
            VALUES(?,?,?,?,?,?,?,?,?)
            """, arguments: [data.code, data.nameVi, data.nameZh, data.spec, data.unit, data.category, data.minStock,
                             data.variant, data.stockNote])
        let id = db.lastInsertedRowID
        try Meta.set(db, freedCodesKey, try freedCodes(db).filter { $0 != data.code }.joined(separator: ","))
        try Meta.touch(db)
        return id
    }

    /// Products that might be the same item as the one just restored, best evidence first (never the restored one):
    /// 1. a product that now owns one of the note names this one used to be recognised by (near certain: made by reading
    ///    a note again after the mistake); 2. the same name + packing + type; 3. the fuzzy matcher's best guess (score >= 0.5).
    /// The first `aliasMatches` rows came from 1: the caller pre-ticks the first one.
    public static func findMergeCandidates(_ db: Database, newId: Int64, _ data: DeletedProduct) throws
        -> (candidates: [Product], aliasMatches: Int) {
        var seen: Set<Int64> = [newId]
        var result: [Product] = []
        for key in data.aliasKeys {
            if let pid = try aliasProduct(db, key: key), !seen.contains(pid), let p = try product(db, id: pid) {
                seen.insert(pid)
                result.append(p)
            }
        }
        let aliasMatches = result.count
        if let same = try findSame(db, nameVi: data.nameVi, spec: data.spec, variant: data.variant), !seen.contains(same.id) {
            seen.insert(same.id)
            result.append(same)
        }
        if let match = try ranked(db, data.nameZh.isEmpty ? data.nameVi : data.nameZh, data.spec)
            .first(where: { $0.0 >= 0.5 && !seen.contains($0.1.id) }) {
            result.append(match.1)
        }
        return (result, aliasMatches)
    }
}
