import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

/// 'Dữ liệu gốc' workbook (excel/master_data.py, catalog.import_master). Swift-only checks (⚠ not a golden file: Python's
/// behaviour was read, not replayed); the workbooks are written into a temporary folder and never committed.
final class MasterDataTests: XCTestCase {
    private var folder: URL!
    private let today = Dates.iso(Date())

    override func setUpWithError() throws {
        folder = FileManager.default.temporaryDirectory.appendingPathComponent("dibekho-master-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: folder) }

    private func database() throws -> DatabaseQueue {
        let q = try DatabaseQueue(configuration: Store.configuration())
        try Schema.migrate(q)
        return q
    }

    private func sheet(_ name: String, headers: [String], rows: [[XValue]], marker: String = "DIBEKHO – x") -> XSheet {
        var s = XSheet(name: name)
        s.put(1, 1, .text(marker))
        for (i, h) in headers.enumerated() { s.put(4, i + 1, .text(h)) }
        for (r, row) in rows.enumerated() { for (c, v) in row.enumerated() { s.put(5 + r, c + 1, v) } }
        return s
    }

    private let productHeaders = ["STT", "Mã", "Tên", "Tên Trung", "Quy cách", "Loại", "ĐV", "Nhóm", "Ngày", "Đang dùng"]
    private let customerHeaders = ["STT", "Tên", "SĐT", "Liên hệ", "Địa chỉ", "Số đơn", "MST", "Email"]

    private func product(_ n: Int, _ code: String, _ name: String, category: String = "") -> [XValue] {
        [.number(Double(n)), .text(code), .text(name), .text(""), .text(""), .text(""), .text("cái"), .text(category), .empty, .text("Có")]
    }

    private func write(products: [[XValue]], stockHeaders: [String], stock: [[XValue]], name: String = "file.xlsx") throws -> URL {
        let url = folder.appendingPathComponent(name)
        try XlsxWriter.write([sheet("p", headers: productHeaders, rows: products), sheet("c", headers: customerHeaders, rows: []),
                              sheet("s", headers: stockHeaders, rows: stock)], to: url)
        return url
    }

    func testExportReadsBackAndImportsIntoAnEmptyShop() throws {
        let a = try database()
        let (p1, p2) = try a.write { db -> (Int64, Int64) in
            let p1 = try Catalog.createProduct(db, nameVi: "Keo dán", nameZh: "胶", spec: "5kg", unit: "Thùng", category: "Keo", variant: "Trắng")
            let p2 = try Catalog.createProduct(db, nameVi: "Sơn", nameZh: "", spec: "18kg", unit: "Thùng", category: "", variant: "")
            try Catalog.updateProduct(db, id: p2, Catalog.ProductFields(active: false))
            try db.execute(sql: "INSERT INTO customers(name, contact, phone, phone_norm, address, tax_code, email) VALUES(?,?,?,?,?,?,?)",
                           arguments: ["Đại lý A", "Lan", "091 111 2222", "0911112222", "Hà Nội", "0101234567", "a@example.com"])
            try db.execute(sql: "INSERT INTO customers(name, phone, phone_norm) VALUES('Khách B', '', '')")
            try Ledger.stockCount(db, date: Dates.iso(Date()), counted: [Ledger.Counted(p1, nil, 12)], note: "")
            return (p1, p2)
        }
        _ = (p1, p2)
        let file = folder.appendingPathComponent("gốc.xlsx")
        _ = try a.read { try MasterData.export($0, to: file) }

        let data = try MasterData.read(file)
        XCTAssertEqual(data.products.map(\.code), ["SP001", "SP002"])
        XCTAssertEqual(data.products[0].nameZh, "胶")
        XCTAssertEqual(data.products[0].spec, "5kg")
        XCTAssertEqual(data.products[0].createdAt.count, 19)
        XCTAssertFalse(data.products[1].active)
        XCTAssertEqual(data.customers.map(\.name), ["Khách B", "Đại lý A"])  // by name, accents as written
        XCTAssertEqual(data.customers.first { $0.name == "Đại lý A" }?.taxCode, "0101234567")
        XCTAssertEqual(data.customers.first { $0.name == "Đại lý A" }?.email, "a@example.com")
        XCTAssertEqual(data.stock.count, 1)  // only the active product
        XCTAssertEqual(data.stock[0].stock, 12)
        XCTAssertEqual(data.stock[0].matchedBy, "code")
        XCTAssertFalse(MasterData.needsCheck(data.stock))

        let b = try database()
        let first = try b.write { try MasterData.importMaster($0, products: data.products, customers: data.customers, stock: data.stock, stockDate: self.today) }
        XCTAssertEqual([first.productsNew, first.productsUpdated, first.customersNew, first.customersUpdated, first.stockCounted], [2, 0, 2, 0, 1])
        let (levels, ids) = try b.read { db -> ([Int64: Double], [String: Int64]) in
            var ids: [String: Int64] = [:]
            for r in try Row.fetchAll(db, sql: "SELECT id, code FROM products") { ids[r["code"]] = r["id"] }
            return (try Ledger.levels(db), ids)
        }
        XCTAssertEqual(levels[ids["SP001"]!], 12)
        let activeFlags = try b.read { try Int.fetchAll($0, sql: "SELECT active FROM products ORDER BY code") }
        XCTAssertEqual(activeFlags, [1, 0])
        XCTAssertEqual(try b.read { try String.fetchOne($0, sql: "SELECT tax_code FROM customers WHERE name = 'Đại lý A'") }, "0101234567")

        let again = try b.write { try MasterData.importMaster($0, products: data.products, customers: data.customers, stock: data.stock, stockDate: self.today) }
        XCTAssertEqual([again.productsNew, again.productsUpdated, again.customersNew, again.customersUpdated], [0, 2, 0, 2])
        XCTAssertEqual(try b.read { try Int.fetchOne($0, sql: "SELECT COUNT(*) FROM products") }, 2)
        XCTAssertEqual(try b.read { try Ledger.levels($0) }[ids["SP001"]!], 12)  // a count sets the number, it does not add
    }

    func testRowsWithoutACodeAreMatchedByNameThenByLabels() throws {
        let url = try write(
            products: [product(1, "SP001", "Keo", category: "Xanh"), product(2, "SP002", "Keo", category: "Đỏ")],
            stockHeaders: ["Tên", "Nhóm", "Loại", "Tồn"],
            stock: [[.text("Keo"), .text("Đỏ"), .text(""), .number(5)], [.text("Keo"), .text("Xanh"), .text(""), .number(9)]])
        let data = try MasterData.read(url)
        XCTAssertEqual(data.stock.map(\.matchedBy), ["name", "name"])
        XCTAssertEqual(data.stock.map(\.productRow), [6, 5])  // Đỏ -> second product (row 6), Xanh -> first (row 5)
        XCTAssertTrue(MasterData.needsCheck(data.stock))
    }

    func testRowsWithChangedNamesFallBackToPosition() throws {
        let url = try write(
            products: [product(1, "SP001", "Sơn A"), product(2, "SP002", "Sơn B")],
            stockHeaders: ["Tên", "Nhóm", "Loại", "Tồn"],
            stock: [[.text("Khác 1"), .text(""), .text(""), .number(1)], [.text("Khác 2"), .text(""), .text(""), .number(2)]])
        let data = try MasterData.read(url)
        XCTAssertEqual(data.stock.map(\.matchedBy), ["position", "position"])
        XCTAssertEqual(data.stock.map(\.productRow), [5, 6])
        XCTAssertTrue(MasterData.stockDiffers(data.stock[0], data.products[0]))
    }

    func testACodeUsedTwiceInTheFileIsRenumberedAndAnExistingProductIsNotDuplicated() throws {
        let url = try write(products: [product(1, "SP001", "Keo"), product(2, "SP001", "Sơn"), product(3, "SP009", "Dây")],
                            stockHeaders: ["Mã", "Tên", "Nhóm", "Loại", "Tồn"], stock: [])
        let data = try MasterData.read(url)
        let q = try database()
        try q.write { _ = try Catalog.createProduct($0, nameVi: "Dây", nameZh: "", spec: "", unit: "cái", category: "", variant: "") }  // SP001
        let r = try q.write { try MasterData.importMaster($0, products: data.products, customers: [], stockDate: self.today) }
        // SP001 exists (updated to "Keo"), the second SP001 row is a new product with the next free code, "Dây" under SP009 is
        // the same item as the one already here but SP001 is in the file: it is kept as a new one
        XCTAssertEqual(r.productsUpdated, 1)
        XCTAssertEqual(r.renumbered.map { $0.row }, [6])
        XCTAssertEqual(try q.read { try String.fetchAll($0, sql: "SELECT code FROM products ORDER BY code") }.count, 3)
    }

    func testAnItemAlreadyHereUnderAnotherCodeIsSkipped() throws {
        let url = try write(products: [product(1, "SP009", "Dây")], stockHeaders: ["Mã", "Tên", "Nhóm", "Loại", "Tồn"], stock: [])
        let data = try MasterData.read(url)
        let q = try database()
        try q.write { _ = try Catalog.createProduct($0, nameVi: "Dây", nameZh: "", spec: "", unit: "cái", category: "", variant: "") }
        let r = try q.write { try MasterData.importMaster($0, products: data.products, customers: [], stockDate: self.today) }
        XCTAssertEqual(r.productsNew, 0)
        XCTAssertEqual(r.skipped.map { $0.existing }, ["SP001"])
    }

    func testAnotherWorkbookIsNotMasterData() throws {
        let url = folder.appendingPathComponent("other.xlsx")
        try XlsxWriter.write([sheet("a", headers: [], rows: [], marker: "Hello"), sheet("b", headers: [], rows: [], marker: "Hello")], to: url)
        XCTAssertThrowsError(try MasterData.read(url)) { XCTAssertTrue($0 is MasterData.NotMasterData) }
    }
}
