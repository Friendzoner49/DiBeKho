import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

/// Phase 1: every lookup query on the made-up shop gives what the Python app gives (Golden.phase1), line by line.
final class LookupTests: XCTestCase {
    private var queue: DatabaseQueue!

    override func setUpWithError() throws {
        queue = try DatabaseQueue(configuration: Store.configuration())
        try Schema.migrate(queue)
        try queue.write { try $0.execute(sql: Golden.shop) }
    }

    // values printed as the generator prints them: numbers with 4 decimals, nothing as ∅
    private func canon(_ value: DatabaseValue) -> String {
        switch value.storage {
        case .null: return "∅"
        case let .int64(i): return String(format: "%.4f", Double(i))
        case let .double(d): return String(format: "%.4f", d)
        case let .string(s): return s
        case .blob: return "?"
        }
    }

    private func canon(_ value: Double?) -> String { value.map { String(format: "%.4f", $0) } ?? "∅" }
    private func canon(_ value: Int?) -> String { value.map { String(format: "%.4f", Double($0)) } ?? "∅" }

    private func line(_ row: Row, _ keys: [String]) -> String {
        keys.map { key -> String in
            let value: DatabaseValue = row[key]
            return "\(key)=\(canon(value))"
        }.joined(separator: "|")
    }

    private func line(_ pairs: [(String, String)]) -> String {
        pairs.map { "\($0.0)=\($0.1)" }.joined(separator: "|")
    }

    private func expect(_ key: String, _ actual: [String], file: StaticString = #filePath, line: UInt = #line) {
        guard let expected = Golden.phase1[key] else { return XCTFail("no golden \(key)", file: file, line: line) }
        XCTAssertEqual(actual, expected, key, file: file, line: line)
    }

    static let customerKeys = ["id", "name", "order_count", "first_order", "last_order", "revenue", "revenue_cny",
                               "revenue_approx"]

    func testCustomers() throws {
        expect("customers", try queue.read { try Lookup.customers($0) }.map { line($0, Self.customerKeys) })
        expect("customers_search", try queue.read { try Lookup.customers($0, text: "ha noi") }.map { line($0, Self.customerKeys) })
    }

    func testOneOrder() throws {
        let headKeys = ["id", "code", "doc_date", "customer_name", "contact", "phone", "address", "goods_amount",
                        "order_total", "unpriced_lines", "fee_amount", "currency", "status", "note"]
        let lineKeys = ["line_no", "code", "name_vi", "name_zh", "spec", "unit", "qty", "unit_price", "amount", "note"]
        for id: Int64 in [2, 3, 4, 7] {
            let (head, lines) = try queue.read { db in
                (try Lookup.documentHead(db, id: id), try Lookup.documentLines(db, id: id))
            }
            let got = [line(try XCTUnwrap(head), headKeys)] + lines.map { line($0, lineKeys) }
            expect("document_\(id)", got)
        }
    }

    func testOneCustomer() throws {
        let productKeys = ["id", "code", "total_qty", "times", "last_date", "revenue", "revenue_cny", "revenue_approx",
                           "min_price", "max_price", "min_price_cny", "max_price_cny"]
        for id: Int64 in [1, 2, 3] {
            let m = try queue.read { try Lookup.customerMoney($0, customerId: id) }
            expect("customer_money_\(id)", [line([
                ("orders", canon(m.orders)), ("unpriced", canon(m.unpriced)), ("goods", canon(m.goods)),
                ("fees", canon(m.fees)), ("total", canon(m.total)), ("returned", canon(m.returned)),
                ("cny_goods", canon(m.goodsCny)), ("cny_fees", canon(m.feesCny)), ("cny_total", canon(m.totalCny)),
                ("cny_returned", canon(m.returnedCny)), ("approx", canon(m.approx)),
            ])])
            expect("customer_products_\(id)",
                   try queue.read { try Lookup.customerProducts($0, customerId: id) }.map { line($0, productKeys) })
        }
    }

    func testOneProduct() throws {
        let productKeys = ["id", "code", "name_vi", "stock", "stock_main", "stock_office"]
        let historyKeys = ["id", "occurred_on", "kind", "qty", "location_id", "code", "doc_kind", "doc_status",
                           "customer_name", "balance"]
        let topKeys = ["id", "name", "total_qty", "times", "last_date", "revenue", "revenue_cny", "revenue_approx"]
        for id: Int64 in [1, 2, 3] {
            let product = try queue.read { try Lookup.product($0, id: id) }
            expect("product_\(id)", [line(try XCTUnwrap(product), productKeys)])
            expect("history_\(id)", try queue.read { try Lookup.productHistory($0, id: id) }.map { line($0, historyKeys) })
            expect("top_\(id)", try queue.read { try Lookup.productTopCustomers($0, id: id) }.map { line($0, topKeys) })
        }
    }

    func testSearch() throws {
        for (i, text) in Golden.searchTexts.enumerated() {
            let found = try queue.read { try Lookup.search($0, text: text) }
            let got = found.products.map { row -> String in let c: String = row["code"]; return "p:\(c)" }
                + found.customers.map { row -> String in let n: String = row["name"]; return "c:\(n)" }
                + found.documents.map { row -> String in let c: String = row["code"]; return "d:\(c)" }
            expect("search_\(i)", got)
        }
    }

    func testStatistics() throws {
        let periods: [(String, String, String)] = [("oct", "2026-10-01", "2026-10-31"), ("nov", "2026-11-01", "2026-11-30"),
                                                   ("all", "2026-01-01", "2026-12-31")]
        for (name, start, end) in periods {
            let rows = try queue.read { try Stats.summary($0, start: start, end: end) }
            expect("summary_\(name)", rows.map { r in
                line([("product_id", canon(Double(r.productId))), ("code", r.code), ("opening", canon(r.opening)),
                      ("qty_in", canon(r.qtyIn)), ("qty_out", canon(r.qtyOut)), ("adjust", canon(r.adjust)),
                      ("closing", canon(r.closing)), ("revenue", canon(r.revenue)), ("revenue_cny", canon(r.revenueCny)),
                      ("revenue_approx", canon(r.revenueApprox)), ("stock_note", r.stockNote)])
            })
            let m = try queue.read { try Stats.money($0, start: start, end: end) }
            expect("money_\(name)", [line([
                ("orders", canon(m.orders)), ("goods", canon(m.goods)), ("fees", canon(m.fees)),
                ("unpriced", canon(m.unpriced)), ("returned", canon(m.returned)), ("goods_cny", canon(m.goodsCny)),
                ("fees_cny", canon(m.feesCny)), ("returned_cny", canon(m.returnedCny)), ("approx", canon(m.approx)),
                ("total", canon(m.total)), ("total_cny", canon(m.totalCny)),
            ])])
            expect("top_out_\(name)", Stats.topOut(rows).map { "\($0.code)=\(canon($0.qtyOut))" })
        }
    }

    /// The Thống kê scope (products, groups, customers), «Chia theo» and the chart; the Excel sheets of the same scope
    func testStatisticsScope() throws {
        let filters: [(String, Stats.Filters)] = [
            ("none", Stats.Filters()), ("products_1_2", Stats.Filters(productIds: [1, 2])),
            ("keo", Stats.Filters(categories: ["Keo"])), ("customer_1", Stats.Filters(customerIds: [1])),
            ("customer_2_son_keo", Stats.Filters(categories: ["Keo", "Sơn"], customerIds: [2])),
        ]
        let periods: [(String, String, String)] = [("oct", "2026-10-01", "2026-10-31"), ("all", "2026-01-01", "2026-12-31")]
        for (fname, f) in filters {
            for (pname, start, end) in periods {
                let key = "\(fname)_\(pname)"
                let rows = try queue.read { try Stats.summary($0, start: start, end: end, filters: f) }
                expect("fsummary_\(key)", rows.map { r in
                    line([("product_id", canon(Double(r.productId))), ("code", r.code), ("opening", canon(r.opening)),
                          ("qty_in", canon(r.qtyIn)), ("qty_out", canon(r.qtyOut)), ("adjust", canon(r.adjust)),
                          ("closing", canon(r.closing)), ("revenue", canon(r.revenue)), ("revenue_cny", canon(r.revenueCny)),
                          ("revenue_approx", canon(r.revenueApprox)), ("stock_note", r.stockNote)])
                })
                let m = try queue.read { try Stats.money($0, start: start, end: end, filters: f) }
                expect("fmoney_\(key)", [line([
                    ("orders", canon(m.orders)), ("goods", canon(m.goods)), ("fees", canon(m.fees)),
                    ("unpriced", canon(m.unpriced)), ("returned", canon(m.returned)), ("goods_cny", canon(m.goodsCny)),
                    ("fees_cny", canon(m.feesCny)), ("returned_cny", canon(m.returnedCny)), ("approx", canon(m.approx)),
                    ("total", canon(m.total)), ("total_cny", canon(m.totalCny)),
                ])])
                let daily = try queue.read { try Stats.dailyOut($0, start: start, end: end, filters: f) }
                expect("fdaily_\(key)", daily.filter { $0.qty != 0 }.map { "\($0.day)=\(canon($0.qty))" } + ["days=\(daily.count)"])
                let cp = try queue.read { try Stats.customerProduct($0, start: start, end: end, filters: f) }
                expect("fcustomer_product_\(key)", cp.map { r in
                    let name: String? = r["customer_name"]
                    let code: String? = r["code"]
                    let last: String? = r["last_date"]
                    let qty: DatabaseValue = r["total_qty"], times: DatabaseValue = r["times"]
                    let rev: DatabaseValue = r["revenue"], cny: DatabaseValue = r["revenue_cny"]
                    return "\(name ?? "None")|\(code ?? "")|\(canon(qty))|\(canon(times))|\(last ?? "None")|\(canon(rev))|\(canon(cny))"
                })
                let detail = try queue.read { try Stats.detailLines($0, start: start, end: end, filters: f) }
                expect("fdetail_\(key)", detail.map { r in
                    let on: String? = r["occurred_on"], kind: String? = r["kind"], code: String? = r["code"]
                    let product: String? = r["product_code"], note: String? = r["note"]
                    let qty: DatabaseValue = r["qty"], price: DatabaseValue = r["unit_price"], amount: DatabaseValue = r["amount"]
                    return "\(on ?? "")|\(kind ?? "")|\(code ?? "")|\(product ?? "")|\(canon(qty))|\(canon(price))|\(canon(amount))|\(note ?? "None")"
                })
            }
        }
        let spans: [(String, String, String)] = [("day", "2026-10-30", "2026-11-02"), ("month", "2026-09-15", "2026-11-10"),
                                                 ("none", "2026-10-01", "2026-10-02")]
        for (by, start, end) in spans {
            expect("buckets_\(by)", Stats.buckets(start: start, end: end, by: by).map { "\($0.label)|\($0.start)|\($0.end)" })
        }
        let split: [(String, String, String, String, Stats.Filters)] = [
            ("month_all", "2026-09-15", "2026-11-10", "month", Stats.Filters()),
            ("day_customer_1", "2026-10-03", "2026-10-06", "day", Stats.Filters(customerIds: [1])),
        ]
        for (name, start, end, by, f) in split {
            let labels = Stats.buckets(start: start, end: end, by: by).map(\.label)
            let rows = try queue.read { try Stats.summary($0, start: start, end: end, filters: f, by: by) }
            expect("per_bucket_\(name)", rows.flatMap { r in
                labels.map { label in
                    let io = r.perBucket[label]
                    return "\(r.code)|\(label)=\(canon(io?.qtyIn ?? 0))/\(canon(io?.qtyOut ?? 0))"
                }
            })
        }
    }

    /// The build workflow opens the app on this shop for its screenshots (only when it asks for the file).
    func testWriteTheShopForTheScreenshots() throws {
        guard let path = ProcessInfo.processInfo.environment["DIBEKHO_SHOP_OUT"] else { return }
        try? FileManager.default.removeItem(atPath: path)
        let file = try DatabaseQueue(path: path, configuration: Store.configuration())
        try Schema.migrate(file)
        try file.write { try $0.execute(sql: Golden.shop) }
        try file.close()
    }

    func testPeriods() {
        XCTAssertEqual(Stats.monthRange(2028, 2).1, "2028-02-29")
        XCTAssertEqual(Stats.monthRange(2026, 2).1, "2026-02-28")
        XCTAssertEqual(Stats.quarterRange(2026, 4).0, "2026-10-01")
        XCTAssertEqual(Stats.quarterRange(2026, 4).1, "2026-12-31")
        XCTAssertEqual(Stats.yearRange(2026).1, "2026-12-31")
    }

    /// The Đơn hàng window's filters (Python queries.documents): kind, period, customer, product, text, cancelled
    func testDocumentFilters() throws {
        let keys = ["id", "code", "doc_date", "status", "customer_name", "supplier_name", "line_count", "total_qty",
                    "goods_amount", "places", "location_id", "to_location_id", "location_set"]
        let cases: [(String, (Database) throws -> [Row])] = [
            ("delivery", { try OrderQueries.documents($0, kind: "delivery") }),
            ("delivery_closed", { try OrderQueries.documents($0, kind: "delivery", includeClosed: true) }),
            ("delivery_oct", { try OrderQueries.documents($0, kind: "delivery", from: "2026-10-01", to: "2026-10-31") }),
            ("delivery_from_nov", { try OrderQueries.documents($0, kind: "delivery", from: "2026-11-01", includeClosed: true) }),
            ("delivery_customer_1", { try OrderQueries.documents($0, kind: "delivery", customerId: 1) }),
            ("delivery_product_2", { try OrderQueries.documents($0, kind: "delivery", productId: 2, includeClosed: true) }),
            ("delivery_product_1_closed", { try OrderQueries.documents($0, kind: "delivery", productId: 1, includeClosed: true) }),
            ("delivery_text_76", { try OrderQueries.documents($0, kind: "delivery", text: "76") }),
            ("delivery_text_cong_ty", { try OrderQueries.documents($0, kind: "delivery", text: "cong ty") }),
            ("delivery_text_khach_mau", { try OrderQueries.documents($0, kind: "delivery", includeClosed: true, text: "Khách mẫu") }),
            ("delivery_text_file", { try OrderQueries.documents($0, kind: "delivery", text: "phieu-76") }),
            ("receipt", { try OrderQueries.documents($0, kind: "receipt") }),
            ("transfer", { try OrderQueries.documents($0, kind: "transfer") }),
            ("trial", { try OrderQueries.documents($0, kind: "trial") }),
            ("stock_count", { try OrderQueries.documents($0, kind: "stock_count") }),
        ]
        for (name, query) in cases {
            expect("documents_\(name)", try queue.read { try query($0) }.map { line($0, keys) })
        }
    }

    /// The customer window's summary and orders tree, a stock count's differences (Python queries)
    func testCustomerWindowAndCount() throws {
        let lineKeys = ["document_id", "doc_date", "code", "fee_amount", "currency", "fx_rate", "product_id", "qty",
                        "unit_price", "amount", "note", "product_code", "name_vi", "name_zh", "spec", "variant", "unit"]
        for cid: Int64 in [1, 2, 3] {
            let head = try queue.read { try Lookup.customer($0, id: cid) }
            expect("customer_\(cid)", head.map { [line($0, ["id", "name", "order_count", "first_order", "last_order"])] } ?? [])
            expect("customer_lines_\(cid)", try queue.read { try Lookup.customerLines($0, customerId: cid) }.map { line($0, lineKeys) })
        }
        expect("customer_lines_1_oct", try queue.read {
            try Lookup.customerLines($0, customerId: 1, start: "2026-10-01", end: "2026-10-31")
        }.map { line($0, lineKeys) })
        let diffs = try queue.read { try Lookup.countDifferences($0, docId: 1) }
        let shown = diffs.sorted { ($0.key.productId, $0.key.locationId) < ($1.key.productId, $1.key.locationId) }
            .map { "\($0.key.productId)|\($0.key.locationId)=\(canon($0.value))" }
        expect("count_differences_1", shown)
    }

    func testCodesAsInPython() {
        XCTAssertEqual(Lookup.normalizeCode(" 076 "), "76")
        XCTAssertEqual(Lookup.normalizeCode("000"), "000")
        XCTAssertEqual(Lookup.clean("  a \t b  "), "a b")
    }
}
