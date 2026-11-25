import Foundation

/// The stock issue note (Phiếu xuất kho 出库单) as a sheet, cell for cell as excel/issue_note.py makes it (and the
/// web page, webapp/xlsx.js): the grid of the shop's own delivery notes with the title 'PHIẾU XUẤT KHO'. The company
/// lines come from the shop's latest delivery note (Deliveries.letterhead). Two hidden columns keep the product code
/// and where each line is taken from, so the file is read back exactly. Only plain values, never formulas.
public enum IssueNote {
    public static let title = "出库单 PHIẾU XUẤT KHO"
    /// a draft order (customer's request 21/11/2026): the same file, nothing recorded; the scan refuses this mark
    public static let draftMark = "(NHÁP)"
    public static let titleDraft = "出库单（草稿） PHIẾU XUẤT KHO " + draftMark

    /// issue_note.is_draft_title
    public static func isDraftTitle(_ title: String) -> Bool {
        title.uppercased().replacingOccurrences(of: " )", with: ")").replacingOccurrences(of: "( ", with: "(").contains(draftMark)
    }
    static let labels: [String: String] = [
        "customer": "客户名称 ( Tên khách hàng ): ",
        "phone": "联系电话 ( Điện thoại liên hệ ): ",
        "code": "订货单号 ( Mã đơn hàng )：",
        "tax_code": "MST 税号： ",
        "email": "email邮箱：",
        "contact": "联系人( Người liên hệ )：",
        "date": "送货日期 ( Ngày giao hàng )：",
        "address": "地址( Địa chỉ):  ",
    ]
    static let headers = ["编 号\nSTT", "商 品 全 名\nTên hàng", "规格\nQUY CÁCH ", "数 量\nSố lượng", "单 价\nVND", "金 额\nVND",
                          "备 注\nGhi chú", "货号\nMã hàng", "取货地点\nLấy từ kho"]
    /// a yuan note (the ₫ | ¥ switch on ¥, user 21/11/2026): the signs the reader takes for yuan (issue_note.HEADERS_CNY)
    static let headersCny = Array(headers[0..<4]) + ["单 价\nCNY", "金 额\nCNY"] + Array(headers[6...])
    // 2 was written "Văn phòng 办公室" before 25/11/2026 (one office); the reader still takes that as Hà Nội
    static let places: [Int64: String] = [1: "Kho tổng 总仓", 2: "Văn phòng Hà Nội 河内办公室", 3: "Văn phòng Bắc Ninh 北宁办公室"]
    static let wordsLabel = "总计大写\n (Tổng cộng viết bằng chữ)"
    static let qtyLabel = "页小计 \n( Tổng số lượng ):\n"
    static let signFrom = "送货单位及经手人（盖章）：Người giao hàng"
    static let signTo = "收货单位及经手人（盖章）：Người nhận hàng"
    public static let sheetName = "出库单"
    /// SimSun: the customer, the code, e-mail and date labels, the two total labels (the template's own)
    static let song = "宋体"
    static let headerRow = 9  // 8 before 18/11/2026 (no MST / email row); the reader finds the header by its label either way
    static let widths: [Double] = [17.0, 62.6640625, 38.33203125, 13.0, 34.6640625, 25.0, 25.83203125, 12.0, 24.0]
    static let hidden: Set<Int> = [8, 9]
    static let heights: [Int: Double] = [1: 61.0, 2: 41.0, 3: 9.0, 4: 40.0, 5: 54.0, 6: 54.0, 7: 44.25, 8: 32.0, 9: 54.0]
    static let lineHeight = 152.0, totalHeight = 83.0, signHeight = 43.75  // the template of 18/11/2026
    /// no thousands separator in any Excel file (user, 21/11/2026: 6182.98, not 6.182,98), as issue_note.MONEY
    static let money = "[$VND]\\ 0"
    static let moneyCny = "[$¥]\\ 0.00"
    static let times = "Times New Roman"

    public struct Row {
        public var code: String
        public var nameVi: String
        public var nameZh: String
        public var spec: String
        public var qty: Double
        /// [(location id, qty)], adding up to qty
        public var places: [(Int64, Double)]
        public var unitPrice: Double?
        public var amount: Double?
        public var note: String
        public init(code: String, nameVi: String, nameZh: String, spec: String, qty: Double, places: [(Int64, Double)],
                    unitPrice: Double?, amount: Double?, note: String) {
            self.code = code; self.nameVi = nameVi; self.nameZh = nameZh; self.spec = spec; self.qty = qty
            self.places = places; self.unitPrice = unitPrice; self.amount = amount; self.note = note
        }
    }

    public struct Head {
        public var code: String
        public var date: String  // yyyy-mm-dd
        public var customer: String
        public var phone = ""
        public var contact = ""
        public var address = ""
        public var taxCode = ""
        public var email = ""
        /// company name, address (from the shop's delivery notes)
        public var letterhead: [String] = []
        /// "CNY": the prices are yuan
        public var currency = "VND"
        /// a draft order: the title says NHÁP
        public var draft = false
        public init(code: String, date: String, customer: String, phone: String = "", contact: String = "",
                    address: String = "", taxCode: String = "", email: String = "", letterhead: [String] = [],
                    currency: String = "VND", draft: Bool = false) {
            self.code = code; self.date = date; self.customer = customer; self.phone = phone
            self.contact = contact; self.address = address; self.taxCode = taxCode; self.email = email
            self.letterhead = letterhead; self.currency = currency; self.draft = draft
        }
    }

    /// '中文名\nTên Việt', like the customer's notes.
    public static func productName(_ nameVi: String, _ nameZh: String) -> String {
        !nameZh.isEmpty && !nameVi.isEmpty ? "\(nameZh)\n\(nameVi)" : (nameVi.isEmpty ? nameZh : nameVi)
    }

    /// 3 -> '3', 2.5 -> '2.5'
    public static func numberText(_ value: Double) -> String {
        value == value.rounded() && abs(value) < 1e15 ? String(Int(value)) : Xlsx.pythonFloat(value)
    }

    public static func placesText(_ places: [(Int64, Double)]) -> String {
        places.filter { $0.1 != 0 }.map { "\(Self.places[$0.0] ?? ""): \(numberText($0.1))" }.joined(separator: "; ")
    }

    static let digits = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
    static let units = ["", "nghìn", "triệu", "tỷ", "nghìn tỷ", "triệu tỷ"]

    static func three(_ n: Int, full: Bool) -> [String] {
        let hundreds = n / 100, tens = n / 10 % 10, ones = n % 10
        var words: [String] = []
        if full || hundreds > 0 { words += [digits[hundreds], "trăm"] }
        if tens == 0 {
            if ones > 0 && (full || hundreds > 0) { words.append("linh") }
        } else if tens == 1 {
            words.append("mười")
        } else {
            words += [digits[tens], "mươi"]
        }
        if ones > 0 {
            words.append(ones == 1 && tens >= 2 ? "mốt" : ones == 5 && tens >= 1 ? "lăm" : digits[ones])
        }
        return words
    }

    /// 2376000 -> 'HAI TRIỆU BA TRĂM BẢY MƯƠI SÁU NGHÌN' (issue_note._number_words, n >= 0).
    static func numberWords(_ number: Int) -> String {
        var n = number
        if n == 0 { return "KHÔNG" }
        var groups: [Int] = []
        repeat {
            groups.append(n % 1000)
            n /= 1000
        } while n > 0
        var words: [String] = []
        for i in stride(from: groups.count - 1, through: 0, by: -1) {
            if groups[i] == 0 && (!words.isEmpty || i > 0) { continue }
            words += three(groups[i], full: !words.isEmpty)
            if !units[i].isEmpty { words.append(units[i]) }
        }
        return words.joined(separator: " ").uppercased()
    }

    /// 2376000 -> 'HAI TRIỆU BA TRĂM BẢY MƯƠI SÁU NGHÌN VIỆT NAM ĐỒNG', as the shop writes it.
    public static func vndWords(_ amount: Double) -> String {
        let n = Int((amount + 0.5).rounded(.down))
        return n < 0 ? "" : numberWords(n) + " VIỆT NAM ĐỒNG"
    }

    /// 1250.5 -> 'MỘT NGHÌN HAI TRĂM NĂM MƯƠI NHÂN DÂN TỆ NĂM MƯƠI XU' (issue_note.cny_words; 1 ¥ = 100 xu).
    public static func cnyWords(_ amount: Double) -> String {
        let cents = Int((amount * 100 + 0.5).rounded(.down))
        if cents < 0 { return "" }
        let whole = cents / 100, fen = cents % 100
        return numberWords(whole) + " NHÂN DÂN TỆ" + (fen > 0 ? " \(numberWords(fen)) XU" : "")
    }

    /// About how many lines a wrapped cell takes (Excel does not grow a row a program wrote).
    static func wrappedLines(_ text: String, width: Double, size: Double) -> Int {
        let perLine = max(1.0, width * 11 / size * 0.72)
        var total = 0
        for part in text.components(separatedBy: "\n") {
            let units = part.unicodeScalars.reduce(0) { $0 + ($1.value > 0x2E7F ? 2 : 1) }
            total += max(1, Int((Double(units) / perLine).rounded(.up)))
        }
        return total
    }

    static func style(size: Double = 15, border: Bool = false, align: String = "center", wrap: Bool = true,
                      money isMoney: Bool = false, font: String = times, underline: Bool = false,
                      moneyFormat: String = money) -> XStyle {
        var s = XStyle()
        s.fontName = font
        s.fontSize = size
        s.bold = true
        s.horizontal = align
        s.vertical = "center"
        s.wrap = wrap
        s.shrink = isMoney
        s.box = border
        if underline { s.borderBottom = true }
        if isMoney { s.numberFormat = moneyFormat }
        return s
    }

    /// The note as a sheet. webapp/xlsx.js issueSheet builds the same cells.
    public static func sheet(_ head: Head, _ rows: [Row]) -> XSheet {
        var sh = XSheet(name: sheetName)
        let cny = head.currency == "CNY"
        let format = cny ? moneyCny : money
        func put(_ r: Int, _ c: Int, _ value: String?, _ s: XStyle) {
            sh.put(r, c, value.map { .text($0) } ?? .empty, s)
        }
        func putNumber(_ r: Int, _ c: Int, _ value: Double?, _ s: XStyle) {
            sh.put(r, c, value.map { .number($0) } ?? .empty, s)
        }
        sh.rowHeights = heights
        let letter = Array((head.letterhead + ["", ""]).prefix(2))
        put(1, 1, letter[0].isEmpty ? nil : letter[0], style(size: 20))
        put(2, 1, letter[1].isEmpty ? nil : letter[1], style(size: 20))
        put(4, 1, head.draft ? titleDraft : title, style(size: 24))
        // the customer block cell for cell as the template of 18/11/2026: fonts, wrapping, merges (row 6 is not merged)
        put(5, 1, labels["customer"]! + " " + head.customer, style(size: 20, align: "left", font: song))
        put(5, 3, labels["phone"]! + head.phone, style(size: 14, align: "left", wrap: false))
        put(5, 6, labels["code"]! + head.code, style(size: 14, align: "left", font: song))
        put(6, 3, labels["tax_code"]! + head.taxCode, style(size: 14, align: "left", wrap: false))
        put(6, 6, labels["email"]! + head.email, style(size: 14, align: "left", font: song))
        put(7, 3, labels["contact"]! + head.contact, style(size: 14, align: "left", wrap: false))
        put(7, 6, labels["date"]! + dmy(head.date), style(size: 14, align: "left", wrap: false, font: song))
        put(8, 1, labels["address"]! + head.address, style(size: 14, align: "left", underline: true))
        for c in 2...7 { put(8, c, nil, style(size: 14, align: "left", underline: true)) }
        sh.merges += ["A1:G1", "A2:G2", "A3:G3", "A4:G4", "A5:B7", "C5:E5", "F5:G5", "C7:E7", "F7:G7", "A8:E8"]
        for (i, text) in (cny ? headersCny : headers).enumerated() { put(headerRow, i + 1, text, style(border: i + 1 <= 7)) }
        var r = headerRow
        var qtyTotal = 0.0, moneyTotal = 0.0, priced = false
        for (i, ln) in rows.enumerated() {
            r = headerRow + i + 1
            let name = productName(ln.nameVi, ln.nameZh)
            putNumber(r, 1, Double(i + 1), style(border: true))
            put(r, 2, name, style(border: true))
            put(r, 3, ln.spec.isEmpty ? nil : ln.spec, style(size: 18, border: true))
            putNumber(r, 4, ln.qty, style(size: 18, border: true))
            putNumber(r, 5, ln.unitPrice, style(size: 18, border: true, wrap: false, money: true, moneyFormat: format))
            putNumber(r, 6, ln.amount, style(size: 18, border: true, wrap: false, money: true, moneyFormat: format))
            put(r, 7, ln.note.isEmpty ? nil : ln.note, style(border: true))
            put(r, 8, "\(ln.code)|\(ln.spec)|\(name)", style(size: 11, wrap: false))  // trusted while the row is unchanged
            let where_ = placesText(ln.places)
            put(r, 9, where_.isEmpty ? nil : where_, style(size: 11, wrap: false))
            let lines = max(wrappedLines(name, width: widths[1], size: 15), wrappedLines(ln.note, width: widths[6], size: 15),
                            wrappedLines(ln.spec, width: widths[2], size: 18))
            sh.rowHeights[r] = max(lineHeight, 20.0 * Double(lines) + 8)
            qtyTotal += ln.qty
            if let amount = ln.amount {
                moneyTotal += amount
                priced = true
            }
        }
        r += 1
        put(r, 1, wordsLabel, style(border: true, font: song))
        put(r, 2, priced ? (cny ? cnyWords(moneyTotal) : vndWords(moneyTotal)) : nil, style(border: true))
        put(r, 3, nil, style(border: true))
        put(r, 4, qtyLabel + numberText(qtyTotal), style(border: true, font: song))
        put(r, 5, nil, style(border: true))
        putNumber(r, 6, priced ? moneyTotal : nil, style(size: 18, border: true, wrap: false, money: true, moneyFormat: format))
        put(r, 7, nil, style(border: true))
        sh.merges.append("B\(r):C\(r)")
        sh.rowHeights[r] = totalHeight
        r += 1
        put(r, 1, signFrom, style(size: 14, align: "left", wrap: false))
        put(r, 4, signTo, style(size: 14, align: "left", wrap: false))
        sh.merges.append("A\(r):C\(r)")
        sh.rowHeights[r] = signHeight
        sh.columnWidths = widths
        sh.hiddenColumns = hidden
        sh.landscapeScale = 67
        sh.sideMargin = 0.0
        sh.topMargin = 0.393700787401575
        sh.bottomMargin = 0.0
        sh.centerHorizontally = true
        sh.printArea = "A1:G\(r)"
        return sh
    }

    /// 2026-11-17 -> 17-11-2026
    static func dmy(_ iso: String) -> String {
        let p = iso.split(separator: "-")
        return p.count == 3 ? "\(p[2])-\(p[1])-\(p[0])" : iso
    }

    @discardableResult
    public static func write(_ url: URL, _ head: Head, _ rows: [Row]) throws -> URL {
        try XlsxWriter.write(sheet(head, rows), to: url)
        return url
    }
}
