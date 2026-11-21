import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

/// Phase 5b: reset the stock, reset everything, restore a backup (core/reset.py, core/backup.restore). A backup is
/// always taken first.
final class ResetTests: XCTestCase {
    private var folder: URL!
    private var q: DatabaseQueue!
    private var shop: ShopFolders { ShopFolders(root: folder) }
    private var backups: URL { folder.appendingPathComponent("sao-luu") }

    override func setUpWithError() throws {
        folder = FileManager.default.temporaryDirectory.appendingPathComponent("dibekho-reset-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: shop.deliveriesDone.appendingPathComponent("sub"), withIntermediateDirectories: true)
        try "a".write(to: shop.deliveriesDone.appendingPathComponent("a.xlsx"), atomically: true, encoding: .utf8)
        try "b".write(to: shop.deliveriesDone.appendingPathComponent("sub/b.xlsx"), atomically: true, encoding: .utf8)
        try "c".write(to: shop.deliveries.appendingPathComponent("a.xlsx"), atomically: true, encoding: .utf8)
        try FileManager.default.createDirectory(at: shop.originals, withIntermediateDirectories: true)
        try "o".write(to: shop.originals.appendingPathComponent("o.xlsx"), atomically: true, encoding: .utf8)
        q = try DatabaseQueue(configuration: Store.configuration())
        try Schema.migrate(q)
        try q.write { db in for statement in Schema.split(Golden.shop) { try db.execute(sql: statement) } }
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: folder) }

    private func count(_ table: String) throws -> Int {
        try q.read { try Int.fetchOne($0, sql: "SELECT COUNT(*) FROM \(table)") ?? 0 }
    }

    func testResetStockKeepsCatalogAndMovesNotesBack() throws {
        XCTAssertGreaterThan(try count("documents"), 0)
        let products = try count("products")
        let moved = try Reset.resetStock(q, shop, backups: backups)
        XCTAssertEqual(moved, 2)
        for t in ["documents", "document_lines", "stock_movements", "customers", "scanned_files"] { XCTAssertEqual(try count(t), 0, t) }
        XCTAssertEqual(try count("products"), products)
        XCTAssertTrue(FileManager.default.fileExists(atPath: shop.deliveries.appendingPathComponent("a (2).xlsx").path), "the name is taken: the moved one gets (2)")
        XCTAssertTrue(FileManager.default.fileExists(atPath: shop.deliveries.appendingPathComponent("sub/b.xlsx").path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: shop.originals.appendingPathComponent("o.xlsx").path), "originals are kept")
        XCTAssertEqual(Reset.backupsList(backups).count, 1)
        XCTAssertTrue(Reset.backupsList(backups)[0].lastPathComponent.hasPrefix("truoc-dat-lai-ton_"))
    }

    func testResetAllThenRestoreTheBackup() throws {
        let docs = try count("documents"), products = try count("products")
        try Reset.resetAll(q, shop, backups: backups)
        for t in ["documents", "products", "customers"] { XCTAssertEqual(try count(t), 0, t) }
        XCTAssertFalse(FileManager.default.fileExists(atPath: shop.originals.appendingPathComponent("o.xlsx").path))
        let backup = try XCTUnwrap(Reset.backupsList(backups).first)
        XCTAssertTrue(backup.lastPathComponent.hasPrefix("truoc-xoa-toan-bo_"))
        try Reset.restore(q, from: backup)
        XCTAssertEqual(try count("documents"), docs)
        XCTAssertEqual(try count("products"), products)
    }
}
