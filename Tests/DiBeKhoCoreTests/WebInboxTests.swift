import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

/// core/cloud/inbox.py on the made-up shop: the checks and their texts, receipt and count approval, the link
/// request -> document. ⚠ Swift-only (no golden); the network half (fetch, file download, confirm) is not run here.
final class WebInboxTests: XCTestCase {
    private var q: DatabaseQueue!
    private var root: URL!

    override func setUpWithError() throws {
        q = try DatabaseQueue(configuration: Store.configuration())
        try Schema.migrate(q)
        try q.write { db in
            for statement in Schema.split(Golden.shop) { try db.execute(sql: statement) }
            try Sync.ensureTriggers(db)
        }
        root = FileManager.default.temporaryDirectory.appendingPathComponent("dibekho-web-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: root) }

    private func request(_ kind: String, _ payload: [String: Any], id: String = "11111111-2222-3333-4444-555555555555") -> WebRequest {
        WebRequest(["id": id, "kind": kind, "created_at": "2026-11-20T12:00:00Z", "created_by": "u1", "payload": payload])!
    }

    private func errors(_ payload: [String: Any]) throws -> [String] {
        try q.read { try WebInbox.receiptInput($0, payload).1 }
    }

    func testReceiptChecksUseThePythonTexts() throws {
        let line: [String: Any] = ["product_id": 1, "code": "SP001", "qty": 5]
        XCTAssertEqual(try errors(["doc_date": "2026-11-20", "lines": [line]]), [])
        XCTAssertEqual(try errors(["doc_date": "2026-13-40", "lines": [line]]), ["Ngày không hợp lệ."])
        XCTAssertEqual(try errors(["doc_date": "2026-11-20", "lines": [["product_id": 99, "qty": 1]]]),
                       ["Mặt hàng #99 không còn trong danh mục (đã xoá hoặc gộp).", "Phiếu không có dòng hàng nào dùng được."])
        XCTAssertEqual(try errors(["doc_date": "2026-11-20", "lines": [["product_id": 1, "code": "SP002", "qty": 1]]]),
                       ["Mặt hàng SP002 đã thay đổi trên máy chính (có thể đã Hoàn tác). Hãy tải lại trang web.",
                        "Phiếu không có dòng hàng nào dùng được."])
        XCTAssertEqual(try errors(["doc_date": "2026-11-20", "lines": [["product_id": 1, "qty": 0]]]),
                       ["Số lượng của SP001 phải lớn hơn 0.", "Phiếu không có dòng hàng nào dùng được."])
        XCTAssertEqual(try errors(["doc_date": "2026-11-20", "lines": [["product_id": "x", "qty": 1]]]),
                       ["Có dòng hàng không đọc được.", "Phiếu không có dòng hàng nào dùng được."])
        XCTAssertEqual(try errors(["doc_date": "2026-11-20", "source": "return", "lines": [line]]),
                       ["Hãy chọn khách hàng trả lại hàng."])
        XCTAssertEqual(try errors(["doc_date": "2026-11-20", "source": "return", "customer_id": 77, "lines": [line]]),
                       ["Khách hàng không còn trong danh sách (có thể đã gộp).", "Hãy chọn khách hàng trả lại hàng."])
    }

    func testApprovingAReceiptRecordsItAndRemembersTheRequest() throws {
        let folders = ShopFolders(root: root)
        let before = try q.read { try Ledger.levels($0)[1] ?? 0 }
        let item = request(WebInbox.receipt, ["doc_date": "2026-11-20", "supplier_name": "Công ty mẹ",
                                              "lines": [["product_id": 1, "code": "SP001", "qty": 5]]])
        let (doc, _) = try WebInbox.applyReceipt(q, folders, item)
        let (after, map, kind) = try q.read { db in
            (try Ledger.levels(db)[1] ?? 0, try WebInbox.appliedMap(db),
             try String.fetchOne(db, sql: "SELECT kind FROM documents WHERE id = ?", arguments: [doc]))
        }
        XCTAssertEqual(after - before, 5, accuracy: 1e-9)
        XCTAssertEqual(map[item.id], doc)
        XCTAssertEqual(kind, "receipt")
        // a request that cannot be applied changes nothing
        let bad = request(WebInbox.receipt, ["doc_date": "2026-11-20", "lines": [["product_id": 99, "qty": 1]]], id: "bad")
        XCTAssertThrowsError(try WebInbox.applyReceipt(q, folders, bad))
        XCTAssertEqual(try q.read { try WebInbox.appliedMap($0).count }, 1)
    }

    func testApprovingACountIsStampedWithTheMomentItWasSent() throws {
        let item = request(WebInbox.stockCount, ["count_date": "2026-11-20", "location_id": 1, "note": "Cuối ngày",
                                                 "lines": [["product_id": 2, "code": "SP002", "qty": 7]]])
        var named = item
        named.sender = "Lan"
        let doc = try WebInbox.applyCount(q, named)
        let (note, created, map) = try q.read { db -> (String, String, [String: Int64]) in
            let row = try Row.fetchOne(db, sql: "SELECT note, created_at FROM documents WHERE id = ?", arguments: [doc])
            return (row?["note"] ?? "", row?["created_at"] ?? "", try WebInbox.appliedMap(db))
        }
        XCTAssertEqual(note, "Kiểm kê từ web (Lan). Cuối ngày")
        XCTAssertEqual(created, WebInbox.stamp(item.sentAt))
        XCTAssertEqual(map[item.id], doc)
    }

    func testCountChecks() throws {
        func problems(_ payload: [String: Any]) throws -> [String] {
            try q.read { try WebInbox.checkCount($0, request(WebInbox.stockCount, payload)).3 }
        }
        let line: [String: Any] = ["product_id": 2, "qty": 3]
        XCTAssertEqual(try problems(["count_date": "2026-11-20", "location_id": 1, "lines": [line]]), [])
        XCTAssertEqual(try problems(["count_date": "2026-12-31", "location_id": 1, "lines": [line]]), ["Ngày kiểm kê ở tương lai."])
        XCTAssertEqual(try problems(["count_date": "2026-11-20", "location_id": 9, "lines": [line]]), ["Nơi kiểm kê không hợp lệ."])
        XCTAssertEqual(try problems(["count_date": "2026-11-20", "location_id": 1, "lines": [line, line]]),
                       ["Mặt hàng SP002 xuất hiện hai lần."])
        XCTAssertEqual(try problems(["count_date": "2026-11-20", "location_id": 1, "lines": [["product_id": 2, "qty": -1]]]),
                       ["Số đếm của SP002 không được âm.", "Phiếu kiểm kê không có dòng nào dùng được."])
    }

    func testDeliveryFileChecksAndNames() throws {
        let ok: [String: Any] = ["file_path": "11111111-2222-3333-4444-555555555555/a.xlsx", "file_name": "a.xlsx", "size": 1000,
                                 "sha256": String(repeating: "a", count: 64)]
        XCTAssertEqual(WebInbox.checkDelivery(request(WebInbox.deliveryFile, ok)), [])
        var bad = ok
        bad["file_path"] = "../x.xlsx"
        bad["file_name"] = "a.pdf"
        bad["size"] = 3_000_000
        bad["sha256"] = "zz"
        XCTAssertEqual(WebInbox.checkDelivery(request(WebInbox.deliveryFile, bad)), [
            "Đường dẫn file trên Cloud không hợp lệ.", "Chỉ nhận file Excel .xlsx.",
            "Kích thước file không hợp lệ (tối đa 2 MB).", "Mã kiểm tra của file không hợp lệ.",
        ])
        XCTAssertEqual(WebInbox.safeFileName("../dir/Phiếu: 1?.XLSX"), "Phiếu_ 1_.xlsx")
        XCTAssertEqual(WebInbox.safeFileName(""), "phieu-web.xlsx")
        XCTAssertThrowsError(try WebInbox.checkXlsx(Data("not a zip".utf8)))
    }
}
