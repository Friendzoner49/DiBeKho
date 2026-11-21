import Foundation
import GRDB

/// The lookup screens' queries (Python core/queries.py), same SQL: customers, one order, one product, the search.
/// They return GRDB rows, as the Python ones return sqlite3 rows; Golden.phase1 checks them on a made-up shop.
public enum Lookup {
    // Money of one note d, as correlated subqueries so joins with its lines never multiply it.
    static let goods = "(SELECT SUM(x.amount) FROM document_lines x WHERE x.document_id = d.id)"
    static let returned = "(d.kind = 'receipt' AND d.receipt_source = 'return')"
    static let saleOrReturn = "(d.kind = 'delivery' OR \(returned))"
    static let cny = "(d.currency = 'CNY')"
    static let plusMinus = "(CASE WHEN d.kind = 'delivery' THEN l.amount ELSE -l.amount END)"
    static let signed = "(CASE WHEN NOT \(cny) THEN \(plusMinus) END)"
    static let signedCny = "(CASE WHEN \(cny) THEN \(plusMinus) END)"
    static let signedApprox = "(\(signedCny) * COALESCE(d.fx_rate, 0))"
    static let unpriced = "(SELECT COUNT(*) FROM document_lines x WHERE x.document_id = d.id AND x.amount IS NULL)"
    static let total = "(CASE WHEN \(goods) IS NULL AND d.fee_amount IS NULL THEN NULL "
        + "ELSE COALESCE(\(goods), 0) + COALESCE(d.fee_amount, 0) END)"

    static func signedSums(_ name: String = "revenue") -> String {
        "SUM(\(signed)) AS \(name), SUM(\(signedCny)) AS \(name)_cny, SUM(\(signedApprox)) AS \(name)_approx"
    }

    /// (dong, yuan, the yuan as dong) of the goods customers sent back, among active documents matching `where`.
    static func returnedAmounts(_ db: Database, _ condition: String, _ args: [DatabaseValueConvertible?]) throws
        -> (Double, Double, Double) {
        let row = try Row.fetchOne(db, sql: """
            SELECT COALESCE(SUM(CASE WHEN NOT \(cny) THEN l.amount END), 0) AS a,
                   COALESCE(SUM(CASE WHEN \(cny) THEN l.amount END), 0) AS b,
                   COALESCE(SUM(CASE WHEN \(cny) THEN l.amount * COALESCE(d.fx_rate, 0) END), 0) AS c
            FROM document_lines l JOIN documents d ON d.id = l.document_id
            JOIN products p ON p.id = l.product_id WHERE d.status = 'active' AND \(returned) AND \(condition)
            """, arguments: StatementArguments(args))
        guard let row else { return (0, 0, 0) }
        let a: Double? = row["a"]
        let b: Double? = row["b"]
        let c: Double? = row["c"]
        return (a ?? 0, b ?? 0, c ?? 0)
    }

    /// Python core/text.clean: whitespace collapsed and trimmed (NFC).
    public static func clean(_ text: String?) -> String {
        (text ?? "").precomposedStringWithCanonicalMapping
            .split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
    }

    /// Order codes '076' and '76' are the same order.
    public static func normalizeCode(_ code: String?) -> String {
        let s = clean(code)
        let stripped = String(s.drop(while: { $0 == "0" }))
        return stripped.isEmpty ? s : stripped
    }

    static func digits(_ text: String) -> String {
        String(String.UnicodeScalarView(text.unicodeScalars.filter {
            $0.properties.numericType == .decimal || $0.properties.numericType == .digit
        }))
    }

    // ---- customers

    public static func customers(_ db: Database, text: String = "") throws -> [Row] {
        var whereSQL = ""
        var args: [DatabaseValueConvertible?] = []
        if !text.isEmpty {
            let like = "%\(TextRules.unaccent(text))%"
            let phone = digits(text)
            whereSQL = "WHERE unaccent(c.name) LIKE ? OR unaccent(c.contact) LIKE ? OR c.phone_norm LIKE ? "
                + "OR unaccent(c.address) LIKE ? OR unaccent(c.tax_code) LIKE ? OR unaccent(c.email) LIKE ?"
            args = [like, like, "%\(phone.isEmpty ? "#" : phone)%", like, like, like]
        }
        return try Row.fetchAll(db, sql: """
            SELECT c.*, COUNT(d.id) AS order_count, MIN(d.doc_date) AS first_order, MAX(d.doc_date) AS last_order,
                   (SELECT SUM(\(signed)) FROM document_lines l JOIN documents d ON d.id = l.document_id
                    WHERE d.customer_id = c.id AND d.status = 'active' AND \(saleOrReturn)) AS revenue,
                   (SELECT SUM(\(signedCny)) FROM document_lines l JOIN documents d ON d.id = l.document_id
                    WHERE d.customer_id = c.id AND d.status = 'active' AND \(saleOrReturn)) AS revenue_cny,
                   (SELECT SUM(\(signedApprox)) FROM document_lines l JOIN documents d ON d.id = l.document_id
                    WHERE d.customer_id = c.id AND d.status = 'active' AND \(saleOrReturn)) AS revenue_approx
            FROM customers c
            LEFT JOIN documents d ON d.customer_id = c.id AND d.kind = 'delivery' AND d.status = 'active'
            \(whereSQL)
            GROUP BY c.id
            ORDER BY last_order DESC NULLS LAST, c.name
            """, arguments: StatementArguments(args))
    }

    /// Money of a customer over all time (Python customer_money without a period).
    public struct CustomerMoney: Equatable {
        public let orders: Int
        public let unpriced: Int?  // NULL without any order, as in Python
        public let goods: Double?
        public let fees: Double?
        public let total: Double?
        public let returned: Double
        public let goodsCny: Double?
        public let feesCny: Double?
        public let totalCny: Double?
        public let returnedCny: Double
        public let approx: Double
    }

    /// " AND d.doc_date >= ? AND d.doc_date <= ?" for the chosen period (Python queries._period), with its arguments
    static func period(_ start: String?, _ end: String?) -> (sql: String, args: [DatabaseValueConvertible?]) {
        var sql = "", args: [DatabaseValueConvertible?] = []
        if let start { sql += " AND d.doc_date >= ?"; args.append(start) }
        if let end { sql += " AND d.doc_date <= ?"; args.append(end) }
        return (sql, args)
    }

    /// start / end ('YYYY-MM-DD', both inclusive; nil = no limit): the customer window's date filter.
    public static func customerMoney(_ db: Database, customerId: Int64, start: String? = nil, end: String? = nil) throws -> CustomerMoney {
        let per = period(start, end)
        let back = try returnedAmounts(db, "d.customer_id = ?" + per.sql, [customerId] + per.args)
        let row = try Row.fetchOne(db, sql: """
            SELECT COUNT(*) AS orders, SUM(CASE WHEN \(unpriced) > 0 THEN 1 ELSE 0 END) AS unpriced,
                   SUM(CASE WHEN NOT \(cny) THEN \(goods) END) AS goods, SUM(CASE WHEN NOT \(cny) THEN d.fee_amount END) AS fees,
                   SUM(CASE WHEN \(cny) THEN \(goods) END) AS goods_cny, SUM(CASE WHEN \(cny) THEN d.fee_amount END) AS fees_cny,
                   SUM(CASE WHEN \(cny) THEN \(goods) * COALESCE(d.fx_rate, 0) END) AS goods_approx
            FROM documents d WHERE d.customer_id = ? AND d.kind = 'delivery' AND d.status = 'active'\(per.sql)
            """, arguments: StatementArguments([customerId] + per.args))
        guard let row else {
            return CustomerMoney(orders: 0, unpriced: nil, goods: nil, fees: nil, total: nil, returned: 0, goodsCny: nil,
                                 feesCny: nil, totalCny: nil, returnedCny: 0, approx: 0)
        }
        let orders: Int? = row["orders"]
        let unpricedCount: Int? = row["unpriced"]
        let goodsVnd: Double? = row["goods"]
        let fees: Double? = row["fees"]
        let goodsCny: Double? = row["goods_cny"]
        let feesCny: Double? = row["fees_cny"]
        let goodsApprox: Double? = row["goods_approx"]
        func total(_ g: Double?, _ r: Double) -> Double? { g == nil && r == 0 ? nil : (g ?? 0) - r }
        return CustomerMoney(orders: orders ?? 0, unpriced: unpricedCount, goods: goodsVnd, fees: fees,
                             total: total(goodsVnd, back.0), returned: back.0, goodsCny: goodsCny, feesCny: feesCny,
                             totalCny: total(goodsCny, back.1), returnedCny: back.1,
                             approx: (goodsApprox ?? 0) - back.2)
    }

    /// What a customer buys (Python customer_products without a period).
    public static func customerProducts(_ db: Database, customerId: Int64, start: String? = nil, end: String? = nil) throws -> [Row] {
        let sold = "d.kind = 'delivery'"
        let per = period(start, end)
        return try Row.fetchAll(db, sql: """
            SELECT p.id, p.code, p.name_vi, p.name_zh, p.spec, p.variant, p.unit,
                   SUM(CASE WHEN \(sold) THEN l.qty END) AS total_qty,
                   COUNT(DISTINCT CASE WHEN \(sold) THEN d.id END) AS times,
                   MAX(CASE WHEN \(sold) THEN d.doc_date END) AS last_date,
                   \(signedSums()),
                   MIN(CASE WHEN \(sold) AND NOT \(cny) THEN l.unit_price END) AS min_price,
                   MAX(CASE WHEN \(sold) AND NOT \(cny) THEN l.unit_price END) AS max_price,
                   MIN(CASE WHEN \(sold) AND \(cny) THEN l.unit_price END) AS min_price_cny,
                   MAX(CASE WHEN \(sold) AND \(cny) THEN l.unit_price END) AS max_price_cny
            FROM document_lines l
            JOIN documents d ON d.id = l.document_id
            JOIN products p ON p.id = l.product_id
            WHERE d.customer_id = ? AND \(saleOrReturn) AND d.status = 'active'\(per.sql)
            GROUP BY p.id
            HAVING times > 0
            ORDER BY total_qty DESC
            """, arguments: StatementArguments([customerId] + per.args))
    }

    /// A customer with the number and dates of its orders in force (Python queries.customer).
    public static func customer(_ db: Database, id: Int64) throws -> Row? {
        try Row.fetchOne(db, sql: """
            SELECT c.*, COUNT(d.id) AS order_count, MIN(d.doc_date) AS first_order, MAX(d.doc_date) AS last_order
            FROM customers c
            LEFT JOIN documents d ON d.customer_id = c.id AND d.kind = 'delivery' AND d.status = 'active'
            WHERE c.id = ? GROUP BY c.id
            """, arguments: [id])
    }

    /// Every line a customer bought in a period, newest order first, with its price (Python queries.customer_lines).
    public static func customerLines(_ db: Database, customerId: Int64, start: String? = nil, end: String? = nil) throws -> [Row] {
        let per = period(start, end)
        return try Row.fetchAll(db, sql: """
            SELECT d.id AS document_id, d.doc_date, d.code, d.fee_amount, d.currency, d.fx_rate, l.product_id, l.qty,
                   l.unit_price, l.amount,
                   l.note, p.code AS product_code, p.name_vi, p.name_zh, p.spec, p.variant, p.unit
            FROM document_lines l
            JOIN documents d ON d.id = l.document_id
            JOIN products p ON p.id = l.product_id
            WHERE d.customer_id = ? AND d.kind = 'delivery' AND d.status = 'active'\(per.sql)
            ORDER BY d.doc_date DESC, d.id DESC, l.line_no
            """, arguments: StatementArguments([customerId] + per.args))
    }

    public struct PlaceKey: Hashable {
        public let productId: Int64
        public let locationId: Int64

        public init(productId: Int64, locationId: Int64) {
            self.productId = productId
            self.locationId = locationId
        }
    }

    /// A stock count: what it changed at each place, by product (Python queries.count_differences).
    public static func countDifferences(_ db: Database, docId: Int64) throws -> [PlaceKey: Double] {
        var result: [PlaceKey: Double] = [:]
        for r in try Row.fetchAll(db, sql: """
            SELECT product_id, location_id, SUM(qty) AS qty FROM stock_movements WHERE document_id = ?
            AND kind = 'count_adjust' GROUP BY product_id, location_id
            """, arguments: [docId]) {
            result[PlaceKey(productId: r["product_id"], locationId: r["location_id"])] = r["qty"]
        }
        return result
    }

    // ---- one order

    public static func documentHead(_ db: Database, id: Int64) throws -> Row? {
        try Row.fetchOne(db, sql: """
            SELECT d.*, c.name AS customer_name, c.contact, c.phone, c.address, s.name AS supplier_name,
                   \(goods) AS goods_amount, \(total) AS order_total, \(unpriced) AS unpriced_lines
            FROM documents d LEFT JOIN customers c ON c.id = d.customer_id
            LEFT JOIN suppliers s ON s.id = d.supplier_id
            WHERE d.id = ?
            """, arguments: [id])
    }

    public static func documentLines(_ db: Database, id: Int64) throws -> [Row] {
        try Row.fetchAll(db, sql: """
            SELECT l.*, p.code, p.name_vi, p.name_zh, p.spec, p.variant, p.unit
            FROM document_lines l JOIN products p ON p.id = l.product_id
            WHERE l.document_id = ? ORDER BY l.line_no
            """, arguments: [id])
    }

    // ---- one product

    public static func product(_ db: Database, id: Int64) throws -> Row? {
        try Row.fetchOne(db, sql: """
            SELECT p.*, COALESCE((SELECT SUM(qty) FROM stock_movements WHERE product_id = p.id), 0) AS stock,
            COALESCE((SELECT SUM(qty) FROM stock_movements WHERE product_id = p.id AND location_id = 1), 0) AS stock_main,
            COALESCE((SELECT SUM(qty) FROM stock_movements WHERE product_id = p.id AND location_id = 2), 0)
            AS stock_office FROM products p WHERE p.id = ?
            """, arguments: [id])
    }

    /// Every movement with its document, oldest first, plus the running balance.
    public static func productHistory(_ db: Database, id: Int64) throws -> [Row] {
        try Row.fetchAll(db, sql: """
            SELECT m.*, d.code, d.kind AS doc_kind, d.status AS doc_status, c.name AS customer_name,
                   (SELECT COALESCE(SUM(qty), 0) FROM stock_movements m2
                    WHERE m2.product_id = m.product_id
                      AND (m2.occurred_on < m.occurred_on OR (m2.occurred_on = m.occurred_on AND m2.id <= m.id))
                   ) AS balance
            FROM stock_movements m
            JOIN documents d ON d.id = m.document_id
            LEFT JOIN customers c ON c.id = d.customer_id
            WHERE m.product_id = ?
            ORDER BY m.occurred_on, m.id
            """, arguments: [id])
    }

    public static func productTopCustomers(_ db: Database, id: Int64, limit: Int = 10) throws -> [Row] {
        let sold = "d.kind = 'delivery'"
        return try Row.fetchAll(db, sql: """
            SELECT c.id, c.name, SUM(CASE WHEN \(sold) THEN l.qty END) AS total_qty,
                   COUNT(DISTINCT CASE WHEN \(sold) THEN d.id END) AS times,
                   MAX(CASE WHEN \(sold) THEN d.doc_date END) AS last_date, \(signedSums())
            FROM document_lines l
            JOIN documents d ON d.id = l.document_id
            JOIN customers c ON c.id = d.customer_id
            WHERE l.product_id = ? AND \(saleOrReturn) AND d.status = 'active'
            GROUP BY c.id HAVING times > 0 ORDER BY total_qty DESC LIMIT ?
            """, arguments: [id, limit])
    }

    // ---- the search box of Tra cứu

    public struct Found {
        public var products: [Row] = []
        public var customers: [Row] = []
        public var documents: [Row] = []

        public init() {}
    }

    public static func search(_ db: Database, text: String, limit: Int = 50) throws -> Found {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let q = TextRules.unaccent(trimmed)
        guard !q.isEmpty else { return Found() }
        let like = "%\(q)%"
        let phone = digits(text)
        var found = Found()
        found.products = try Row.fetchAll(db, sql: """
            SELECT p.*, COALESCE((SELECT SUM(qty) FROM stock_movements WHERE product_id = p.id), 0) AS stock
            FROM products p
            WHERE unaccent(p.name_vi) LIKE ?1 OR unaccent(p.name_zh) LIKE ?1 OR unaccent(p.code) LIKE ?1
               OR unaccent(p.spec) LIKE ?1 OR unaccent(p.category) LIKE ?1 OR unaccent(p.variant) LIKE ?1
               OR EXISTS (SELECT 1 FROM product_aliases a WHERE a.product_id = p.id AND unaccent(a.key) LIKE ?3)
               OR matches_words(?5, COALESCE(p.code, '') || ' ' || COALESCE(p.name_vi, '') || ' ' ||
                                    COALESCE(p.name_zh, '') || ' ' || COALESCE(p.spec, '') || ' ' ||
                                    COALESCE(p.variant, '') || ' ' || COALESCE(p.category, ''))
            ORDER BY p.active DESC, p.name_vi LIMIT ?4
            """, arguments: [like, "%\(trimmed)%", "%\(q.replacingOccurrences(of: " ", with: ""))%", limit, trimmed])
        found.customers = try Row.fetchAll(db, sql: """
            SELECT * FROM customers
            WHERE unaccent(name) LIKE ?1 OR unaccent(contact) LIKE ?1 OR unaccent(address) LIKE ?1
               OR unaccent(tax_code) LIKE ?1 OR unaccent(email) LIKE ?1
               OR (?2 <> '' AND phone_norm LIKE '%' || ?2 || '%')
            ORDER BY name LIMIT ?3
            """, arguments: [like, phone.count >= 3 ? phone : "", limit])
        found.documents = try Row.fetchAll(db, sql: """
            SELECT DISTINCT d.*, c.name AS customer_name
            FROM documents d
            LEFT JOIN customers c ON c.id = d.customer_id
            LEFT JOIN document_lines l ON l.document_id = d.id
            WHERE d.code_norm = ?1 OR unaccent(d.code) LIKE ?2 OR unaccent(d.note) LIKE ?2 OR unaccent(c.name) LIKE ?2
               OR unaccent(d.source_file) LIKE ?2 OR unaccent(l.note) LIKE ?2 OR unaccent(l.raw_name) LIKE ?2
            ORDER BY d.doc_date DESC LIMIT ?3
            """, arguments: [normalizeCode(text), like, limit])
        return found
    }
}
