import Foundation
import GRDB

/// 'Dữ liệu gốc': the catalog, the customer list and the stock as one Excel workbook (Python excel/master_data.py and
/// catalog.import_master). Sheet 1 products, sheet 2 customers, sheet 3 stock; A1 of each starts with `marker`; header
/// in row 4, data from row 5. Read by position, so the file reads back whatever language it was written in.
public enum MasterData {
    public static let marker = "DIBEKHO"
    public static let headerRow = 4

    public struct NotMasterData: Error, LocalizedError {
        public let reason: String
        public var errorDescription: String? { reason }
    }

    public struct Product {
        public var row: Int
        public var code: String
        public var nameVi: String
        public var nameZh = "", spec = "", variant = "", unit = "", category = ""
        /// 'YYYY-MM-DD HH:MM:SS' or ''
        public var createdAt = ""
        public var active = true
    }

    public struct Stock {
        public var row: Int
        public var code: String
        public var name: String
        public var stock: Double?
        /// the row of sheet 1 it belongs to; nil = not found
        public var productRow: Int?
        public var category = "", variant = ""
        /// "code" | "name" | "position" | "" (not found)
        public var matchedBy = ""
        /// the product's stock note; nil = a file without that column (keep the app's)
        public var note: String?
    }

    public struct Customer {
        public var row: Int
        public var name: String
        public var phone = "", contact = "", address = ""
        /// nil: a file from before 18/11/2026 has no such column (the app keeps its own)
        public var taxCode: String?
        public var email: String?
    }

    public struct Contents {
        public var products: [Product]
        public var customers: [Customer]
        public var stock: [Stock]
    }

    // ---- matching helpers (also used by the check dialog) ----------------------------------------------------

    /// True when some stock row is not tied to its product by a unique code.
    public static func needsCheck(_ stock: [Stock]) -> Bool { stock.contains { $0.matchedBy != "code" } }

    /// Compared without case, spaces or full-width forms ('（HY98）' = '(hy98)').
    static func norm(_ text: String) -> String { String(TextRules.matchKey(TextRules.clean(text), "").dropLast()) }

    static func nameText(_ nameVi: String, _ spec: String, _ nameZh: String) -> String {
        var first = nameVi
        if !spec.isEmpty && !first.lowercased().contains(spec.lowercased()) { first += " (\(spec))" }
        return (!nameZh.isEmpty && nameZh != nameVi) ? "\(first)\n\(nameZh)" : first
    }

    static func productKey(_ p: Product) -> String { norm(nameText(p.nameVi, p.spec, p.nameZh)) }

    struct ChineseKey: Hashable { let zh: String, spec: String }

    static func chineseKey(_ p: Product) -> ChineseKey? { p.nameZh.isEmpty ? nil : ChineseKey(zh: norm(p.nameZh), spec: norm(p.spec)) }

    static func fitsChinese(_ text: String, _ key: ChineseKey) -> Bool { text.hasSuffix(key.zh) && text.contains(key.spec) }

    /// Category and type/colour as a set: users put the same label in either column.
    static func labels(_ values: String...) -> Set<String> {
        var out = Set<String>()
        for v in values { for word in TextRules.clean(v).split(separator: " ") { out.insert(norm(String(word))) } }
        return out
    }

    /// The stock row names another product: neither the whole name nor the Chinese name + packing fit.
    public static func stockDiffers(_ st: Stock, _ p: Product) -> Bool {
        let text = norm(st.name)
        if text == productKey(p) { return false }
        if let key = chineseKey(p), fitsChinese(text, key) { return false }
        return true
    }

    /// (product's 'category · type', stock sheet's) when the stock sheet says otherwise; the import applies the
    /// stock sheet's, since the customer edits only that sheet.
    public static func labelChange(_ st: Stock, _ p: Product) -> (old: String, new: String)? {
        guard p.category != st.category || p.variant != st.variant else { return nil }
        func join(_ a: String, _ b: String) -> String { let s = [a, b].filter { !$0.isEmpty }.joined(separator: " · "); return s.isEmpty ? "—" : s }
        return (join(p.category, p.variant), join(st.category, st.variant))
    }

    /// Rows of the stock sheet that cannot be told apart (same name, category and type/colour): row -> the other such rows.
    public static func sameRows(_ stock: [Stock]) -> [Int: [Int]] {
        var groups: [String: [Int]] = [:]
        for st in stock {
            let labelKey = labels(st.category, st.variant).sorted().joined(separator: "\u{1}")
            groups[norm(st.name) + "\u{2}" + labelKey, default: []].append(st.row)
        }
        var out: [Int: [Int]] = [:]
        for rows in groups.values where rows.count > 1 { for r in rows { out[r] = rows.filter { $0 != r } } }
        return out
    }

    // ---- write -----------------------------------------------------------------------------------------------

    @discardableResult
    public static func export(_ db: Database, to url: URL, now: Date = Date()) throws -> URL {
        let stamp = DateFormatter()
        stamp.locale = Locale(identifier: "en_US_POSIX")
        stamp.dateFormat = "dd/MM/yyyy HH:mm"
        let note = t("master.note", ["at": stamp.string(from: now)])

        var products = XSheet(name: t("master.sheet_products"))
        var rows: [[XValue]] = []
        for (i, p) in try Row.fetchAll(db, sql: "SELECT * FROM products ORDER BY code").enumerated() {
            rows.append([.number(Double(i + 1)), .text(p["code"] ?? ""), .text(p["name_vi"] ?? ""), .text(p["name_zh"] ?? ""),
                         .text(p["spec"] ?? ""), .text(p["variant"] ?? ""), .text(p["unit"] ?? ""), .text(p["category"] ?? ""),
                         createdValue(p["created_at"] ?? ""), .text(((p["active"] as Int?) ?? 1) != 0 ? t("btn.yes") : t("btn.no"))])
        }
        fill(&products, title: t("master.title_products"), note: note,
             headers: [t("master.col_no"), t("col.code"), t("master.col_name_vi"), t("col.name_zh"), t("col.spec"), t("col.variant"),
                       t("col.unit"), t("col.category"), t("master.col_created"), t("settings.active")],
             rows: rows, widths: [5, 10, 42, 30, 14, 20, 8, 24, 12, 9], dateCol: 9)

        var customers = XSheet(name: t("master.sheet_customers"))
        rows = []
        let list = try Row.fetchAll(db, sql: """
            SELECT c.*, (SELECT COUNT(*) FROM documents d WHERE d.customer_id = c.id AND d.kind = 'delivery'
                         AND d.status = 'active') AS orders FROM customers c ORDER BY c.name
            """)
        for (i, c) in list.enumerated() {
            rows.append([.number(Double(i + 1)), .text(c["name"] ?? ""), .text(c["phone"] ?? ""), .text(c["contact"] ?? ""),
                         .text(c["address"] ?? ""), .number(Double((c["orders"] as Int?) ?? 0)), .text(c["tax_code"] ?? ""),
                         .text(c["email"] ?? "")])
        }
        fill(&customers, title: t("master.title_customers"), note: note,
             headers: [t("master.col_no"), t("col.customer"), t("col.phone"), t("col.contact"), t("col.address"),
                       t("master.col_orders"), t("col.tax_code"), t("col.email")],
             rows: rows, widths: [5, 36, 15, 18, 48, 9, 16, 28], dateCol: nil)

        var stock = XSheet(name: t("master.sheet_stock"))
        let levels = try Ledger.levels(db)
        let placed = try Ledger.levelsByPlace(db)
        rows = []
        for p in try Row.fetchAll(db, sql: "SELECT * FROM products WHERE active = 1 ORDER BY code") {
            let id: Int64 = p["id"]
            rows.append([.text(p["code"] ?? ""),
                         .text(nameText(p["name_vi"] ?? "", p["spec"] ?? "", p["name_zh"] ?? "")),
                         .text(p["category"] ?? ""), .text(p["variant"] ?? ""),
                         .number(levels[id] ?? 0),
                         .number(placed[Ledger.PlaceKey(id, Ledger.main)] ?? 0),
                         .number(placed[Ledger.PlaceKey(id, Ledger.office)] ?? 0),
                         .number(placed[Ledger.PlaceKey(id, Ledger.bacNinh)] ?? 0),
                         .text(p["stock_note"] ?? "")])
        }
        fill(&stock, title: t("master.title_stock"), note: note,
             headers: [t("col.code"), t("col.product"), t("col.category"), t("col.variant"), t("col.stock"), t("loc.main"),
                       t("loc.office"), t("loc.office_bn"), t("col.stock_note")],
             rows: rows, widths: [10, 52, 26, 22, 12, 12, 14, 14, 40], dateCol: nil)

        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try XlsxWriter.write([products, customers, stock], to: url)
        return url
    }

    private static func createdValue(_ text: String) -> XValue {
        guard let p = isoParts(text) else { return .text(text) }
        // a day number with the time of day as a fraction (openpyxl writes a datetime this way); shown as dd/mm/yyyy
        let seconds = Double(p.3 * 3600 + p.4 * 60 + p.5)
        return .number(Double(XlsxWriter.excelDay(p.0, p.1, p.2)) + seconds / 86400)
    }

    private static func fill(_ ws: inout XSheet, title: String, note: String, headers: [String], rows: [[XValue]],
                             widths: [Double], dateCol: Int?) {
        var big = XStyle(); big.bold = true; big.fontSize = 14
        ws.put(1, 1, .text("\(marker) – \(title)"), big)
        var small = XStyle(); small.italic = true; small.fontColor = "595959"
        ws.put(2, 1, .text(note), small)
        var head = XStyle()
        head.bold = true; head.fontColor = "FFFFFF"; head.fill = "1F4E78"; head.box = true; head.borderColor = "BFBFBF"
        head.horizontal = "center"; head.vertical = "center"; head.wrap = true
        for (i, h) in headers.enumerated() { ws.put(headerRow, i + 1, .text(h), head) }
        var body = XStyle()
        body.box = true; body.borderColor = "BFBFBF"; body.vertical = "top"; body.wrap = true
        for (r, row) in rows.enumerated() {
            for (c, value) in row.enumerated() {
                var style = body
                if c + 1 == dateCol { style.numberFormat = "dd/mm/yyyy" }
                ws.put(headerRow + 1 + r, c + 1, value, style)
            }
        }
        ws.columnWidths = widths
        ws.freeze = (headerRow + 1, 3)
        ws.autoFilter = "A\(headerRow):\(XlsxWriter.columnName(headers.count))\(max(headerRow + rows.count, headerRow))"
    }

    // ---- read ------------------------------------------------------------------------------------------------

    public static func read(_ url: URL) throws -> Contents {
        let sheets: [Worksheet]
        do { sheets = try Xlsx.read(url) } catch { throw NotMasterData(reason: error.localizedDescription) }
        guard sheets.count >= 2, sheets.prefix(2).allSatisfy({ cell($0, 1, 1).hasPrefix(marker) }) else {
            throw NotMasterData(reason: t("master.not_master"))
        }
        // files exported before 28/10/2026 have an extra 'min_stock' column (dropped) between created and active
        let activeIndex = headerCount(sheets[0]) >= 11 ? 10 : 9
        var products: [Product] = []
        for (r, row) in dataRows(sheets[0], 11) {
            let name = TextRules.clean(text(row[2]))
            if name.isEmpty { continue }
            products.append(Product(row: r, code: TextRules.clean(text(row[1])), nameVi: name,
                                    nameZh: TextRules.clean(text(row[3])), spec: TextRules.clean(text(row[4])),
                                    variant: TextRules.clean(text(row[5])), unit: TextRules.clean(text(row[6])),
                                    category: TextRules.clean(text(row[7])), createdAt: created(row[8]),
                                    active: isActive(row[activeIndex])))
        }
        // MST and Email (from 18/11/2026) come after the order count; an older file has neither column
        let hasTax = headerCount(sheets[1]) >= 8
        var customers: [Customer] = []
        for (r, row) in dataRows(sheets[1], 8) {
            let name = TextRules.clean(text(row[1])), phone = TextRules.clean(text(row[2]))
            if name.isEmpty && phone.isEmpty { continue }
            customers.append(Customer(row: r, name: name, phone: phone, contact: TextRules.clean(text(row[3])),
                                      address: TextRules.clean(text(row[4])),
                                      taxCode: hasTax ? TextRules.clean(wholeText(row[6])) : nil,
                                      email: hasTax ? TextRules.clean(text(row[7])) : nil))
        }
        var stock: [Stock] = []
        if sheets.count > 2, cell(sheets[2], 1, 1).hasPrefix(marker) { stock = readStock(sheets[2], products) }
        return Contents(products: products, customers: customers, stock: stock)
    }

    private static func text(_ value: CellValue?) -> String { value?.pythonText ?? "" }

    private static func cell(_ ws: Worksheet, _ row: Int, _ col: Int) -> String {
        guard row >= 1, row <= ws.rows.count, col >= 1, col <= ws.rows[row - 1].count else { return "" }
        return text(ws.rows[row - 1][col - 1])
    }

    private static func headerCount(_ ws: Worksheet) -> Int {
        guard headerRow <= ws.rows.count else { return 0 }
        return ws.rows[headerRow - 1].filter { !TextRules.clean(text($0)).isEmpty }.count
    }

    /// (row number, the row padded with empty cells to at least `width`) for every row from the first data row.
    private static func dataRows(_ ws: Worksheet, _ width: Int) -> [(Int, [CellValue?])] {
        guard ws.rows.count > headerRow else { return [] }
        return (headerRow..<ws.rows.count).map { i in
            var row = ws.rows[i]
            while row.count < width { row.append(nil) }
            return (i + 1, row)
        }
    }

    /// A tax code typed as a number: 101234567.0 -> 101234567 (not '101234567.0').
    private static func wholeText(_ value: CellValue?) -> String {
        if case let .double(d)? = value, d == d.rounded(), abs(d) < 1e15 { return String(Int64(d)) }
        return text(value)
    }

    private static func isActive(_ value: CellValue?) -> Bool {
        !["không", "khong", "no", "0", "false", "否"].contains(TextRules.clean(text(value)).lowercased())
    }

    /// (y, m, d, h, mi, s) of 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM[:SS]' (also with a 'T'); nil when it is not one.
    private static func isoParts(_ text: String) -> (Int, Int, Int, Int, Int, Int)? {
        let s = TextRules.clean(text)
        guard let re = try? NSRegularExpression(pattern: #"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$"#),
              let m = re.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) else { return nil }
        func num(_ i: Int) -> Int {
            guard let r = Range(m.range(at: i), in: s) else { return 0 }
            return Int(s[r]) ?? 0
        }
        let parts = (num(1), num(2), num(3), num(4), num(5), num(6))
        guard (1...12).contains(parts.1), (1...31).contains(parts.2), parts.3 < 24, parts.4 < 60, parts.5 < 60 else { return nil }
        return parts
    }

    private static func created(_ value: CellValue?) -> String {
        func fmt(_ p: (Int, Int, Int, Int, Int, Int)) -> String {
            String(format: "%04d-%02d-%02d %02d:%02d:%02d", p.0, p.1, p.2, p.3, p.4, p.5)
        }
        if case let .date(y, m, d, h, mi, s)? = value { return fmt((y, m, d, h, mi, s)) }
        let s = TextRules.clean(text(value))
        if let p = isoParts(s) { return fmt(p) }
        let head = String(s.prefix(10))
        if let re = try? NSRegularExpression(pattern: #"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})"#),
           let m = re.firstMatch(in: head, range: NSRange(head.startIndex..., in: head)),
           let a = Range(m.range(at: 1), in: head), let b = Range(m.range(at: 2), in: head), let c = Range(m.range(at: 3), in: head),
           let day = Int(head[a]), let month = Int(head[b]), let year = Int(head[c]),
           (1...12).contains(month), (1...31).contains(day) {
            return fmt((year, month, day, 0, 0, 0))
        }
        return ""
    }

    private static func stockValue(_ value: CellValue?) -> Double? {
        guard let value else { return nil }
        switch value {
        case let .int(i): return Double(i)
        case let .double(d): return d
        case let .bool(b): return b ? 1 : 0
        case .date, .time: return nil
        case let .text(s):
            let t = TextRules.clean(s)
            return t.isEmpty ? nil : parseNumber(t)
        }
    }

    /// Rows of the stock sheet, each tied to a row of sheet 1 (by code, then by what the row says, then by position).
    static func readStock(_ ws: Worksheet, _ products: [Product]) -> [Stock] {
        let count = headerCount(ws)
        let withCode = count >= 5
        let withNote = withCode && count >= 8
        let noteAt = count >= 9 ? 8 : 7  // a Văn phòng Bắc Ninh column before the note from 25/11/2026
        var rows: [Stock] = []
        for (r, raw) in dataRows(ws, 9) {
            var row = raw
            if !withCode { row.insert(nil, at: 0) }
            let code = TextRules.clean(text(row[0])), name = TextRules.clean(text(row[1]))
            if code.isEmpty && name.isEmpty { continue }
            rows.append(Stock(row: r, code: code, name: name, stock: stockValue(row[4]), productRow: nil,
                              category: TextRules.clean(text(row[2])), variant: TextRules.clean(text(row[3])),
                              matchedBy: "", note: withNote ? TextRules.clean(text(row[noteAt])) : nil))
        }
        let active = products.filter { $0.active }
        var codeCount: [String: Int] = [:]
        for p in products { codeCount[p.code, default: 0] += 1 }
        var byCode: [String: Product] = [:]
        for p in products where !p.code.isEmpty && codeCount[p.code] == 1 { byCode[p.code] = p }
        var taken = Set<Int>()

        for i in rows.indices where !rows[i].code.isEmpty {  // 1. code
            if let p = byCode[rows[i].code], !taken.contains(p.row) {
                rows[i].productRow = p.row
                rows[i].matchedBy = "code"
                taken.insert(p.row)
            }
        }

        // 2. what the row says: the whole name, then the Chinese name + packing
        var position: [Int: Int] = [:]
        for (i, p) in active.enumerated() { position[p.row] = i }
        func pass<K: Hashable>(_ key: (Product) -> K?, _ fits: (String, K) -> Bool) {
            var order: [K] = []
            var groups: [K: (stocks: [Int], prods: [Product])] = [:]
            for p in active where !taken.contains(p.row) {
                guard let k = key(p) else { continue }
                if groups[k] == nil { groups[k] = ([], []); order.append(k) }
                groups[k]!.prods.append(p)
            }
            for i in rows.indices where rows[i].productRow == nil {
                let text = norm(rows[i].name)
                let keys = order.filter { fits(text, $0) }
                if keys.count == 1 { groups[keys[0]]!.stocks.append(i) }
            }
            for k in order {
                let g = groups[k]!
                for (i, p) in bestPairs(g.stocks, g.prods, rows, position) {
                    rows[i].productRow = p.row
                    rows[i].matchedBy = "name"
                    taken.insert(p.row)
                }
            }
        }
        pass({ productKey($0) }, { $0 == $1 })
        pass({ chineseKey($0) }, { fitsChinese($0, $1) })

        // 3. position, for rows whose name was changed in one sheet only
        if rows.count == active.count {
            for i in rows.indices where rows[i].productRow == nil && !taken.contains(active[i].row) {
                rows[i].productRow = active[i].row
                rows[i].matchedBy = "position"
                taken.insert(active[i].row)
            }
        }
        return rows.filter { $0.stock != nil }
    }

    /// Stock rows (their indexes in the sheet) and products sharing one name: pair them for the most labels in common,
    /// then the most rows at the same position. A handful of rows per name, so trying every pairing is cheap.
    private static func bestPairs(_ stocks: [Int], _ prods: [Product], _ rows: [Stock], _ position: [Int: Int]) -> [(Int, Product)] {
        if stocks.isEmpty || prods.isEmpty { return [] }
        if stocks.count > 7 || prods.count > 7 { return zip(stocks, prods).map { ($0, $1) } }

        func score(_ pairs: [(Int, Product)]) -> (Int, Int) {
            var common = 0, same = 0
            for (i, p) in pairs {
                common += labels(rows[i].category, rows[i].variant).intersection(labels(p.category, p.variant)).count
                if i == position[p.row] { same += 1 }
            }
            return (common, same)
        }
        var best: [(Int, Product)] = []
        var bestScore = (-1, -1)
        func consider(_ pairs: [(Int, Product)]) {
            let s = score(pairs)
            if s.0 > bestScore.0 || (s.0 == bestScore.0 && s.1 > bestScore.1) { best = pairs; bestScore = s }
        }
        if stocks.count <= prods.count {
            for chosen in arrangements(prods.count, stocks.count) { consider(zip(stocks, chosen.map { prods[$0] }).map { ($0, $1) }) }
        } else {
            for chosen in arrangements(stocks.count, prods.count) { consider(zip(chosen.map { stocks[$0] }, prods).map { ($0, $1) }) }
        }
        return best
    }

    /// Every ordered choice of k of n indexes, in lexicographic order (Python itertools.permutations(range(n), k)).
    private static func arrangements(_ n: Int, _ k: Int) -> [[Int]] {
        var out: [[Int]] = []
        var current: [Int] = []
        var used = [Bool](repeating: false, count: n)
        func go() {
            if current.count == k { out.append(current); return }
            for i in 0..<n where !used[i] {
                used[i] = true
                current.append(i)
                go()
                current.removeLast()
                used[i] = false
            }
        }
        go()
        return out
    }

    // ---- import ----------------------------------------------------------------------------------------------

    public struct Outcome {
        public var productsNew = 0, productsUpdated = 0, customersNew = 0, customersUpdated = 0
        public var skipped: [(row: Int, code: String, existing: String)] = []
        public var stockCounted = 0
        public var stockSkipped: [(row: Int, name: String)] = []
        public var renumbered: [(row: Int, code: String, new: String)] = []
        public var labelsUpdated: [String] = []
    }

    /// Next SPxxx that is neither in the database nor used further down in the file.
    private static func freeCode(_ db: Database, reserved: Set<String>) throws -> String {
        var code = try Catalog.nextProductCode(db)
        while reserved.contains(code) { code = "SP" + String(format: "%03d", Catalog.codeNumber(code) + 1) }
        return code
    }

    /// A code that exists is updated to the file's values; a new code is created as is (no code: next free one). A
    /// product whose name/packing/variant already exists here under a code that is not in the file is skipped.
    /// Customers are matched by phone number, then by name. Stock rows give one stock count on `stockDate`, so the
    /// app's stock equals the file's numbers; the stock sheet's category and type/colour replace the product's.
    public static func importMaster(_ db: Database, products: [Product], customers: [Customer], stock: [Stock] = [],
                                    stockDate: String, note: String = "") throws -> Outcome {
        var result = Outcome()
        var rowIds: [Int: Int64] = [:]
        var seen = Set<String>()
        let fileCodes = Set(products.map { $0.code }.filter { !$0.isEmpty })
        for p in products {
            let unit = p.unit.isEmpty ? Catalog.guessUnit(p.spec) : p.unit
            let duplicate = !p.code.isEmpty && seen.contains(p.code)
            seen.insert(p.code)
            var existing: Int64?
            if !p.code.isEmpty && !duplicate {
                existing = try Int64.fetchOne(db, sql: "SELECT id FROM products WHERE code = ?", arguments: [p.code])
            }
            if let id = existing {
                try Catalog.updateProduct(db, id: id, Catalog.ProductFields(nameVi: p.nameVi, nameZh: p.nameZh, spec: p.spec, unit: unit,
                                                                           category: p.category, variant: p.variant, active: p.active))
                if !p.createdAt.isEmpty { try db.execute(sql: "UPDATE products SET created_at = ? WHERE id = ?", arguments: [p.createdAt, id]) }
                result.productsUpdated += 1
                rowIds[p.row] = id
                continue
            }
            // the category counts too: users tell variants apart in either column
            if let same = try Catalog.findSame(db, nameVi: p.nameVi, spec: p.spec, variant: p.variant, category: p.category),
               !fileCodes.contains(same.code) {
                result.skipped.append((p.row, p.code, same.code))
                rowIds[p.row] = same.id
                continue
            }
            var code = p.code
            if p.code.isEmpty || duplicate { code = try freeCode(db, reserved: fileCodes) }
            if duplicate { result.renumbered.append((p.row, p.code, code)) }
            try db.execute(sql: """
                INSERT INTO products(code, name_vi, name_zh, spec, unit, category, active, variant, created_at)
                VALUES(?,?,?,?,?,?,?,?, COALESCE(NULLIF(?, ''), datetime('now','localtime')))
                """, arguments: [code, p.nameVi, p.nameZh, p.spec, unit, p.category, p.active ? 1 : 0, p.variant, p.createdAt])
            rowIds[p.row] = db.lastInsertedRowID
            try Meta.set(db, Catalog.freedCodesKey, try Catalog.freedCodes(db).filter { $0 != code }.joined(separator: ","))
            result.productsNew += 1
        }
        for c in customers {
            let phoneNorm = Catalog.normalizePhone(c.phone)
            var id: Int64?
            if !phoneNorm.isEmpty { id = try Int64.fetchOne(db, sql: "SELECT id FROM customers WHERE phone_norm = ?", arguments: [phoneNorm]) }
            if id == nil && !c.name.isEmpty {
                id = try Int64.fetchOne(db, sql: "SELECT id FROM customers WHERE unaccent(name) = ?", arguments: [TextRules.unaccent(c.name)])
            }
            let name = c.name.isEmpty ? c.phone : c.name
            if let id {
                var sql = "UPDATE customers SET name = ?, contact = ?, phone = ?, phone_norm = ?, address = ?"
                var args: [DatabaseValueConvertible] = [name, c.contact, c.phone, phoneNorm, c.address]
                // a file made before 18/11/2026 has no MST / Email columns (nil): what the app has stays
                if let tax = c.taxCode { sql += ", tax_code = ?"; args.append(tax) }
                if let email = c.email { sql += ", email = ?"; args.append(email) }
                try db.execute(sql: sql + " WHERE id = ?", arguments: StatementArguments(args + [id]))
                result.customersUpdated += 1
            } else {
                try db.execute(sql: "INSERT INTO customers(name, contact, phone, phone_norm, address, tax_code, email) VALUES(?,?,?,?,?,?,?)",
                               arguments: [name, c.contact, c.phone, phoneNorm, c.address, c.taxCode ?? "", c.email ?? ""])
                result.customersNew += 1
            }
        }
        try Meta.touch(db)
        try Meta.log(db, "master_import", "\(result.productsNew)+\(result.productsUpdated) products, \(result.customersNew)+\(result.customersUpdated) customers")
        var counted: [Ledger.Counted] = []
        for st in stock {
            guard let pr = st.productRow, let pid = rowIds[pr], let qty = st.stock else {
                result.stockSkipped.append((st.row, st.code.isEmpty ? st.name : st.code))
                continue
            }
            if let i = counted.firstIndex(where: { $0.productId == pid }) { counted[i].qty = qty } else { counted.append(Ledger.Counted(pid, nil, qty)) }
            if let row = try Row.fetchOne(db, sql: "SELECT code, category, variant FROM products WHERE id = ?", arguments: [pid]) {
                let category: String = row["category"] ?? "", variant: String = row["variant"] ?? ""
                if category != st.category || variant != st.variant {
                    try Catalog.updateProduct(db, id: pid, Catalog.ProductFields(category: st.category, variant: st.variant))
                    result.labelsUpdated.append(row["code"] ?? "")
                }
            }
            if let note = st.note { try Catalog.updateProduct(db, id: pid, Catalog.ProductFields(stockNote: note)) }
        }
        if !counted.isEmpty {
            try Ledger.stockCount(db, date: stockDate, counted: counted, note: note)
            result.stockCounted = counted.count
        }
        return result
    }
}
