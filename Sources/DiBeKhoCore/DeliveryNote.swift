import Foundation

/// The reader of the shop's bilingual delivery notes (销售单 PHIẾU GIAO HÀNG), line for line the Python one
/// (excel/delivery_note.py): cells are found by their labels, never by position; prices never block a note.
/// Checked against it on made-up notes (GoldenNotes) and, on the developer's Mac, on the customer's own notes.
public struct DeliveryLine: Equatable {
    public let row: Int
    public let rawName: String
    public let nameVi: String
    public let nameZh: String
    public let spec: String
    public let qty: Double
    public let note: String
    public let unitPrice: Double?
    public let amount: Double?
    public let productCode: String
    /// where the goods are taken from ((location id, qty), ...) adding up to qty; empty = not said
    public let places: [(Int, Double)]

    public var key: String { TextRules.matchKey(rawName, spec) }

    public static func == (a: DeliveryLine, b: DeliveryLine) -> Bool {
        a.row == b.row && a.rawName == b.rawName && a.spec == b.spec && a.qty == b.qty && a.note == b.note
            && a.unitPrice == b.unitPrice && a.amount == b.amount && a.productCode == b.productCode
            && a.places.map(\.0) == b.places.map(\.0) && a.places.map(\.1) == b.places.map(\.1)
    }
}

public struct DeliveryNote {
    public let code: String
    public let docDate: String  // YYYY-MM-DD
    public let customerName: String
    public let phone: String
    public let contact: String
    public let address: String
    public let lines: [DeliveryLine]
    public let skippedRows: [String]
    public let fees: [(String, Double)]
    public let total: Double?
    public let warnings: [String]
    public let title: String
    public let letterhead: [String]
    /// MST and e-mail of the new template (18/11/2026); empty on older notes
    public let taxCode: String
    public let email: String
    public var currency: String = "VND"

    public var codeNorm: String { Lookup.normalizeCode(code) }
}

public enum DeliveryNoteError: Error, LocalizedError, Equatable {
    /// the file is not a delivery note at all
    case notDeliveryNote(String)
    /// a delivery note, but required data is missing or wrong
    case invalid(String)

    public var errorDescription: String? {
        switch self {
        case let .notDeliveryNote(text), let .invalid(text): return text
        }
    }
}

public enum DeliveryNoteReader {
    static let headerLabels: [(String, String)] = [
        ("customer", "ten khach hang"), ("phone", "dien thoai"), ("code", "ma don hang"),
        ("contact", "nguoi lien he"), ("date", "ngay giao hang"), ("address", "dia chi"),
    ]
    static let headerLabelsZh: [(String, String)] = [
        ("customer", "客户名称"), ("phone", "联系电话"), ("code", "订货单号"), ("contact", "联系人"),
        ("date", "送货日期"), ("address", "地址"),
    ]
    static let columnLabels: [(String, String)] = [
        ("name", "ten hang"), ("spec", "quy cach"), ("qty", "so luong"), ("note", "ghi chu"),
    ]
    static let extraLabels: [(String, String, String)] = [("code", "ma hang", "货号"), ("place", "lay tu kho", "取货地点")]
    static let placeValues: [(String, Int)] = [("kho tong", 1), ("总仓", 1), ("van phong", 2), ("办公室", 2)]
    static let priceLabels: [(String, String, String)] = [("price", "don gia", "单价"), ("amount", "thanh tien", "金额")]
    static let endMarkers = ["tong cong", "nguoi giao hang"]
    static let optionalFields: Set<String> = ["phone", "contact", "address", "tax_code", "email"]
    /// the tax code and e-mail of the new template ('MST 税号：', 'email邮箱：'), looked for at the start of a cell (a bare
    /// 'mst' inside a product name is not a label) or by their Chinese words; matched on unaccent()
    static let extraHeadLabels: [(String, NSRegularExpression)] = [
        ("tax_code", try! NSRegularExpression(pattern: #"^\s*(mst|ma so thue)(?![a-z])|税号"#)),
        ("email", try! NSRegularExpression(pattern: #"^\s*e-?mail|邮箱"#)),
    ]
    static let titleMarkers = ["phieu giao hang", "phieu xuat kho", "销售单", "出库单"]
    static let totalMarker = "tong cong"
    static let cnyWords = ["nhan dan te", "人民币", "人民幣"]

    typealias Grid = [[CellValue?]]

    // ---- small helpers, as the Python ones

    static func text(_ value: CellValue?) -> String { value?.pythonText ?? "" }

    /// value in (None, "")
    static func isEmpty(_ value: CellValue?) -> Bool {
        guard let value else { return true }
        if case let .text(s) = value { return s.isEmpty }
        return false
    }

    /// Python truthiness of a header value
    static func truthy(_ value: CellValue?) -> Bool {
        switch value {
        case .none: return false
        case let .some(.text(s)): return !s.isEmpty
        case let .some(.int(i)): return i != 0
        case let .some(.double(d)): return d != 0
        case let .some(.bool(b)): return b
        default: return true
        }
    }

    static func cell(_ row: [CellValue?], _ index: Int?) -> CellValue? {
        guard let index, index < row.count else { return nil }
        return row[index]
    }

    static func matches(_ pattern: String, _ text: String, options: NSString.CompareOptions = .regularExpression) -> Bool {
        text.range(of: pattern, options: options) != nil
    }

    static func fullMatch(_ pattern: String, _ text: String) -> Bool {
        matches("^(?:\(pattern))$", text)
    }

    /// Python repr() of a cell value (for the warnings)
    static func repr(_ value: CellValue?) -> String {
        guard let value else { return "None" }
        guard case let .text(s) = value else {
            if case let .date(y, m, d, h, mi, sec) = value {
                return "datetime.datetime(\(y), \(m), \(d), \(h), \(mi)" + (sec != 0 ? ", \(sec))" : ")")
            }
            return value.pythonText
        }
        let quote: Character = s.contains("'") && !s.contains("\"") ? "\"" : "'"
        var out = String(quote)
        for ch in s {
            switch ch {
            case "\\": out += "\\\\"
            case "\n": out += "\\n"
            case "\r": out += "\\r"
            case "\t": out += "\\t"
            case "\r\n": out += "\\r\\n"
            default:
                if ch == quote { out += "\\\(quote)" } else { out.append(ch) }
            }
        }
        out.append(quote)
        return out
    }

    // ---- reading

    public static func read(_ url: URL) throws -> DeliveryNote {
        let sheets: [Worksheet]
        do {
            sheets = try Xlsx.read(url)
        } catch {
            throw DeliveryNoteError.notDeliveryNote("Không mở được file Excel: \(error.localizedDescription)")
        }
        for sheet in sheets where findHeaderRow(sheet.rows) != nil {
            var note = try parse(sheet.rows)
            note.currency = currency(sheet)
            return note
        }
        throw DeliveryNoteError.notDeliveryNote("Không thấy bảng hàng có cột 'Tên hàng' — không phải phiếu giao hàng.")
    }

    static func findHeaderRow(_ grid: Grid) -> Int? {
        let label = columnLabels[0].1
        return grid.firstIndex { row in row.contains { TextRules.unaccent(text($0)).contains(label) } }
    }

    /// A note priced in yuan: the price cells formatted as CNY / ¥, a price header naming it, or the total in words.
    static func currency(_ sheet: Worksheet) -> String {
        let grid = sheet.rows
        guard let headerRow = findHeaderRow(grid), let columns = try? mapColumns(grid[headerRow]) else { return "VND" }
        let money = [columns["price"], columns["amount"]].compactMap { $0 }
        let cnyHeader = "CNY|RMB|[¥￥]|人民币"
        let cnyFormat = "CNY|RMB|[¥￥元]|人民币"
        if money.contains(where: { matches(cnyHeader, text(cell(grid[headerRow], $0)), options: [.regularExpression, .caseInsensitive]) }) {
            return "CNY"
        }
        for r in (headerRow + 1)..<max(grid.count, headerRow + 1) {
            let row = grid[r]
            for value in row {
                if case let .text(s)? = value,
                   cnyWords.contains(where: { TextRules.unaccent(s).contains($0) || s.contains($0) }) {
                    return "CNY"
                }
            }
            for c in money {
                if let value = cell(row, c), value.isNumber, c < sheet.formats[r].count,
                   matches(cnyFormat, sheet.formats[r][c], options: [.regularExpression, .caseInsensitive]) {
                    return "CNY"
                }
            }
        }
        return "VND"
    }

    static func parse(_ grid: Grid) throws -> DeliveryNote {
        guard let headerRow = findHeaderRow(grid) else {
            throw DeliveryNoteError.notDeliveryNote("Không thấy bảng hàng có cột 'Tên hàng' — không phải phiếu giao hàng.")
        }
        let above = Array(grid[..<headerRow])
        let head = readHeaderFields(above)
        let (title, letterhead) = titleOf(above)
        let columns = try mapColumns(grid[headerRow])

        var warnings: [String] = []
        if !truthy(head["code"] ?? nil) { throw DeliveryNoteError.invalid("Không tìm thấy 'Mã đơn hàng'.") }
        guard let docDate = parseDate(head["date"] ?? nil) else {
            let shown = TextRules.clean(text(head["date"] ?? nil))
            throw DeliveryNoteError.invalid("Không đọc được 'Ngày giao hàng' (\(shown.isEmpty ? "trống" : shown)).")
        }
        if !truthy(head["customer"] ?? nil) { warnings.append("Không tìm thấy tên khách hàng.") }

        var lines: [DeliveryLine] = []
        var skipped: [String] = []
        var fees: [(String, Double)] = []
        var badQty: [String] = []
        var total: Double?
        var r = headerRow + 1
        while r < grid.count {
            defer { r += 1 }
            let row = grid[r]
            let marks = row.enumerated().filter { $0.offset != columns["note"] }.map { TextRules.unaccent(text($0.element)) }
            if marks.contains(where: { mark in endMarkers.contains { mark.contains($0) } }) {
                if marks.contains(where: { $0.contains(totalMarker) }) {
                    total = toMoney(cell(row, columns["amount"]))
                }
                break
            }
            let rawName = text(cell(row, columns["name"]))
            var qtyValue = cell(row, columns["qty"])
            if case let .text(s)? = qtyValue, TextRules.clean(s).isEmpty { qtyValue = nil }
            if TextRules.clean(rawName).isEmpty && isEmpty(qtyValue) { continue }
            let excelRow = r + 1
            if isEmpty(qtyValue) {
                skipped.append(TextRules.clean(rawName))
                if let fee = toMoney(cell(row, columns["amount"])), fee != 0 {
                    fees.append((TextRules.clean(rawName), fee))
                }
                continue
            }
            let parsedQty = toNumber(qtyValue)
            if parsedQty == 0 {
                warnings.append("Dòng \(excelRow): số lượng 0, bỏ qua.")
                continue
            }
            if (parsedQty == nil || parsedQty! < 0) && !TextRules.clean(rawName).isEmpty {
                badQty.append("\(excelRow) ('\(TextRules.clean(text(qtyValue)))')")
                continue
            }
            guard let qty = parsedQty, qty >= 0 else {
                warnings.append("Dòng \(excelRow): số lượng không hợp lệ (\(repr(qtyValue))), bỏ qua.")
                continue
            }
            if TextRules.clean(rawName).isEmpty {
                warnings.append("Dòng \(excelRow): có số lượng nhưng thiếu tên hàng, bỏ qua.")
                continue
            }
            let (price, amount) = lineMoney(row, columns, qty, excelRow, &warnings)
            let names = TextRules.splitBilingual(rawName)
            let spec = TextRules.clean(text(cell(row, columns["spec"])))
            let (code, written) = codeOf(text(cell(row, columns["code"])))
            let trusted = written == nil || written == TextRules.matchKey(rawName, spec)
            lines.append(DeliveryLine(
                row: excelRow, rawName: TextRules.clean(rawName),
                nameVi: names.vi.isEmpty ? TextRules.clean(rawName) : names.vi, nameZh: names.zh, spec: spec, qty: qty,
                note: TextRules.clean(text(cell(row, columns["note"]))), unitPrice: price, amount: amount,
                productCode: trusted ? code : "",
                places: trusted ? placesOf(text(cell(row, columns["place"])), qty) : []))
        }
        if !badQty.isEmpty {
            throw DeliveryNoteError.invalid("Dòng \(badQty.joined(separator: ", ")): không đọc được số lượng. Hãy sửa file phiếu "
                                            + "(ô Số lượng chỉ ghi số, ví dụ 1500 hoặc 2,5) rồi bấm Quét lại.")
        }
        if lines.isEmpty { throw DeliveryNoteError.invalid("Phiếu không có dòng hàng nào có số lượng.") }
        return DeliveryNote(
            code: TextRules.clean(text(head["code"] ?? nil)), docDate: docDate,
            customerName: TextRules.clean(text(head["customer"] ?? nil)), phone: TextRules.clean(text(head["phone"] ?? nil)),
            contact: TextRules.clean(text(head["contact"] ?? nil)), address: TextRules.clean(text(head["address"] ?? nil)),
            lines: lines, skippedRows: skipped, fees: fees, total: total, warnings: warnings, title: title,
            letterhead: letterhead, taxCode: TextRules.clean(numberText(head["tax_code"] ?? nil)),
            email: TextRules.clean(text(head["email"] ?? nil)))
    }

    /// The title of the note and the lines above it (the first text of each row).
    static func titleOf(_ rows: Grid) -> (String, [String]) {
        for (r, row) in rows.enumerated() {
            for value in row {
                let t = TextRules.clean(text(value))
                if titleMarkers.contains(where: { TextRules.unaccent(t).contains($0) || t.contains($0) }) {
                    let above = rows[..<r].map { prev -> String in
                        cellLines(prev.first { !TextRules.clean(text($0)).isEmpty } ?? nil)
                    }
                    return (t, above.filter { !$0.isEmpty })
                }
            }
        }
        return ("", [])
    }

    /// A cell's text with its own line breaks kept.
    static func cellLines(_ value: CellValue?) -> String {
        text(value).components(separatedBy: "\n").map { TextRules.clean($0) }.filter { !$0.isEmpty }.joined(separator: "\n")
    }

    static func readHeaderFields(_ rows: Grid) -> [String: CellValue?] {
        var found: [String: CellValue?] = [:]
        for (r, row) in rows.enumerated() {
            for (c, value) in row.enumerated() {
                let t = text(value)
                let plain = TextRules.unaccent(t)
                for (key, label) in headerLabels where found.index(forKey: key) == nil && plain.contains(label) {
                    let after = valueAfterLabel(t, label)
                    found.updateValue(after.map { CellValue.text($0) } ?? neighbourValue(rows, r, c, key), forKey: key)
                }
            }
        }
        // some notes keep only the Chinese label: '客户名称 Khách Mẫu' (no 'Tên khách hàng', no colon)
        for (r, row) in rows.enumerated() {
            for (c, value) in row.enumerated() {
                let t = text(value)
                let trimmed = String(t.drop(while: { $0.isWhitespace }))
                for (key, label) in headerLabelsZh where found.index(forKey: key) == nil && trimmed.hasPrefix(label) {
                    var rest = String(trimmed.dropFirst(label.count))
                    if let range = rest.range(of: #"^\s*(\([^)]*\)|（[^）]*）)?\s*[:：]?\s*"#, options: .regularExpression) {
                        rest.removeSubrange(range)
                    }
                    let cleaned = TextRules.clean(rest)
                    found.updateValue(cleaned.isEmpty ? neighbourValue(rows, r, c, key) : .text(cleaned), forKey: key)
                }
            }
        }
        for (r, row) in rows.enumerated() {
            for (c, value) in row.enumerated() {
                let t = text(value)
                let plain = TextRules.unaccent(t)
                for (key, pattern) in extraHeadLabels where found.index(forKey: key) == nil {
                    guard let m = pattern.firstMatch(in: plain, range: NSRange(plain.startIndex..., in: plain)),
                          let end = Range(m.range, in: plain)?.upperBound else { continue }
                    // as Python: the match ends at a code point offset of the unaccented text, the colon is looked for
                    // from the same offset in the original
                    let offset = plain.unicodeScalars.distance(from: plain.unicodeScalars.startIndex, to: end)
                    let scalars = t.unicodeScalars
                    var rest = ""
                    if offset <= scalars.count {
                        var i = scalars.index(scalars.startIndex, offsetBy: offset)
                        while i < scalars.endIndex {
                            if scalars[i] == ":" || scalars[i] == "：" {
                                rest = String(String.UnicodeScalarView(scalars[scalars.index(after: i)...]))
                                break
                            }
                            i = scalars.index(after: i)
                        }
                    }
                    let cleaned = TextRules.clean(rest)
                    found.updateValue(cleaned.isEmpty ? neighbourValue(rows, r, c, key) : .text(cleaned), forKey: key)
                }
            }
        }
        return found
    }

    /// A tax code typed as a number in its own cell: 101234567.0 -> '101234567' (a lost leading zero cannot come back).
    static func numberText(_ value: CellValue?) -> String {
        if case let .double(d)? = value, d == d.rounded(.towardZero), abs(d) < 1e15 { return String(Int(d)) }
        return text(value)
    }

    /// '联系电话 ( Điện thoại liên hệ ): 0901 234 567' -> '0901 234 567'
    static func valueAfterLabel(_ t: String, _ label: String) -> String? {
        var index = t.startIndex
        while index < t.endIndex {
            if t[index] == ":" || t[index] == "：" {
                if TextRules.unaccent(String(t[..<index])).contains(label) {
                    let rest = TextRules.clean(String(t[t.index(after: index)...]))
                    return rest.isEmpty ? nil : rest
                }
            }
            index = t.index(after: index)
        }
        return nil
    }

    /// The value in the next non-empty cell to the right, or the cell below; for an optional field another field's
    /// label there means the field is empty.
    static func neighbourValue(_ rows: Grid, _ r: Int, _ c: Int, _ key: String) -> CellValue? {
        let optional = optionalFields.contains(key)
        let row = rows[r]
        if c + 1 < row.count {
            for value in row[(c + 1)...] where !isEmpty(value) {
                return optional && isLabel(value) ? nil : value
            }
        }
        if r + 1 < rows.count && c < rows[r + 1].count {
            let below = rows[r + 1][c]
            if !isEmpty(below) && !(optional && isLabel(below)) { return below }
        }
        return nil
    }

    static func isLabel(_ value: CellValue?) -> Bool {
        let t = text(value)
        let plain = TextRules.unaccent(t)
        return headerLabels.contains { plain.contains($0.1) } || headerLabelsZh.contains { t.contains($0.1) }
            || extraHeadLabels.contains { $0.1.firstMatch(in: plain, range: NSRange(plain.startIndex..., in: plain)) != nil }
    }

    static func mapColumns(_ header: [CellValue?]) throws -> [String: Int] {
        var columns: [String: Int] = [:]
        for (c, value) in header.enumerated() {
            let plain = TextRules.unaccent(text(value))
            for (key, label) in columnLabels where columns[key] == nil && plain.contains(label) {
                columns[key] = c
            }
            let compact = String(text(value).filter { !$0.isWhitespace })
            for (key, vi, zh) in extraLabels where columns[key] == nil && (plain.contains(vi) || compact.contains(zh)) {
                columns[key] = c
            }
            for (key, vi, zh) in priceLabels where columns[key] == nil && (plain.contains(vi) || compact.contains(zh)) {
                columns[key] = c
            }
        }
        if columns["qty"] == nil { throw DeliveryNoteError.invalid("Không tìm thấy cột 'Số lượng'.") }
        return columns
    }

    /// 'Kho tổng' / 'Văn phòng' / '总仓' / '办公室' -> location id
    static func placeOf(_ t: String) -> Int? {
        let plain = TextRules.unaccent(t)
        let found = Set(placeValues.filter { plain.contains($0.0) || t.contains($0.0) }.map(\.1))
        return found.count == 1 ? found.first : nil
    }

    /// The hidden 'Mã hàng' cell: 'SP008|10KG|中文名\nTên Việt' -> ('SP008', its match key); 'SP008' -> ('SP008', nil)
    static func codeOf(_ t: String) -> (String, String?) {
        guard let bar = t.firstIndex(of: "|") else { return (TextRules.clean(t).uppercased(), nil) }
        let code = String(t[..<bar])
        let rest = String(t[t.index(after: bar)...])
        let spec: String
        let name: String
        if let second = rest.firstIndex(of: "|") {
            spec = String(rest[..<second])
            name = String(rest[rest.index(after: second)...])
        } else {
            spec = rest
            name = ""
        }
        return (TextRules.clean(code).uppercased(), TextRules.matchKey(name, spec))
    }

    /// 'Kho tổng 总仓: 3; Văn phòng 办公室: 2' -> [(1, 3), (2, 2)]; anything that does not add up to qty -> []
    static func placesOf(_ t: String, _ qty: Double) -> [(Int, Double)] {
        var found: [Int: Double] = [:]
        for part in TextRules.clean(t).components(separatedBy: ";") {
            if part.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { continue }
            let name: String
            let number: String
            if let colon = part.lastIndex(of: ":") {
                name = String(part[..<colon])
                number = String(part[part.index(after: colon)...])
            } else {
                name = ""
                number = part
            }
            guard let location = placeOf(name),
                  let value = toNumber(.text(number.trimmingCharacters(in: .whitespacesAndNewlines))),
                  value > 0, found[location] == nil else { return [] }
            found[location] = value
        }
        if found.isEmpty || abs(found.values.reduce(0, +) - qty) > 1e-9 { return [] }
        return found.sorted { $0.key < $1.key }.map { ($0.key, $0.value) }
    }

    /// A quantity. Text with thousands dots ('1.500': 1500 or 1,5?) is not guessed: nil.
    static func toNumber(_ value: CellValue?) -> Double? {
        switch value {
        case .none, .some(.bool): return nil
        case let .some(.int(i)): return Double(i)
        case let .some(.double(d)): return d.isFinite ? d : nil
        default:
            let t = TextRules.clean(text(value))
            if fullMatch(#"-?\d{1,3}([.,]\d{3})+"#, t) || matches(#"\d[.,]\d{3}[.,]"#, t) { return nil }
            guard let number = pythonFloat(t.replacingOccurrences(of: ",", with: ".")) else { return nil }
            return number.isFinite ? number : nil
        }
    }

    /// 1188000, '1.188.000', '1,188,000 đ', '1188000.5' -> number; anything else -> nil.
    static func toMoney(_ value: CellValue?) -> Double? {
        switch value {
        case .none, .some(.bool): return nil
        case let .some(.int(i)): return Double(i)
        case let .some(.double(d)): return d
        default:
            var t = TextRules.clean(text(value)).replacingOccurrences(of: #"[^\d.,-]"#, with: "", options: .regularExpression)
            if fullMatch(#"-?\d{1,3}([.,]\d{3})+"#, t) {
                t = t.replacingOccurrences(of: #"[.,]"#, with: "", options: .regularExpression)
            }
            return pythonFloat(t.replacingOccurrences(of: ",", with: "."))
        }
    }

    /// Python float(text): digits with an optional sign, point and exponent; inf / nan; surrounding spaces allowed.
    static func pythonFloat(_ t: String) -> Double? {
        let s = t.trimmingCharacters(in: .whitespacesAndNewlines).replacingOccurrences(of: "_", with: "")
        guard !s.isEmpty, !s.hasPrefix("0x"), !s.hasPrefix("-0x"), !s.hasPrefix("+0x") else { return nil }
        let lower = s.lowercased()
        let words = ["inf", "+inf", "-inf", "infinity", "+infinity", "-infinity", "nan", "+nan", "-nan"]
        if words.contains(lower) {
            if lower.contains("nan") { return .nan }
            return lower.hasPrefix("-") ? -.infinity : .infinity
        }
        guard fullMatch(#"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?"#, s) else { return nil }
        return Double(s)
    }

    /// (unit price, amount) of a goods line; one worked out from the other when missing.
    static func lineMoney(_ row: [CellValue?], _ columns: [String: Int], _ qty: Double, _ excelRow: Int,
                          _ warnings: inout [String]) -> (Double?, Double?) {
        let rawPrice = cell(row, columns["price"])
        let rawAmount = cell(row, columns["amount"])
        var price = toMoney(rawPrice)
        var amount = toMoney(rawAmount)
        for (raw, value) in [(rawPrice, price), (rawAmount, amount)] where !isEmpty(raw) && value == nil {
            warnings.append("Dòng \(excelRow): không đọc được giá (\(repr(raw))).")
        }
        if amount == nil, let price { amount = price * qty }
        if price == nil, let amount { price = amount / qty }
        return (price, amount)
    }

    /// A date cell, or dd-mm-yyyy / dd/mm/yyyy / dd.mm.yyyy inside a text -> "YYYY-MM-DD"
    static func parseDate(_ value: CellValue?) -> String? {
        if case let .date(y, m, d, _, _, _)? = value { return Stats.iso(y, m, d) }
        let t = text(value)
        guard let range = t.range(of: #"(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{4})"#, options: .regularExpression)
        else { return nil }
        let numbers = t[range].split(whereSeparator: { !$0.isNumber }).compactMap { Int($0) }
        guard numbers.count == 3 else { return nil }
        let (day, month, year) = (numbers[0], numbers[1], numbers[2])
        guard year >= 1, month >= 1, month <= 12, day >= 1, day <= Stats.daysIn(year, month) else { return nil }
        return Stats.iso(year, month, day)
    }
}

/// What the reader reads in one note, as the plain lines of tools/note_lines.py (numbers with 4 decimals, nothing as
/// ∅; an error as 'ERROR <kind>: <message>'): the tests compare these with the Python reader's.
public enum NoteLines {
    static func canon(_ value: Double?) -> String { value.map { String(format: "%.4f", $0) } ?? "∅" }

    public static func lines(_ url: URL) -> [String] {
        let note: DeliveryNote
        do {
            note = try DeliveryNoteReader.read(url)
        } catch let DeliveryNoteError.notDeliveryNote(text) {
            return ["ERROR not-a-note: " + (text.hasPrefix("Không mở được file Excel") ? "Không mở được file Excel" : text)]
        } catch let DeliveryNoteError.invalid(text) {
            return ["ERROR invalid: \(text)"]
        } catch {
            return ["ERROR other: \(error)"]
        }
        var out = [
            "code=\(note.code)|date=\(note.docDate)|customer=\(note.customerName)|phone=\(note.phone)|contact=\(note.contact)"
                + "|address=\(note.address)|tax_code=\(note.taxCode)|email=\(note.email)|currency=\(note.currency)|total=\(canon(note.total))",
            "title=\(note.title)", "letterhead=" + note.letterhead.joined(separator: " / "),
        ]
        for l in note.lines {
            let places = l.places.map { "\($0.0):\(canon($0.1))" }.joined(separator: ";")
            out.append("line row=\(l.row)|raw=\(l.rawName)|vi=\(l.nameVi)|zh=\(l.nameZh)|spec=\(l.spec)|qty=\(canon(l.qty))"
                       + "|note=\(l.note)|price=\(canon(l.unitPrice))|amount=\(canon(l.amount))|code=\(l.productCode)"
                       + "|places=\(places)|key=\(l.key)")
        }
        out += note.skippedRows.map { "skipped=\($0)" }
        out += note.fees.map { "fee=\($0.0)=\(canon($0.1))" }
        out += note.warnings.map { "warning=\($0)" }
        return out
    }
}
