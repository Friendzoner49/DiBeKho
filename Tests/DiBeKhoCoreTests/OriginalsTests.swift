import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

/// User, 21/11/2026: (1) on the Swift Phiếu xuất kho, typing an old customer's name filled none of the other boxes (the
/// Python box completes the name to «Tên · SĐT» and picks it); (2) after the app was removed and the data came back from
/// the cloud, no order could open its original: the stored copies are listed here and downloaded by CloudRunner.
/// ⚠ The download itself (Storage) is not tested here: it needs a real cloud.
final class OriginalsTests: XCTestCase {
    private let shop: [Issues.CustomerChoice] = [
        (name: "Đại lý Mẫu", phone: "0901234567", contact: "Chị Ba", address: "Hà Nội", taxCode: "0101", email: "mau@example.com"),
        (name: "Chị Mai", phone: "", contact: "", address: "Đà Nẵng", taxCode: "", email: ""),
    ]

    func testAnOldCustomersNameTypedPicksTheCustomer() {
        XCTAssertEqual(Issues.pickedCustomer("Đại lý Mẫu · 0901234567", shop), 0, "the list's own label")
        XCTAssertEqual(Issues.pickedCustomer("Đại lý Mẫu", shop), 0, "the name alone")
        XCTAssertEqual(Issues.pickedCustomer("  đại   LÝ mẫu ", shop), 0, "letter case and spaces aside")
        XCTAssertEqual(Issues.pickedCustomer("Chị Mai", shop), 1, "a customer without a phone")
        XCTAssertNil(Issues.pickedCustomer("Đại lý Mẫ", shop), "half a name picks nobody")
        XCTAssertNil(Issues.pickedCustomer("Khách mới", shop))
        XCTAssertNil(Issues.pickedCustomer("   ", shop))
    }

    /// «Đại lý Mẫu» filled the boxes, then the user typed on («Đại lý Mẫu Hai», a new customer): the old details go, what
    /// the user typed stays, or the new customer would be saved with the old phone and merged with them on reading back
    func testTypingPastAnOldCustomersNameEmptiesTheBoxesTheyFilled() {
        let old = shop[0]
        let boxes: Issues.CustomerChoice = (name: "", phone: old.phone, contact: old.contact, address: "Huế",
                                            taxCode: old.taxCode, email: old.email)
        let left = Issues.unfilled(boxes, from: old)
        XCTAssertEqual([left.phone, left.contact, left.address, left.taxCode, left.email], ["", "", "Huế", "", ""])
    }

    func testEveryMissingOriginalIsListedTheUndecidedOnesFirst() throws {
        let fm = FileManager.default
        let temp = fm.temporaryDirectory.appendingPathComponent("originals-\(UUID().uuidString)")
        defer { try? fm.removeItem(at: temp) }
        let folders = ShopFolders(root: temp)
        try fm.createDirectory(at: folders.originals, withIntermediateDirectories: true)
        let q = try DatabaseQueue(configuration: Store.configuration())
        try Schema.migrate(q)
        let (a, b, c) = (String(repeating: "a", count: 64), String(repeating: "b", count: 64), String(repeating: "c", count: 64))
        try q.write { db in
            try db.execute(sql: "INSERT INTO customers(id, name, phone, phone_norm) VALUES (1, 'Đại lý A', '', '')")
            for (id, hash, currency) in [(1, a, "VND"), (2, b, ""), (3, c, "CNY"), (4, "", "VND")] {
                try db.execute(sql: "INSERT INTO documents(id, kind, code, code_norm, doc_date, customer_id, status, source_file, source_hash, currency) "
                               + "VALUES (?, 'delivery', ?, ?, '2026-11-10', 1, 'active', 'p.xlsx', ?, ?)",
                               arguments: [id, "\(id)", "\(id)", hash, currency])
            }
        }
        try Data("x".utf8).write(to: folders.originals.appendingPathComponent("\(c).xlsx"))  // this one is here
        XCTAssertEqual(try q.read { try Deliveries.missingOriginals($0, folders) }, ["\(b).xlsx", "\(a).xlsx"])
    }
}
