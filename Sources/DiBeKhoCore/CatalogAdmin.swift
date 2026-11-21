import Foundation
import GRDB

/// Python core/catalog: editing the catalog (Cài đặt → Mặt hàng): update, delete, merge, import from a sheet.
extension Catalog {
    static func freeACode(_ db: Database, _ code: String) throws {
        let codes = try freedCodes(db)
        if !codes.contains(code) { try Meta.set(db, freedCodesKey, (codes + [code]).joined(separator: ",")) }
    }

    public static func codeNum(_ code: String) -> Int {
        guard code.hasPrefix("SP"), code.count > 2, code.dropFirst(2).allSatisfy({ $0.isASCII && $0.isNumber }) else { return -1 }
        return Int(code.dropFirst(2)) ?? -1  // a code outside the SPxxx scheme never loses a merge
    }

    /// The fields the editor changes; nil leaves a field as it is.
    public struct ProductFields {
        public var nameVi: String?, nameZh: String?, spec: String?, unit: String?, category: String?, variant: String?
        public var minStock: Double?, active: Bool?, stockNote: String?
        public init(nameVi: String? = nil, nameZh: String? = nil, spec: String? = nil, unit: String? = nil,
                    category: String? = nil, variant: String? = nil, minStock: Double? = nil, active: Bool? = nil,
                    stockNote: String? = nil) {
            self.nameVi = nameVi; self.nameZh = nameZh; self.spec = spec; self.unit = unit; self.category = category
            self.variant = variant; self.minStock = minStock; self.active = active; self.stockNote = stockNote
        }
    }

    /// Python update_product: the values are stored as given (the editor cleans them).
    public static func updateProduct(_ db: Database, id: Int64, _ f: ProductFields) throws {
        var sets: [(String, DatabaseValueConvertible)] = []
        if let v = f.nameVi { sets.append(("name_vi", v)) }
        if let v = f.nameZh { sets.append(("name_zh", v)) }
        if let v = f.spec { sets.append(("spec", v)) }
        if let v = f.unit { sets.append(("unit", v)) }
        if let v = f.category { sets.append(("category", v)) }
        if let v = f.minStock { sets.append(("min_stock", v)) }
        if let v = f.active { sets.append(("active", v ? 1 : 0)) }
        if let v = f.variant { sets.append(("variant", v)) }
        if let v = f.stockNote { sets.append(("stock_note", v)) }
        if sets.isEmpty { return }
        var args: [DatabaseValueConvertible?] = sets.map { $0.1 }
        args.append(id)
        try db.execute(sql: "UPDATE products SET \(sets.map { "\($0.0) = ?" }.joined(separator: ", ")) WHERE id = ?",
                       arguments: StatementArguments(args))
        try Meta.touch(db)
    }

    /// How many documents (any status, cancelled ones too) have a line with this product.
    public static func productDocuments(_ db: Database, id: Int64) throws -> Int {
        try Int.fetchOne(db, sql: """
            SELECT COUNT(DISTINCT document_id) FROM (
             SELECT document_id FROM document_lines WHERE product_id = ?
             UNION ALL SELECT document_id FROM stock_movements WHERE product_id = ?)
            """, arguments: [id, id]) ?? 0
    }

    /// A product no document uses, with the delivery-note names learned for it. One that is in documents is kept.
    public static func deleteProduct(_ db: Database, id: Int64) throws {
        if try productDocuments(db, id: id) > 0 { throw WriteError("Mặt hàng đã có trong phiếu, không xoá được.") }
        if let code = try String.fetchOne(db, sql: "SELECT code FROM products WHERE id = ?", arguments: [id]), codeNum(code) >= 0 {
            let used = Int(try Meta.get(db, codeMaxKey, "0")) ?? 0
            try Meta.set(db, codeMaxKey, String(max(used, codeNum(code))))
        }
        try db.execute(sql: "DELETE FROM product_aliases WHERE product_id = ?", arguments: [id])
        try db.execute(sql: "DELETE FROM products WHERE id = ?", arguments: [id])
        try Meta.touch(db)
    }

    /// Two products that are the same item: everything of the larger code moves onto the smaller, empty fields are
    /// filled from the other, the larger is deleted and its code freed. Returns the id that survived.
    @discardableResult
    public static func mergeProducts(_ db: Database, _ idA: Int64, _ idB: Int64) throws -> Int64 {
        guard let a = try Row.fetchOne(db, sql: "SELECT * FROM products WHERE id = ?", arguments: [idA]),
              let b = try Row.fetchOne(db, sql: "SELECT * FROM products WHERE id = ?", arguments: [idB]), idA != idB else {
            throw WriteError("Chọn hai mặt hàng khác nhau để gộp.")
        }
        let (keep, drop) = codeNum(a["code"] ?? "") <= codeNum(b["code"] ?? "") ? (a, b) : (b, a)
        let keepId: Int64 = keep["id"], dropId: Int64 = drop["id"]
        for table in ["document_lines", "stock_movements", "product_aliases"] {
            try db.execute(sql: "UPDATE \(table) SET product_id = ? WHERE product_id = ?", arguments: [keepId, dropId])
        }
        var fill = ProductFields()
        func empty(_ r: Row, _ k: String) -> Bool { TextRules.clean(r[k] as String? ?? "").isEmpty }
        if empty(keep, "name_zh") && !empty(drop, "name_zh") { fill.nameZh = drop["name_zh"] }
        if empty(keep, "category") && !empty(drop, "category") { fill.category = drop["category"] }
        if empty(keep, "stock_note") && !empty(drop, "stock_note") { fill.stockNote = drop["stock_note"] }
        if ((keep["min_stock"] as Double?) ?? 0) == 0 && ((drop["min_stock"] as Double?) ?? 0) != 0 { fill.minStock = drop["min_stock"] }
        try updateProduct(db, id: keepId, fill)
        try db.execute(sql: "DELETE FROM products WHERE id = ?", arguments: [dropId])
        let dropCode: String = drop["code"] ?? ""
        if codeNum(dropCode) >= 0 { try freeACode(db, dropCode) }
        try Meta.touch(db)
        return keepId
    }

    /// One product of a catalog sheet (excel/catalog_sheet.CatalogItem).
    public struct CatalogItem {
        public var nameVi: String, nameZh: String, spec: String, unit: String, category: String, variant: String
        public var stock: Double?
        public init(nameVi: String, nameZh: String = "", spec: String = "", unit: String = "", category: String = "",
                    variant: String = "", stock: Double? = nil) {
            self.nameVi = nameVi; self.nameZh = nameZh; self.spec = spec; self.unit = unit; self.category = category
            self.variant = variant; self.stock = stock
        }
    }

    /// Creates the products that do not exist yet (same name + packing + type). With stockDate, the sheet's stock of
    /// every item becomes a stock count on that date. Returns (created, skipped, counted).
    public static func importCatalog(_ db: Database, _ items: [CatalogItem], stockDate: String? = nil,
                                     note: String = "") throws -> (created: Int, skipped: Int, counted: Int) {
        var created = 0, skipped = 0
        var counted: [(Int64, Double)] = []
        for it in items {
            let id: Int64
            if let same = try findSame(db, nameVi: it.nameVi, spec: it.spec, variant: it.variant) {
                skipped += 1
                id = same.id
            } else {
                id = try createProduct(db, nameVi: it.nameVi, nameZh: it.nameZh, spec: it.spec, unit: it.unit,
                                       category: it.category, variant: it.variant)
                created += 1
            }
            if stockDate != nil, let stock = it.stock {
                if let i = counted.firstIndex(where: { $0.0 == id }) { counted[i].1 = stock } else { counted.append((id, stock)) }
            }
        }
        if let stockDate, !counted.isEmpty {
            try Ledger.stockCount(db, date: stockDate, counted: counted.map { Ledger.Counted($0.0, nil, $0.1) }, note: note)
        }
        try Meta.log(db, "catalog_import", "\(created) created, \(skipped) skipped, \(counted.count) stock")
        return (created, skipped, counted.count)
    }
}
