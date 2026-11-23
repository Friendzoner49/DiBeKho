import XCTest

@testable import DiBeKhoCore

/// The customers offered while a name is typed in Phiếu xuất kho (user's request 24/11/2026). The same cases as the
/// Python app's tests/test_customer_suggest.py, so both apps offer the same names.
final class CustomerSuggestTests: XCTestCase {
    private let labels = [
        "Công ty A · 0900 000 001",
        "Khách Mẫu · 0900 000 002",
        "Đại lý Chưa Mua",
        "Cửa hàng Khánh · 0911 222 333",
    ]

    private func names(_ typed: String) -> [String] {
        Issues.suggestCustomers(labels, typed).map { labels[$0] }
    }

    func testNothingTypedOffersEveryone() {
        XCTAssertEqual(names(""), labels)
        XCTAssertEqual(names("   "), labels)
    }

    func testWithoutAccents() {
        XCTAssertEqual(names("khach mau"), ["Khách Mẫu · 0900 000 002"])
        XCTAssertEqual(names("KHACH"), ["Khách Mẫu · 0900 000 002"])  // «Khánh» is khanh, not khach
        XCTAssertEqual(names("kh"), ["Khách Mẫu · 0900 000 002", "Cửa hàng Khánh · 0911 222 333"])
    }

    func testWithAccentsToo() {
        XCTAssertEqual(names("Khánh"), ["Cửa hàng Khánh · 0911 222 333"])
    }

    func testDWithStrokeIsD() {
        XCTAssertEqual(names("dai ly"), ["Đại lý Chưa Mua"])
    }

    func testWordsInAnyOrder() {
        XCTAssertEqual(names("mau khach"), ["Khách Mẫu · 0900 000 002"])
    }

    func testPartOfAPhoneNumber() {
        XCTAssertEqual(names("0911"), ["Cửa hàng Khánh · 0911 222 333"])
        XCTAssertEqual(names("000 001"), ["Công ty A · 0900 000 001"])
    }

    func testNothingFits() {
        XCTAssertEqual(names("xyz"), [])
    }
}
