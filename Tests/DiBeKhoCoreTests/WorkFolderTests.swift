import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

/// The shared lock (data/dibekho.lock, as Qt's QLockFile in the Python app) and opening the shop's work folder.
final class WorkFolderTests: XCTestCase {
    private var temp: URL!

    override func setUpWithError() throws {
        temp = FileManager.default.temporaryDirectory.appendingPathComponent("wf-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: temp.appendingPathComponent("data"), withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        ActivityLog.file = nil
        try? FileManager.default.removeItem(at: temp)
    }

    private var lockURL: URL { temp.appendingPathComponent("data/dibekho.lock") }

    func testTheLockIsWrittenAsQtWritesIt() throws {
        let lock = try XCTUnwrap(LockFile.acquire(lockURL))
        let text = try String(contentsOf: lockURL, encoding: .utf8)
        let lines = text.components(separatedBy: "\n")
        XCTAssertEqual(lines.count, 6, text)  // 5 lines, each ended by \n (Qt 6.10, checked against a real QLockFile)
        XCTAssertEqual(Int32(lines[0]), getpid())
        XCTAssertFalse(lines[1].isEmpty)
        XCTAssertEqual(lines[2], LockInfo.hostName())
        XCTAssertEqual(lines[5], "")
        XCTAssertNil(LockFile.acquire(lockURL), "a second copy must not open the same data")
        lock.release()
        XCTAssertFalse(FileManager.default.fileExists(atPath: lockURL.path))
        XCTAssertNotNil(LockFile.acquire(lockURL))
    }

    func testALockLeftByAGoneCopyOrAnotherComputerIsTakenOver() throws {
        var gone = LockInfo.mine()
        gone.pid = 99_999  // no such process
        try gone.contents.write(to: lockURL, atomically: true, encoding: .utf8)
        XCTAssertNotNil(LockFile.acquire(lockURL)?.release())

        var other = LockInfo.mine()
        other.host = "another-mac"
        try other.contents.write(to: lockURL, atomically: true, encoding: .utf8)
        XCTAssertNotNil(LockFile.acquire(lockURL)?.release())

        // the Python app on this Mac, still running (this very process stands for it)
        try LockInfo.mine().contents.write(to: lockURL, atomically: true, encoding: .utf8)
        XCTAssertNil(LockFile.acquire(lockURL))
        // the Python app written by Qt on Windows (empty boot id) parses too
        XCTAssertEqual(LockInfo.parse("31052\npython\nPC\n02dda034\n\n")?.pid, 31052)
    }

    func testOpeningTheWorkFolderLocksItAndBacksItUp() throws {
        let db = try DatabaseQueue(path: temp.appendingPathComponent("data/kho.sqlite").path, configuration: Store.configuration())
        try Schema.migrate(db)
        try db.write { d in for s in Schema.split(Golden.shop) { try d.execute(sql: s) } }
        try db.close()

        let folder = try WorkFolder(root: temp)
        XCTAssertTrue(FileManager.default.fileExists(atPath: lockURL.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: temp.appendingPathComponent("sao-luu/DiBeKho_\(Dates.today).sqlite").path))
        XCTAssertThrowsError(try WorkFolder(root: temp)) { error in
            XCTAssertEqual(error.localizedDescription, L10n.t("app.already_running"))
        }
        _ = try folder.queue.write { try Ledger.trialUse($0, date: "2026-11-15", locationId: 1, lines: [LedgerLine(1, 1)]) }
        let triggers = try folder.queue.read { try Int.fetchOne($0, sql: "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger'") }
        XCTAssertEqual(triggers, SyncTriggers.statements.count)
        folder.close()
        XCTAssertFalse(FileManager.default.fileExists(atPath: lockURL.path))
        XCTAssertNoThrow(try WorkFolder(root: temp).close())
        XCTAssertThrowsError(try WorkFolder(root: temp.appendingPathComponent("nothing")))
    }

    func testBackupsKeepTenAndTheNewestThree() throws {
        let folder = temp.appendingPathComponent("sao-luu")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        for i in 0..<14 {
            let f = folder.appendingPathComponent("DiBeKho_2026-10-\(String(format: "%02d", i + 1)).sqlite")
            try Data().write(to: f)
            let age = Date().addingTimeInterval(Double(-i) * 86400 * (i < 5 ? 1 : 10))
            try FileManager.default.setAttributes([.modificationDate: age], ofItemAtPath: f.path)
        }
        Backups.prune(folder)
        let left = try FileManager.default.contentsOfDirectory(atPath: folder.path).count
        XCTAssertLessThanOrEqual(left, 10)
        XCTAssertGreaterThanOrEqual(left, 3)
    }
}
