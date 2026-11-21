import Foundation
import GRDB
import XCTest
import ZIPFoundation

@testable import DiBeKhoCore

/// Phase 5b: the .dibekho package (core/transfer.py): export, read, replace-by-import, refusals. Swift-only check on
/// made-up data (⚠ not yet compared with a package made by the Python app).
final class TransferTests: XCTestCase {
    private var folder: URL!
    private var q: DatabaseQueue!
    private var shop: ShopFolders { ShopFolders(root: folder) }
    private let sha = String(repeating: "ab", count: 32)

    override func setUpWithError() throws {
        folder = FileManager.default.temporaryDirectory.appendingPathComponent("dibekho-transfer-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: shop.originals, withIntermediateDirectories: true)
        try "original".write(to: shop.originals.appendingPathComponent("\(sha).xlsx"), atomically: true, encoding: .utf8)
        try "lock".write(to: shop.originals.appendingPathComponent("~$\(sha).xlsx"), atomically: true, encoding: .utf8)
        q = try DatabaseQueue(configuration: Store.configuration())
        try Schema.migrate(q)
        try q.write { db in for statement in Schema.split(Golden.shop) { try db.execute(sql: statement) } }
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: folder) }

    private func count(_ queue: DatabaseQueue, _ table: String) throws -> Int {
        try queue.read { try Int.fetchOne($0, sql: "SELECT COUNT(*) FROM \(table)") ?? 0 }
    }

    func testExportThenImportIntoAnotherShop() throws {
        let docs = try count(q, "documents"), products = try count(q, "products")
        let file = try Transfer.exportPackage(q, shop, deviceName: "Máy 1", deviceId: "abc123")
        XCTAssertEqual(file.pathExtension, "dibekho")
        XCTAssertTrue(file.lastPathComponent.hasPrefix("DiBeKho_My1_") || file.lastPathComponent.hasPrefix("DiBeKho_Máy1_"), file.lastPathComponent)
        XCTAssertFalse(try q.read { try Transfer.hasUnsentChanges($0) })

        let manifest = try Transfer.readManifest(file)
        XCTAssertEqual(manifest.deviceName, "Máy 1")
        XCTAssertEqual(manifest.schemaVersion, Schema.supportedVersion)
        XCTAssertFalse(Transfer.isOlder(manifest))
        XCTAssertGreaterThan(manifest.products, 0)

        let archive = try Archive(url: file, accessMode: .read)
        XCTAssertNotNil(archive["phieu-goc/\(sha).xlsx"])
        XCTAssertNil(archive["phieu-goc/~$\(sha).xlsx"], "a lock file is not data")

        // another machine with other data
        let other = FileManager.default.temporaryDirectory.appendingPathComponent("dibekho-transfer-b-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: other) }
        let otherShop = ShopFolders(root: other)
        let q2 = try DatabaseQueue(configuration: Store.configuration())
        try Schema.migrate(q2)
        XCTAssertEqual(try count(q2, "documents"), 0)
        let got = try Transfer.importPackage(q2, otherShop, file)
        try q2.write { try Transfer.afterImport($0, got) }
        XCTAssertEqual(try count(q2, "documents"), docs)
        XCTAssertEqual(try count(q2, "products"), products)
        XCTAssertTrue(FileManager.default.fileExists(atPath: otherShop.originals.appendingPathComponent("\(sha).xlsx").path))
        XCTAssertEqual(try q2.read { try Meta.get($0, "last_import_from") }, "Máy 1 (\(manifest.exportedAt))")
        XCTAssertFalse(try q2.read { try Transfer.hasUnsentChanges($0) })
        XCTAssertEqual(try q2.read { try Schema.version($0) }, Schema.supportedVersion)

        let moved = try Transfer.moveToProcessed(otherShop, file)
        XCTAssertTrue(moved.path.contains("da-xu-ly"))
        XCTAssertFalse(FileManager.default.fileExists(atPath: file.path))
    }

    func testBrokenPackagesChangeNothing() throws {
        let bad = folder.appendingPathComponent("hong.dibekho")
        try "not a zip".write(to: bad, atomically: true, encoding: .utf8)
        XCTAssertThrowsError(try Transfer.importPackage(q, shop, bad))

        // a package whose database is empty: must not replace the data
        let empty = folder.appendingPathComponent("trong.dibekho")
        let archive = try Archive(url: empty, accessMode: .create)
        func add(_ path: String, _ data: Data) throws {
            try archive.addEntry(with: path, type: .file, uncompressedSize: Int64(data.count), compressionMethod: .deflate) {
                position, size in data.subdata(in: Data.Index(position)..<(Data.Index(position) + size))
            }
        }
        try add("manifest.json", Data(#"{"schema_version": \#(Schema.supportedVersion), "app_version": "0.6.2"}"#.utf8))
        try add("kho.sqlite", Data())
        let before = try count(q, "documents")
        XCTAssertThrowsError(try Transfer.importPackage(q, shop, empty))
        XCTAssertEqual(try count(q, "documents"), before)
    }

    func testNewerPackageIsRefused() throws {
        let file = folder.appendingPathComponent("moi.dibekho")
        let archive = try Archive(url: file, accessMode: .create)
        for (path, text) in [("manifest.json", #"{"schema_version": 999}"#), ("kho.sqlite", "x")] {
            let data = Data(text.utf8)
            try archive.addEntry(with: path, type: .file, uncompressedSize: Int64(data.count), compressionMethod: .deflate) {
                position, size in data.subdata(in: Data.Index(position)..<(Data.Index(position) + size))
            }
        }
        XCTAssertThrowsError(try Transfer.readManifest(file)) { XCTAssertTrue(($0 as? Transfer.TransferError)?.message.contains("mới hơn") == true) }
    }

    func testTrimOldKeepsRecentLinesWithTheirTraceback() {
        let today = Date()
        let old = Dates.iso(today.addingTimeInterval(-20 * 86400)), fresh = Dates.iso(today)
        let text = "\(old) 10:00:00 a x\n    old trace\n\(fresh) 10:00:00 b y\n    new trace"
        XCTAssertEqual(Transfer.trimOld(text, today: today), "\(fresh) 10:00:00 b y\n    new trace")
    }
}
