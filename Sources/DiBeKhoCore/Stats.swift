import Foundation
import GRDB

/// Period statistics (Python core/stats.py, same SQL). Dates are business dates. Transfers are neither in nor out;
/// trial use is an adjustment. Revenue = goods of the active notes less what customers sent back; fees apart.
/// Filters: the scope of the Thống kê window (Mặt hàng / Nhóm hàng / Khách hàng); `by` splits in and out per day or month.
public enum Stats {
    static let inKinds = ["receipt_in", "receipt_reverse"]
    static let outKinds = ["delivery_out", "delivery_reverse"]
    static let adjKinds = ["count_adjust", "count_reverse", "trial_out", "trial_reverse"]

    /// Python stats.Filters: empty = all. The customers change the outgoing quantities only.
    public struct Filters: Equatable {
        public var productIds: [Int64]
        public var categories: [String]
        public var customerIds: [Int64]

        public init(productIds: [Int64] = [], categories: [String] = [], customerIds: [Int64] = []) {
            self.productIds = productIds
            self.categories = categories
            self.customerIds = customerIds
        }

        public var customerFiltered: Bool { !customerIds.isEmpty }
        /// fees belong to no product: unknown once products or groups are chosen
        public var productScoped: Bool { !productIds.isEmpty || !categories.isEmpty }

        func productSQL(_ alias: String = "p") -> (String, [DatabaseValueConvertible?]) {
            var parts: [String] = [], args: [DatabaseValueConvertible?] = []
            if !productIds.isEmpty {
                parts.append("\(alias).id IN (\(productIds.map { _ in "?" }.joined(separator: ",")))")
                args += productIds.map { $0 as DatabaseValueConvertible? }
            }
            if !categories.isEmpty {
                parts.append("\(alias).category IN (\(categories.map { _ in "?" }.joined(separator: ",")))")
                args += categories.map { $0 as DatabaseValueConvertible? }
            }
            return (parts.isEmpty ? "1=1" : parts.joined(separator: " AND "), args)
        }

        func customerSQL(_ alias: String = "d") -> (String, [DatabaseValueConvertible?]) {
            guard !customerIds.isEmpty else { return ("1=1", []) }
            return ("\(alias).customer_id IN (\(customerIds.map { _ in "?" }.joined(separator: ",")))",
                    customerIds.map { $0 as DatabaseValueConvertible? })
        }
    }

    /// A day or a month of «Chia theo» (label 'dd/MM' or 'MM/yyyy'; start / end ISO days inside the period)
    public struct Bucket: Equatable {
        public let label: String
        public let start: String
        public let end: String
    }

    public struct InOut: Equatable {
        public let qtyIn: Double
        public let qtyOut: Double
    }

    public struct SummaryRow: Equatable {
        public let productId: Int64
        public let code: String
        public let nameVi: String
        public let nameZh: String
        public let spec: String
        public let variant: String
        public let unit: String
        public let category: String
        public let stockNote: String
        /// nil when customers are chosen (the stock is not the customers')
        public let opening: Double?
        public let qtyIn: Double
        public let qtyOut: Double
        public let adjust: Double
        public var closing: Double? { opening.map { $0 + qtyIn - qtyOut + adjust } }
        public var revenue: Double?
        public var revenueCny: Double?
        public var revenueApprox: Double?
        /// bucket label -> in / out
        public var perBucket: [String: InOut] = [:]
    }

    public struct Money: Equatable {
        public let orders: Int
        public let goods: Double
        public let fees: Double?
        public let unpriced: Int
        public let returned: Double
        public let goodsCny: Double
        public let feesCny: Double?
        public let returnedCny: Double
        public let approx: Double
        public var total: Double { goods - returned }
        public var totalCny: Double { goodsCny - returnedCny }
    }

    static func marks(_ kinds: [String]) -> String { kinds.map { _ in "?" }.joined(separator: ",") }

    static func values(_ items: [String]) -> [DatabaseValueConvertible?] { items.map { $0 as DatabaseValueConvertible? } }

    /// start, end, then the product and customer arguments of a filter
    static func scoped(_ start: String, _ end: String, _ first: [DatabaseValueConvertible?],
                       _ second: [DatabaseValueConvertible?]) -> [DatabaseValueConvertible?] {
        var out: [DatabaseValueConvertible?] = [start, end]
        out += first
        out += second
        return out
    }

    private static func text(_ row: Row, _ column: String) -> String {
        let value: String? = row[column]
        return value ?? ""
    }

    private static func number(_ row: Row, _ column: String) -> Double {
        let value: Double? = row[column]
        return value ?? 0
    }

    // ---- periods split by day or month (Python buckets)

    static let isoDay: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.calendar = Calendar(identifier: .gregorian)
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    /// Every day from start to end (ISO), both included
    static func days(_ start: String, _ end: String) -> [String] {
        guard let first = isoDay.date(from: start), let last = isoDay.date(from: end) else { return [] }
        var out: [String] = [], d = first
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        while d <= last {
            out.append(isoDay.string(from: d))
            guard let next = calendar.date(byAdding: .day, value: 1, to: d) else { break }
            d = next
        }
        return out
    }

    /// by: "day" | "month" | anything else = none
    public static func buckets(start: String, end: String, by: String) -> [Bucket] {
        if by == "day" {
            return days(start, end).map { iso in
                let p = iso.split(separator: "-")
                return Bucket(label: "\(p[2])/\(p[1])", start: iso, end: iso)
            }
        }
        guard by == "month", let y0 = Int(start.prefix(4)), let m0 = Int(start.dropFirst(5).prefix(2)) else { return [] }
        var out: [Bucket] = [], y = y0, m = m0
        while iso(y, m, 1) <= end {
            let (s, e) = monthRange(y, m)
            out.append(Bucket(label: String(format: "%02d/%d", m, y), start: max(s, start), end: min(e, end)))
            (y, m) = m == 12 ? (y + 1, 1) : (y, m + 1)
        }
        return out
    }

    // ---- queries

    public static func summary(_ db: Database, start: String, end: String, filters f: Filters = Filters(),
                               by: String = "none") throws -> [SummaryRow] {
        let (psql, pargs) = f.productSQL()
        let (csql, cargs) = f.customerSQL()
        let period: [DatabaseValueConvertible?] = [start, end]
        var args: [DatabaseValueConvertible?] = [start]
        args += period
        args += values(inKinds)
        args += period
        args += values(outKinds)
        args += cargs
        args += period
        args += values(adjKinds)
        args += pargs
        let rows = try Row.fetchAll(db, sql: """
            SELECT p.id, p.code, p.name_vi, p.name_zh, p.spec, p.variant, p.unit, p.category, p.stock_note,
              COALESCE(SUM(CASE WHEN m.occurred_on < ? THEN m.qty END), 0) AS opening,
              COALESCE(SUM(CASE WHEN m.occurred_on BETWEEN ? AND ? AND m.kind IN (\(marks(inKinds))) THEN m.qty END), 0) AS qty_in,
              COALESCE(-SUM(CASE WHEN m.occurred_on BETWEEN ? AND ? AND m.kind IN (\(marks(outKinds))) AND (\(csql))
                                 THEN m.qty END), 0) AS qty_out,
              COALESCE(SUM(CASE WHEN m.occurred_on BETWEEN ? AND ? AND m.kind IN (\(marks(adjKinds))) THEN m.qty END), 0) AS adjust
            FROM products p
            LEFT JOIN stock_movements m ON m.product_id = p.id
            LEFT JOIN documents d ON d.id = m.document_id
            WHERE \(psql) AND (p.active = 1 OR m.id IS NOT NULL)
            GROUP BY p.id
            ORDER BY p.category, p.name_vi, p.spec, p.variant
            """, arguments: StatementArguments(args))
        let money = try revenue(db, start: start, end: end, filters: f)
        var result = rows.map { row -> SummaryRow in
            let id: Int64 = row["id"]
            let r = money[id]
            return SummaryRow(productId: id, code: text(row, "code"), nameVi: text(row, "name_vi"),
                              nameZh: text(row, "name_zh"), spec: text(row, "spec"), variant: text(row, "variant"),
                              unit: text(row, "unit"), category: text(row, "category"),
                              stockNote: text(row, "stock_note"),
                              opening: f.customerFiltered ? nil : number(row, "opening"),
                              qtyIn: number(row, "qty_in"), qtyOut: number(row, "qty_out"), adjust: number(row, "adjust"),
                              revenue: r?.0, revenueCny: r?.1, revenueApprox: r?.2)
        }
        if f.customerFiltered { result = result.filter { $0.qtyOut != 0 } }
        if by == "day" || by == "month", !result.isEmpty {
            try fillBuckets(db, &result, buckets(start: start, end: end, by: by), f)
        }
        return result
    }

    /// product id -> (dong, yuan, the yuan as dong)
    static func revenue(_ db: Database, start: String, end: String, filters f: Filters = Filters()) throws
        -> [Int64: (Double?, Double?, Double?)] {
        let (psql, pargs) = f.productSQL()
        let (csql, cargs) = f.customerSQL()
        let rows = try Row.fetchAll(db, sql: """
            SELECT l.product_id, \(Lookup.signedSums()) FROM document_lines l
            JOIN documents d ON d.id = l.document_id JOIN products p ON p.id = l.product_id
            WHERE \(Lookup.saleOrReturn) AND d.status = 'active' AND d.doc_date BETWEEN ? AND ? AND l.amount IS NOT NULL
              AND \(psql) AND \(csql)
            GROUP BY l.product_id
            """, arguments: StatementArguments(scoped(start, end, pargs, cargs)))
        var out: [Int64: (Double?, Double?, Double?)] = [:]
        for row in rows {
            let id: Int64 = row["product_id"]
            let a: Double? = row["revenue"]
            let b: Double? = row["revenue_cny"]
            let c: Double? = row["revenue_approx"]
            out[id] = (a, b, c)
        }
        return out
    }

    public static func money(_ db: Database, start: String, end: String, filters f: Filters = Filters()) throws -> Money {
        let cny = Lookup.cny
        let (psql, pargs) = f.productSQL()
        let (csql, cargs) = f.customerSQL()
        guard let row = try Row.fetchOne(db, sql: """
            SELECT COUNT(DISTINCT d.id) AS orders, COALESCE(SUM(CASE WHEN NOT \(cny) THEN l.amount END), 0) AS goods,
                   COALESCE(SUM(CASE WHEN \(cny) THEN l.amount END), 0) AS goods_cny,
                   COALESCE(SUM(CASE WHEN \(cny) THEN l.amount * COALESCE(d.fx_rate, 0) END), 0) AS goods_approx,
                   COUNT(DISTINCT CASE WHEN l.amount IS NULL THEN d.id END) AS unpriced
            FROM document_lines l
            JOIN documents d ON d.id = l.document_id JOIN products p ON p.id = l.product_id
            WHERE d.kind = 'delivery' AND d.status = 'active' AND d.doc_date BETWEEN ? AND ? AND \(psql) AND \(csql)
            """, arguments: StatementArguments(scoped(start, end, pargs, cargs))) else {
            return Money(orders: 0, goods: 0, fees: 0, unpriced: 0, returned: 0, goodsCny: 0, feesCny: 0,
                         returnedCny: 0, approx: 0)
        }
        var fees: Double? = nil
        var feesCny: Double? = nil
        if !f.productScoped, let feeRow = try Row.fetchOne(db, sql: """
            SELECT COALESCE(SUM(CASE WHEN NOT \(cny) THEN d.fee_amount END), 0) AS a,
                   COALESCE(SUM(CASE WHEN \(cny) THEN d.fee_amount END), 0) AS b FROM documents d WHERE d.kind = 'delivery'
            AND d.status = 'active' AND d.doc_date BETWEEN ? AND ? AND \(csql)
            """, arguments: StatementArguments(scoped(start, end, [], cargs))) {
            fees = feeRow["a"]
            feesCny = feeRow["b"]
        }
        let back = try Lookup.returnedAmounts(db, "d.doc_date BETWEEN ? AND ? AND \(psql) AND \(csql)",
                                              scoped(start, end, pargs, cargs))
        return Money(orders: Int(number(row, "orders")), goods: number(row, "goods"),
                     fees: fees, unpriced: Int(number(row, "unpriced")), returned: back.0,
                     goodsCny: number(row, "goods_cny"), feesCny: feesCny, returnedCny: back.1,
                     approx: number(row, "goods_approx") - back.2)
    }

    /// In and out of each product in each bucket (Python _fill_buckets)
    static func fillBuckets(_ db: Database, _ rows: inout [SummaryRow], _ buckets: [Bucket], _ f: Filters) throws {
        let (csql, cargs) = f.customerSQL()
        let ids = rows.map(\.productId)
        var index: [Int64: Int] = [:]
        for (i, r) in rows.enumerated() {
            index[r.productId] = i
            var empty: [String: InOut] = [:]
            for b in buckets { empty[b.label] = InOut(qtyIn: 0, qtyOut: 0) }
            rows[i].perBucket = empty
        }
        for b in buckets {
            var args = values(inKinds)
            args += values(outKinds)
            args += cargs
            args += scoped(b.start, b.end, ids.map { $0 as DatabaseValueConvertible? }, [])
            for r in try Row.fetchAll(db, sql: """
                SELECT m.product_id,
                  COALESCE(SUM(CASE WHEN m.kind IN (\(marks(inKinds))) THEN m.qty END), 0) AS qin,
                  COALESCE(-SUM(CASE WHEN m.kind IN (\(marks(outKinds))) AND (\(csql)) THEN m.qty END), 0) AS qout
                FROM stock_movements m JOIN documents d ON d.id = m.document_id
                WHERE m.occurred_on BETWEEN ? AND ? AND m.product_id IN (\(ids.map { _ in "?" }.joined(separator: ",")))
                GROUP BY m.product_id
                """, arguments: StatementArguments(args)) {
                let pid: Int64 = r["product_id"]
                if let i = index[pid] { rows[i].perBucket[b.label] = InOut(qtyIn: number(r, "qin"), qtyOut: number(r, "qout")) }
            }
        }
    }

    /// Total outgoing quantity per day, every day of the period (the chart; Python daily_out)
    public static func dailyOut(_ db: Database, start: String, end: String, filters f: Filters = Filters()) throws
        -> [(day: String, qty: Double)] {
        let (psql, pargs) = f.productSQL()
        let (csql, cargs) = f.customerSQL()
        var got: [String: Double] = [:]
        for r in try Row.fetchAll(db, sql: """
            SELECT m.occurred_on AS day, -SUM(m.qty) AS qty
            FROM stock_movements m JOIN products p ON p.id = m.product_id JOIN documents d ON d.id = m.document_id
            WHERE m.kind IN (\(marks(outKinds))) AND m.occurred_on BETWEEN ? AND ? AND \(psql) AND \(csql)
            GROUP BY m.occurred_on
            """, arguments: StatementArguments(values(outKinds) + scoped(start, end, pargs, cargs))) {
            got[text(r, "day")] = number(r, "qty")
        }
        return days(start, end).map { (day: $0, qty: got[$0] ?? 0) }
    }

    /// The products that went out most in the period (ties keep the summary's order, as Python's stable sort).
    public static func topOut(_ rows: [SummaryRow], limit: Int = 10) -> [SummaryRow] {
        let out = rows.enumerated().filter { $0.element.qtyOut > 0 }
        let sorted = out.sorted { a, b in
            a.element.qtyOut != b.element.qtyOut ? a.element.qtyOut > b.element.qtyOut : a.offset < b.offset
        }
        return sorted.prefix(limit).map(\.element)
    }

    // ---- periods (Python day_range, month_range, quarter_range, year_range), as "YYYY-MM-DD"

    public static func iso(_ year: Int, _ month: Int, _ day: Int) -> String {
        String(format: "%04d-%02d-%02d", year, month, day)
    }

    public static func daysIn(_ year: Int, _ month: Int) -> Int {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let date = calendar.date(from: DateComponents(year: year, month: month, day: 1))!
        return calendar.range(of: .day, in: .month, for: date)!.count
    }

    public static func monthRange(_ year: Int, _ month: Int) -> (String, String) {
        (iso(year, month, 1), iso(year, month, daysIn(year, month)))
    }

    public static func quarterRange(_ year: Int, _ quarter: Int) -> (String, String) {
        let first = 3 * (quarter - 1) + 1
        return (iso(year, first, 1), monthRange(year, first + 2).1)
    }

    public static func yearRange(_ year: Int) -> (String, String) {
        (iso(year, 1, 1), iso(year, 12, 31))
    }
}
