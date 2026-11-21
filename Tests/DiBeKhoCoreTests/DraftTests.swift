import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

/// Đơn nháp (customer's request 21/11/2026), as tests/test_issue_drafts.py: the issue note's file with NHÁP in the title
/// and its own code (N1, N2…) in output/phieu-xuat/nhap/; nothing recorded; read back into the window; once a real note
/// the draft goes to da-chot/; the scan never records a draft dropped into the notes folder.
final class DraftTests: XCTestCase {
    private var temp: URL!
    private var folders: ShopFolders!
    private var q: DatabaseQueue!
    private var fm: FileManager { .default }

    override func setUpWithError() throws {
        temp = fm.temporaryDirectory.appendingPathComponent("draft-\(UUID().uuidString)")
        folders = ShopFolders(root: temp.appendingPathComponent("work"))
        try fm.createDirectory(at: folders.deliveriesDone, withIntermediateDirectories: true)
        Deliveries.knownRate = { nil }
        q = try DatabaseQueue(configuration: Store.configuration())
        try Schema.migrate(q)
        try q.write { db in
            for statement in Schema.split(Golden.shop) { try db.execute(sql: statement) }
            try Meta.set(db, "freed_codes", "SP010,SP008")
            try Meta.set(db, "product_code_max", "4")
        }
    }

    override func tearDownWithError() throws { try? fm.removeItem(at: temp) }

    private func counts() throws -> [String] {
        try q.read { db in
            try ["documents", "products", "customers", "stock_movements"].map { table in
                "\(table)=\(try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM \(table)") ?? -1)"
            }
        }
    }

    private func draft(_ currency: String = "VND") -> Issues.Input {
        Issues.Input(date: "2026-11-20", customerName: "Công ty A", phone: "0900 000 001", contact: "Anh B",
                     address: "1 Đường X", taxCode: "0101234567", email: "a@example.com", lines: [
                         Issues.LineInput(productId: 1, qtyMain: 10, qtyOffice: 3, unitPrice: 6182.98, note: "giao sáng"),
                         Issues.LineInput(productId: 2, qtyMain: 2, unitPrice: nil),
                         Issues.LineInput(productId: nil, qtyOffice: 4, unitPrice: 9000,
                                          new: NewProduct("Băng keo mới", nameZh: "胶带", spec: "5cm"))],
                     currency: currency)
    }

    func testADraftRecordsNothingAndReadsBack() throws {
        let before = try counts()
        let url = try q.read { try Issues.saveDraft($0, folders, draft()) }
        XCTAssertEqual(try counts(), before)
        XCTAssertEqual(url.lastPathComponent, "PhieuXuat_NHAP_N1.xlsx")
        XCTAssertEqual(url.deletingLastPathComponent().lastPathComponent, Issues.drafts)
        let (code, back) = try q.read { try Issues.loadDraft($0, url) }
        XCTAssertEqual(code, "N1")
        XCTAssertEqual([back.date, back.customerName, back.phone, back.contact, back.address, back.taxCode, back.email],
                       ["2026-11-20", "Công ty A", "0900 000 001", "Anh B", "1 Đường X", "0101234567", "a@example.com"])
        XCTAssertEqual(back.lines.map { $0.productId }, [1, 2, nil])
        XCTAssertEqual(back.lines.map { $0.qtyMain }, [10, 2, 0])
        XCTAssertEqual(back.lines.map { $0.qtyOffice }, [3, 0, 4])
        XCTAssertEqual(back.lines.map { $0.unitPrice }, [6182.98, nil, 9000])
        XCTAssertEqual(back.lines[2].new?.nameVi, "Băng keo mới")
        XCTAssertEqual(back.lines[2].new?.nameZh, "胶带")
    }

    func testSavedAgainKeepsItsCodeAndNumbersGoOn() throws {
        let first = try q.read { try Issues.saveDraft($0, folders, draft()) }
        let second = try q.read { try Issues.saveDraft($0, folders, draft()) }
        XCTAssertEqual(second.lastPathComponent, "PhieuXuat_NHAP_N2.xlsx")
        var data = try q.read { try Issues.loadDraft($0, first) }.data
        data.lines[0].qtyMain = 1
        XCTAssertEqual(try q.read { try Issues.saveDraft($0, folders, data, over: first) }, first)
        XCTAssertEqual(try q.read { try Issues.loadDraft($0, first) }.data.lines[0].qtyMain, 1)
        try Issues.closeDraft(folders, first)
        XCTAssertFalse(fm.fileExists(atPath: first.path))
        XCTAssertEqual(Issues.newDraftCode(folders), "N3", "a closed draft's number is not reused")
    }

    func testAYuanDraftStaysInYuanAndBecomesARealNoteOnce() throws {
        let url = try q.read { try Issues.saveDraft($0, folders, draft("CNY")) }
        let data = try q.read { try Issues.loadDraft($0, url) }.data
        XCTAssertEqual(data.currency, "CNY")
        let (doc, _) = try q.write { try Issues.save($0, folders, data) }
        try Issues.closeDraft(folders, url)
        let row = try q.read { try Row.fetchOne($0, sql: "SELECT code, currency FROM documents WHERE id = ?", arguments: [doc])! }
        XCTAssertEqual(row["currency"] as String?, "CNY")
        XCTAssertTrue((row["code"] as String? ?? "").hasPrefix("A"))
        XCTAssertNotNil(try q.read { try Int64.fetchOne($0, sql: "SELECT id FROM products WHERE name_vi = 'Băng keo mới'") })
    }

    func testADraftDroppedIntoTheNotesFolderIsNeverRecorded() throws {
        let url = try q.read { try Issues.saveDraft($0, folders, draft()) }
        let before = try counts()
        try fm.copyItem(at: url, to: folders.deliveries.appendingPathComponent(url.lastPathComponent))
        _ = try Deliveries.scan(q, folders)
        let after = try counts()
        XCTAssertEqual(after.filter { !$0.hasPrefix("customers") }, before.filter { !$0.hasPrefix("customers") })
        let message = try q.read { try String.fetchOne($0, sql: "SELECT message FROM scanned_files WHERE status = 'error'") }
        XCTAssertEqual(message, Deliveries.draftRefused)
        XCTAssertTrue(IssueNote.isDraftTitle(IssueNote.titleDraft))
        XCTAssertFalse(IssueNote.isDraftTitle(IssueNote.title))
    }
}
