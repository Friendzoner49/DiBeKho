import CryptoKit
import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

/// The activity log sent to the cloud is anonymized exactly as the Python app does (Generated/GoldenLogs.swift,
/// tools/gen_logs.py), and the restore-from-cloud pieces that need no network: names, gzip, checks, the batch that
/// replaces the shared data, after_restore. ⚠ The real download / push against a Cloud is not tested here.
final class CloudRestoreTests: XCTestCase {
    func testTheLogIsAnonymizedAsPython() {
        let days = CloudLogs.anonymize(GoldenLogs.log)
        XCTAssertEqual(days.keys.sorted(), GoldenLogs.days.keys.sorted())
        for (day, text) in GoldenLogs.days {
            XCTAssertEqual(days[day], text, day)
        }
    }

    func testTheWindowTitlesAreThoseOfPython() {
        let titles = CloudLogs.appTitles.sorted { $0.unicodeScalars.lexicographicallyPrecedes($1.unicodeScalars) }
        XCTAssertEqual(titles.count, GoldenLogs.titleCount)
        let digest = Insecure.SHA1.hash(data: Data(titles.joined(separator: "\n").utf8)).map { String(format: "%02x", $0) }.joined()
        XCTAssertEqual(digest, GoldenLogs.titleHash)
    }

    /// builtin.json written by scripts/make_app.sh (core/cloud/builtin.py): both values or none
    func testTheBuiltInAddress() {
        let both = CloudBuiltin.parse(Data(#"{"url": " https://x.example.co ", "key": "pk"}"#.utf8))
        XCTAssertEqual(both?.0, "https://x.example.co")
        XCTAssertEqual(both?.1, "pk")
        XCTAssertNil(CloudBuiltin.parse(Data(#"{"url": "https://x.example.co", "key": ""}"#.utf8)))
        XCTAssertNil(CloudBuiltin.parse(Data("not json".utf8)))
        XCTAssertFalse(CloudBuiltin.has)  // the test bundle carries none
    }

    func testBackupNames() throws {
        let item = try XCTUnwrap(CloudBackup.parse("2026-11-11T09-30-00Z__MacBook-Air__s12.sqlite.gz", size: 2048))
        XCTAssertEqual(item.device, "MacBook-Air")
        XCTAssertEqual(item.schema, 12)
        XCTAssertEqual(item.size, 2048)
        XCTAssertEqual(item.at, Date(timeIntervalSince1970: 1_794_389_400))
        XCTAssertNotNil(CloudBackup.parse("2026-11-11T09-30-00Z__may__s9.sqlite"))
        XCTAssertNil(CloudBackup.parse("nhat-ky/may-1.log.gz"))
        XCTAssertNil(CloudBackup.parse("phieu-goc"))
    }

    func testGzipRoundTrip() throws {
        let data = Data((0..<50_000).map { UInt8(truncatingIfNeeded: $0 * 7 % 251) })
        XCTAssertEqual(try CloudBackup.gunzip(try CloudBackup.gzip(data)), data)
        var broken = try CloudBackup.gzip(data)
        broken[broken.count - 5] ^= 0xFF  // the CRC
        XCTAssertThrowsError(try CloudBackup.gunzip(broken))
        XCTAssertThrowsError(try CloudBackup.gunzip(Data("not gzip at all, long enough".utf8)))
    }

    func testGunzipReadsWhatPythonWrote() throws {
        let packed = try XCTUnwrap(Data(base64Encoded: GoldenLogs.sampleGz))
        let plain = try CloudBackup.gunzip(packed)
        XCTAssertEqual(SHA256.hash(data: plain).map { String(format: "%02x", $0) }.joined(), GoldenLogs.sampleSha256)
    }

    /// A backup as the Python app uploads it: unpacked, checked, then after_restore as from another machine.
    func testAPythonBackupRestores() throws {
        let dir = try folder()
        let path = dir.appendingPathComponent("kho.sqlite")
        try CloudBackup.gunzip(try XCTUnwrap(Data(base64Encoded: GoldenLogs.backupGz))).write(to: path)
        XCTAssertEqual(try CloudBackup.validate(path), GoldenLogs.backupSchema)
        let queue = try DatabaseQueue(path: path.path, configuration: Store.configuration())
        let other = try XCTUnwrap(CloudBackup.parse("2026-11-11T09-30-00Z__MayWindows__s\(GoldenLogs.backupSchema).sqlite.gz"))
        try queue.write { try CloudBackup.afterRestore($0, deviceName: "MacBook", other) }
        try queue.read { db in
            XCTAssertEqual(try String.fetchOne(db, sql: "SELECT name FROM customers"), "Khách Mẫu")
            XCTAssertEqual(try String.fetchOne(db, sql: "SELECT status FROM scanned_files"), "missing_ignored")
        }
        try queue.close()
    }

    private func folder() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("dibekho-restore-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }

    private func shop(at url: URL) throws -> DatabaseQueue {
        let queue = try DatabaseQueue(path: url.path, configuration: Store.configuration())
        try Schema.migrate(queue)
        try queue.write { db in
            for statement in Schema.split(Golden.shop) { try db.execute(sql: statement) }
            try Sync.ensureTriggers(db)
        }
        return queue
    }

    func testValidateTakesAShopAndRefusesTheRest() throws {
        let dir = try folder()
        let good = dir.appendingPathComponent("kho.sqlite")
        try shop(at: good).close()
        XCTAssertEqual(try CloudBackup.validate(good), Schema.supportedVersion)

        let junk = dir.appendingPathComponent("junk.sqlite")
        try Data("this is not a database at all".utf8).write(to: junk)
        XCTAssertThrowsError(try CloudBackup.validate(junk))

        let other = dir.appendingPathComponent("other.sqlite")
        let queue = try DatabaseQueue(path: other.path)
        try queue.write { try $0.execute(sql: "CREATE TABLE notes(x); PRAGMA user_version = 3") }
        try queue.close()
        XCTAssertThrowsError(try CloudBackup.validate(other)) { error in
            XCTAssertTrue("\(error.localizedDescription)".contains("không phải dữ liệu DiBeKho"))
        }

        let newer = dir.appendingPathComponent("newer.sqlite")
        let n = try shop(at: newer)
        try n.write { try $0.execute(sql: "PRAGMA user_version = \(Schema.supportedVersion + 1)") }
        try n.close()
        XCTAssertThrowsError(try CloudBackup.validate(newer)) { error in
            XCTAssertTrue(error.localizedDescription.contains("mới hơn"))
        }
    }

    func testTheBatchDeletesEveryLiveCloudRowFirst() throws {
        let products = try XCTUnwrap(SyncSchema.tables.first { $0.name == "products" })
        let meta = try XCTUnwrap(SyncSchema.tables.first { $0.name == "meta" })
        let pulled = Pulled(tables: [
            "products": [["id": .text("u-2"), "deleted": .bool(false)], ["id": .text("u-1"), "deleted": .bool(false)],
                         ["id": .text("u-gone"), "deleted": .bool(true)]],
            "meta": [["key": .text("shop_name"), "deleted": .bool(false)]],
        ], maxRev: 9)
        let rows: [String: [CloudRow]] = ["products": [["id": .text("u-1"), "name_vi": .text("Sơn"), "deleted": .bool(false)]]]
        let batch = CloudAdmin.buildBatch(rows, pulled: pulled)
        XCTAssertEqual(batch.keys.sorted(), SyncSchema.tables.map(\.name).sorted())
        let p = try XCTUnwrap(batch[products.name])
        XCTAssertEqual(p.count, 3)
        XCTAssertEqual(p[0], ["id": .text("u-1"), "deleted": .bool(true)])
        XCTAssertEqual(p[1], ["id": .text("u-2"), "deleted": .bool(true)])
        XCTAssertEqual(p[2]["name_vi"], .text("Sơn"))
        XCTAssertEqual(batch[meta.name], [["key": .text("shop_name"), "deleted": .bool(true)]])
    }

    func testNotReadyWhileChangesWait() throws {
        let queue = try shop(at: try folder().appendingPathComponent("kho.sqlite"))
        try queue.read { XCTAssertNoThrow(try CloudAdmin.checkReady($0)) }
        try queue.write { db in
            try TwoWay.startFromThisMachine(db)
            try db.execute(sql: "UPDATE products SET name_vi = name_vi || ' x' WHERE id = (SELECT MIN(id) FROM products)")
        }
        try queue.read { db in
            XCTAssertThrowsError(try CloudAdmin.checkReady(db)) { error in
                XCTAssertTrue(error.localizedDescription.contains("chưa gửi lên Cloud"))
            }
        }
    }

    func testAfterRestoreHidesTheNotesOfAnotherMachine() throws {
        let queue = try shop(at: try folder().appendingPathComponent("kho.sqlite"))
        try queue.write { db in
            try db.execute(sql: """
                INSERT INTO scanned_files(hash, rel_path, status) VALUES
                ('h1', 'phieu-giao-hang/a.xlsx', 'imported'), ('h2', 'phieu-giao-hang/b.xlsx', 'missing'),
                ('h3', 'phieu-giao-hang/c.xlsx', 'error')
                """)
        }
        let before = try queue.read { try Int.fetchOne($0, sql: "SELECT COUNT(*) FROM scanned_files WHERE status IN ('imported', 'missing')") ?? 0 }
        let other = try XCTUnwrap(CloudBackup.parse("2026-11-11T09-30-00Z__MayKhac__s12.sqlite.gz"))
        try queue.write { try CloudBackup.afterRestore($0, deviceName: "MacBook", other) }
        let after = try queue.read { try Int.fetchOne($0, sql: "SELECT COUNT(*) FROM scanned_files WHERE status IN ('imported', 'missing')") ?? 0 }
        XCTAssertEqual(after, 0)
        let hidden = try queue.read { try Int.fetchOne($0, sql: "SELECT COUNT(*) FROM scanned_files WHERE status = 'missing_ignored'") ?? 0 }
        XCTAssertEqual(before, 2)
        XCTAssertEqual(hidden, 2)
        let logged = try queue.read { try String.fetchOne($0, sql: "SELECT detail FROM app_log WHERE action = 'cloud_restore' ORDER BY id DESC LIMIT 1") }
        XCTAssertEqual(logged, other.name)
    }
}
