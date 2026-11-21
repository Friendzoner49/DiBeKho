import Foundation
import GRDB

/// Python excel/report.py: the Statistics workbook (sheets summary, details, customers, top). Money columns are the selling
/// prices read from the delivery notes. The files never follow the ₫ | ¥ switch of the screen. Whole catalog only (the
/// product / group / customer filters and the per-period split of the Python screen are not in the Swift page yet).
public enum Report {
    public static let sheetKeys = ["summary", "details", "customers", "top"]
    /// no thousands separator in any Excel file (user, 21/11/2026: 6182.98, not 6.182,98), as report.MONEY
    static let money = "0"
    static let moneyCny = "\"¥\"0.00"
    static let dateFormat = "DD/MM/YYYY"

    public struct ReportError: Error, LocalizedError {
        public let message: String
        public var errorDescription: String? { message }
    }

    // ---- the text of the money lines (Python _dong / _both): no thousands separator, a dot before decimals

    static func dong(_ value: Double?) -> String {
        let rounded = (value ?? 0).rounded(.toNearestOrEven)
        return String(format: "%.0f", rounded == 0 ? 0 : rounded)
    }

    /// 1234.5 -> "1234.5", 100 -> "100" (Python f"{x:.2f}".rstrip("0").rstrip("."))
    static func plain(_ value: Double) -> String {
        var text = String(format: "%.2f", value)
        if text.hasPrefix("-0.00") { text = "0.00" }
        while text.hasSuffix("0") { text.removeLast() }
        if text.hasSuffix(".") { text.removeLast() }
        return text
    }

    static func both(_ vnd: Double?, _ cny: Double?, _ approx: Double? = nil) -> String {
        guard let cny, cny != 0 else { return dong(vnd) }
        let yuan = "¥" + plain((cny * 100).rounded(.toNearestOrEven) / 100)
        let about = (approx ?? 0) != 0 ? " (≈ \(dong((vnd ?? 0) + (approx ?? 0))) ₫)" : ""
        return ((vnd ?? 0) != 0 ? "\(dong(vnd)) ₫ + \(yuan)" : yuan) + about
    }

    static func back(_ returned: Double?, _ returnedCny: Double?) -> String {
        (returned ?? 0) != 0 || (returnedCny ?? 0) != 0
            ? t("money.returned", ["returned": both(returned, returnedCny)]) : ""
    }

    static func moneyLine(_ m: Stats.Money) -> String {
        let total = both(m.total, m.totalCny, m.approx)
        guard let fees = m.fees else {
            return t("stats.money_goods", ["goods": total, "orders": String(m.orders)]) + back(m.returned, m.returnedCny)
        }
        _ = fees
        return t("stats.money", ["total": total, "goods": both(m.goods, m.goodsCny), "fees": both(m.fees, m.feesCny),
                                 "orders": String(m.orders)]) + back(m.returned, m.returnedCny)
    }

    // ---- the workbook

    /// Writes the chosen sheets (in the fixed order) to `url`.
    @discardableResult
    public static func export(_ db: Database, to url: URL, start: String, end: String, filters: Stats.Filters = Stats.Filters(),
                              by: String = "none", sheets: Set<String>, periodLabel: String, scopeLabel: String,
                              now: Date = Date()) throws -> URL {
        let at = DateFormatter()
        at.locale = Locale(identifier: "en_US_POSIX")
        at.dateFormat = "dd/MM/yyyy HH:mm"
        let info = [
            t("report.period", ["period": periodLabel]),
            t("report.scope", ["scope": scopeLabel]),
            moneyLine(try Stats.money(db, start: start, end: end, filters: filters)),
            t("report.exported_at", ["at": at.string(from: now)]),
        ]
        var made: [XSheet] = []
        if sheets.contains("summary") { made.append(try summary(db, start, end, filters, by, info)) }
        if sheets.contains("details") { made.append(try details(db, start, end, filters, info)) }
        if sheets.contains("customers") { made.append(try customers(db, start, end, filters, info)) }
        if sheets.contains("top") { made.append(try top(db, start, end, filters, info)) }
        if made.isEmpty { throw ReportError(message: "no sheet selected") }
        try XlsxWriter.write(made, to: url)
        return url
    }

    /// Python export_customer: what one customer bought, in the period chosen in the customer window (nil = all time).
    /// Sheet 1: every order with its lines, goods total and separate fees; sheet 2: the products with quantity, revenue
    /// and price range. ⚠ not golden-tested (Swift-only checks).
    @discardableResult
    public static func exportCustomer(_ db: Database, to url: URL, customerId: Int64, start: String? = nil, end: String? = nil,
                                      periodLabel: String? = nil, now: Date = Date()) throws -> URL {
        guard let c = try Row.fetchOne(db, sql: "SELECT * FROM customers WHERE id = ?", arguments: [customerId]) else {
            throw ReportError(message: "customer not found")
        }
        let money = try Lookup.customerMoney(db, customerId: customerId, start: start, end: end)
        let per = Lookup.period(start, end)
        let at = DateFormatter()
        at.locale = Locale(identifier: "en_US_POSIX")
        at.dateFormat = "dd/MM/yyyy HH:mm"
        let phone = str(c, "phone") ?? ""
        let info = [
            t("report.customer", ["name": str(c, "name") ?? "", "phone": phone.isEmpty ? "—" : phone]),
            t("report.period", ["period": periodLabel ?? t("filter.all_time")]),
            t("cust.money_value", ["total": both(money.total, money.totalCny, money.approx), "orders": String(money.orders),
                                   "goods": both(money.goods, money.goodsCny), "fees": both(money.fees, money.feesCny)])
                + back(money.returned, money.returnedCny),
            t("report.exported_at", ["at": at.string(from: now)]),
        ]

        // sheet 1: orders, oldest first
        let headers = [t("col.date"), t("col.doc_code"), t("col.code"), t("col.product"), t("col.name_zh"), t("col.spec"),
                       t("col.variant"), t("col.qty"), t("col.unit"), t("col.unit_price"), t("col.amount"), t("col.note")]
        var (ws, r) = sheet(t("sheet.customer_orders"), info, headers)
        var lines: [Int64: [Row]] = [:]
        for ln in try Row.fetchAll(db, sql: """
            SELECT d.id AS document_id, l.qty, l.unit_price, l.amount, l.note, p.code AS product_code, p.name_vi, p.name_zh,
                   p.spec, p.variant, p.unit
            FROM document_lines l JOIN documents d ON d.id = l.document_id JOIN products p ON p.id = l.product_id
            WHERE d.customer_id = ? AND d.kind = 'delivery' AND d.status = 'active'\(per.sql)
            ORDER BY l.line_no
            """, arguments: StatementArguments([customerId] + per.args)) {
            lines[ln["document_id"], default: []].append(ln)
        }
        for d in try OrderQueries.deliveries(db).filter({
            $0.customerId == customerId && (start == nil || $0.date >= start!) && (end == nil || $0.date <= end!)
        }).reversed() {
            let cny: Set<Int> = d.isYuan ? [10, 11] : []
            for ln in lines[d.id] ?? [] {
                write(&ws, r, [.day(d.date), .text(d.code), .text(str(ln, "product_code")), .text(str(ln, "name_vi")),
                               .text(str(ln, "name_zh")), .text(str(ln, "spec")), .text(str(ln, "variant")),
                               .number(num(ln, "qty")), .text(str(ln, "unit")), .number(num(ln, "unit_price")),
                               .number(num(ln, "amount")), .text(str(ln, "note"))],
                      moneyCols: [10, 11], dateCols: [1], cnyCols: cny)
                r += 1
            }
            write(&ws, r, [.day(d.date), .text(d.code), .none, .text(t("report.order_total")), .none, .none, .none,
                           .number(d.totalQty), .none, .none, .number(d.goods)], moneyCols: [11], dateCols: [1], cnyCols: cny)
            for col in 1...headers.count { restyle(&ws, r, col, bold: true, fill: "F2F2F2") }
            r += 1
            if let fee = d.fees, fee != 0 {  // apart, not in the revenue
                write(&ws, r, [.day(d.date), .text(d.code), .none, .text(t("cust.fees")), .none, .none, .none, .none, .none,
                               .none, .number(fee)], moneyCols: [11], dateCols: [1], cnyCols: cny)
                for col in 1...headers.count { restyle(&ws, r, col, italic: true, color: "777777") }
                r += 1
            }
        }
        widths(&ws, [11, 9, 9, 40, 20, 16, 14, 8, 8, 13, 15, 30])

        // sheet 2: products
        let prods = try Lookup.customerProducts(db, customerId: customerId, start: start, end: end)
        let yuan = prods.contains { num($0, "min_price_cny") != nil }
        var headers2 = [t("col.code"), t("col.product"), t("col.name_zh"), t("col.spec"), t("col.variant"), t("col.total_qty"),
                        t("col.unit"), t("col.revenue"), t("report.price_low"), t("report.price_high"), t("col.times"),
                        t("col.last_date")]
        if yuan { headers2 += [t("col.revenue_cny"), t("report.price_low") + " (¥)", t("report.price_high") + " (¥)"] }
        var (ws2, r2) = sheet(t("sheet.customer_products"), info, headers2)
        for p in prods {
            var values: [Cell] = [.text(str(p, "code")), .text(str(p, "name_vi")), .text(str(p, "name_zh")), .text(str(p, "spec")),
                                  .text(str(p, "variant")), .number(num(p, "total_qty")), .text(str(p, "unit")),
                                  .number(num(p, "revenue")), .number(num(p, "min_price")), .number(num(p, "max_price")),
                                  .number(num(p, "times")), .day(str(p, "last_date") ?? "")]
            if yuan { values += [.number(num(p, "revenue_cny")), .number(num(p, "min_price_cny")), .number(num(p, "max_price_cny"))] }
            write(&ws2, r2, values, moneyCols: [8, 9, 10], dateCols: [12], cnyCols: [13, 14, 15])
            r2 += 1
        }
        widths(&ws2, [9, 40, 20, 16, 14, 10, 8, 15, 13, 13, 9, 12, 14, 13, 13])

        try XlsxWriter.write([ws, ws2], to: url)
        return url
    }

    // ---- sheet scaffolding (Python _sheet, _widths, _write)

    private static func sheet(_ title: String, _ info: [String], _ headers: [String]) -> (XSheet, Int) {
        var ws = XSheet(name: String(title.prefix(31)))
        var note = XStyle()
        note.italic = true
        note.fontColor = "555555"
        for (i, line) in info.enumerated() { ws.put(i + 1, 1, .text(line), note) }
        let headerRow = info.count + 2
        var head = XStyle()
        head.bold = true
        head.fill = "DDEBF7"
        head.wrap = true
        head.vertical = "center"
        head.horizontal = "center"
        for (i, h) in headers.enumerated() { ws.put(headerRow, i + 1, .text(h), head) }
        ws.freeze = (headerRow + 1, 3)
        return (ws, headerRow + 1)
    }

    /// Font and fill of an existing cell change, its number format stays (openpyxl: cell.font = ..., cell.fill = ...).
    private static func restyle(_ ws: inout XSheet, _ r: Int, _ col: Int, bold: Bool = false, italic: Bool = false,
                                color: String? = nil, fill: String? = nil) {
        var cell = ws.cells[r]?[col] ?? XCell(.empty)
        cell.style.bold = bold
        cell.style.italic = italic
        if let color { cell.style.fontColor = color }
        if let fill { cell.style.fill = fill }
        ws.cells[r, default: [:]][col] = cell
    }

    private static func widths(_ ws: inout XSheet, _ list: [Double]) { ws.columnWidths = list }

    private enum Cell {
        case none
        case text(String?)
        case number(Double?)
        case day(String)
    }

    private static func write(_ ws: inout XSheet, _ r: Int, _ values: [Cell], moneyCols: Set<Int> = [],
                              dateCols: Set<Int> = [], cnyCols: Set<Int> = []) {
        for (i, v) in values.enumerated() {
            let col = i + 1
            var style = XStyle()
            if cnyCols.contains(col) { style.numberFormat = moneyCny }
            else if moneyCols.contains(col) { style.numberFormat = money }
            else if dateCols.contains(col) { style.numberFormat = dateFormat }
            switch v {
            case .none: ws.put(r, col, .empty, style)
            case let .text(s): ws.put(r, col, s.map { .text($0) } ?? .empty, style)
            case let .number(n): ws.put(r, col, n.map { .number($0) } ?? .empty, style)
            case let .day(iso):
                let p = iso.prefix(10).split(separator: "-").compactMap { Int($0) }
                if p.count == 3 { ws.put(r, col, .date(year: p[0], month: p[1], day: p[2]), style) } else { ws.put(r, col, .empty, style) }
            }
        }
    }

    private static func str(_ row: Row, _ column: String) -> String? {
        let v: String? = row[column]
        return v
    }

    private static func num(_ row: Row, _ column: String) -> Double? {
        let v: Double? = row[column]
        return v
    }

    // ---- sheets

    private static func summary(_ db: Database, _ start: String, _ end: String, _ filters: Stats.Filters, _ by: String,
                                _ info: [String]) throws -> XSheet {
        let rows = try Stats.summary(db, start: start, end: end, filters: filters, by: by)
        let labels = Stats.buckets(start: start, end: end, by: by).map(\.label)
        let stock = !filters.customerFiltered  // no opening / closing for chosen customers (the stock is not theirs)
        var headers = [t("col.code"), t("col.product"), t("col.name_zh"), t("col.spec"), t("col.variant"), t("col.unit"),
                       t("col.category")]
        if stock { headers.append(t("col.opening")) }
        headers += [t("col.in"), t("col.out"), t("col.adjust")]
        if stock { headers.append(t("col.closing")) }
        let yuan = rows.contains { ($0.revenueCny ?? 0) != 0 }
        headers.append(t("col.revenue"))
        if yuan { headers.append(t("col.revenue_cny")) }
        headers.append(t("col.stock_note"))
        let moneyCol = headers.count - 1 - (yuan ? 1 : 0)
        for label in labels { headers += ["\(t("col.in")) \(label)", "\(t("col.out")) \(label)"] }
        var (ws, r) = sheet(t("sheet.summary"), info, headers)
        for row in rows {
            var values: [Cell] = [.text(row.code), .text(row.nameVi), .text(row.nameZh), .text(row.spec), .text(row.variant),
                                  .text(row.unit), .text(row.category)]
            if stock { values.append(.number(row.opening)) }
            values += [.number(row.qtyIn), .number(row.qtyOut), .number(row.adjust)]
            if stock { values.append(.number(row.closing)) }
            values.append(.number(row.revenue))
            if yuan { values.append(.number(row.revenueCny)) }
            values.append(.text(row.stockNote.isEmpty ? nil : row.stockNote))
            for label in labels {
                let qin = row.perBucket[label]?.qtyIn ?? 0
                let qout = row.perBucket[label]?.qtyOut ?? 0
                values.append(.number(qin == 0 ? nil : qin))  // `qin or None`
                values.append(.number(qout == 0 ? nil : qout))
            }
            write(&ws, r, values, moneyCols: [moneyCol], cnyCols: yuan ? [moneyCol + 1] : [])
            r += 1
        }
        let extra = max(0, headers.count - moneyCol - 1 - (yuan ? 1 : 0))
        widths(&ws, [9, 45, 20, 16, 14, 8, 14] + Array(repeating: 11, count: max(0, moneyCol - 8))
               + Array(repeating: 14, count: yuan ? 2 : 1) + [36] + Array(repeating: 11, count: extra))
        return ws
    }

    private static func details(_ db: Database, _ start: String, _ end: String, _ filters: Stats.Filters,
                                _ info: [String]) throws -> XSheet {
        let kinds: [String: String] = [
            "delivery_out": t("kind.delivery"), "delivery_reverse": t("kind.delivery_cancel"),
            "receipt_in": t("kind.receipt"), "receipt_reverse": t("kind.receipt_cancel"),
            "count_adjust": t("kind.count"), "count_reverse": t("kind.count_cancel"),
            "transfer_out": t("move.transfer_out"), "transfer_in": t("move.transfer_in"),
            "transfer_reverse": t("move.transfer_reverse"),
            "trial_out": t("move.trial_out"), "trial_reverse": t("move.trial_reverse"),
        ]
        let headers = [t("col.date"), t("col.kind"), t("col.doc_code"), t("col.customer"), t("col.place"), t("col.code"),
                       t("col.product"), t("col.name_zh"), t("col.spec"), t("col.variant"), t("col.unit"),
                       t("col.qty_change"), t("col.unit_price"), t("col.amount"), t("col.note")]
        var (ws, r) = sheet(t("sheet.details"), info, headers)
        let headerRow = r - 1
        for m in try Stats.detailLines(db, start: start, end: end, filters: filters) {
            let kindKey = str(m, "kind") ?? ""
            var kind = kinds[kindKey] ?? kindKey
            if str(m, "receipt_source") == "return", kindKey == "receipt_in" || kindKey == "receipt_reverse" {
                kind += " · " + t("receipt_form.source_short_return")
            }
            let place: String? = (m["location_id"] as Int64?).flatMap { Ledger.locationCodes[$0] }.map { t("loc.\($0)") } ?? ""
            let price = num(m, "unit_price")
            var values: [Cell] = [.day(str(m, "occurred_on") ?? ""), .text(kind), .text(str(m, "code")),
                                  .text(str(m, "customer_name")), .text(place), .text(str(m, "product_code")),
                                  .text(str(m, "name_vi")), .text(str(m, "name_zh")), .text(str(m, "spec")),
                                  .text(str(m, "variant")), .text(str(m, "unit")), .number(num(m, "qty")),
                                  .number(price), .number(num(m, "amount")), .text(str(m, "note"))]
            let yuan = str(m, "currency") == "CNY"  // the price cells of a note in yuan show ¥
            if yuan, price != nil {
                values.append(.text("CNY"))
                var bold = XStyle()
                bold.bold = true
                ws.put(headerRow, 16, .text(t("report.currency")), bold)
            }
            write(&ws, r, values, moneyCols: [13, 14], dateCols: [1], cnyCols: yuan ? [13, 14] : [])
            r += 1
        }
        widths(&ws, [11, 16, 10, 30, 12, 9, 40, 20, 16, 14, 8, 10, 12, 14, 30, 10])
        return ws
    }

    private static func customers(_ db: Database, _ start: String, _ end: String, _ filters: Stats.Filters,
                                  _ info: [String]) throws -> XSheet {
        let rows = try Stats.customerProduct(db, start: start, end: end, filters: filters)
        let yuan = rows.contains { (num($0, "revenue_cny") ?? 0) != 0 }
        var headers = [t("col.customer"), t("col.code"), t("col.product"), t("col.name_zh"), t("col.spec"), t("col.variant"),
                       t("col.unit"), t("col.total_qty"), t("col.revenue"), t("col.times"), t("col.last_date")]
        if yuan { headers.append(t("col.revenue_cny")) }
        var (ws, r) = sheet(t("sheet.customers"), info, headers)
        for row in rows {
            var values: [Cell] = [.text(str(row, "customer_name")), .text(str(row, "code")), .text(str(row, "name_vi")),
                                  .text(str(row, "name_zh")), .text(str(row, "spec")), .text(str(row, "variant")),
                                  .text(str(row, "unit")), .number(num(row, "total_qty")), .number(num(row, "revenue")),
                                  .number(num(row, "times")), .day(str(row, "last_date") ?? "")]
            if yuan { values.append(.number(num(row, "revenue_cny"))) }
            write(&ws, r, values, moneyCols: [9], dateCols: [11], cnyCols: [12])
            r += 1
        }
        widths(&ws, [32, 9, 40, 20, 16, 14, 8, 12, 14, 10, 12, 14])
        return ws
    }

    private static func top(_ db: Database, _ start: String, _ end: String, _ filters: Stats.Filters,
                            _ info: [String]) throws -> XSheet {
        let rows = Stats.topOut(try Stats.summary(db, start: start, end: end, filters: filters), limit: 50)
        let yuan = rows.contains { ($0.revenueCny ?? 0) != 0 }
        var headers = [t("col.rank"), t("col.code"), t("col.product"), t("col.name_zh"), t("col.spec"), t("col.variant"),
                       t("col.unit"), t("col.out"), t("col.revenue")]
        if yuan { headers.append(t("col.revenue_cny")) }
        var (ws, r) = sheet(t("sheet.top"), info, headers)
        for (i, row) in rows.enumerated() {
            var values: [Cell] = [.number(Double(i + 1)), .text(row.code), .text(row.nameVi), .text(row.nameZh), .text(row.spec),
                                  .text(row.variant), .text(row.unit), .number(row.qtyOut), .number(row.revenue)]
            if yuan { values.append(.number(row.revenueCny)) }
            write(&ws, r, values, moneyCols: [9], cnyCols: [10])
            r += 1
        }
        widths(&ws, [6, 9, 45, 20, 16, 14, 8, 12, 14, 14])
        return ws
    }

    /// 'ThongKe_<label>_<yyyyMMdd-HHmmss>.xlsx' (the label keeps letters and digits; the rest become '-')
    public static func fileName(label: String, now: Date = Date()) -> String {
        let safe = String(label.map { $0.isLetter || $0.isNumber ? $0 : "-" }).trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyyMMdd-HHmmss"
        return "ThongKe_\(safe)_\(f.string(from: now)).xlsx"
    }
}

extension Stats {
    /// Python customer_product: per customer and product, what was delivered in the period (returns netted in the revenue).
    public static func customerProduct(_ db: Database, start: String, end: String, filters f: Filters = Filters()) throws -> [Row] {
        let (psql, pargs) = f.productSQL()
        let (csql, cargs) = f.customerSQL()
        return try Row.fetchAll(db, sql: """
            SELECT c.name AS customer_name, p.code, p.name_vi, p.name_zh, p.spec, p.variant, p.unit,
                   SUM(CASE WHEN d.kind = 'delivery' THEN l.qty END) AS total_qty,
                   COUNT(DISTINCT CASE WHEN d.kind = 'delivery' THEN d.id END) AS times,
                   MAX(CASE WHEN d.kind = 'delivery' THEN d.doc_date END) AS last_date, \(Lookup.signedSums())
            FROM document_lines l
            JOIN documents d ON d.id = l.document_id
            JOIN products p ON p.id = l.product_id
            LEFT JOIN customers c ON c.id = d.customer_id
            WHERE \(Lookup.saleOrReturn) AND d.status = 'active' AND d.doc_date BETWEEN ? AND ? AND \(psql) AND \(csql)
            GROUP BY d.customer_id, p.id
            HAVING times > 0
            ORDER BY c.name, total_qty DESC
            """, arguments: StatementArguments(scoped(start, end, pargs, cargs)))
    }

    /// Python detail_lines: every movement of the period with its document; a delivery movement gets the price of its own line.
    /// Chosen customers keep every movement that is not a delivery (Python customer_clause).
    public static func detailLines(_ db: Database, start: String, end: String, filters f: Filters = Filters()) throws -> [Row] {
        let (psql, pargs) = f.productSQL()
        let (csql, cargs) = f.customerSQL()
        let customerClause = f.customerFiltered ? "AND (m.kind NOT IN (\(marks(outKinds))) OR \(csql))" : ""
        var customerArgs: [DatabaseValueConvertible?] = []
        if f.customerFiltered {
            customerArgs = values(outKinds)
            customerArgs += cargs
        }
        return try Row.fetchAll(db, sql: """
            WITH mv AS (SELECT m.*, ROW_NUMBER() OVER (PARTITION BY m.document_id, m.product_id, m.kind
                                                       ORDER BY m.id) AS n FROM stock_movements m),
                 ln AS (SELECT l.*, ROW_NUMBER() OVER (PARTITION BY l.document_id, l.product_id ORDER BY l.id) AS n
                        FROM document_lines l)
            SELECT m.occurred_on, m.kind, m.qty, m.location_id, d.code, d.kind AS doc_kind, d.receipt_source,
                   c.name AS customer_name, p.code AS product_code, p.name_vi, p.name_zh, p.spec, p.variant, p.unit,
                   COALESCE(x.note, (SELECT note FROM document_lines l WHERE l.document_id = d.id
                                     AND l.product_id = p.id LIMIT 1)) AS note,
                   x.unit_price, CASE WHEN m.kind = 'receipt_in' THEN -x.amount ELSE x.amount END AS amount, d.currency
            FROM mv m
            LEFT JOIN ln x ON m.kind IN ('delivery_out', 'receipt_in') AND x.document_id = m.document_id AND x.product_id = m.product_id
                           AND x.n = m.n
            JOIN documents d ON d.id = m.document_id
            JOIN products p ON p.id = m.product_id
            LEFT JOIN customers c ON c.id = d.customer_id
            WHERE m.occurred_on BETWEEN ? AND ? AND \(psql) \(customerClause)
            ORDER BY m.occurred_on, d.id, p.name_vi, m.id
            """, arguments: StatementArguments(scoped(start, end, pargs, customerArgs)))
    }
}
