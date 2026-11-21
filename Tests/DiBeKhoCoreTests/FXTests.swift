import Foundation
import XCTest

@testable import DiBeKhoCore

/// The ₫ | ¥ switch (core/fx.py): provider answers, the cache file, and how amounts read in each mode.
/// Swift-only checks on made-up numbers (⚠ the money text in yuan mode is argued from reading the Python code).
final class FXTests: XCTestCase {
    private var savedLanguage = ""

    override func setUp() {
        savedLanguage = L10n.language
        FX.currency = "vnd"
        FX.rate = nil
    }

    override func tearDown() {
        FX.currency = "vnd"
        FX.rate = nil
        L10n.language = savedLanguage
    }

    private func rate(_ v: Double = 3600) -> FX.Rate {
        FX.Rate(vndPerCny: v, updated: Date(timeIntervalSince1970: 1_700_000_000), fetched: Date(timeIntervalSince1970: 1_700_000_100))
    }

    func testParseFXRatesAPI() throws {
        let json = #"{"success":true,"base":"CNY","timestamp":1700000000,"rates":{"VND":3512.5}}"#
        let r = try FX.parse(Data(json.utf8))
        XCTAssertEqual(r.vndPerCny, 3512.5)
        XCTAssertEqual(r.source, FX.source)
        XCTAssertEqual(r.updated, Date(timeIntervalSince1970: 1_700_000_000))
    }

    func testParseExchangeRateAPI() throws {
        let json = #"{"result":"success","base_code":"CNY","time_last_update_unix":1700000000,"rates":{"VND":3500}}"#
        let r = try FX.parse(Data(json.utf8))
        XCTAssertEqual(r.vndPerCny, 3500)
        XCTAssertEqual(r.source, FX.dailySource)
    }

    func testBadAnswersAreRefused() {
        for bad in ["", "[]", "{}", #"{"success":true,"base":"USD","rates":{"VND":1}}"#,
                    #"{"success":true,"base":"CNY","rates":{}}"#,
                    #"{"success":true,"base":"CNY","rates":{"VND":0}}"#,
                    #"{"success":true,"base":"CNY","rates":{"VND":true}}"#,
                    #"{"success":true,"base":"CNY","rates":{"VND":"3500"}}"#] {
            XCTAssertThrowsError(try FX.parse(Data(bad.utf8)), bad)
        }
    }

    func testCacheRoundTrip() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("fx-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: file) }
        XCTAssertNil(FX.cached(from: file))
        FX.save(rate(3601.5), to: file)
        let back = try XCTUnwrap(FX.cached(from: file))
        XCTAssertEqual(back.vndPerCny, 3601.5)
        XCTAssertEqual(back.updated.timeIntervalSince1970, 1_700_000_000, accuracy: 1)
        XCTAssertEqual(back.fetched.timeIntervalSince1970, 1_700_000_100, accuracy: 1)
        try "{not json".write(to: file, atomically: true, encoding: .utf8)
        XCTAssertNil(FX.cached(from: file))
    }

    func testFreshness() {
        let r = rate()
        XCTAssertTrue(FX.isFresh(r, now: r.fetched.addingTimeInterval(599)))
        XCTAssertFalse(FX.isFresh(r, now: r.fetched.addingTimeInterval(601)))
        XCTAssertFalse(FX.isFresh(nil))
    }

    func testYuanSeparatorsFollowTheLanguage() {
        L10n.language = "vi"
        XCTAssertEqual(Format.yuan(1234.5), "¥1.234,5")
        L10n.language = "en"
        XCTAssertEqual(Format.yuan(1234.5), "¥1,234.5")
    }

    func testDongMode() {
        L10n.language = "vi"
        XCTAssertEqual(Format.showMoney(3_600_000), "3.600.000")
        XCTAssertEqual(Format.showMoney(nil), "—")
        // switch on ¥ but no rate: still dong
        FX.currency = "cny"
        XCTAssertEqual(Format.showMoney(3_600_000), "3.600.000")
    }

    func testYuanMode() {
        L10n.language = "vi"
        FX.rate = rate(3600)
        FX.currency = "cny"
        XCTAssertEqual(Format.showMoney(3_600_000), "¥1.000")
        XCTAssertEqual(Format.money(7200, currency: "CNY", rate: 3500), "¥7.200", "no ≈ dong part in yuan mode")
        XCTAssertEqual(Format.both(3_600_000, 100, approx: 350_000), "¥1.100")
    }

    func testNotesInYuanShowDongApproxInDongMode() {
        L10n.language = "vi"
        XCTAssertEqual(Format.money(100, currency: "CNY", rate: 3500), "¥100 (≈ 350.000 ₫)")
        // note without its own rate: today's rate is used when known
        FX.rate = rate(3600)
        XCTAssertEqual(Format.money(100, currency: "CNY", rate: nil), "¥100 (≈ 360.000 ₫)")
        XCTAssertEqual(Format.both(1_000_000, 100, approx: 350_000), "1.000.000 ₫ + ¥100 (≈ 1.350.000 ₫)")
    }
}
