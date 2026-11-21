import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

/// core/catalog «Khôi phục mặt hàng đã xoá». Swift-only checks (⚠ not a golden file: Python's behaviour was read, not replayed).
final class RestoreProductsTests: XCTestCase {
    private var q: DatabaseQueue!
    private var folder: URL!

    override func setUpWithError() throws {
        q = try DatabaseQueue(configuration: Store.configuration())
        try Schema.migrate(q)
        folder = FileManager.default.temporaryDirectory.appendingPathComponent("dibekho-restore-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: folder) }

    func testADeletedProductIsFoundInABackupAndComesBackWithItsCode() throws {
        let id = try q.write { try Catalog.createProduct($0, nameVi: "Keo dán", nameZh: "胶", spec: "5kg", unit: "Thùng", category: "Keo", variant: "") }
        try q.write { try Catalog.setAlias($0, key: "keo dan|5kg", productId: id, label: "Keo dán 5kg") }
        _ = try Backups.named(q, folder: folder, label: "thu-cong")
        try q.write { try Catalog.deleteProduct($0, id: id) }

        let found = try q.read { try Catalog.deletedProducts($0, backups: folder) }
        XCTAssertEqual(found.map(\.code), ["SP001"])
        XCTAssertEqual(found.first?.nameVi, "Keo dán")
        XCTAssertEqual(found.first?.aliasKeys, ["keo dan|5kg"])

        let newId = try q.write { try Catalog.restoreProduct($0, found[0]) }
        let (code, name, freed) = try q.read { db in
            (try String.fetchOne(db, sql: "SELECT code FROM products WHERE id = ?", arguments: [newId]),
             try String.fetchOne(db, sql: "SELECT name_vi FROM products WHERE id = ?", arguments: [newId]),
             try Catalog.freedCodes(db))
        }
        XCTAssertEqual(code, "SP001")
        XCTAssertEqual(name, "Keo dán")
        XCTAssertFalse(freed.contains("SP001"))
        XCTAssertTrue(try q.read { try Catalog.deletedProducts($0, backups: folder) }.isEmpty)
    }

    func testACodeMergedAwayOnPurposeIsNotOffered() throws {
        let id = try q.write { try Catalog.createProduct($0, nameVi: "Sơn", nameZh: "", spec: "18kg", unit: "Thùng", category: "", variant: "") }
        _ = try Backups.named(q, folder: folder, label: "thu-cong")
        try q.write { db in
            try Catalog.deleteProduct(db, id: id)
            try Catalog.freeACode(db, "SP001")
        }
        XCTAssertTrue(try q.read { try Catalog.deletedProducts($0, backups: folder) }.isEmpty)
    }

    func testACopyMadeAfterTheDeleteIsOfferedForMerging() throws {
        let id = try q.write { try Catalog.createProduct($0, nameVi: "Băng keo", nameZh: "", spec: "10cm", unit: "Cuộn", category: "", variant: "") }
        _ = try Backups.named(q, folder: folder, label: "thu-cong")
        try q.write { try Catalog.deleteProduct($0, id: id) }
        // the same item typed again before anyone noticed: a delete never gives its code back, so it is SP002
        let copy = try q.write { try Catalog.createProduct($0, nameVi: "Băng keo", nameZh: "", spec: "10cm", unit: "Cuộn", category: "", variant: "") }
        let found = try q.read { try Catalog.deletedProducts($0, backups: folder) }
        XCTAssertEqual(found.map(\.code), ["SP001"])

        let newId = try q.write { try Catalog.restoreProduct($0, found[0]) }
        let result = try q.read { try Catalog.findMergeCandidates($0, newId: newId, found[0]) }
        XCTAssertEqual(result.candidates.map(\.id), [copy])
        XCTAssertEqual(result.aliasMatches, 0)
    }

    func testAnUnreadableBackupIsSkipped() throws {
        try Data("not a database".utf8).write(to: folder.appendingPathComponent("broken.sqlite"))
        XCTAssertTrue(try q.read { try Catalog.deletedProducts($0, backups: folder) }.isEmpty)
    }
}
