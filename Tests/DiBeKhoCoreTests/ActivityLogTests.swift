import Foundation
import XCTest

@testable import DiBeKhoCore

/// core/activity.py: line format, the 1 MB cap, the 7-day trim, other machines' logs. Swift-only checks
/// (⚠ the Python app's own tests are the reference, not a golden file).
final class ActivityLogTests: XCTestCase {
    private var folder: URL!

    override func setUpWithError() throws {
        folder = FileManager.default.temporaryDirectory.appendingPathComponent("dibekho-log-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        ActivityLog.file = nil
        try? FileManager.default.removeItem(at: folder)
    }

    private func day(_ text: String) -> Date {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd HH:mm"
        return f.date(from: text + " 12:00")!
    }

    func testLineFormatAndIndentedContinuation() {
        let line = ActivityLog.format("click", "Lưu phiếu\r\nbước hai\n", now: day("2026-10-17"))
        XCTAssertEqual(line, "2026-10-17 12:00:00 [click] Lưu phiếu\n    bước hai\n")
    }

    func testWriteAppendsAndClearEmpties() throws {
        let file = folder.appendingPathComponent("app.log")
        ActivityLog.setup(file)
        ActivityLog.write("a", "một")
        ActivityLog.write("b", "hai")
        let lines = ActivityLog.read().split(separator: "\n")
        XCTAssertEqual(lines.count, 2)
        XCTAssertTrue(lines[0].hasSuffix("[a] một"))
        ActivityLog.clear()
        XCTAssertEqual(ActivityLog.read(), "")
    }

    func testTrimOldDropsWeekOldLinesAndTheirTraceback() throws {
        let file = folder.appendingPathComponent("app.log")
        let text = """
        2026-11-01 08:00:00 [old] cũ
            dòng nối của cũ
        2026-11-12 08:00:00 [edge] đủ mới
        2026-11-18 09:00:00 [new] mới
            dòng nối
        """
        try text.write(to: file, atomically: true, encoding: .utf8)
        ActivityLog.trimOld(file, today: day("2026-11-19"))
        let kept = ActivityLog.read(file)
        XCTAssertFalse(kept.contains("[old]"))
        XCTAssertFalse(kept.contains("dòng nối của cũ"))
        XCTAssertTrue(kept.contains("[edge]"), "exactly 7 days old stays")
        XCTAssertTrue(kept.contains("dòng nối"))
    }

    func testTrimOldDropsEverythingWhenAllAreOld() throws {
        let file = folder.appendingPathComponent("app.log")
        try "2026-01-01 00:00:00 [x] y\n".write(to: file, atomically: true, encoding: .utf8)
        ActivityLog.trimOld(file, today: day("2026-11-19"))
        XCTAssertEqual(ActivityLog.read(file).trimmingCharacters(in: .whitespacesAndNewlines), "")
    }

    func testTheFileNeverGrowsPastTheCap() throws {
        let file = folder.appendingPathComponent("app.log")
        var big = ""
        let line = "2026-11-19 10:00:00 [fill] " + String(repeating: "đ", count: 90) + "\n"
        while big.utf8.count < ActivityLog.maxBytes - 500 { big += line }
        try big.write(to: file, atomically: true, encoding: .utf8)
        ActivityLog.file = file
        for i in 0..<20 { ActivityLog.write("last", "dòng \(i)") }
        let size = try FileManager.default.attributesOfItem(atPath: file.path)[.size] as! Int
        XCTAssertLessThanOrEqual(size, ActivityLog.maxBytes)
        XCTAssertLessThan(size, ActivityLog.keepBytes + 2000, "cut down to about the newest 720 KB")
        let text = ActivityLog.read(file)
        XCTAssertTrue(text.hasSuffix("[last] dòng 19\n"))
        XCTAssertTrue(text.hasPrefix("2026-"), "starts at a whole line")
    }

    func testOtherMachinesLogs() throws {
        for name in ["nhat-ky-May-B.log", "nhat-ky-May-A.log", "app.log", "nhat-ky-x.txt"] {
            try Data().write(to: folder.appendingPathComponent(name))
        }
        let names = ActivityLog.otherDevices(dataFolder: folder).map(\.lastPathComponent)
        XCTAssertEqual(names, ["nhat-ky-May-A.log", "nhat-ky-May-B.log"])
    }
}
