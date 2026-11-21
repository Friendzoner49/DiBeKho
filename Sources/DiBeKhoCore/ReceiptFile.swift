import Foundation
import GRDB

/// Goods receipt (hàng về) Excel files, as excel/receipt.py: the file of a receipt entered in the app
/// (output/hang-ve/, to keep or print) and the reader of a goods-in file dropped into input/.
/// Products are identified by their code (column A), so renaming a product does not break a file written earlier.
public enum ReceiptFile {
    public static let marker = "PHIẾU HÀNG VỀ / GOODS RECEIPT"
    static let markerPlain = ["phieu hang ve", "goods receipt"]
    static let sourceLabels = [
        "supplier": "Cửa khẩu / công ty mẹ  口岸/母公司",
        "return": "Khách hàng trả lại  客户退货",
        "other": "Nhà cung cấp khác  其他供应商",
    ]

    // MARK: writing

    public struct Head {
        public var code: String
        /// yyyy-mm-dd
        public var date: String
        public var note: String
        public var source: String
        public var supplierName: String
        public var customerName: String
        public var refCode: String
        public init(code: String, date: String, note: String, source: String, supplierName: String, customerName: String,
                    refCode: String) {
            self.code = code; self.date = date; self.note = note; self.source = source
            self.supplierName = supplierName; self.customerName = customerName; self.refCode = refCode
        }
    }

    public struct OutLine {
        public var code: String
        public var nameVi: String
        public var nameZh: String
        public var spec: String
        public var unit: String
        public var qty: Double
        public var variant: String
        public var note: String
        public init(code: String, nameVi: String, nameZh: String, spec: String, unit: String, qty: Double, variant: String,
                    note: String) {
            self.code = code; self.nameVi = nameVi; self.nameZh = nameZh; self.spec = spec; self.unit = unit
            self.qty = qty; self.variant = variant; self.note = note
        }
    }

    static let line = "999999"

    /// The sheet of a receipt entered in the app. It reads like a sheet a person made: Vietnamese and Chinese labels
    /// like the company's own notes, no mention of the app. Label rows, then a table whose column A is the code and F
    /// the quantity, so `read` still recognises it.
    public static func sheet(_ head: Head, _ lines: [OutLine]) -> XSheet {
        var sh = XSheet(name: "Hàng về")
        func text(_ s: String) -> XValue { s.isEmpty ? .empty : .text(s) }
        var bold = XStyle()
        bold.bold = true
        var big = bold
        big.fontSize = 14
        sh.put(1, 1, .text("PHIẾU HÀNG VỀ  到货单"), big)
        let named = head.source == "supplier" || head.source == "other"
        let who = named ? head.supplierName : head.customerName
        var rows: [(String, XValue)] = [
            ("Ngày về  到货日期:", dateValue(head.date)),
            ("Ghi chú  备注:", text(head.note)),
            ("Số phiếu  单号:", text(head.code)),
            ("Nguồn hàng  来源:", text(sourceLabels[head.source] ?? "")),
            (named ? "Nhà cung cấp  供应商:" : "Khách hàng  客户:", text(who)),
        ]
        if head.source == "return" && !head.refCode.isEmpty { rows.append(("Đơn gốc  原订单:", text(head.refCode))) }
        for (i, row) in rows.enumerated() {
            let r = 3 + i
            sh.put(r, 1, .text(row.0), bold)
            var style = XStyle()
            if i == 0 {
                style.numberFormat = "dd/mm/yyyy"  // lower case: Quick Look and Numbers read a capital D as the day of the year
                style.horizontal = "left"
            }
            sh.put(r, 2, row.1, style)
        }
        let headerRow = 3 + rows.count + 1
        let headers = ["Mã hàng\n编码", "Tên hàng\n品名", "Tên tiếng Trung\n中文名", "Quy cách\n规格", "Đơn vị\n单位",
                       "Số lượng\n数量", "Loại, màu\n类型、颜色", "Ghi chú\n备注"]
        var box = XStyle()
        box.box = true
        box.borderColor = line
        var headerStyle = box
        headerStyle.bold = true
        headerStyle.horizontal = "center"
        headerStyle.vertical = "center"
        headerStyle.wrap = true
        for (i, h) in headers.enumerated() { sh.put(headerRow, i + 1, .text(h), headerStyle) }
        sh.rowHeights[headerRow] = 32
        var total = 0.0
        var r = headerRow
        for (i, ln) in lines.enumerated() {
            r = headerRow + 1 + i
            let values: [XValue] = [text(ln.code), text(ln.nameVi), text(ln.nameZh), text(ln.spec), text(ln.unit),
                                    .number(ln.qty), text(ln.variant), text(ln.note)]
            for (c, v) in values.enumerated() { sh.put(r, c + 1, v, box) }
            total += ln.qty
        }
        sh.put(r + 1, 5, .text("Tổng cộng  合计"), bold)
        sh.put(r + 1, 6, .number(total), bold)
        sh.columnWidths = [11, 45, 22, 16, 10, 12, 20, 24]
        return sh
    }

    static func dateValue(_ iso: String) -> XValue {
        let p = iso.split(separator: "-").compactMap { Int($0) }
        return p.count == 3 ? .date(year: p[0], month: p[1], day: p[2]) : .empty
    }

    @discardableResult
    public static func write(_ url: URL, _ head: Head, _ lines: [OutLine]) throws -> URL {
        try XlsxWriter.write(sheet(head, lines), to: url)
        return url
    }

    // MARK: reading

    public struct Line: Equatable {
        public let row: Int
        public let code: String
        public let qty: Double
    }

    public struct Parsed: Equatable {
        /// yyyy-mm-dd
        public let date: String
        public let note: String
        public let lines: [Line]
        public let warnings: [String]
    }

    public enum Failure: Error, LocalizedError, Equatable {
        /// not a goods receipt at all
        case notReceipt
        /// a goods receipt that cannot be used
        case invalid(String)
        public var errorDescription: String? {
            switch self {
            case .notReceipt: return "Không phải file hàng về (thiếu tiêu đề 'PHIẾU HÀNG VỀ')."
            case let .invalid(message): return message
            }
        }
    }

    static func firstSheet(_ url: URL) -> Worksheet? { (try? Xlsx.read(url))?.first }

    public static func isReceipt(_ url: URL) -> Bool {
        guard let sheet = firstSheet(url) else { return false }
        for row in sheet.rows.prefix(3) {
            for v in row {
                if let v {
                    let plain = TextRules.unaccent(v.pythonText)
                    if markerPlain.contains(where: { plain.contains($0) }) { return true }
                }
            }
        }
        return false
    }

    public static func read(_ url: URL) throws -> Parsed {
        guard isReceipt(url), let sheet = firstSheet(url) else { throw Failure.notReceipt }
        let rows = sheet.rows
        var date: String?
        var note = ""
        var header: Int?
        for (i, row) in rows.enumerated() {
            let first = row.first.flatMap { $0 }.map { TextRules.unaccent($0.pythonText) } ?? ""
            let second: CellValue? = row.count > 1 ? row[1] : nil
            if first.hasPrefix("ngay ve") {
                date = parseDate(second)
            } else if first.hasPrefix("ghi chu") {
                note = TextRules.clean(second?.pythonText ?? "")
            } else if first.hasPrefix("ma") {
                header = i
                break
            }
        }
        guard let day = date else { throw Failure.invalid("Thiếu hoặc sai 'Ngày về' (ô B3, dạng ngày/tháng/năm).") }
        guard let header else { throw Failure.invalid("Không thấy dòng tiêu đề bảng (cột 'Mã / Code').") }
        var lines: [Line] = []
        var warnings: [String] = []
        for i in (header + 1)..<max(header + 1, rows.count) {
            var row = rows[i]
            while row.count < 6 { row.append(nil) }
            let code = TextRules.clean(row[0]?.pythonText ?? "")
            guard let qty = row[5], !code.isEmpty else { continue }
            if case let .text(s) = qty, s.isEmpty { continue }
            guard let value = parseNumber(qty.pythonText) else {
                warnings.append("Dòng \(i + 1): số lượng '\(qty.pythonText)' không phải số, bỏ qua.")
                continue
            }
            if value < 0 {
                warnings.append("Dòng \(i + 1): số lượng âm, bỏ qua.")
                continue
            }
            if value > 0 { lines.append(Line(row: i + 1, code: code, qty: value)) }
        }
        if lines.isEmpty { throw Failure.invalid("Chưa điền số lượng cho mặt hàng nào.") }
        return Parsed(date: day, note: note, lines: lines, warnings: warnings)
    }

    static func parseDate(_ value: CellValue?) -> String? {
        guard let value else { return nil }
        if case let .date(y, m, d, _, _, _) = value { return String(format: "%04d-%02d-%02d", y, m, d) }
        let text = value.pythonText
        guard let m = text.range(of: #"(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{4})"#, options: .regularExpression) else { return nil }
        let nums = text[m].split(whereSeparator: { !$0.isNumber }).compactMap { Int($0) }
        guard nums.count == 3 else { return nil }
        let (d, mo, y) = (nums[0], nums[1], nums[2])
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        guard y >= 1, let made = calendar.date(from: DateComponents(year: y, month: mo, day: d)) else { return nil }
        let back = calendar.dateComponents([.year, .month, .day], from: made)
        guard back.year == y, back.month == mo, back.day == d else { return nil }
        return String(format: "%04d-%02d-%02d", y, mo, d)
    }
}

extension Receipts {
    /// What the receipt's file needs, from the database.
    static func outFile(_ db: Database, docId: Int64) throws -> (ReceiptFile.Head, [ReceiptFile.OutLine])? {
        guard let d = try Row.fetchOne(db, sql: """
            SELECT d.*, s.name AS supplier_name, c.name AS customer_name FROM documents d
            LEFT JOIN suppliers s ON s.id = d.supplier_id LEFT JOIN customers c ON c.id = d.customer_id WHERE d.id = ?
            """, arguments: [docId]) else { return nil }
        let head = ReceiptFile.Head(code: d["code"] ?? "", date: d["doc_date"] ?? "", note: d["note"] ?? "",
                                    source: d["receipt_source"] ?? "", supplierName: d["supplier_name"] ?? "",
                                    customerName: d["customer_name"] ?? "", refCode: d["ref_code"] ?? "")
        let lines = try Row.fetchAll(db, sql: """
            SELECT l.qty, l.note, p.code, p.name_vi, p.name_zh, p.spec, p.unit, p.variant FROM document_lines l
            JOIN products p ON p.id = l.product_id WHERE l.document_id = ? ORDER BY l.line_no
            """, arguments: [docId]).map { r in
            ReceiptFile.OutLine(code: r["code"] ?? "", nameVi: r["name_vi"] ?? "", nameZh: r["name_zh"] ?? "",
                                spec: r["spec"] ?? "", unit: r["unit"] ?? "", qty: r["qty"] ?? 0,
                                variant: r["variant"] ?? "", note: r["note"] ?? "")
        }
        return (head, lines)
    }

    /// Write the receipt to output/hang-ve/ and remember the file on the document (Python receipts.export_file).
    public static func exportFile(_ db: Database, _ f: ShopFolders, docId: Int64) throws -> URL {
        guard let (head, lines) = try outFile(db, docId: docId) else { throw WriteError("Không thấy phiếu hàng về.") }
        let base = "HangVe_\(head.code)_\(head.date)"
        var url = f.output.appendingPathComponent(folder).appendingPathComponent("\(base).xlsx")
        var n = 2
        while FileManager.default.fileExists(atPath: url.path) {
            url = f.output.appendingPathComponent(folder).appendingPathComponent("\(base)_\(n).xlsx")
            n += 1
        }
        try ReceiptFile.write(url, head, lines)
        try db.execute(sql: "UPDATE documents SET source_file = ?, source_hash = ? WHERE id = ?",
                       arguments: [url.lastPathComponent, try Deliveries.fileHash(url), docId])
        return url
    }

    /// Write the receipt's Excel file under the given name without touching the database (a receipt entered on the web:
    /// every machine that pulls it writes the same file and the shared row stays as it is). Python receipts.write_file.
    @discardableResult
    public static func writeFile(_ db: Database, _ f: ShopFolders, docId: Int64, name: String) throws -> URL {
        guard Deliveries.validRel(name), let (head, lines) = try outFile(db, docId: docId) else {
            throw WriteError("Không thấy phiếu hàng về.")
        }
        let url = f.output.appendingPathComponent(folder).appendingPathComponent(name)
        return try ReceiptFile.write(url, head, lines)
    }

    /// The file of a receipt saved earlier, when it is still in output/hang-ve/.
    public static func exportedFile(_ f: ShopFolders, name: String) -> URL? {
        guard Deliveries.validRel(name) else { return nil }
        let url = f.output.appendingPathComponent(folder).appendingPathComponent(name)
        return FileManager.default.fileExists(atPath: url.path) ? url : nil
    }
}
