import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

/// The Statistics workbook (excel/report.py) and the multi-sheet writer. Swift-only checks on the made-up shop
/// (⚠ not compared cell by cell with a workbook made by the Python app; CI loads the file with openpyxl).
final class ReportTests: XCTestCase {
    private var q: DatabaseQueue!
    private var folder: URL!

    override func setUpWithError() throws {
        folder = FileManager.default.temporaryDirectory.appendingPathComponent("dibekho-report-\(UUID().uuidString)")
        q = try DatabaseQueue(configuration: Store.configuration())
        try Schema.migrate(q)
        try q.write { db in for statement in Schema.split(Golden.shop) { try db.execute(sql: statement) } }
        FX.currency = "vnd"
        FX.rate = nil
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: folder)
        FX.currency = "vnd"
        FX.rate = nil
    }

    func testTwoSheetsWithFillAndFrozenHeader() throws {
        var a = XSheet(name: "Một")
        var head = XStyle()
        head.bold = true
        head.fill = "DDEBF7"
        a.put(1, 1, .text("Tiêu đề"), head)
        a.put(2, 1, .number(1234.5))
        a.freeze = (2, 3)
        var b = XSheet(name: "Hai")
        b.put(1, 1, .text("Trang hai"))
        let file = folder.appendingPathComponent("hai.xlsx")
        try XlsxWriter.write([a, b], to: file)
        let sheets = try Xlsx.read(file)
        XCTAssertEqual(sheets.map(\.name), ["Một", "Hai"])
        XCTAssertEqual(sheets[0].rows[0][0], .text("Tiêu đề"))
        XCTAssertEqual(sheets[1].rows[0][0], .text("Trang hai"))
        let parts = XlsxWriter.build([a, b]).map(\.0)
        XCTAssertTrue(parts.contains("xl/worksheets/sheet2.xml"))
        let xml = XlsxWriter.build([a, b]).first { $0.0 == "xl/worksheets/sheet1.xml" }!.1
        XCTAssertTrue(xml.contains("state=\"frozen\""))
        XCTAssertTrue(xml.contains("topLeftCell=\"C2\""))
        let styles = XlsxWriter.build([a, b]).first { $0.0 == "xl/styles.xml" }!.1
        XCTAssertTrue(styles.contains("FFDDEBF7"))
    }

    func testStatisticsWorkbookHasTheChosenSheets() throws {
        let file = folder.appendingPathComponent("tk.xlsx")
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        try q.read { db in
            try Report.export(db, to: file, start: "2000-01-01", end: "2100-12-31",
                              sheets: Set(Report.sheetKeys), periodLabel: "2026", scopeLabel: "Mặt hàng: Tất cả", now: now)
        }
        let sheets = try Xlsx.read(file)
        XCTAssertEqual(sheets.map(\.name), [t("sheet.summary"), t("sheet.details"), t("sheet.customers"), t("sheet.top")])
        for sheet in sheets {
            XCTAssertEqual(sheet.rows[0][0], .text(t("report.period", ["period": "2026"])), sheet.name)
            XCTAssertEqual(sheet.rows[1][0], .text(t("report.scope", ["scope": "Mặt hàng: Tất cả"])), sheet.name)
        }
        XCTAssertEqual(sheets[0].rows[5][0], .text(t("col.code")))  // 4 info lines, a blank row, then the header
        // the summary has one line per product of the shop
        let products = try q.read { try Int.fetchOne($0, sql: "SELECT COUNT(*) FROM products WHERE active = 1") ?? 0 }
        XCTAssertGreaterThanOrEqual(sheets[0].rows.count - 5, products)
    }

    /// A scope and «Chia theo» (report._summary): a group gives no fees in the money line; chosen customers drop the
    /// opening / closing columns; a month split adds 'Nhập 10/2026', 'Xuất 10/2026'…
    func testScopedWorkbookFollowsTheWindow() throws {
        let file = folder.appendingPathComponent("pham-vi.xlsx")
        try q.read { db in
            try Report.export(db, to: file, start: "2026-10-01", end: "2026-11-30", filters: Stats.Filters(categories: ["Keo"]),
                              by: "month", sheets: ["summary"], periodLabel: "x", scopeLabel: "y")
        }
        var summary = try Xlsx.read(file)[0]
        guard case let .text(money) = summary.rows[2][0] else { return XCTFail("no money line") }
        let m = try q.read { try Stats.money($0, start: "2026-10-01", end: "2026-11-30", filters: Stats.Filters(categories: ["Keo"])) }
        XCTAssertNil(m.fees, "fees belong to no product")
        XCTAssertEqual(money, Report.moneyLine(m))
        XCTAssertFalse(money.contains("{"), money)
        let header = summary.rows[5].compactMap { cell -> String? in if case let .text(s) = cell { return s } else { return nil } }
        XCTAssertTrue(header.contains(t("col.opening")))
        XCTAssertTrue(header.contains("\(t("col.in")) 10/2026"))
        XCTAssertTrue(header.contains("\(t("col.out")) 11/2026"))
        XCTAssertEqual(summary.rows.count - 6, 1, "only the products of the group Keo (SP002; SP004 is inactive and unmoved)")
        try q.read { db in
            try Report.export(db, to: file, start: "2026-10-01", end: "2026-11-30", filters: Stats.Filters(customerIds: [1]),
                              sheets: ["summary"], periodLabel: "x", scopeLabel: "y")
        }
        summary = try Xlsx.read(file)[0]
        let customerHeader = summary.rows[5].compactMap { cell -> String? in if case let .text(s) = cell { return s } else { return nil } }
        XCTAssertFalse(customerHeader.contains(t("col.opening")))
        XCTAssertFalse(customerHeader.contains(t("col.closing")))
    }

    func testOnlyTheChosenSheetsAndNoneIsRefused() throws {
        let file = folder.appendingPathComponent("top.xlsx")
        try q.read { db in
            try Report.export(db, to: file, start: "2000-01-01", end: "2100-12-31", sheets: ["top"], periodLabel: "x", scopeLabel: "y")
        }
        XCTAssertEqual(try Xlsx.read(file).map(\.name), [t("sheet.top")])
        XCTAssertThrowsError(try q.read { db in
            try Report.export(db, to: file, start: "2000-01-01", end: "2100-12-31", sheets: [], periodLabel: "x", scopeLabel: "y")
        })
    }

    func testFilesStayInDongWhateverTheScreenShows() throws {
        FX.rate = FX.Rate(vndPerCny: 3600, updated: Date(), fetched: Date())
        FX.currency = "cny"
        XCTAssertEqual(Report.both(1_000_000, 100, 350_000), "1.000.000 ₫ + ¥100 (≈ 1.350.000 ₫)")
        XCTAssertEqual(Report.both(1_000_000, nil), "1.000.000")
        XCTAssertEqual(Report.both(nil, 100.5), "¥100,5")
        L10n.language = "en"
        defer { L10n.language = "vi" }
        XCTAssertEqual(Report.both(nil, 1234.5), "¥1.234,5", "Vietnamese separators in the files")
    }

    func testFileName() {
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let name = Report.fileName(label: "Q4/2026", now: now)
        XCTAssertTrue(name.hasPrefix("ThongKe_Q4-2026_"), name)
        XCTAssertTrue(name.hasSuffix(".xlsx"))
    }
}
