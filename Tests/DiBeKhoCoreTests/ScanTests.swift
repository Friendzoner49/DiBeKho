import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

/// Phase 3b: the delivery-note scan and "Cần xử lý" on the made-up shop. The same scenario as tools/gen_scan.py (a first
/// scan with every kind of file, decisions, a partly approved note, edited / other-order notes, a moved note, lost
/// files, notes read after a stock count, a name forgotten) must leave the folder and every table as the Python app
/// does (GoldenScan), step by step.
final class ScanTests: XCTestCase {
    private var temp: URL!
    private var folders: ShopFolders!
    private var q: DatabaseQueue!
    private var checks: [String] = []
    private let c = Canon.self
    private var notes: URL { Bundle.module.resourceURL!.appendingPathComponent("ScanNotes") }
    private var fm: FileManager { .default }

    override func setUpWithError() throws {
        temp = fm.temporaryDirectory.appendingPathComponent("scan-\(UUID().uuidString)")
        folders = ShopFolders(root: temp.appendingPathComponent("work"))
        try fm.createDirectory(at: folders.deliveries, withIntermediateDirectories: true)
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

    override func tearDownWithError() throws {
        Deliveries.knownRate = { FXCache.rate() }
        try? fm.removeItem(at: temp)
    }

    // ---- helpers, the ones of the generator

    private func run(_ name: String, _ body: () throws -> String) {
        do {
            checks.append("\(name)=\(try body())")
        } catch let e as WriteError {
            checks.append("\(name)!\(e.message)")
        } catch {
            checks.append("\(name)?\(error)")
        }
    }

    @discardableResult
    private func put(_ source: String, _ rel: String) throws -> URL {
        let target = folders.deliveries.appendingPathComponent(rel)
        try fm.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? fm.removeItem(at: target)
        try fm.copyItem(at: notes.appendingPathComponent(source), to: target)
        return target
    }

    private func layout() -> String {
        let names = (fm.enumerator(atPath: folders.deliveries.path)?.allObjects as? [String]) ?? []
        return names.map { name -> String in
            var dir: ObjCBool = false
            fm.fileExists(atPath: folders.deliveries.appendingPathComponent(name).path, isDirectory: &dir)
            return (dir.boolValue ? "d:" : "f:") + name.precomposedStringWithCanonicalMapping
        }.sorted { Deliveries.scalarsLess($0, $1) }.joined(separator: ",")
    }

    private func message(_ text: String) -> String {
        text.hasPrefix("Không mở được file Excel") ? "Không mở được file Excel" : text
    }

    private func state(_ label: String) throws {
        let rows = try q.read { try Row.fetchAll($0, sql: "SELECT rel_path, status, message, document_id FROM scanned_files ORDER BY rel_path, hash") }
        checks.append("state_\(label)=" + layout() + " || " + rows.map {
            "\($0["rel_path"] as String)|\($0["status"] as String)|\(message($0["message"]))|\(c.canon($0["document_id"] as Int64?))"
        }.joined(separator: " ; "))
    }

    private func scan(_ label: String, partial: Bool = false) throws {
        let r = try Deliveries.scan(q, folders, allowPartial: partial)
        checks.append("scan_\(label)=imported:\(r.imported.joined(separator: ","))|pending:\(r.pending)|copies:\(r.copies.joined(separator: ","))")
        try state(label)
    }

    private func py(_ value: Bool) -> String { value ? "True" : "False" }

    private func waiting(_ label: String) throws {
        try q.read { db in
            let unknown = try Deliveries.unknownLines(db, folders).map { u in
                let top = try Catalog.suggestProducts(db, name: u.rawName, spec: u.spec).map { String($0.id) }.joined(separator: ",")
                return "\(u.key)|\(u.nameVi)|\(u.nameZh)|\(u.spec)|sug=\(c.canon(u.suggestion))|fee=\(py(u.isFee))|first=\(u.firstDate ?? "None")"
                    + "|files=\(u.files.joined(separator: "/"))|orders=\(u.orders.joined(separator: "/"))|top3=\(top)"
            }
            checks.append("unknown_\(label)=" + unknown.joined(separator: " ;; "))
            let notes = try Deliveries.waitingNotes(db, folders).map { n in
                "\(n.relPath)|\(n.code)|\(n.docDate ?? "None")|\(n.customer)|" + n.lines.map {
                    "\($0.row):\($0.key):\(c.canon($0.qty)):\(c.canon($0.productId)):\(py($0.ignored))"
                }.joined(separator: ",")
            }
            checks.append("waiting_\(label)=" + notes.joined(separator: " ;; "))
            let files = try Deliveries.pendingFiles(db).map {
                "\($0.status)|\($0.relPath)|\(message($0.message))|\($0.docCode ?? "None")"
            }
            checks.append("pending_\(label)=\(try Deliveries.pendingCount(db))::" + files.joined(separator: " ;; "))
            checks.append("unplaced_\(label)=" + (try Deliveries.unplaced(db)).map {
                "\($0.id):\($0.code):\($0.docDate):\($0.customer):\($0.lineCount):\(c.canon($0.totalQty))"
            }.joined(separator: ","))
        }
    }

    private func learned(_ label: String) throws {
        try q.write { db in  // the first call records the dropped lines of old notes, so it writes
            let names = try Deliveries.learnedNames(db, folders).map {
                "\($0.key)|\($0.label)|\(c.canon($0.productId))|\($0.documents.map { String($0) }.joined(separator: ","))"
            }
            checks.append("learned_\(label)=" + names.joined(separator: " ;; "))
            let orders = try Deliveries.learnedByOrder(db, folders).map { o in
                "\(c.canon(o.docId))|\(o.code)|\(o.docDate)|\(o.customer)|" + o.lines.map {
                    "\($0.key):\($0.label):\(c.canon($0.qty)):\(c.canon($0.productId)):\($0.documents.map { String($0) }.joined(separator: "/"))"
                }.joined(separator: ",")
            }
            checks.append("learned_orders_\(label)=" + orders.joined(separator: " ;; "))
        }
    }

    private func hashOf(_ rel: String) throws -> String {
        try q.read { try String.fetchOne($0, sql: "SELECT hash FROM scanned_files WHERE rel_path = ?", arguments: [rel])! }
    }

    private func docOf(_ code: String) throws -> Int64 {
        try q.read { try Int64.fetchOne($0, sql: """
            SELECT id FROM documents WHERE kind = 'delivery' AND code = ? AND status = 'active' ORDER BY id DESC
            """, arguments: [code])! }
    }

    private func lose(_ rel: String) throws { try fm.removeItem(at: folders.deliveries.appendingPathComponent(rel)) }

    private func levels(_ label: String) throws {
        let text = try q.read { try Ledger.levelsByPlace($0).sorted { $0.key < $1.key }
            .map { "\($0.key.productId)/\($0.key.locationId):\(c.canon($0.value))" }.joined(separator: ",") }
        checks.append("levels_\(label)=" + text)
    }

    private func write<T>(_ body: (Database) throws -> T) throws -> T { try q.write(body) }

    // ---- the scenario

    func testTheScanDoesWhatPythonDoes() throws {
        try write { db in
            try Catalog.setAlias(db, key: TextRules.matchKey("Keo dán đa năng", "5KG"), productId: 2, label: "Keo dán đa năng")
            try Catalog.setAlias(db, key: TextRules.matchKey("Sơn chống thấm", "20KG/thùng"), productId: 1, label: "Sơn chống thấm")
        }

        // 1. the first scan: every kind of file
        try put("n201.xlsx", "n201.xlsx")
        try put("n201.xlsx", "z-copy.xlsx")
        try put("n202.xlsx", "Khach/n202.xlsx")
        try put("n203.xlsx", "n203.xlsx")
        try put("n76.xlsx", "n76.xlsx")
        try put("n77.xlsx", "n77.xlsx")
        try put("n155.xlsx", "n155.xlsx")
        try put("n301-issue.xlsx", "n301-issue.xlsx")
        try put("n210.xlsx", "Tháng 11".decomposedStringWithCanonicalMapping + "/n210.xlsx")
        try put("notnote.xlsx", "notnote.xlsx")
        try put("broken.xlsx", "broken.xlsx")
        try put("old.xls", "old.xls")
        try put("lock.bin", "~$n201.xlsx")
        try put("lock.bin", ".n201.xlsx")
        try state("start")
        try scan("first")
        try waiting("first")

        // 2. decisions in "Cần xử lý"
        let unknown = try q.read { try Deliveries.unknownLines($0, folders) }
        let byName = Dictionary(uniqueKeysWithValues: unknown.map { ($0.nameVi, $0) })
        try write { db in
            try Deliveries.mapLine(db, key: byName["Sơn chống thấm lót"]!.key, productId: 1, label: byName["Sơn chống thấm lót"]!.label)
            try Deliveries.ignoreUnknown(db, byName["Phí vận chuyển"]!)
        }
        run("create_net") { "\(try write { try Deliveries.createProduct($0, for: byName["Lưới thuỷ tinh"]!, category: "Lưới", opening: 12, note: "Tồn đầu") })" }
        try write { try Deliveries.mapLine($0, key: byName["Băng keo butyl"]!.key, productId: 2, label: "Băng keo butyl") }
        try scan("partial", partial: true)
        try waiting("partial")
        try levels("partial")

        // 3. the rest of the partly approved note
        try write { try Deliveries.mapLine($0, key: byName["Màng khò nóng SBS 3mm"]!.key, productId: 3, label: "Màng khò nóng SBS 3mm") }
        try scan("rest")
        try waiting("rest")
        let unplaced = try q.read { try Deliveries.unplaced($0) }
        for (i, d) in unplaced.enumerated() {
            try write { try Ledger.setLocation($0, docId: d.id, locationId: i == 0 ? Ledger.office : Ledger.main) }
        }
        try levels("placed")

        // 4. an edited note, and a note of another order with the same code
        let h76 = try hashOf("n76.xlsx"), h77 = try hashOf("n77.xlsx")
        checks.append("other_76=\(py(try q.read { try Deliveries.looksLikeOtherOrder($0, folders, hash: h76) }))")
        checks.append("other_77=\(py(try q.read { try Deliveries.looksLikeOtherOrder($0, folders, hash: h77) }))")
        run("replace_76") { try write { try Deliveries.replaceChanged($0, folders, hash: h76) }; return "None" }
        run("separate_77") { try write { try Deliveries.importSeparately($0, folders, hash: h77) }; return "None" }
        try scan("changed")
        try levels("changed")

        // 5. a note moved and renamed by the user
        let rel201 = try q.read { try String.fetchAll($0, sql: "SELECT rel_path FROM scanned_files WHERE rel_path LIKE '%n201.xlsx'")[0] }
        try fm.createDirectory(at: folders.deliveries.appendingPathComponent("Mới"), withIntermediateDirectories: false)
        try fm.moveItem(at: folders.deliveries.appendingPathComponent(rel201),
                        to: folders.deliveries.appendingPathComponent("Mới/n201 đổi tên.xlsx"))
        try scan("moved")

        // 6. the same order edited in Excel; the user keeps the old one
        try put("n201-edited.xlsx", "n201-sua.xlsx")
        try scan("edited")
        try waiting("edited")
        let hEdited = try hashOf("n201-sua.xlsx")
        run("keep_old") { try write { try Deliveries.keepOld($0, hash: hEdited) }; return "None" }
        try scan("kept")

        // 7. files lost
        try lose("da-xu-ly/Khach/n202.xlsx")
        try scan("lost1")
        try waiting("lost1")
        let h202 = try hashOf("da-xu-ly/Khach/n202.xlsx")
        run("restore") { try write { try Deliveries.restoreMissing($0, folders, hash: h202) }.lastPathComponent }
        try scan("restored")
        try lose("da-xu-ly/n203.xlsx")
        try lose("da-xu-ly/n155.xlsx")
        try scan("lost2")
        let h203 = try hashOf("da-xu-ly/n203.xlsx"), h155 = try hashOf("da-xu-ly/n155.xlsx")
        run("cancel_203") { try write { try Deliveries.cancelMissing($0, hash: h203) }; return "None" }
        run("ignore_155") { try write { try Deliveries.ignoreMissing($0, hash: h155) }; return "None" }
        try scan("lost3")
        try levels("lost")

        // 8. notes read after a stock count
        try write { db in
            try Ledger.stockCount(db, date: "2026-11-20", counted: [.init(1, Ledger.main, 90), .init(2, Ledger.main, 30)], note: "đếm")
            try db.execute(sql: "UPDATE documents SET created_at = '2000-01-01 00:00:00' WHERE kind = 'stock_count' AND doc_date = '2026-11-20'")
        }
        try put("n208.xlsx", "n208.xlsx")
        try put("n209.xlsx", "n209.xlsx")
        try scan("late")
        for code in ["208", "209"] {
            let id = try docOf(code)
            try write { try Ledger.setLocation($0, docId: id, locationId: Ledger.main) }
        }
        let conflicts = try q.read { try Deliveries.countConflicts($0) }
        checks.append("conflicts=" + conflicts.map { "\($0.id):\($0.code):\($0.docDate):\($0.customer):\($0.countDate)" }.joined(separator: ","))
        try levels("before_keep")
        let d208 = try docOf("208"), d209 = try docOf("209")
        run("keep_counted") { try write { try Deliveries.keepCounted($0, docId: d208) }; return "None" }
        run("subtract_too") { try write { try Deliveries.subtractToo($0, docId: d209) }; return "None" }
        checks.append("conflicts_after=" + (try q.read { try Deliveries.countConflicts($0) }).map { "\($0.id):\($0.code)" }.joined(separator: ","))
        try levels("after_keep")

        // 9. what was learned, a name forgotten and the notes read again; a note read again as it is
        try learned("before")
        let d201 = try docOf("201")
        run("forget_201") { try write { try Deliveries.forgetOrder($0, folders, docId: d201) }; return "1" }
        try scan("forgotten")
        try waiting("forgotten")
        let d210 = try docOf("210")
        run("reread_210") { try write { try Deliveries.rereadDocument($0, folders, docId: d210) }; return "None" }
        try scan("reread")
        run("reread_cancelled") { try write { try Deliveries.rereadDocument($0, folders, docId: 5) }; return "None" }
        run("forget_cancelled") { try write { try Deliveries.forgetOrder($0, folders, docId: 5) }; return "1" }
        try learned("after_order")
        let first = try q.read { try Deliveries.learnedNames($0, folders) }.first { $0.productId != nil && !$0.documents.isEmpty }?.key ?? "none"
        run("forget_name") { String(try write { try Deliveries.forgetName($0, folders, key: first) }) }
        run("forget_name_nothing") { String(try write { try Deliveries.forgetName($0, folders, key: "khong-co-ten-nay") }) }
        try scan("name_forgotten")
        try learned("after_name")
        try levels("end")

        XCTAssertEqual(checks.count, GoldenScan.checks.count)
        for (got, expected) in zip(checks, GoldenScan.checks) where got != expected {
            XCTFail("\n  Swift  \(got)\n  Python \(expected)")
        }
        try q.read { db in
            for (table, expected) in GoldenScan.tables {
                let got = try Self.dump(db, table)
                XCTAssertEqual(got.count, expected.count, table)
                for (i, (a, b)) in zip(got, expected).enumerated() where a != b {
                    XCTFail("\(table) row \(i + 1):\n  Swift  \(a)\n  Python \(b)")
                }
            }
        }
    }

    /// Every column but the times, rows in rowid order, as the generator prints them.
    static func dump(_ db: Database, _ table: String) throws -> [String] {
        let skip: Set<String> = ["created_at", "closed_at", "at", "first_seen", "last_seen"]
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
                case let .string(s):
                    return "\(col)=" + (table == "scanned_files" && col == "message" && s.hasPrefix("Không mở được file Excel")
                        ? "Không mở được file Excel" : s)
                case .blob: return "\(col)=<blob>"
                }
            }.joined(separator: "|")
        }
    }

    // ---- nothing outside the work folder is read, written or moved

    func testNamesFromTheDatabaseStayInsideTheWorkFolder() throws {
        XCTAssertNil(Deliveries.notePath(folders, "../secret.xlsx"))
        XCTAssertNil(Deliveries.notePath(folders, "/etc/passwd"))
        XCTAssertNil(Deliveries.notePath(folders, "a/../../b.xlsx"))
        XCTAssertNil(Deliveries.notePath(folders, ""))
        XCTAssertNotNil(Deliveries.notePath(folders, "a/b.xlsx"))
        XCTAssertNil(Deliveries.originalCopy(folders, "../../etc/passwd"))
        let hash = String(repeating: "a", count: 64)  // a stored copy exists, the name it came from is not a plain name
        try fm.createDirectory(at: folders.originals, withIntermediateDirectories: true)
        try fm.copyItem(at: notes.appendingPathComponent("n201.xlsx"), to: folders.originals.appendingPathComponent("\(hash).xlsx"))
        try q.write { db in
            try db.execute(sql: "INSERT INTO scanned_files(hash, rel_path, status, message) VALUES(?, '../escape.xlsx', 'missing', '')",
                           arguments: [hash])
            XCTAssertThrowsError(try Deliveries.restoreMissing(db, folders, hash: hash))
        }
        XCTAssertFalse(fm.fileExists(atPath: temp.appendingPathComponent("escape.xlsx").path))
    }

    func testALinkLeadingOutOfTheFolderIsNotFollowed() throws {
        try write { db in
            try Catalog.setAlias(db, key: TextRules.matchKey("Keo dán đa năng", "5KG"), productId: 2)
            try Catalog.setAlias(db, key: TextRules.matchKey("Sơn chống thấm", "20KG/thùng"), productId: 1)
        }
        let outside = temp.appendingPathComponent("outside")
        try fm.createDirectory(at: outside, withIntermediateDirectories: true)
        try fm.copyItem(at: notes.appendingPathComponent("n201.xlsx"), to: outside.appendingPathComponent("evil.xlsx"))
        // a note that is a link to a file outside, and a sub-folder that is a link to a folder outside
        try fm.createSymbolicLink(at: folders.deliveries.appendingPathComponent("link.xlsx"),
                                  withDestinationURL: outside.appendingPathComponent("evil.xlsx"))
        try fm.createSymbolicLink(at: folders.deliveries.appendingPathComponent("folder"), withDestinationURL: outside)
        XCTAssertEqual(Deliveries.deliveryFiles(folders).count, 0)
        let result = try Deliveries.scan(q, folders)
        XCTAssertTrue(result.imported.isEmpty)

        // a done note is never moved into a da-xu-ly/ that leads out of the folder
        try fm.removeItem(at: folders.deliveriesDone)
        try fm.createSymbolicLink(at: folders.deliveriesDone, withDestinationURL: outside)
        try put("n210.xlsx", "n210.xlsx")
        _ = try Deliveries.scan(q, folders)
        XCTAssertTrue(fm.fileExists(atPath: folders.deliveries.appendingPathComponent("n210.xlsx").path))
        XCTAssertEqual(try fm.contentsOfDirectory(atPath: outside.path), ["evil.xlsx"])
    }

    func testTheSameNoteIsNotReadTwiceAndAnEditedOneIsAsked() throws {
        try write { db in
            try Catalog.setAlias(db, key: TextRules.matchKey("Keo dán đa năng", "5KG"), productId: 2)
            try Catalog.setAlias(db, key: TextRules.matchKey("Sơn chống thấm", "20KG/thùng"), productId: 1)
        }
        try put("n201.xlsx", "a.xlsx")
        XCTAssertEqual(try Deliveries.scan(q, folders).imported, ["a.xlsx"])
        let before = try q.read { try Int.fetchOne($0, sql: "SELECT COUNT(*) FROM stock_movements")! }
        let again = try Deliveries.scan(q, folders)
        XCTAssertTrue(again.imported.isEmpty)
        XCTAssertEqual(try q.read { try Int.fetchOne($0, sql: "SELECT COUNT(*) FROM stock_movements")! }, before)
        try put("n201-edited.xlsx", "b.xlsx")
        XCTAssertEqual(try Deliveries.scan(q, folders).pending, 1)
    }
}
