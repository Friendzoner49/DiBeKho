import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

/// Report.exportCustomer (excel/report.export_customer, all time). Swift-only checks (⚠ not a golden file).
final class CustomerExportTests: XCTestCase {
    func testOrdersAndProductsSheets() throws {
        let q = try DatabaseQueue(configuration: Store.configuration())
        try Schema.migrate(q)
        let cid = try q.write { db -> Int64 in
            try db.execute(sql: "INSERT INTO customers(name, phone, phone_norm) VALUES('Đại lý A', '0911112222', '0911112222')")
            let cid = db.lastInsertedRowID
            let p = try Catalog.createProduct(db, nameVi: "Keo", nameZh: "", spec: "5kg", unit: "Thùng", category: "", variant: "")
            _ = try Ledger.insertDocument(db, kind: "delivery", date: "2026-11-02",
                                          lines: [LedgerLine(p, 3, unitPrice: 100_000, amount: 300_000)], code: "A001", codeNorm: "a001",
                                          customerId: cid)
            _ = try Ledger.insertDocument(db, kind: "delivery", date: "2026-11-09",
                                          lines: [LedgerLine(p, 2, unitPrice: 120_000, amount: 240_000)], code: "A002", codeNorm: "a002",
                                          customerId: cid)
            return cid
        }
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("kh-\(UUID().uuidString).xlsx")
        defer { try? FileManager.default.removeItem(at: url) }
        try q.read { _ = try Report.exportCustomer($0, to: url, customerId: cid) }
        let sheets = try Xlsx.read(url)
        XCTAssertEqual(sheets.count, 2)
        let orders = sheets[0].rows.map { $0.map { $0?.pythonText ?? "" } }
        // 4 info lines, a blank line, the header, then: line + total of A001, line + total of A002 (oldest first)
        let body = orders.filter { $0.count > 1 && ($0[1] == "A001" || $0[1] == "A002") }
        XCTAssertEqual(body.map { $0[1] }, ["A001", "A001", "A002", "A002"])
        XCTAssertEqual(body[1][3], t("report.order_total"))
        let products = sheets[1].rows.map { $0.map { $0?.pythonText ?? "" } }
        let keo = products.first { $0.count > 1 && $0[1] == "Keo" }
        XCTAssertNotNil(keo)
        XCTAssertEqual(Double(keo?[5] ?? ""), 5)  // total quantity 3 + 2
    }

    func testPeriodKeepsOnlyOrdersInsideIt() throws {
        let q = try DatabaseQueue(configuration: Store.configuration())
        try Schema.migrate(q)
        let cid = try q.write { db -> Int64 in
            try db.execute(sql: "INSERT INTO customers(name, phone, phone_norm) VALUES('Đại lý A', '0911112222', '0911112222')")
            let cid = db.lastInsertedRowID
            let p = try Catalog.createProduct(db, nameVi: "Keo", nameZh: "", spec: "5kg", unit: "Thùng", category: "", variant: "")
            _ = try Ledger.insertDocument(db, kind: "delivery", date: "2026-11-02",
                                          lines: [LedgerLine(p, 3, unitPrice: 100_000, amount: 300_000)], code: "A001", codeNorm: "a001",
                                          customerId: cid)
            _ = try Ledger.insertDocument(db, kind: "delivery", date: "2026-11-09",
                                          lines: [LedgerLine(p, 2, unitPrice: 120_000, amount: 240_000)], code: "A002", codeNorm: "a002",
                                          customerId: cid)
            return cid
        }
        let all = try q.read { try Lookup.customerMoney($0, customerId: cid) }
        let part = try q.read { try Lookup.customerMoney($0, customerId: cid, start: "2026-11-05", end: "2026-11-30") }
        XCTAssertEqual([all.orders, part.orders], [2, 1])
        XCTAssertEqual(part.total, 240_000)
        let rows = try q.read { try Lookup.customerProducts($0, customerId: cid, start: "2026-11-05", end: nil) }
        XCTAssertEqual(rows.count, 1)
        XCTAssertEqual(rows[0]["total_qty"] as Double, 2)
        let none = try q.read { try Lookup.customerProducts($0, customerId: cid, start: "2026-12-01", end: nil) }
        XCTAssertTrue(none.isEmpty)
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("kh-\(UUID().uuidString).xlsx")
        defer { try? FileManager.default.removeItem(at: url) }
        try q.read { _ = try Report.exportCustomer($0, to: url, customerId: cid, start: "2026-11-05", end: nil, periodLabel: "05/11/2026 – ") }
        let orders = try Xlsx.read(url)[0].rows.map { $0.map { $0?.pythonText ?? "" } }
        XCTAssertEqual(orders.filter { $0.count > 1 && $0[1] == "A001" }.count, 0)
        XCTAssertEqual(orders.filter { $0.count > 1 && $0[1] == "A002" }.count, 2)
    }
}
