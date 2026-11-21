import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

/// Phase 5a: editing the catalog on the made-up shop gives what tools/gen_catalog.py got from the Python app, step by step.
final class CatalogTests: XCTestCase {
    private var q: DatabaseQueue!
    private var checks: [String] = []

    override func setUpWithError() throws {
        q = try DatabaseQueue(configuration: Store.configuration())
        try Schema.migrate(q)
        try q.write { db in
            for statement in Schema.split(Golden.shop) { try db.execute(sql: statement) }
            try Meta.set(db, "freed_codes", "SP010,SP008")
            try Meta.set(db, "product_code_max", "4")
        }
    }

    private func cell(_ v: DatabaseValue) -> String {
        switch v.storage {
        case .null: return "∅"
        case let .int64(i): return String(format: "%.4f", Double(i))
        case let .double(d): return String(format: "%.4f", d)
        case let .string(s): return s
        case .blob: return "<blob>"
        }
    }

    private func run(_ name: String, _ body: () throws -> String) {
        do { checks.append("\(name)=\(try body())") } catch let e as WriteError { checks.append("\(name)!\(e.message)") } catch {
            checks.append("\(name)?\(error)")
        }
    }

    private func state(_ label: String) throws {
        try q.read { db in
            let products = try Row.fetchAll(db, sql: """
                SELECT id, code, name_vi, name_zh, spec, unit, category, variant, min_stock, active, stock_note
                FROM products ORDER BY id
                """).map { r in (0..<r.count).map { i -> String in let v: DatabaseValue = r[i]; return cell(v) }.joined(separator: "|") }
            checks.append("\(label)_products=" + products.joined(separator: ";"))
            checks.append("\(label)_freed=" + (try Meta.get(db, "freed_codes", "")) + " max=" + (try Meta.get(db, "product_code_max", "")))
            checks.append("\(label)_aliases=" + (try Row.fetchAll(db, sql: "SELECT key, product_id FROM product_aliases ORDER BY key")
                .map { "\($0["key"] as String)>\($0["product_id"] as Int64)" }.joined(separator: ";")))
            checks.append("\(label)_moves=" + (try Row.fetchAll(db, sql: "SELECT product_id, qty, kind FROM stock_movements ORDER BY id")
                .map { "\($0["product_id"] as Int64):\(String(format: "%.4f", $0["qty"] as Double)):\($0["kind"] as String)" }.joined(separator: ";")))
            checks.append("\(label)_lines=" + (try Row.fetchAll(db, sql: "SELECT product_id, COUNT(*) AS n FROM document_lines GROUP BY product_id ORDER BY product_id")
                .map { "\($0["product_id"] as Int64)x\($0["n"] as Int64)" }.joined(separator: ",")))
        }
    }

    func testCatalogEditingMatchesPython() throws {
        let ids = try q.read { try Int64.fetchAll($0, sql: "SELECT id FROM products ORDER BY id") }
        checks.append("ids=" + ids.map(String.init).joined(separator: ","))
        try state("start")
        checks.append("categories=" + (try q.read { try Catalog.categories($0) }).joined(separator: "|"))
        checks.append("docs_of=" + (try ids.map { id in "\(id):\(try q.read { try Catalog.productDocuments($0, id: id) })" }).joined(separator: ","))

        let new1 = try q.write { try Catalog.createProduct($0, nameVi: " Băng keo Y ", nameZh: "胶带Y", spec: "5cm", unit: "", category: "Keo", variant: "Xanh") }
        let new1Code = try q.read { try String.fetchOne($0, sql: "SELECT code FROM products WHERE id = ?", arguments: [new1]) ?? "" }
        checks.append("new1=\(new1):\(new1Code)")
        try q.write { try Catalog.updateProduct($0, id: new1, .init(nameVi: "Băng keo Y2", minStock: 7, active: false)) }
        try q.write { try Catalog.updateProduct($0, id: new1, .init()) }
        try state("edited")

        let new2 = try q.write { try Catalog.createProduct($0, nameVi: "Đinh", spec: "", unit: "hộp", category: "Sắt") }
        run("delete_unused") { try q.write { try Catalog.deleteProduct($0, id: new2) }; return "None" }
        let used = try ids.first { id in try q.read { try Catalog.productDocuments($0, id: id) } > 0 }!
        run("delete_used") { try q.write { try Catalog.deleteProduct($0, id: used) }; return "None" }
        try state("deleted")
        checks.append("next_code=" + (try q.read { try Catalog.nextProductCode($0) }))

        let a = try q.write { try Catalog.createProduct($0, nameVi: "Sơn M", spec: "5KG") }
        let b = try q.write { try Catalog.createProduct($0, nameVi: "Sơn M", nameZh: "油漆M", spec: "5KG", category: "Sơn") }
        try q.write { db in
            try db.execute(sql: "UPDATE products SET min_stock = 3 WHERE id = ?", arguments: [b])
            try Catalog.setAlias(db, key: "son m", productId: b, label: "Sơn M")
            try Catalog.updateProduct(db, id: b, .init(stockNote: "ghi chú b"))
            try Ledger.stockCount(db, date: "2026-11-14", counted: [Ledger.Counted(b, nil, 9)], note: "đếm")
        }
        run("merge_same") { String(try q.write { try Catalog.mergeProducts($0, a, a) }) }
        run("merge_missing") { String(try q.write { try Catalog.mergeProducts($0, a, 9999) }) }
        run("merge") { String(try q.write { try Catalog.mergeProducts($0, b, a) }) }
        try state("merged")
        checks.append("next_code_after_merge=" + (try q.read { try Catalog.nextProductCode($0) }))

        let items = [Catalog.CatalogItem(nameVi: "Băng keo Y2", spec: "5cm", variant: "Xanh", stock: 4),
                     Catalog.CatalogItem(nameVi: "BANG KEO Z", spec: "7cm", unit: "cuộn", category: "Keo", stock: 10),
                     Catalog.CatalogItem(nameVi: "Sơn M", spec: "5KG"),
                     Catalog.CatalogItem(nameVi: "Vít", nameZh: "螺丝", category: "Sắt", stock: 25)]
        run("import_no_stock") { let r = try q.write { try Catalog.importCatalog($0, Array(items[1..<2])) }; return "(\(r.created), \(r.skipped), \(r.counted))" }
        run("import_stock") {
            let r = try q.write { try Catalog.importCatalog($0, items, stockDate: "2026-11-15", note: "đợt nhập") }
            return "(\(r.created), \(r.skipped), \(r.counted))"
        }
        try state("imported")
        checks.append("log=" + (try q.read { try Row.fetchAll($0, sql: "SELECT action, detail FROM app_log WHERE action = 'catalog_import' ORDER BY id")
            .map { "\($0["action"] as String):\($0["detail"] as String)" }.joined(separator: ";") }))

        let sheet = Bundle.module.resourceURL!.appendingPathComponent("InboxFiles/catalog_sheet.xlsx")
        func num(_ d: Double?) -> String { d.map { String(format: "%.4f", $0) } ?? "∅" }
        func str(_ s: String) -> String { s.isEmpty ? "∅" : s }
        let cols = try CatalogSheet.columns(sheet)
        checks.append("sheet_stock_col=\(cols.stockCol.map(String.init) ?? "None")")
        checks.append("sheet_columns=" + cols.columns.map { "\($0.col)\($0.letter)[\($0.label)]" + $0.samples.joined(separator: "/") }.joined(separator: ";"))
        for it in try CatalogSheet.read(sheet) {
            checks.append("sheet_item=" + [num(Double(it.row)), str(it.nameVi), str(it.nameZh), str(it.spec), str(it.unit),
                                            str(it.category), str(it.variant), num(it.stock)].joined(separator: "|"))
        }
        for it in try CatalogSheet.read(sheet, stockCol: 3) { checks.append("sheet_stock_c=\(it.row):\(num(it.stock))") }

        XCTAssertEqual(checks.count, GoldenCatalog.checks.count)
        for (got, expected) in zip(checks, GoldenCatalog.checks) where got != expected {
            XCTFail("\n  Swift  \(got)\n  Python \(expected)")
        }
    }
}
