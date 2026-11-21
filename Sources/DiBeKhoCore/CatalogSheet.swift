import Foundation

/// Python excel/catalog_sheet: reads the customer's monthly stock sheet (Bảng thống kê nhập - xuất kho tháng …) into
/// catalog items. Layout by label: a header row with 'Tên sản phẩm' and 'Phân loại'; one product per row below it;
/// column A = Vietnamese name + Chinese name; a merged name block means the rows are variants of one product.
public enum CatalogSheet {
    public struct Item: Equatable {
        public var row: Int
        public var nameVi: String, nameZh: String, spec: String, unit: String, category: String, variant: String
        public var stock: Double?
    }

    public struct Column: Equatable {
        public let col: Int
        public let letter: String
        public let label: String
        public let samples: [String]
    }

    public struct Columns {
        public let stockCol: Int?
        public let columns: [Column]
    }

    public struct NotCatalogSheet: Error, LocalizedError {
        public let reason: String
        public var errorDescription: String? { reason }
    }

    static let categoryNames = ["涂料类": "Sơn, vữa, keo (涂料类)", "自粘膜": "Màng tự dính (自粘膜)", "SBS": "Màng SBS",
                                "聚酯布": "Vải polyester (聚酯布)"]
    static let variantNames = ["纯原料": "Nguyên sinh (纯原料)", "再生料": "Tái chế (再生料)",
                               "瑞德牌": "Hiệu Thụy Đức (瑞德牌)", "纯白色": "Trắng tinh (纯白色)"]
    static let colours = ["纯白色": "Trắng tinh", "浅灰色": "Xám nhạt", "白色": "Trắng", "灰色": "Xám", "蓝色": "Xanh dương"]
    static let rollCategory = "Màng PPE/PPP (卷材)"
    static let notFound = "Không thấy cột 'Tên sản phẩm' / 'Phân loại'."

    /// stockCol: 1-based column with the stock (6 = F), overriding the label search.
    public static func read(_ url: URL, stockCol: Int? = nil) throws -> [Item] {
        for ws in try open(url) {
            if let items = readSheet(ws, stockCol) { return items }
        }
        throw NotCatalogSheet(reason: notFound)
    }

    public static func columns(_ url: URL) throws -> Columns {
        for ws in try open(url) {
            guard let h = header(ws) else { continue }
            let items = readSheet(ws, nil) ?? []
            let maxColumn = ws.rows.map(\.count).max() ?? 0
            var out: [Column] = []
            if maxColumn > 0 {
                for col in 1...maxColumn where col != h.nameCol && col != h.typeCol {
                    let label = (cell(ws, h.row, col)?.pythonText ?? "").components(separatedBy: .newlines)
                        .map { TextRules.clean($0) }.filter { !$0.isEmpty }.joined(separator: " / ")
                    let samples = items.prefix(4).map { sample(cell(ws, $0.row, col)) }
                    if !label.isEmpty || samples.contains(where: { !$0.isEmpty }) {
                        out.append(Column(col: col, letter: letter(col), label: label, samples: samples))
                    }
                }
            }
            return Columns(stockCol: h.stockCol, columns: out)
        }
        throw NotCatalogSheet(reason: notFound)
    }

    static func letter(_ col: Int) -> String {
        var n = col, s = ""
        while n > 0 {
            let r = (n - 1) % 26
            s = String(UnicodeScalar(UInt8(65 + r))) + s
            n = (n - 1) / 26
        }
        return s
    }

    private static func open(_ url: URL) throws -> [Worksheet] {
        do { return try Xlsx.read(url) } catch { throw NotCatalogSheet(reason: "Không mở được file Excel: \(error.localizedDescription)") }
    }

    static func cell(_ ws: Worksheet, _ r: Int, _ c: Int) -> CellValue? {
        guard r >= 1, c >= 1, r <= ws.rows.count, c <= ws.rows[r - 1].count else { return nil }
        return ws.rows[r - 1][c - 1]
    }

    private static func sample(_ v: CellValue?) -> String {
        if case let .double(d)? = v, d == d.rounded(), abs(d) < 1e15 { return String(Int(d)) }
        return TextRules.clean(v?.pythonText)
    }

    private static func header(_ ws: Worksheet) -> (row: Int, nameCol: Int, typeCol: Int?, stockCol: Int?)? {
        var headerRow: Int?, nameCol = 0
        var typeCol: Int?, stockCol: Int?
        for r in 1...max(1, min(ws.rows.count, 20)) where r <= ws.rows.count {
            for (i, v) in ws.rows[r - 1].enumerated() {
                let raw = v?.pythonText ?? ""
                let plain = TextRules.unaccent(raw)
                if plain.contains("ten san pham") {
                    headerRow = r; nameCol = i + 1
                } else if plain.contains("phan loai") {
                    typeCol = i + 1
                } else if plain.contains("ton kho con lai") || raw.contains("利余库存") || raw.contains("剩余库存") {
                    stockCol = i + 1
                }
            }
            if headerRow != nil { break }
        }
        guard let headerRow else { return nil }
        return (headerRow, nameCol, typeCol, stockCol)
    }

    private static func readSheet(_ ws: Worksheet, _ chosen: Int?) -> [Item]? {
        guard let h = header(ws) else { return nil }
        let stockCol = chosen ?? h.stockCol
        var blockStart: [Int: Int] = [:], blockSize: [Int: Int] = [:]
        for m in ws.merges where m.minCol <= h.nameCol && h.nameCol <= m.maxCol && m.minRow > h.row {
            for r in m.minRow...m.maxRow { blockStart[r] = m.minRow }
            blockSize[m.minRow] = m.maxRow - m.minRow + 1
        }
        var items: [Item] = []
        var lastNameRow: Int?
        guard ws.rows.count > h.row else { return items }
        for r in (h.row + 1)...ws.rows.count {
            let raw = cell(ws, r, h.nameCol)
            let kind = h.typeCol.map { TextRules.clean(cell(ws, r, $0)?.pythonText) } ?? ""
            if let raw, TextRules.clean(raw.pythonText).count <= 1 { continue }  // the 'A | B | C' column-letter row
            var start = blockStart[r]
            if start == nil, raw == nil, !kind.isEmpty, let last = lastNameRow { start = last }
            if raw == nil && start == nil { continue }
            let sourceRow = start ?? r
            if raw != nil { lastNameRow = r }
            let text = cell(ws, sourceRow, h.nameCol)?.pythonText
            if TextRules.clean(text).isEmpty { continue }
            let grouped = start != nil && ((blockSize[start!] ?? 1) > 1 || start! != r)
            var item = makeItem(r, text ?? "", kind, grouped)
            if let stockCol { item.stock = stock(cell(ws, r, stockCol)) }
            items.append(item)
        }
        return items
    }

    private static func stock(_ v: CellValue?) -> Double? {
        guard let v else { return nil }
        switch v {
        case let .int(i): return Double(i)
        case let .double(d): return d
        default:
            let s = v.pythonText
            return TextRules.clean(s).isEmpty ? nil : parseNumber(s)
        }
    }

    // ---- one row -> product

    private static func regex(_ pattern: String) -> NSRegularExpression {
        // swiftlint:disable:next force_try
        try! NSRegularExpression(pattern: pattern, options: [.caseInsensitive])
    }

    private static let weight = regex(#"[（(]?\s*(\d+(?:[.,]\d+)?)\s*kg\s*[)）]?"#)
    private static let thick = regex(#"(\d+(?:[.,]\d+)?)\s*mm"#)
    private static let dims = regex(#"(\d+(?:[.,]\d+)?\s*c?m\s*\*\s*\d+(?:[.,]\d+)?\s*m)"#)
    private static let gsm = regex(#"(\d+)\s*g(?:/m²)?(?![a-z])"#)
    private static let plainKg = regex(#"\d+(?:[.,]\d+)?\s*kg"#)
    private static let sbs = try! NSRegularExpression(pattern: #"SBS\s+(\d+(?:[.,]\d+)?)\b"#)
    private static let trailingParen = try! NSRegularExpression(pattern: #"[（(]\s*([^（）()]+?)\s*[)）]\s*$"#)
    private static let emptyParen = try! NSRegularExpression(pattern: #"[（(]\s*[)）]"#)
    private static let ppe = try! NSRegularExpression(pattern: #"PP[EP]"#)

    private static func firstMatch(_ re: NSRegularExpression, _ s: String) -> (NSTextCheckingResult, NSString)? {
        let ns = s as NSString
        guard let m = re.firstMatch(in: s, range: NSRange(location: 0, length: ns.length)) else { return nil }
        return (m, ns)
    }

    private static func group(_ re: NSRegularExpression, _ s: String, _ i: Int = 1) -> String? {
        guard let (m, ns) = firstMatch(re, s), m.range(at: i).location != NSNotFound else { return nil }
        return ns.substring(with: m.range(at: i))
    }

    private static func replaceAll(_ re: NSRegularExpression, _ s: String, _ with: String) -> String {
        re.stringByReplacingMatches(in: s, range: NSRange(location: 0, length: (s as NSString).length), withTemplate: with)
    }

    private static func dot(_ s: String) -> String { s.replacingOccurrences(of: ",", with: ".") }

    static func makeItem(_ row: Int, _ text: String, _ kind: String, _ grouped: Bool) -> Item {
        let lines = text.precomposedStringWithCanonicalMapping.components(separatedBy: .newlines)
            .map { TextRules.clean($0) }.filter { !$0.isEmpty }
        var nameVi = "", nameZh = ""
        if lines.count == 1 {
            nameVi = lines[0]
            nameZh = TextRules.hasCJK(lines[0]) && !latinHeavy(lines[0]) ? lines[0] : ""
        } else if let first = lines.first {
            nameVi = first
            nameZh = lines.dropFirst().joined(separator: " ")
        }
        var variants: [String] = []
        if let (m, ns) = firstMatch(trailingParen, nameZh) {
            let inside = ns.substring(with: m.range(at: 1))
            if let colour = colours[inside] {
                variants.append(colour)
                nameZh = ns.substring(to: m.range.location).trimmingCharacters(in: .whitespacesAndNewlines)
            }
        }
        let spec = specOf("\(nameVi) \(nameZh)")
        nameVi = stripWeight(nameVi)
        nameZh = stripWeight(nameZh)
        var category: String
        if grouped {
            category = firstMatch(ppe, text) != nil ? rollCategory : ""
            if !kind.isEmpty { variants.append(variantNames[kind] ?? kind) }
        } else {
            category = categoryNames[kind] ?? kind
        }
        return Item(row: row, nameVi: nameVi.isEmpty ? nameZh : nameVi, nameZh: nameZh, spec: spec,
                    unit: unitOf(spec, category, nameZh), category: category, variant: variants.joined(separator: ", "), stock: nil)
    }

    private static func latinHeavy(_ text: String) -> Bool {
        let letters = text.filter { $0.isLetter }
        guard !letters.isEmpty else { return false }
        let cjk = letters.filter { TextRules.hasCJK(String($0)) }.count
        return Double(cjk) / Double(letters.count) < 0.3
    }

    private static func specOf(_ text: String) -> String {
        var parts: [String] = []
        if let v = group(thick, text) {
            parts.append("\(dot(v))mm")
        } else if let v = group(sbs, text) {
            parts.append("\(dot(v))mm")
        }
        if let v = group(gsm, replaceAll(plainKg, text, "")) { parts.append("\(v)g") }
        if let v = group(dims, text) { parts.append(v.components(separatedBy: .whitespacesAndNewlines).joined()) }
        if let v = group(weight, text) { parts.append("\(dot(v))KG") }
        return parts.joined(separator: " ")
    }

    private static func stripWeight(_ name: String) -> String {
        TextRules.clean(replaceAll(emptyParen, replaceAll(weight, name, " "), " "))
    }

    private static func unitOf(_ spec: String, _ category: String, _ nameZh: String) -> String {
        if nameZh.contains("袋") { return "gói" }
        if category.contains("Màng") || category.contains("Vải") || spec.contains("*") || spec.contains("mm") { return "cuộn" }
        if spec.contains("KG") { return "thùng" }
        return ""
    }
}
