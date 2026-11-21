import Foundation
import GRDB

/// «Tên trên phiếu đã học» (core/deliveries.learned_names, learned_by_order, forget_name): what the user taught the app
/// in Cần xử lý, found again from the order it spoiled, with the way to forget it and read the notes again.
extension Deliveries {
    public struct LearnedName: Equatable {
        public var key: String
        public var label: String
        public var productId: Int64?  // nil = dropped as "not goods"
        public var documents: [Int64]
    }

    public struct LearnedLine: Equatable {
        public var key: String
        public var label: String  // the line as written on the note
        public var qty: Double
        public var productId: Int64?  // nil = dropped as "not goods"
        public var documents: [Int64]  // every active note with this line (forgetting reads them all again)
    }

    public struct LearnedOrder: Equatable {
        public var docId: Int64?  // nil: names learned but no longer in any active note
        public var code: String
        public var docDate: String
        public var customer: String
        public var lines: [LearnedLine]
    }

    /// Every active delivery note that has this line: kept as a dropped line, or written on the note.
    public static func documentsWithKey(_ db: Database, key: String) throws -> [Int64] {
        var ids = Set(try Int64.fetchAll(db, sql: """
            SELECT s.document_id FROM document_skipped_lines s JOIN documents d ON d.id = s.document_id
            WHERE s.key = ? AND d.status = 'active'
            """, arguments: [key]))
        for r in try Row.fetchAll(db, sql: """
            SELECT l.document_id, l.raw_name, l.raw_spec FROM document_lines l JOIN documents d ON d.id = l.document_id
            WHERE d.kind = 'delivery' AND d.status = 'active'
            """) where TextRules.matchKey(r["raw_name"] ?? "", r["raw_spec"] ?? "") == key {
            ids.insert(r["document_id"])
        }
        return ids.sorted()
    }

    /// Python sorts with str.casefold(): code point by code point on the lower-cased text
    private static func before(_ a: String, _ b: String) -> Bool {
        let x = Array(a.lowercased().unicodeScalars.map(\.value)), y = Array(b.lowercased().unicodeScalars.map(\.value))
        return x.lexicographicallyPrecedes(y)
    }

    /// Every name the user taught the app (matched to a product or dropped as "not goods").
    /// `backfill: false` for a read-only connection (the one-time record of dropped lines is not made then).
    public static func learnedNames(_ db: Database, _ f: ShopFolders, backfill: Bool = true) throws -> [LearnedName] {
        if backfill { try backfillSkippedLines(db, f) }
        let lines = try Row.fetchAll(db, sql: """
            SELECT l.document_id, l.raw_name, l.raw_spec FROM document_lines l JOIN documents d ON d.id = l.document_id
            WHERE d.kind = 'delivery' AND d.status = 'active'
            """)
        var byKey: [String: [Row]] = [:]
        for r in lines { byKey[TextRules.matchKey(r["raw_name"] ?? "", r["raw_spec"] ?? ""), default: []].append(r) }
        var result: [LearnedName] = []
        for a in try Row.fetchAll(db, sql: "SELECT * FROM product_aliases") {
            let key: String = a["key"]
            let rows = byKey[key] ?? []
            var label: String = a["label"] ?? ""
            if label.isEmpty {
                label = rows.first.map { [$0["raw_name"] ?? "", $0["raw_spec"] ?? ""].filter { !$0.isEmpty }.joined(separator: " ") } ?? key
            }
            let docs = Set(rows.map { $0["document_id"] as Int64 }).sorted()
            result.append(LearnedName(key: key, label: label, productId: a["product_id"], documents: docs))
        }
        for g in try Catalog.ignoredLines(db) {
            let key: String = g["key"]
            let label: String = g["label"] ?? ""
            result.append(LearnedName(key: key, label: label.isEmpty ? key : label, productId: nil,
                                      documents: try documentsWithKey(db, key: key)))
        }
        return result.enumerated().sorted { l, r in
            before(l.element.label, r.element.label) || (!before(r.element.label, l.element.label) && l.offset < r.offset)
        }.map(\.element)
    }

    /// What the app learned, grouped by delivery note (newest first), so a wrong choice is found from the order it
    /// spoiled. Names in no active note come last.
    public static func learnedByOrder(_ db: Database, _ f: ShopFolders, backfill: Bool = true) throws -> [LearnedOrder] {
        let all = try learnedNames(db, f, backfill: backfill)
        var names: [String: LearnedName] = [:]
        for n in all where names[n.key] == nil { names[n.key] = n }
        var orders: [LearnedOrder] = []
        var used = Set<String>()
        let docs = try Row.fetchAll(db, sql: """
            SELECT d.id, d.code, d.doc_date, COALESCE(c.name, '') AS customer FROM documents d
            LEFT JOIN customers c ON c.id = d.customer_id WHERE d.kind = 'delivery' AND d.status = 'active'
            ORDER BY d.doc_date DESC, d.id DESC
            """)
        for d in docs {
            var lines: [LearnedLine] = []
            for r in try Row.fetchAll(db, sql: "SELECT line_no, raw_name, raw_spec, qty FROM document_lines WHERE document_id = ? ORDER BY line_no",
                                      arguments: [d["id"] as Int64]) {
                let key = TextRules.matchKey(r["raw_name"] ?? "", r["raw_spec"] ?? "")
                if let n = names[key] {
                    lines.append(LearnedLine(key: key, label: [r["raw_name"] ?? "", r["raw_spec"] ?? ""].filter { !$0.isEmpty }.joined(separator: " "),
                                             qty: r["qty"] ?? 0, productId: n.productId, documents: n.documents))
                }
            }
            for r in try Row.fetchAll(db, sql: "SELECT key, raw_name FROM document_skipped_lines WHERE document_id = ?",
                                      arguments: [d["id"] as Int64]) {
                let key: String = r["key"]
                if let n = names[key] {
                    let raw: String = r["raw_name"] ?? ""
                    lines.append(LearnedLine(key: key, label: raw.isEmpty ? n.label : raw, qty: 0, productId: nil, documents: n.documents))
                }
            }
            if !lines.isEmpty {
                used.formUnion(lines.map(\.key))
                orders.append(LearnedOrder(docId: d["id"], code: d["code"], docDate: d["doc_date"], customer: d["customer"], lines: lines))
            }
        }
        var seen = Set<String>()
        let rest = all.filter { !used.contains($0.key) && seen.insert($0.key).inserted }
            .map { LearnedLine(key: $0.key, label: $0.label, qty: 0, productId: $0.productId, documents: []) }
        if !rest.isEmpty { orders.append(LearnedOrder(docId: nil, code: "", docDate: "", customer: "", lines: rest)) }
        return orders
    }

    /// Forget a learned name and read again the notes containing it. Returns the number of notes.
    @discardableResult
    public static func forgetName(_ db: Database, _ f: ShopFolders, key: String) throws -> Int {
        try backfillSkippedLines(db, f)
        let docs = try documentsWithKey(db, key: key)
        try checkRereadable(db, f, docs)
        try Catalog.forgetAlias(db, key: key)
        try Catalog.unignoreLine(db, key: key)
        for id in docs { try rereadDocument(db, f, docId: id) }
        return docs.count
    }
}
