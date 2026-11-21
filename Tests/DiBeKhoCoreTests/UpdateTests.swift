import XCTest

@testable import DiBeKhoCore

/// The choice of the release to offer (core/update.py pick / is_newer). ⚠ Swift-only (no golden), no network.
final class UpdateTests: XCTestCase {
    func testVersionOrder() {
        XCTAssertTrue(Update.isNewer("v0.6.3", than: "0.6.2"))
        XCTAssertTrue(Update.isNewer("0.10.0", than: "0.9.9"))
        XCTAssertTrue(Update.isNewer("1.0", than: "0.9.9"))
        XCTAssertFalse(Update.isNewer("0.6.2", than: "0.6.2"))
        XCTAssertFalse(Update.isNewer("0.6.2.0", than: "0.6.2"))
        XCTAssertFalse(Update.isNewer("0.6.1", than: "0.6.2"))
        XCTAssertFalse(Update.isNewer("latest", than: "0.6.2"))
        XCTAssertNil(Update.parseVersion("v1.2.x"))
    }

    private func release(tag: String = "v0.7.0", draft: Bool = false, pre: Bool = false, name: String = Update.assetName,
                         state: String = "uploaded", size: Int = 1000, digest: String? = "sha256:ABCDEF") -> [String: Any] {
        var asset: [String: Any] = ["name": name, "state": state, "size": size, "browser_download_url": "https://example.invalid/f.dmg"]
        if let digest { asset["digest"] = digest }
        return ["tag_name": tag, "draft": draft, "prerelease": pre, "body": "notes", "assets": [asset]]
    }

    func testOffersOnlyANewerFinishedRelease() {
        let offered = Update.pick(release(), local: "0.6.2")
        XCTAssertEqual(offered?.version, "0.7.0")
        XCTAssertEqual(offered?.sha256, "abcdef")
        XCTAssertEqual(offered?.size, 1000)
        XCTAssertNil(Update.pick(release(), local: "0.7.0"))
        XCTAssertNil(Update.pick(release(draft: true), local: "0.6.2"))
        XCTAssertNil(Update.pick(release(pre: true), local: "0.6.2"))
        XCTAssertNil(Update.pick(release(name: "other.dmg"), local: "0.6.2"))
        XCTAssertNil(Update.pick(release(state: "starter"), local: "0.6.2"))
        XCTAssertNil(Update.pick(release(size: 0), local: "0.6.2"))
        XCTAssertEqual(Update.pick(release(digest: nil), local: "0.6.2")?.sha256, "")
        XCTAssertNil(Update.pick("not a release", local: "0.6.2"))
    }

    func testAHalfFileIsNotTheAnnouncedOne() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("dibekho-upd-\(UUID().uuidString)")
        try Data("hello".utf8).write(to: file)
        defer { try? FileManager.default.removeItem(at: file) }
        var rel = Update.pick(release(digest: "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"), local: "0.6.2")!
        XCTAssertTrue(Update.digestOK(file, rel))  // sha256("hello")
        rel.sha256 = "00"
        XCTAssertFalse(Update.digestOK(file, rel))
        rel.sha256 = ""
        XCTAssertTrue(Update.digestOK(file, rel))
    }
}
