import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

/// Phase 3: the same operations as tools/gen_phase3.py, on the same made-up shop, must leave every table exactly as
/// the Python core leaves it (GoldenWrites), and return the same values or refuse with the same message.
enum Canon {
    static func canon(_ value: Double?) -> String { value.map { String(format: "%.4f", $0) } ?? "∅" }
    static func canon(_ value: Int64?) -> String { canon(value.map(Double.init)) }
    static func canon(_ value: String?) -> String { value ?? "∅" }
    static func canon(_ value: Bool) -> String { canon(value ? 1.0 : 0.0) }
}

final class WritesTests: XCTestCase {

    static func shop() throws -> DatabaseQueue {
        let queue = try DatabaseQueue(configuration: Store.configuration())
        try Schema.migrate(queue)
        try queue.write { db in
            for statement in Schema.split(Golden.shop) { try db.execute(sql: statement) }
            try Sync.ensureTriggers(db)
            try db.execute(sql: "UPDATE sync_flags SET value = '1' WHERE key = 'enabled'")
            try Meta.set(db, "freed_codes", "SP010,SP008")
            try Meta.set(db, "product_code_max", "4")
        }
        return queue
    }

    func testTheSameOperationsWriteWhatPythonWrites() throws {
        let q = try Self.shop()
        var checks: [String] = []
        func run(_ name: String, _ body: () throws -> String) {
            do {
                checks.append("\(name)=\(try body())")
            } catch let e as WriteError {
                checks.append("\(name)!\(e.message)")
            } catch {
                checks.append("\(name)?\(error)")
            }
        }
        func read(_ name: String, _ body: @escaping (Database) throws -> String) { run(name) { try q.read(body) } }
        func write(_ name: String, _ body: @escaping (Database) throws -> String) { run(name) { try q.write(body) } }
        typealias L = Receipts.LineInput
        let c = Canon.self

        read("return_price_76_p1") { c.canon(try Receipts.returnPrice($0, customerId: 1, productId: 1, refCode: "076")) }
        read("return_price_none_p2") { c.canon(try Receipts.returnPrice($0, customerId: 1, productId: 2, on: "2026-10-01")) }
        read("return_price_p2") { c.canon(try Receipts.returnPrice($0, customerId: 1, productId: 2, on: "2026-11-20")) }
        read("return_price_nobody") { c.canon(try Receipts.returnPrice($0, customerId: nil, productId: 2)) }
        read("return_currency_77") { let (a, b) = try Receipts.returnCurrency($0, customerId: 2, refCode: "077"); return "\(a)/\(c.canon(b))" }
        read("return_currency_c1") { let (a, b) = try Receipts.returnCurrency($0, customerId: 1, on: "2026-11-20"); return "\(a)/\(c.canon(b))" }
        read("return_currency_c3") { let (a, b) = try Receipts.returnCurrency($0, customerId: 3); return "\(a)/\(c.canon(b))" }
        read("suggest_supplier") { try Receipts.suggestions($0, source: "supplier", supplierName: "cong ty me").map(String.init).joined(separator: ",") }
        read("suggest_return_c1") { try Receipts.suggestions($0, source: "return", customerId: 1).map(String.init).joined(separator: ",") }
        read("suggest_return_76") { try Receipts.suggestions($0, source: "return", customerId: 1, refCode: "076").map(String.init).joined(separator: ",") }
        read("suppliers_all") { try Receipts.supplierNames($0).joined(separator: ",") }
        read("customer_orders_1") { try Receipts.customerOrders($0, customerId: 1).joined(separator: ",") }
        read("next_code") { try Receipts.nextCode($0) }
        read("next_transfer") { try Ledger.nextTransferCode($0) }
        read("next_trial") { try Ledger.nextTrialCode($0) }
        read("next_product") { try Catalog.nextProductCode($0) }
        run("guess_unit_1") { Catalog.guessUnit("10KG/Thùng") }
        run("guess_unit_2") { Catalog.guessUnit("1m*20m/ cuộn") }
        run("guess_unit_3") { Catalog.guessUnit("Gói") }
        run("guess_unit_4") { Catalog.guessUnit("20 kg") }
        run("amount_1") { c.canon(Receipts.lineAmount(1.5, 160000.333)) }
        run("amount_2") { c.canon(Receipts.lineAmount(3, 0.125)) }
        run("amount_3") { c.canon(Receipts.lineAmount(2, nil)) }
        run("amount_4") { c.canon(Receipts.lineAmount(0.7, 1234.565)) }

        write("receipt_supplier") { c.canon(try Receipts.save($0, Receipts.Input(
            date: "2026-11-10", source: "supplier", supplierName: "  CÔNG TY  ME ", note: " về  sáng ",
            lines: [L(20, 1, note: " hàng  mới "),
                    L(5, new: NewProduct("Lưới thuỷ tinh", nameZh: "玻璃纤维网", spec: "1m×50m/cuộn", variant: "Trắng",
                                         unit: "", category: "Lưới")),
                    L(0, 2), L(3)], locationId: Ledger.office))) }
        write("receipt_other") { c.canon(try Receipts.save($0, Receipts.Input(
            date: "2026-11-11", source: "other", supplierName: "Nhà cung cấp Mới",
            lines: [L(2.5, 3), L(1, new: NewProduct("Băng keo", spec: "5cm x 20m", unit: "cuộn"))]))) }
        write("receipt_return") { c.canon(try Receipts.save($0, Receipts.Input(
            date: "2026-11-12", source: "return", customerId: 1, refCode: " 076 ",
            lines: [L(2, 1, unitPrice: 380000), L(1.5, 2, unitPrice: 160000.333), L(1, 3, unitPrice: -5)]))) }
        let firstReturn = try q.read { try Int64.fetchOne($0, sql: "SELECT MAX(id) FROM documents")! }
        write("receipt_return_new_customer") { c.canon(try Receipts.save($0, Receipts.Input(
            date: "2026-11-13", source: "return", customerName: "  Khách Lẻ  Mới ", lines: [L(1, 2, unitPrice: 150000)]))) }
        write("receipt_edit") { c.canon(try Receipts.save($0, Receipts.Input(
            date: "2026-11-12", source: "return", customerId: 1, refCode: "076", note: "sửa",
            lines: [L(1, 1, unitPrice: 380000)]), replaces: firstReturn)) }
        write("receipt_edit_wrong_kind") { c.canon(try Receipts.save($0, Receipts.Input(
            date: "2026-11-12", source: "supplier", supplierName: "X", lines: [L(1, 1)]), replaces: 8)) }
        run("receipt_problems") { Receipts.problems(Receipts.Input(
            date: "2026-11-12", source: "supplier", lines: [L(1, 1), L(2, 1), L(1, new: NewProduct(" "))])).map(\.0).joined(separator: ";") }
        run("receipt_problems_2") { Receipts.problems(Receipts.Input(
            date: "2026-11-12", source: "return",
            lines: [L(1, new: NewProduct("A b", spec: "1")), L(1, new: NewProduct("ab", spec: " 1 "))])).map(\.0).joined(separator: ";") }
        run("receipt_problems_3") { Receipts.problems(Receipts.Input(date: "2026-11-12", source: "other")).map(\.0).joined(separator: ";") }
        run("looks_like_place") { ["Kho", "kho Tổng", "Văn phòng", "Kho hàng A", "Công ty mẹ", "khoai"]
            .map { Receipts.looksLikePlace($0) ? "True" : "False" }.joined(separator: ",") }
        read("loaded") { try Receipts.load($0, docId: firstReturn + 2)!.lines
            .map { "\($0.productId.map { String($0) } ?? "None"):\(c.canon($0.qty)):\(c.canon($0.unitPrice)):\($0.note)" }
            .joined(separator: "|") }

        write("transfer") { c.canon(try Ledger.transfer($0, date: "2026-11-14", from: 1, to: 2,
                                                         lines: [LedgerLine(1, 5, note: "cho văn phòng"), LedgerLine(3, 2.5)], note: "chuyển")) }
        let transferId = try q.read { try Int64.fetchOne($0, sql: "SELECT MAX(id) FROM documents")! }
        write("transfer_edit") { c.canon(try Ledger.transfer($0, date: "2026-11-14", from: 1, to: 2, lines: [LedgerLine(1, 4)],
                                                              replaces: transferId)) }
        write("transfer_same") { c.canon(try Ledger.transfer($0, date: "2026-11-14", from: 2, to: 2, lines: [LedgerLine(1, 1)])) }
        write("transfer_empty") { c.canon(try Ledger.transfer($0, date: "2026-11-14", from: 2, to: 1, lines: [])) }
        write("transfer_back") { c.canon(try Ledger.transfer($0, date: "2026-11-15", from: 2, to: 1, lines: [LedgerLine(2, 1)])) }
        write("trial") { c.canon(try Ledger.trialUse($0, date: "2026-11-15", locationId: 2,
                                                      lines: [LedgerLine(1, 1, note: "thử màu")], note: "khách xem")) }
        write("trial_bad") { c.canon(try Ledger.trialUse($0, date: "2026-11-15", locationId: 3, lines: [LedgerLine(1, 1)])) }
        write("count_place") { c.canon(try Ledger.stockCount($0, date: "2026-11-15", counted: [
            .init(1, 1, 70), .init(2, 2, 0), .init(3, 2, 4.5)], note: "đếm")) }
        write("count_total") { c.canon(try Ledger.stockCount($0, date: "2026-11-16", counted: [.init(3, nil, 30), .init(1, nil, 999.25)])) }
        write("count_back") { c.canon(try Ledger.stockCount($0, date: "2026-10-01", counted: [.init(2, nil, 41)])) }
        write("cancel") { try Ledger.close($0, docId: 4); return "∅" }
        write("cancel_again") { try Ledger.close($0, docId: 4); return "∅" }
        write("place") { try Ledger.setLocation($0, docId: 3, locationId: 2); return "∅" }
        write("place_receipt") { try Ledger.setLocation($0, docId: 6, locationId: 2); return "∅" }
        write("place_transfer") { try Ledger.setLocation($0, docId: 8, locationId: 2); return "∅" }
        write("cancel_trial") { try Ledger.close($0, docId: 9); return "∅" }
        write("product_freed") { c.canon(try Catalog.createProduct($0, nameVi: "  Sơn  lót ", spec: "18L / Thùng ")) }
        write("customer_same_phone") { c.canon(try Catalog.upsertCustomer($0, name: "Tên khác", phone: "+84 900 000 001",
                                                                         contact: "Chị C", address: "Địa chỉ")) }
        write("customer_same_name") { c.canon(try Catalog.upsertCustomer($0, name: "khach mau", contact: "Anh D", address: "Đà Nẵng")) }
        write("customer_new") { c.canon(try Catalog.upsertCustomer($0, name: "", phone: "0900 000 009")) }
        write("customer_none") { c.canon(try Catalog.upsertCustomer($0, name: " ")) }
        write("customer_named_later") { c.canon(try Catalog.upsertCustomer($0, name: "Cửa hàng E", phone: "0900000009")) }
        read("levels") { try Ledger.levels($0).sorted { $0.key < $1.key }.map { "\($0.key):\(c.canon($0.value))" }.joined(separator: ",") }
        read("levels_place") { try Ledger.levelsByPlace($0).sorted { $0.key < $1.key }
            .map { "\($0.key.productId)/\($0.key.locationId):\(c.canon($0.value))" }.joined(separator: ",") }
        read("levels_oct") { try Ledger.levels($0, asOf: "2026-10-31").sorted { $0.key < $1.key }
            .map { "\($0.key):\(c.canon($0.value))" }.joined(separator: ",") }
        read("mixed_3") { c.canon(try Ledger.isMixed($0, 3)) }

        XCTAssertEqual(checks.count, GoldenWrites.checks.count)
        for (got, expected) in zip(checks, GoldenWrites.checks) {
            XCTAssertEqual(got, expected)
        }

        try q.read { db in
            let touched = try Meta.get(db, "last_change_at")
            XCTAssertNotNil(touched.range(of: #"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$"#, options: .regularExpression), touched)
            for (table, expected) in GoldenWrites.tables {
                let got = try Self.dump(db, table)
                XCTAssertEqual(got.count, expected.count, table)
                for (i, (a, b)) in zip(got, expected).enumerated() where a != b {
                    XCTFail("\(table) row \(i + 1):\n  Swift  \(a)\n  Python \(b)")
                }
            }
            // created_at and closed_at as the database writes them (local time, no T)
            let stamps = try String.fetchAll(db, sql: "SELECT created_at FROM stock_movements UNION SELECT closed_at FROM documents WHERE closed_at IS NOT NULL")
            for s in stamps {
                XCTAssertNotNil(s.range(of: #"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$"#, options: .regularExpression), s)
            }
        }
    }

    /// Every column but the times, rows in rowid order, values as the generator prints them.
    static func dump(_ db: Database, _ table: String) throws -> [String] {
        let skip: Set<String> = ["created_at", "closed_at", "at"]
        let cols = try Row.fetchAll(db, sql: "PRAGMA table_info(\(table))").map { $0["name"] as String }.filter { !skip.contains($0) }
        return try Row.fetchAll(db, sql: "SELECT \(cols.joined(separator: ", ")) FROM \(table) ORDER BY rowid").map { row in
            let key: String? = table == "meta" ? row["key"] : nil
            return cols.map { col -> String in
                if key == "last_change_at" && col == "value" { return "\(col)=T" }
                let value: DatabaseValue = row[col]
                switch value.storage {
                case .null: return "\(col)=∅"
                case let .int64(i): return "\(col)=\(String(format: "%.4f", Double(i)))"
                case let .double(d): return "\(col)=\(String(format: "%.4f", d))"
                case let .string(s): return "\(col)=\(s)"
                case .blob: return "\(col)=<blob>"
                }
            }.joined(separator: "|")
        }
    }

    func testSyncTriggersAreThePythonOnesAndStayAfterAnotherOpen() throws {
        let q = try Self.shop()
        try q.write { db in
            try Sync.ensureTriggers(db)  // a second open changes nothing
            let names = try String.fetchAll(db, sql: "SELECT name FROM sqlite_master WHERE type = 'trigger' ORDER BY name")
            XCTAssertEqual(names.count, SyncTriggers.statements.count)
            // an older trigger (other SQL) is replaced
            try db.execute(sql: "DROP TRIGGER sync_products_ins")
            try db.execute(sql: "CREATE TRIGGER sync_products_ins AFTER INSERT ON products BEGIN SELECT 1; END")
            try Sync.ensureTriggers(db)
            let sql = try String.fetchOne(db, sql: "SELECT sql FROM sqlite_master WHERE name = 'sync_products_ins'")
            XCTAssertTrue(sql?.contains("sync_outbox") ?? false)
        }
    }

    func testAFailedSaveLeavesNothing() throws {
        let q = try Self.shop()
        let before = try q.read { try Self.dump($0, "documents") + Self.dump($0, "products") }
        XCTAssertThrowsError(try q.write { db in
            try Receipts.save(db, Receipts.Input(date: "2026-11-12", source: "supplier", supplierName: "X",
                                                 lines: [.init(1, new: NewProduct("Mới"))]), replaces: 8)
        })
        XCTAssertEqual(try q.read { try Self.dump($0, "documents") + Self.dump($0, "products") }, before)
    }

    /// The screenshots' made-up shop: made from a kho.sqlite that stays as it was, written to, still there when opened again.
    func testTheDemoShopNeverTouchesTheOriginal() throws {
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent("demo-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: temp) }
        let work = temp.appendingPathComponent("shop")
        try FileManager.default.createDirectory(at: work.appendingPathComponent("data/phieu-goc"), withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: work.appendingPathComponent("phieu-giao-hang"), withIntermediateDirectories: true)
        try Data("x".utf8).write(to: work.appendingPathComponent("phieu-giao-hang/a.xlsx"))
        let source = work.appendingPathComponent("data/kho.sqlite")
        let original = try DatabaseQueue(path: source.path, configuration: Store.configuration())
        try Schema.migrate(original)
        try original.write { db in for s in Schema.split(Golden.shop) { try db.execute(sql: s) } }
        try original.close()
        let before = try Data(contentsOf: source)

        DemoShop.folderOverride = temp.appendingPathComponent("Demo")
        defer { DemoShop.folderOverride = nil }
        try DemoShop.make(from: source)
        XCTAssertTrue(FileManager.default.fileExists(atPath: DemoShop.deliveries.appendingPathComponent("a.xlsx").path))
        var q = try DemoShop.open()
        _ = try q.write { try Ledger.transfer($0, date: "2026-11-14", from: 1, to: 2, lines: [LedgerLine(1, 3)]) }
        try q.close()
        XCTAssertEqual(try Data(contentsOf: source), before, "the original was written")
        q = try DemoShop.open()
        XCTAssertEqual(try q.read { try Ledger.nextTransferCode($0) }, "CH003")
        try q.close()
        ActivityLog.file = nil
    }

    /// Every t("…") written in the app's sources is a text of the Python app (no key shown as is on a button).
    func testEveryTextKeyUsedExists() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let pattern = try NSRegularExpression(pattern: #"\bt\("([a-z_]+\.[a-z_0-9.]+)""#)
        var missing: [String] = []
        var seen = 0
        let walker = FileManager.default.enumerator(at: root.appendingPathComponent("Sources"), includingPropertiesForKeys: nil)
        while let file = walker?.nextObject() as? URL {
            guard file.pathExtension == "swift", !file.path.contains("/Generated/") else { continue }
            let text = try String(contentsOf: file, encoding: .utf8)
            for m in pattern.matches(in: text, range: NSRange(text.startIndex..., in: text)) {
                let key = String(text[Range(m.range(at: 1), in: text)!])
                seen += 1
                if !L10n.has(key) { missing.append("\(file.lastPathComponent): \(key)") }
            }
        }
        XCTAssertGreaterThan(seen, 100)
        XCTAssertEqual(missing, [])
    }

    func testTheScreenTextsAreThePythonOnes() {
        L10n.language = "vi"
        XCTAssertEqual(t("app.name"), "DiBeKho")
        XCTAssertTrue(L10n.has("receipt_form.need_supplier"))
        L10n.language = "zh"
        XCTAssertNotEqual(t("receipt_form.need_supplier"), "receipt_form.need_supplier")
        L10n.language = "vi"
        XCTAssertEqual(t("no.such.key"), "no.such.key")
        XCTAssertFalse(t("app.folder_error", ["path": "/x", "error": "e"]).contains("{path}"))
    }
}
