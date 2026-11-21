import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

/// The first start on a Mac without a work folder (core/workspace.py). ⚠ Swift-only (no golden). Never touches the real
/// ~/Library/Application Support/DiBeKho/config.json: every call gets a config file in a temporary folder.
final class FirstRunTests: XCTestCase {
    private var root: URL!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("dibekho-first-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: root) }

    func testCreatesTheFolderTheDatabaseAndTheConfig() throws {
        let folder = root.appendingPathComponent("DiBeKho")
        let config = root.appendingPathComponent("cfg/config.json")
        try FirstRun.create(folder: folder, language: "en", config: config)
        for sub in ["phieu-giao-hang/da-xu-ly", "input/da-xu-ly", "output", "sao-luu", "data", "phieu-goc"] {
            var isDirectory: ObjCBool = false
            XCTAssertTrue(FileManager.default.fileExists(atPath: folder.appendingPathComponent(sub).path, isDirectory: &isDirectory), sub)
            XCTAssertTrue(isDirectory.boolValue, sub)
        }
        let object = try JSONSerialization.jsonObject(with: Data(contentsOf: config)) as? [String: Any]
        XCTAssertEqual(object?["workspace"] as? String, folder.path)
        XCTAssertEqual(object?["language"] as? String, "en")
        XCTAssertEqual((object?["device_id"] as? String)?.count, 12)
        // the folder opens like any other
        let work = try WorkFolder(root: folder)
        XCTAssertEqual(try work.queue.read { try Int.fetchOne($0, sql: "SELECT COUNT(*) FROM products") }, 0)
        work.close()
    }

    func testNeverOverwritesAnExistingConfigOrDatabase() throws {
        let folder = root.appendingPathComponent("DiBeKho")
        let config = root.appendingPathComponent("config.json")
        try FirstRun.create(folder: folder, language: "vi", config: config)
        let before = try Data(contentsOf: config)
        XCTAssertThrowsError(try FirstRun.create(folder: root.appendingPathComponent("Other"), language: "zh", config: config))
        XCTAssertEqual(try Data(contentsOf: config), before)
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("Other").path))
        let second = root.appendingPathComponent("second.json")
        XCTAssertThrowsError(try FirstRun.create(folder: folder, language: "vi", config: second))
        XCTAssertFalse(FileManager.default.fileExists(atPath: second.path))
    }

    func testAStaleConfigWhoseFolderIsGoneIsSetAsideAndTheFirstStartGoesOn() throws {
        let config = root.appendingPathComponent("config.json")
        try Data(#"{"workspace": "\#(root.path)/gone"}"#.utf8).write(to: config)
        let folder = root.appendingPathComponent("DiBeKho")
        try FirstRun.create(folder: folder, language: "vi", config: config)
        XCTAssertTrue(FileManager.default.fileExists(atPath: root.appendingPathComponent("config.json.cu").path))
        let object = try JSONSerialization.jsonObject(with: Data(contentsOf: config)) as? [String: Any]
        XCTAssertEqual(object?["workspace"] as? String, folder.path)
    }

    func testChangingTheFolderKeepsTheOtherKeysAndMakesAnEmptyDatabase() throws {
        let config = root.appendingPathComponent("config.json")
        try FirstRun.create(folder: root.appendingPathComponent("Old"), language: "zh", config: config)
        let before = try JSONSerialization.jsonObject(with: Data(contentsOf: config)) as? [String: Any]
        let folder = root.appendingPathComponent("New")
        try FirstRun.changeWorkspace(to: folder, config: config)
        let after = try JSONSerialization.jsonObject(with: Data(contentsOf: config)) as? [String: Any]
        XCTAssertEqual(after?["workspace"] as? String, folder.path)
        XCTAssertEqual(after?["language"] as? String, "zh")
        XCTAssertEqual(after?["device_id"] as? String, before?["device_id"] as? String)
        let work = try WorkFolder(root: folder)
        XCTAssertEqual(try work.queue.read { try Int.fetchOne($0, sql: "SELECT COUNT(*) FROM products") }, 0)
        work.close()
        // a folder that has data keeps it
        let size = try FileManager.default.attributesOfItem(atPath: folder.appendingPathComponent("data/kho.sqlite").path)[.size] as? Int
        try FirstRun.changeWorkspace(to: folder, config: config)
        XCTAssertEqual(try FileManager.default.attributesOfItem(atPath: folder.appendingPathComponent("data/kho.sqlite").path)[.size] as? Int, size)
    }

    func testNamesTheSyncServicesToAvoid() {
        XCTAssertEqual(FirstRun.syncService(URL(fileURLWithPath: "/Users/a/OneDrive/DiBeKho")), "OneDrive")
        XCTAssertEqual(FirstRun.syncService(URL(fileURLWithPath: "/Users/a/Library/Mobile Documents/x")), "iCloud")
        XCTAssertNil(FirstRun.syncService(URL(fileURLWithPath: "/Users/a/Documents/DiBeKho")))
    }
}
