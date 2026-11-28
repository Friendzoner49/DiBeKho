import GRDB
import XCTest

@testable import DiBeKhoCore

/// The price column of Nhập hàng về (28/11/2026). The same cases as the Python app's
/// test_latest_price_is_that_of_the_newest_priced_order_in_its_own_money; only the columns the rule reads.
final class LatestPriceTests: XCTestCase {
    func testNewestPricedOrderInItsOwnMoney() throws {
        let queue = try DatabaseQueue()
        try queue.write { db in
            try db.execute(sql: """
                CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE documents (id INTEGER PRIMARY KEY, kind TEXT, status TEXT, doc_date TEXT, currency TEXT,
                                        fx_rate REAL, customer_id INTEGER);
                CREATE TABLE document_lines (document_id INTEGER, product_id INTEGER, line_no INTEGER, unit_price REAL);
                """)

            func sold(_ id: Int, _ day: Int, _ price: Double?, _ currency: String = "VND") throws {
                try db.execute(sql: "INSERT INTO documents VALUES (?, 'delivery', 'active', ?, ?, NULL, NULL)",
                               arguments: [id, "2026-11-\(day)", currency])
                try db.execute(sql: "INSERT INTO document_lines VALUES (?, 1, 1, ?)", arguments: [id, price])
            }
            func latest(_ product: Int64? = 1) throws -> String {
                try Issues.latestPrice(db, productId: product).map { "\($0.price) \($0.currency)" } ?? "none"
            }

            XCTAssertEqual(try latest(), "none")
            XCTAssertEqual(try latest(nil), "none")
            try sold(1, 10, 500000)
            XCTAssertEqual(try latest(), "500000.0 VND")
            try sold(2, 12, 12.5, "CNY")
            try sold(3, 11, 400000)  // entered later, dated earlier: not the latest
            XCTAssertEqual(try latest(), "12.5 CNY")
            try sold(4, 13, nil)  // no price on it: skipped
            XCTAssertEqual(try latest(), "12.5 CNY")
            try sold(5, 12, 450000)  // the same day: the one recorded last
            XCTAssertEqual(try latest(), "450000.0 VND")
            try db.execute(sql: "UPDATE documents SET status = 'cancelled' WHERE id <> 2")
            XCTAssertEqual(try latest(), "12.5 CNY")
            XCTAssertEqual(try latest(2), "none")
        }
    }
}
