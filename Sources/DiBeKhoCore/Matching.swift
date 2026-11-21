import Foundation
import GRDB

/// Python difflib.SequenceMatcher(None, a, b).ratio(), step for step (including the "popular element" shortcut for
/// a second string of 200 characters or more), so a product name scores the same here as in the Python app.
struct SequenceMatcher {
    private let a: [UInt32]
    private let b: [UInt32]
    private var b2j: [UInt32: [Int]] = [:]

    init(_ first: String, _ second: String) {
        a = first.unicodeScalars.map(\.value)
        b = second.unicodeScalars.map(\.value)
        for (i, element) in b.enumerated() { b2j[element, default: []].append(i) }
        let n = b.count
        if n >= 200 {
            let limit = n / 100 + 1
            for (element, indexes) in b2j where indexes.count > limit { b2j[element] = nil }
        }
    }

    private func longestMatch(_ alo: Int, _ ahi: Int, _ blo: Int, _ bhi: Int) -> (i: Int, j: Int, size: Int) {
        var besti = alo, bestj = blo, bestsize = 0
        var j2len: [Int: Int] = [:]
        for i in alo..<max(alo, ahi) {
            var newj2len: [Int: Int] = [:]
            for j in b2j[a[i]] ?? [] {
                if j < blo { continue }
                if j >= bhi { break }
                let k = (j2len[j - 1] ?? 0) + 1
                newj2len[j] = k
                if k > bestsize {
                    besti = i - k + 1
                    bestj = j - k + 1
                    bestsize = k
                }
            }
            j2len = newj2len
        }
        // extend over the elements the shortcut left out (no junk is declared, so every element may extend)
        while besti > alo && bestj > blo && a[besti - 1] == b[bestj - 1] {
            besti -= 1
            bestj -= 1
            bestsize += 1
        }
        while besti + bestsize < ahi && bestj + bestsize < bhi && a[besti + bestsize] == b[bestj + bestsize] {
            bestsize += 1
        }
        return (besti, bestj, bestsize)
    }

    func ratio() -> Double {
        let length = a.count + b.count
        if length == 0 { return 1.0 }
        var matches = 0
        var queue = [(0, a.count, 0, b.count)]
        while let (alo, ahi, blo, bhi) = queue.popLast() {
            let (i, j, k) = longestMatch(alo, ahi, blo, bhi)
            if k > 0 {
                matches += k
                if alo < i && blo < j { queue.append((alo, i, blo, j)) }
                if i + k < ahi && j + k < bhi { queue.append((i + k, ahi, j + k, bhi)) }
            }
        }
        return 2.0 * Double(matches) / Double(length)
    }
}

/// Python core/catalog: the name matching of "Cần xử lý" (which product is this line of a note?), the names learned
/// from the user's choices ("not goods", aliases) and the check against making a near-duplicate product.
extension Catalog {
    // ---- learned names

    public static func aliasProduct(_ db: Database, key: String) throws -> Int64? {
        try Int64.fetchOne(db, sql: "SELECT product_id FROM product_aliases WHERE key = ?", arguments: [key])
    }

    public static func setAlias(_ db: Database, key: String, productId: Int64, label: String = "") throws {
        try db.execute(sql: """
            INSERT INTO product_aliases(key, product_id, label) VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET product_id = excluded.product_id,
            label = CASE WHEN excluded.label <> '' THEN excluded.label ELSE product_aliases.label END
            """, arguments: [key, productId, label])
        try db.execute(sql: "DELETE FROM ignored_lines WHERE key = ?", arguments: [key])
        try Meta.touch(db)
    }

    static let feeWords = ["van chuyen", "ship", "dich vu", "cuoc", "运费", "服务费", "费用", "运输", "fee"]

    /// Whether a line of a note looks like a fee rather than goods (only pre-selects "not goods").
    public static func looksLikeFee(_ name: String) -> Bool {
        let text = TextRules.unaccent(name).trimmingCharacters(in: .whitespacesAndNewlines)
        return text.hasPrefix("phi ") || feeWords.contains { text.contains($0) }
    }

    public static func isIgnored(_ db: Database, key: String) throws -> Bool {
        try Row.fetchOne(db, sql: "SELECT 1 FROM ignored_lines WHERE key = ?", arguments: [key]) != nil
    }

    public static func ignoreLine(_ db: Database, key: String, label: String) throws {
        try db.execute(sql: "INSERT OR REPLACE INTO ignored_lines(key, label) VALUES(?, ?)", arguments: [key, label])
        try db.execute(sql: "DELETE FROM product_aliases WHERE key = ?", arguments: [key])
        try Meta.touch(db)
    }

    public static func unignoreLine(_ db: Database, key: String) throws {
        try db.execute(sql: "DELETE FROM ignored_lines WHERE key = ?", arguments: [key])
        try Meta.touch(db)
    }

    public static func forgetAlias(_ db: Database, key: String) throws {
        try db.execute(sql: "DELETE FROM product_aliases WHERE key = ?", arguments: [key])
        try Meta.touch(db)
    }

    public static func ignoredLines(_ db: Database) throws -> [Row] {
        try Row.fetchAll(db, sql: "SELECT * FROM ignored_lines ORDER BY label")
    }

    // ---- what a text says about a product: Chinese characters, model codes, weights, sizes

    struct Features {
        var cjk: Set<Character> = []
        var models: Set<String> = []
        var kg: Set<String> = []
        var dims: Set<String> = []
    }

    private static let modelPattern = try! NSRegularExpression(pattern: #"\b([A-Z]{2,4})\s*-?\s*(\d{2,4})\b"#)
    private static let kgPattern = try! NSRegularExpression(pattern: #"(\d+(?:[.,]\d+)?)\s*kg"#, options: .caseInsensitive)
    private static let dimPattern = try! NSRegularExpression(
        pattern: #"(\d+(?:[.,]\d+)?c?m)\s*\*\s*(\d+(?:[.,]\d+)?m)"#, options: .caseInsensitive)

    private static func groups(_ regex: NSRegularExpression, _ text: String) -> [[String]] {
        let ns = text as NSString
        return regex.matches(in: text, range: NSRange(location: 0, length: ns.length)).map { m in
            (1..<m.numberOfRanges).map { ns.substring(with: m.range(at: $0)) }
        }
    }

    /// Python rstrip("0").rstrip(".") (so "10" becomes "1": kept as it is, both sides compare the same way)
    private static func trimmedWeight(_ text: String) -> String {
        var s = text.replacingOccurrences(of: ",", with: ".")
        while s.hasSuffix("0") { s.removeLast() }
        while s.hasSuffix(".") { s.removeLast() }
        return s
    }

    static func features(_ text: String) -> Features {
        var f = Features()
        for scalar in text.unicodeScalars where (0x3400...0x4DBF).contains(scalar.value) || (0x4E00...0x9FFF).contains(scalar.value) {
            f.cjk.insert(Character(scalar))
        }
        for g in groups(modelPattern, text.uppercased()) { f.models.insert(g[0] + g[1]) }
        for g in groups(kgPattern, text) { f.kg.insert(trimmedWeight(g[0])) }
        for g in groups(dimPattern, text) { f.dims.insert("\(g[0])*\(g[1])".lowercased()) }
        return f
    }

    /// True when both are given and clearly describe different packaging (Python _spec_conflicts).
    static func specConflicts(_ first: String, _ second: String) -> Bool {
        let a = TextRules.unaccent(TextRules.clean(first)), b = TextRules.unaccent(TextRules.clean(second))
        if a.isEmpty || b.isEmpty { return false }
        let fa = features(a), fb = features(b)
        if !fa.kg.isEmpty && !fb.kg.isEmpty { return fa.kg.isDisjoint(with: fb.kg) }
        if !fa.dims.isEmpty && !fb.dims.isEmpty { return fa.dims.isDisjoint(with: fb.dims) }
        return !b.contains(a) && !a.contains(b)
    }

    /// How likely a line of a note is this product (Python catalog.match_score).
    static func matchScore(_ noteText: String, _ noteSpec: String, _ p: Product, labels: Bool = false) -> Double {
        let a = features("\(noteText) \(noteSpec)")
        let extra = labels ? " \(p.category) \(p.variant)" : ""
        let b = features("\(p.nameZh) \(p.nameVi) \(p.spec)\(extra)")
        var score = 0.0
        if !a.cjk.isEmpty && !b.cjk.isEmpty {
            let overlap = Double(a.cjk.intersection(b.cjk).count) / Double(a.cjk.count)
            if overlap < 0.5 { return 0.3 * overlap }  // the Chinese name is the most reliable identifier
            score += 0.6 * overlap
        }
        score += 0.2 * SequenceMatcher(TextRules.unaccent(noteText), TextRules.unaccent("\(p.nameVi) \(p.nameZh)")).ratio()
        if !a.models.isEmpty && !b.models.isEmpty {
            score += !a.models.isDisjoint(with: b.models) ? 0.3 : -0.6
        }
        if !a.kg.isEmpty && !b.kg.isEmpty {
            score = !a.kg.isDisjoint(with: b.kg) ? score + 0.2 : score * 0.4  // same product, other packing = other item
        }
        if !a.dims.isEmpty && !b.dims.isEmpty {
            score += !a.dims.isDisjoint(with: b.dims) ? 0.15 : -0.15
        }
        return score
    }

    /// (score, product) of the products whose Chinese name matches best, best first (Python catalog._ranked).
    static func ranked(_ db: Database, _ name: String, _ spec: String) throws -> [(Double, Product)] {
        let note = features("\(name) \(spec)").cjk
        var candidates = try products(db)
        if !note.isEmpty {
            let overlap = candidates.map { Double(note.intersection(features($0.nameZh).cjk).count) / Double(note.count) }
            let top = overlap.max() ?? 0
            if top == 0 { return [] }
            candidates = zip(candidates, overlap).filter { $0.1 >= top - 1e-9 }.map(\.0)
        }
        let scored = candidates.map { (matchScore(name, spec, $0), $0) }.filter { $0.0 > 0 }
        return stableSorted(scored)
    }

    /// Python sorted(key=-score): best first, equal scores keep the catalog order.
    static func stableSorted(_ items: [(Double, Product)]) -> [(Double, Product)] {
        items.enumerated().sorted { l, r in
            l.element.0 != r.element.0 ? l.element.0 > r.element.0 : l.offset < r.offset
        }.map(\.element)
    }

    /// The best match, nil when nothing is close enough (Python catalog.suggest_product).
    public static func suggestProduct(_ db: Database, name: String, spec: String) throws -> Int64? {
        guard let best = try ranked(db, name, spec).first, best.0 >= 0.5 else { return nil }
        return best.1.id
    }

    /// The few products that could be this line, best first (Python catalog.suggest_products).
    public static func suggestProducts(_ db: Database, name: String, spec: String, n: Int = 3) throws -> [Product] {
        let scored = try products(db).map { (matchScore(name, spec, $0, labels: true), $0) }
        return Array(stableSorted(scored).filter { $0.0 > 0.15 }.prefix(n).map(\.1))
    }

    /// Existing products that might already be this one, before a new one is created (Python
    /// catalog.find_possible_duplicates): the exact name + packing + type, then the close ones of the matcher.
    public static func findPossibleDuplicates(_ db: Database, nameVi: String, nameZh: String = "", spec: String = "",
                                              variant: String = "", category: String = "") throws -> [Product] {
        var seen = Set<Int64>(), result: [Product] = []
        if let same = try findSame(db, nameVi: nameVi, spec: spec, variant: variant, category: category.isEmpty ? nil : category) {
            seen.insert(same.id)
            result.append(same)
        }
        let variantNorm = TextRules.unaccent(TextRules.clean(variant))
        let categoryNorm = TextRules.unaccent(TextRules.clean(category))
        for (score, p) in try ranked(db, "\(nameZh) \(nameVi)", spec) {
            if score < 0.5 || seen.contains(p.id) { continue }
            if specConflicts(spec, p.spec) { continue }
            if !variantNorm.isEmpty && !p.variant.isEmpty && TextRules.unaccent(TextRules.clean(p.variant)) != variantNorm { continue }
            if !categoryNorm.isEmpty && !p.category.isEmpty && TextRules.unaccent(TextRules.clean(p.category)) != categoryNorm { continue }
            seen.insert(p.id)
            result.append(p)
        }
        return result
    }
}
