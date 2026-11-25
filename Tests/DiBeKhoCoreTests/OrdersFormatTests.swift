import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

final class FormatTests: XCTestCase {
    func testQuantitiesAreShownAsInPython() {
        for (value, expected) in Golden.quantities {
            XCTAssertEqual(Format.quantity(value), expected, "quantity(\(String(describing: value)))")
        }
    }

    func testMoneyIsShownAsInPython() {
        for (value, currency, rate, approx, expected) in Golden.money {
            XCTAssertEqual(Format.money(value, currency: currency, rate: rate, approx: approx), expected,
                           "money(\(String(describing: value)), \(currency), \(String(describing: rate)), \(approx))")
        }
    }

    func testSumsOfBothCurrenciesAsInPython() {
        for (vnd, cny, approx, expected) in Golden.both {
            XCTAssertEqual(Format.both(vnd, cny, approx: approx), expected,
                           "both(\(String(describing: vnd)), \(String(describing: cny)), \(String(describing: approx)))")
        }
    }

    func testDates() {
        XCTAssertEqual(Format.date("2026-11-05"), "05/11/2026")
        XCTAssertEqual(Format.date("2026-11-05 08:30:00"), "05/11/2026")
        XCTAssertEqual(Format.date(nil), "")
        XCTAssertEqual(Format.date(""), "")
    }
}

final class OrderTests: XCTestCase {
    /// Made-up orders: one in dong from Kho tổng, one in yuan, one from both places, one cancelled, one still
    /// waiting for its place, and a stock count that is not an order.
    private func shop() throws -> DatabaseQueue {
        let queue = try DatabaseQueue()
        try Schema.migrate(queue)
        try queue.write { db in
            try db.execute(sql: """
                INSERT INTO products(id, code, name_vi) VALUES (1, 'SP001', 'Sơn chống thấm'), (2, 'SP002', 'Keo');
                INSERT INTO customers(id, name) VALUES (1, 'Công ty A'), (2, 'Khách Mẫu');
                INSERT INTO documents(id, kind, code, code_norm, doc_date, customer_id, status, source_file, fee_amount, currency,
                                      fx_rate, location_id, location_set) VALUES
                    (1, 'delivery', '160', '160', '2026-11-05', 1, 'active', 'phieu-a.xlsx', 50000, 'VND', NULL, 1, 1),
                    (2, 'delivery', '161', '161', '2026-11-06', 2, 'active', 'phieu-b.xlsx', NULL, 'CNY', 3650, 1, 1),
                    (3, 'delivery', 'A162', 'A162', '2026-11-06', 1, 'active', '', NULL, '', NULL, 1, 1),
                    (4, 'delivery', '159', '159', '2026-11-04', 2, 'cancelled', 'phieu-c.xlsx', NULL, '', NULL, 2, 1),
                    (5, 'delivery', '163', '163', '2026-11-07', 1, 'active', 'phieu-d.xlsx', NULL, '', NULL, 1, 0),
                    (6, 'stock_count', 'KK001', 'KK001', '2026-11-01', NULL, 'active', '', NULL, '', NULL, 1, 1);
                INSERT INTO document_lines(document_id, line_no, product_id, qty, unit_price, amount) VALUES
                    (1, 9, 1, 10, 380000, 3800000), (1, 10, 2, 2.5, NULL, NULL),
                    (2, 9, 1, 4, 1200, 4800),
                    (3, 9, 1, 3, 380000, 1140000), (3, 10, 1, 2, 380000, 760000),
                    (4, 9, 2, 1, 160000, 160000),
                    (5, 9, 2, 6, NULL, NULL),
                    (6, 9, 1, 50, NULL, NULL);
                INSERT INTO stock_movements(product_id, qty, document_id, kind, occurred_on, location_id) VALUES
                    (1, -10, 1, 'delivery_out', '2026-11-05', 1), (2, -2.5, 1, 'delivery_out', '2026-11-05', 1),
                    (1, -4, 2, 'delivery_out', '2026-11-06', 1),
                    (1, -3, 3, 'delivery_out', '2026-11-06', 1), (1, -2, 3, 'delivery_out', '2026-11-06', 2),
                    (2, -6, 5, 'delivery_out', '2026-11-07', 1);
                """)
        }
        return queue
    }

    func testOrdersNewestFirstWithTheirMoneyAndPlace() throws {
        let rows = try shop().read { try OrderQueries.deliveries($0) }
        XCTAssertEqual(rows.map(\.code), ["163", "A162", "161", "160"])  // no cancelled note, no stock count
        let byCode = Dictionary(uniqueKeysWithValues: rows.map { ($0.code, $0) })
        let dong = try XCTUnwrap(byCode["160"])
        XCTAssertEqual(dong.customer, "Công ty A")
        XCTAssertEqual(dong.lineCount, 2)
        XCTAssertEqual(dong.totalQty, 12.5)
        XCTAssertEqual(dong.goods, 3800000)  // the line without a price adds nothing
        XCTAssertEqual(dong.fees, 50000)
        XCTAssertEqual(dong.place, "Kho tổng")
        XCTAssertFalse(dong.isYuan)
        let yuan = try XCTUnwrap(byCode["161"])
        XCTAssertTrue(yuan.isYuan)
        XCTAssertEqual(Format.money(yuan.goods, currency: yuan.currency, rate: yuan.fxRate), "¥4.800 (≈ 17.520.000 ₫)")
        XCTAssertEqual(byCode["A162"]?.place, "Nhiều nơi")
        XCTAssertEqual(byCode["163"]?.place, "Kho tổng (?)")
        XCTAssertNil(byCode["163"]?.goods)
    }

    func testCancelledNotesWhenAskedFor() throws {
        let rows = try shop().read { try OrderQueries.deliveries($0, includeClosed: true) }
        let cancelled = try XCTUnwrap(rows.first { $0.code == "159" })
        XCTAssertEqual(OrderQueries.statusName(cancelled.status), "Đã huỷ")
        XCTAssertEqual(cancelled.place, "Văn phòng Hà Nội")
    }
}
