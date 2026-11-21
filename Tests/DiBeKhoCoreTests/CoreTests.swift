import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

/// The Swift core against what the Python app does (Generated/Golden.swift comes from it), with made-up data only.
final class SchemaTests: XCTestCase {
    func testMigrationsReachThePythonSchemaVersion() throws {
        let queue = try DatabaseQueue()
        try Schema.migrate(queue)
        XCTAssertEqual(Schema.supportedVersion, Golden.schemaVersion)
        XCTAssertEqual(try queue.read { try Schema.version($0) }, Golden.schemaVersion)
    }

    func testTheSchemaIsThePythonOne() throws {
        let queue = try DatabaseQueue()
        try Schema.migrate(queue)
        let (columns, others) = try queue.read { db -> ([[String]], [[String]]) in
            let tables = try String.fetchAll(db, sql: """
                SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name
                """)
            var columns: [[String]] = []
            for table in tables {
                for row in try Row.fetchAll(db, sql: "PRAGMA table_info(\(table))") {
                    let name: String = row["name"]
                    let type: String = row["type"]
                    let notNull: Int = row["notnull"]
                    let dflt: String? = row["dflt_value"]
                    let pk: Int = row["pk"]
                    columns.append([table, name, type, String(notNull), dflt ?? "", String(pk)])
                }
            }
            let others = try Row.fetchAll(db, sql: """
                SELECT type, name, tbl_name FROM sqlite_master WHERE type <> 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY type, name
                """).map { row -> [String] in [row["type"], row["name"], row["tbl_name"]] }
            return (columns, others)
        }
        XCTAssertEqual(columns, Golden.columns)
        XCTAssertEqual(others, Golden.others)
    }

    func testNoTableOfItsOwnIsAdded() throws {
        let queue = try DatabaseQueue()
        try Schema.migrate(queue)
        let grdb = try queue.read { try Int.fetchOne($0, sql: "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'grdb%'") }
        XCTAssertEqual(grdb, 0)
    }

    func testMigratingTwiceChangesNothing() throws {
        let queue = try DatabaseQueue()
        try Schema.migrate(queue)
        try Schema.migrate(queue)
        XCTAssertEqual(try queue.read { try Schema.version($0) }, Golden.schemaVersion)
    }

    func testCommentsAndSemicolonsSplitAsInPython() {
        let sql = "CREATE TABLE a (x TEXT); -- a note; with a semicolon\n\nINSERT INTO a VALUES ('y');\n"
        XCTAssertEqual(Schema.split(sql), ["CREATE TABLE a (x TEXT)", "INSERT INTO a VALUES ('y')"])
    }
}

final class TextTests: XCTestCase {
    func testUnaccentIsThePythonOne() {
        for (text, expected) in Golden.unaccent {
            XCTAssertEqual(TextRules.unaccent(text), expected, "unaccent(\(text))")
        }
        XCTAssertEqual(TextRules.unaccent(nil), "")
    }

    func testMatchesWordsIsThePythonOne() {
        for (needle, haystack, expected) in Golden.matchesWords {
            XCTAssertEqual(TextRules.matchesWords(needle, haystack), expected, "matchesWords(\(needle), \(haystack))")
        }
    }
}

final class StoreTests: XCTestCase {
    private var folder: URL!

    override func setUpWithError() throws {
        folder = FileManager.default.temporaryDirectory.appendingPathComponent("DiBeKhoTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: folder)
        Store.removeCopies()
    }

    /// A made-up shop: two products, a count, a delivery from both places, a transfer, an inactive product.
    private func makeShop() throws -> URL {
        let file = folder.appendingPathComponent("kho.sqlite")
        let queue = try DatabaseQueue(path: file.path)
        try Schema.migrate(queue)
        try queue.write { db in
            try db.execute(sql: """
                INSERT INTO products(id, code, name_vi, name_zh, spec, unit, category, variant, active)
                VALUES (1, 'SP001', 'Sơn chống thấm', '防水涂料', '20KG/thùng', 'thùng', 'Sơn', 'Xám', 1),
                       (2, 'SP002', 'Keo cố định cát', '', '5KG', 'can', 'Keo', '', 1),
                       (3, 'SP003', 'Hàng ngừng bán', '', '', '', 'Keo', '', 0);
                INSERT INTO meta(key, value) VALUES ('low_stock_default', '30');
                INSERT INTO documents(id, kind, code, doc_date) VALUES (1, 'stock_count', 'KK001', '2026-11-01'),
                       (2, 'delivery', '160', '2026-11-05'), (3, 'transfer', 'CH001', '2026-11-06');
                INSERT INTO stock_movements(product_id, qty, document_id, kind, occurred_on, location_id) VALUES
                       (1, 50, 1, 'count_adjust', '2026-11-01', 1), (1, 8, 1, 'count_adjust', '2026-11-01', 2),
                       (2, 20, 1, 'count_adjust', '2026-11-01', 1), (3, 5, 1, 'count_adjust', '2026-11-01', 1),
                       (1, -10, 2, 'delivery_out', '2026-11-05', 1), (1, -3, 2, 'delivery_out', '2026-11-05', 2),
                       (2, -4, 3, 'transfer_out', '2026-11-06', 1), (2, 4, 3, 'transfer_in', '2026-11-06', 2);
                """)
        }
        try queue.close()
        return file
    }

    func testStockIsTheSumOfMovementsPerPlace() throws {
        let (queue, _) = try Store.openCopy(of: try makeShop())
        let rows = try queue.read { try StockQueries.table($0) }
        XCTAssertEqual(rows.map(\.code), ["SP002", "SP001"])  // ordered by group (Keo, Sơn); the inactive one left out
        let paint = try XCTUnwrap(rows.first { $0.code == "SP001" })
        XCTAssertEqual([paint.stock, paint.stockMain, paint.stockOffice], [45, 40, 5])
        XCTAssertEqual(paint.lastOut, "2026-11-05")
        XCTAssertEqual(paint.nameZh, "防水涂料")
        let glue = try XCTUnwrap(rows.first { $0.code == "SP002" })
        XCTAssertEqual([glue.stock, glue.stockMain, glue.stockOffice], [20, 16, 4])
        XCTAssertNil(glue.lastOut)
        XCTAssertEqual(try queue.read { try StockQueries.lowStockDefault($0) }, 30)
        XCTAssertTrue(StockQueries.isLow(glue.stock, 30))
        XCTAssertFalse(StockQueries.isLow(glue.stock, 0))
    }

    func testTheOriginalIsNeverWritten() throws {
        let original = try makeShop()
        let before = try Data(contentsOf: original)
        let (queue, copy) = try Store.openCopy(of: original)
        try queue.write { try $0.execute(sql: "DELETE FROM stock_movements") }
        XCTAssertNotEqual(copy.standardizedFileURL, original.standardizedFileURL)
        XCTAssertEqual(try Data(contentsOf: original), before)
    }

    func testDataOfANewerAppIsRefused() throws {
        let file = try makeShop()
        let queue = try DatabaseQueue(path: file.path)
        try queue.writeWithoutTransaction { try $0.execute(sql: "PRAGMA user_version = \(Schema.supportedVersion + 1)") }
        try queue.close()
        XCTAssertThrowsError(try Store.openCopy(of: file)) { error in
            XCTAssertEqual(error as? DataError, .newer(found: Schema.supportedVersion + 1, supported: Schema.supportedVersion))
        }
    }

    func testAFileThatIsNotDiBeKhoIsRefused() throws {
        let file = folder.appendingPathComponent("other.sqlite")
        let queue = try DatabaseQueue(path: file.path)
        try queue.write { try $0.execute(sql: "CREATE TABLE notes (x TEXT)") }
        try queue.close()
        XCTAssertThrowsError(try Store.openCopy(of: file)) { error in
            XCTAssertEqual(error as? DataError, .notDiBeKho)
        }
    }

    func testDataOfAnOlderAppIsBroughtUpToDateInTheCopyOnly() throws {
        let file = folder.appendingPathComponent("old.sqlite")
        let old = try DatabaseQueue(path: file.path)
        try old.writeWithoutTransaction { db in
            try db.execute(sql: "PRAGMA foreign_keys = OFF")  // as the Python app while it migrates
            for migration in Migrations.files.sorted(by: { $0.version < $1.version }) where migration.version <= 9 {
                for statement in Schema.split(migration.sql) { try db.execute(sql: statement) }
                try db.execute(sql: "PRAGMA user_version = \(migration.version)")
            }
        }
        try old.close()
        let (queue, _) = try Store.openCopy(of: file)
        XCTAssertEqual(try queue.read { try Schema.version($0) }, Schema.supportedVersion)
        let check = try DatabaseQueue(path: file.path)
        XCTAssertEqual(try check.read { try Schema.version($0) }, 9)
        try check.close()
    }
}
