import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

/// Phase 3c: the stock issue note, the goods-receipt file and the files of input/ on the made-up shop. The same scenario as
/// tools/gen_issue.py (helpers, problems, four issue notes with deletes, four goods receipts with their files, the
/// files of input/) must give what the Python app gives (GoldenIssue), step by step.
///
/// The .xlsx files written here are also read back by the Swift reader (an issue note must give the lines the Python
/// reader reads in the Python file), and with DIBEKHO_XLSX_OUT set they are copied there for CI, where openpyxl compares
/// them cell by cell with the Python app's files (tools/check_xlsx.py).
final class IssueTests: XCTestCase {
    private var temp: URL!
    private var folders: ShopFolders!
    private var q: DatabaseQueue!
    private var checks: [String] = []
    private var kept: [String] = []
    private var readbacks: [String] = []
    private let c = Canon.self
    private var fm: FileManager { .default }
    private var fixtures: URL { Bundle.module.resourceURL!.appendingPathComponent("InboxFiles") }
    private var notes: URL { Bundle.module.resourceURL!.appendingPathComponent("ScanNotes") }

    override func setUpWithError() throws {
        temp = fm.temporaryDirectory.appendingPathComponent("issue-\(UUID().uuidString)")
        folders = ShopFolders(root: temp.appendingPathComponent("work"))
        try fm.createDirectory(at: folders.deliveriesDone, withIntermediateDirectories: true)
        try fm.createDirectory(at: folders.input, withIntermediateDirectories: true)
        Deliveries.knownRate = { nil }
        q = try DatabaseQueue(configuration: Store.configuration())
        try Schema.migrate(q)
        try q.write { db in
            for statement in Schema.split(Golden.shop) { try db.execute(sql: statement) }
            try Meta.set(db, "freed_codes", "SP010,SP008")
            try Meta.set(db, "product_code_max", "4")
            try Meta.set(db, Deliveries.letterheadKey, "[\"CÔNG TY MẪU\", \"Hà Nội\"]")
        }
    }

    override func tearDownWithError() throws {
        Deliveries.knownRate = { FXCache.rate() }
        try? fm.removeItem(at: temp)
    }

    // ---- helpers, the ones of the generator

    private func write<T>(_ body: (Database) throws -> T) throws -> T { try q.write(body) }

    private func run(_ name: String, _ body: () throws -> String) {
        do {
            checks.append("\(name)=\(try body())")
        } catch let e as WriteError {
            checks.append("\(name)!\(e.message)")
        } catch {
            checks.append("\(name)?\(error)")
        }
    }

    private func stampFree(_ text: String) -> String {
        text.replacingOccurrences(of: #"__\d{8}-\d{6}"#, with: "__T", options: .regularExpression)
    }

    private func layout() -> String {
        let names = (fm.enumerator(atPath: folders.root.path)?.allObjects as? [String]) ?? []
        return names.filter { name in
            var dir: ObjCBool = false
            fm.fileExists(atPath: folders.root.appendingPathComponent(name).path, isDirectory: &dir)
            return !dir.boolValue && !name.hasPrefix("data/") && !name.hasPrefix("sao-luu/")
        }.map { stampFree($0.precomposedStringWithCanonicalMapping) }
            .sorted { Deliveries.scalarsLess($0, $1) }.joined(separator: ",")
    }

    private func relative(_ url: URL) -> String { url.path.replacingOccurrences(of: folders.root.path + "/", with: "") }

    private func levels(_ label: String) throws {
        let text = try q.read { try Ledger.levelsByPlace($0).sorted { $0.key < $1.key }
            .map { "\($0.key.productId)/\($0.key.locationId):\(c.canon($0.value))" }.joined(separator: ",") }
        checks.append("levels_\(label)=" + text)
    }

    private func scan(_ label: String) throws {
        let r = try Deliveries.scan(q, folders)
        checks.append("scan_\(label)=imported:\(r.imported.joined(separator: ","))|pending:\(r.pending)|copies:\(r.copies.joined(separator: ","))")
    }

    /// A column as the generator prints it: nothing = ∅, numbers with 4 decimals.
    private func cell(_ db: Database, _ column: String, _ docId: Int64) throws -> String {
        let value = try DatabaseValue.fetchOne(db, sql: "SELECT \(column) FROM documents WHERE id = ?", arguments: [docId]) ?? .null
        switch value.storage {
        case .null: return "∅"
        case let .int64(i): return String(format: "%.4f", Double(i))
        case let .double(d): return String(format: "%.4f", d)
        case let .string(s): return s
        case .blob: return "<blob>"
        }
    }

    private func docLine(_ docId: Int64) throws -> String {
        try q.read { db in
            let d = try Row.fetchOne(db, sql: """
                SELECT d.*, COALESCE(c.name, '') AS customer FROM documents d LEFT JOIN customers c ON c.id = d.customer_id
                WHERE d.id = ?
                """, arguments: [docId])!
            let lines = try Row.fetchAll(db, sql: "SELECT product_id, qty, unit_price, amount, note FROM document_lines WHERE document_id = ? ORDER BY line_no",
                                         arguments: [docId]).map {
                "\($0["product_id"] as Int64):\(c.canon($0["qty"] as Double?)):\(c.canon($0["unit_price"] as Double?)):\(c.canon($0["amount"] as Double?)):\($0["note"] as String? ?? "")"
            }
            let moves = try Row.fetchAll(db, sql: "SELECT product_id, location_id, qty FROM stock_movements WHERE document_id = ? ORDER BY id",
                                         arguments: [docId]).map {
                "\($0["product_id"] as Int64)/\($0["location_id"] as Int64):\(c.canon($0["qty"] as Double?))"
            }
            let location: Int64? = d["location_set"]
            return "\(d["code"] as String)|\(d["doc_date"] as String)|\(d["status"] as String)|\(d["customer"] as String)|\(d["source_file"] as String)|\(c.canon(location))"
                + "|L:" + lines.joined(separator: ",") + "|M:" + moves.joined(separator: ",")
        }
    }

    /// The file is a reference: copied for CI, and read back by the Swift reader (issue notes).
    private func keep(_ url: URL, _ label: String) throws {
        kept.append(label)
        if let out = ProcessInfo.processInfo.environment["DIBEKHO_XLSX_OUT"], !out.isEmpty {
            try fm.createDirectory(atPath: out, withIntermediateDirectories: true)
            let target = URL(fileURLWithPath: out).appendingPathComponent("\(label).xlsx")
            try? fm.removeItem(at: target)
            try fm.copyItem(at: url, to: target)
        }
        if label.hasPrefix("issue") { readbacks.append(label + "::" + NoteLines.lines(url).joined(separator: "\n")) }
    }

    private func py(_ problems: [(String, [String: String])]) -> String {
        "[" + problems.map { key, values in
            let items = values.sorted { $0.key < $1.key }.map { k, v in "'\(k)': " + (k == "id" ? v : "'\(v)'") }
            return "('\(key)', {\(items.joined(separator: ", "))})"
        }.joined(separator: ", ") + "]"
    }

    private func issueSave(_ label: String, _ data: Issues.Input) throws -> Int64 {
        let (doc, url) = try write { try Issues.save($0, folders, data) }
        checks.append("\(label)_file=\(relative(url))")
        try keep(url, label)
        checks.append("\(label)_doc=" + (try docLine(doc)))
        checks.append("\(label)_layout=" + layout())
        return doc
    }

    private func receiptSave(_ label: String, _ data: Receipts.Input, replaces: Int64? = nil) throws -> Int64 {
        let doc = try write { try Receipts.save($0, data, replaces: replaces, outputFolder: folders.output) }
        let url = try write { try Receipts.exportFile($0, folders, docId: doc) }
        checks.append("\(label)_file=\(relative(url))")
        try keep(url, label)
        checks.append("\(label)_doc=" + (try docLine(doc)))
        let head = try q.read { db in
            try ["receipt_source", "supplier_id", "customer_id", "ref_code", "note", "prices_read", "currency"].map { try cell(db, $0, doc) }
        }
        checks.append("\(label)_head=" + head.joined(separator: "|"))
        return doc
    }

    // ---- the scenario

    func testIssueNotesReceiptFilesAndInputDoWhatPythonDoes() throws {
        // 1. helper functions
        for amount in [0.0, 1, 15, 21, 100, 105, 115, 1000, 1001, 2376000, 1987654320, 21500000, 1100100, 10000000000, 999.5, 0.4] {
            let shown = amount == amount.rounded() ? String(Int(amount)) : String(amount)
            checks.append("words_\(shown)=" + IssueNote.vndWords(amount))
        }
        for value in [3.0, 2.5, 0.1, 1234.0, 7.25, 100000.0] { checks.append("number_text_\(value)=" + IssueNote.numberText(value)) }
        for codes in [["076", "077"], ["A80", "W90", "12"], [], ["abc", "A5", " 007 "], ["A", "W1x"]] as [[String]] {
            checks.append("next_code_\(codes.isEmpty ? "none" : codes.joined(separator: "-"))=\(Issues.nextCode(codes))|\(Issues.nextCode(codes, prefix: "W"))")
        }
        checks.append("is_issue_code=" + ["A160", "w9", " A1 ", "160", "AB1", "", ""].enumerated().map { i, code in
            i == 6 ? "False" : (Issues.isIssueCode(code) ? "True" : "False")
        }.joined(separator: ","))
        checks.append("new_code_start=" + (try q.read { try Issues.newCode($0) }))
        let prices: [(String, Int64?)] = [("Công ty A", 1), ("Công ty A", 2), ("Khách Mẫu", 3), ("Khách Mẫu", 1), ("", 1),
                                         ("Nobody", 3), ("Công ty A", nil), ("Công ty A", 99)]
        checks.append("last_price=" + (try q.read { db in
            try prices.map { c.canon(try Issues.lastPrice(db, customerName: $0.0, productId: $0.1)) }.joined(separator: ",")
        }))

        // 2. problems and warnings
        let newX = NewProduct("Màng chống thấm X", spec: "3mm", unit: "cuộn", category: "Màng")
        let day = "2026-11-14"
        checks.append("problems_empty=" + py(Issues.problems(Issues.Input(date: day, customerName: ""))))
        checks.append("problems_no_lines=" + py(Issues.problems(Issues.Input(date: day, customerName: "Công ty A"))))
        checks.append("problems_negative=" + py(Issues.problems(Issues.Input(date: day, customerName: "A", lines: [
            Issues.LineInput(productId: 1, qtyMain: 2, qtyOffice: 0, unitPrice: -5), Issues.LineInput(productId: 2, qtyMain: -1, qtyOffice: 3)]))))
        checks.append("problems_new_no_name=" + py(Issues.problems(Issues.Input(date: day, customerName: "A", lines: [
            Issues.LineInput(productId: nil, qtyMain: 1, new: NewProduct(" "))]))))
        let big = Issues.Input(date: day, customerName: "Công ty A", lines: [
            Issues.LineInput(productId: 1, qtyMain: 100, qtyOffice: 5), Issues.LineInput(productId: 1, qtyMain: 1),
            Issues.LineInput(productId: 2, qtyMain: 0, qtyOffice: 3), Issues.LineInput(productId: 3, qtyMain: 1),
            Issues.LineInput(productId: nil, qtyMain: 2, new: newX)])
        checks.append("short_of=" + (try q.read { try Issues.shortOf($0, big) }).map {
            "\($0.productId)/\($0.locationId):\(c.canon($0.asked)):\(c.canon($0.have))"
        }.joined(separator: ","))
        let same = Issues.Input(date: day, customerName: "A", lines: [
            Issues.LineInput(productId: nil, qtyMain: 1, new: NewProduct("Keo FS 101", spec: "5KG")),
            Issues.LineInput(productId: nil, qtyMain: 1, new: newX)])
        checks.append("same_as_existing=" + (try q.read { try Issues.sameAsExisting($0, same) }).map {
            "\(same.lines[$0.index].new!.nameVi)->\($0.existing.code)"
        }.joined(separator: ","))
        run("save_nothing") {
            _ = try write { try Issues.save($0, folders, Issues.Input(date: day, customerName: "Công ty A")) }
            return "None"
        }
        checks.append("products_after_nothing=\(try q.read { try Int.fetchOne($0, sql: "SELECT COUNT(*) FROM products")! })")

        // 3. issue notes
        let first = try issueSave("issue_1", Issues.Input(
            date: day, customerName: "Công ty A", phone: "0900 000 001", contact: "Anh B", address: "1 Đường X, Hà Nội", taxCode: "0101234567", email: "a@example.com", lines: [
                Issues.LineInput(productId: 1, qtyMain: 2, qtyOffice: 1, unitPrice: 390000, note: "giao sáng"),
                Issues.LineInput(productId: 1, qtyMain: 1, unitPrice: 512500.5),
                Issues.LineInput(productId: 2, qtyMain: 1.5),
                Issues.LineInput(productId: nil, qtyMain: 4, unitPrice: 100000, new: newX),
                Issues.LineInput(productId: 3, qtyMain: 0, qtyOffice: 0, unitPrice: 5)]))
        checks.append("new_product=" + (try q.read { db in
            try Row.fetchAll(db, sql: "SELECT * FROM products WHERE id > 4").map {
                "\($0["code"] as String):\($0["name_vi"] as String):\($0["spec"] as String):\($0["unit"] as String):\($0["category"] as String)"
            }.joined(separator: ",")
        }))
        try levels("after_1")
        let second = try issueSave("issue_2", Issues.Input(
            date: "2026-11-15", customerName: "Đại lý Mới", phone: "0911 222 333", address: "Đà Nẵng", lines: [
                Issues.LineInput(productId: 1, qtyMain: 0, qtyOffice: 2, unitPrice: 380000,
                                 note: String(repeating: "A very long note, ", count: 8)),
                Issues.LineInput(productId: 3, qtyMain: 3, unitPrice: 1200000)]))
        try levels("after_2")
        checks.append("customer_new=" + (try q.read { db in
            try Row.fetchAll(db, sql: "SELECT * FROM customers WHERE id > 3").map {
                "\($0["name"] as String)|\($0["phone"] as String)|\($0["phone_norm"] as String)|\($0["address"] as String)"
            }.joined(separator: ",")
        }))
        checks.append("new_code_next=" + (try q.read { try Issues.newCode($0) }))
        try scan("again")
        checks.append("scan_layout=" + layout())
        try levels("after_scan")
        run("delete_shop_note") { String(try write { try Issues.delete($0, folders, docId: 2) }) }
        run("delete_second") { String(try write { try Issues.delete($0, folders, docId: second) }) }
        checks.append("delete_second_layout=" + layout())
        checks.append("new_code_after_delete=" + (try q.read { try Issues.newCode($0) }))
        try levels("after_delete_2")
        try scan("after_delete")
        let third = try issueSave("issue_3", Issues.Input(
            date: "2026-11-16", customerName: "Khách Mẫu", phone: "0900 000 002", lines: [
                Issues.LineInput(productId: 2, qtyMain: 0, qtyOffice: 1, unitPrice: 160000, note: "một can")]))
        _ = third
        run("delete_first") { String(try write { try Issues.delete($0, folders, docId: first) }) }
        checks.append("delete_first_layout=" + layout())
        try levels("after_delete_1")

        // a note corrected (customer's request 19/11/2026): same code, the old file to da-sua, stock counted again
        func headOf(_ d: Issues.Input) -> String {
            [d.date, d.customerName, d.phone, d.contact, d.address, d.taxCode, d.email].joined(separator: "|")
        }
        func linesOf(_ d: Issues.Input) -> String {
            d.lines.map { "\($0.productId.map(String.init) ?? "nil"):\(c.canon($0.qtyMain)):\(c.canon($0.qtyOffice)):\(c.canon($0.unitPrice)):\($0.note)" }
                .joined(separator: ",")
        }
        run("edit_load_shop_note") { String(try q.read { try Issues.load($0, docId: 2) }.code) }
        let loaded = try q.read { try Issues.load($0, docId: third) }
        checks.append("edit_load=\(loaded.code)|\(headOf(loaded.data))|\(linesOf(loaded.data))")
        var changed = loaded.data
        changed.taxCode = "0100000002"
        changed.email = "khach@example.com"
        changed.lines[0].unitPrice = 170000
        changed.lines[0].qtyMain = 1
        changed.lines.append(Issues.LineInput(productId: 1, qtyMain: 2, qtyOffice: 0, unitPrice: 390000, note: "thêm"))
        let toEdit = changed
        run("edit_shop_note") { String(try write { try Issues.edit($0, folders, docId: 2, toEdit).docId }) }
        let (doc4, path4) = try write { try Issues.edit($0, folders, docId: third, toEdit) }
        checks.append("issue_edit_file=\(relative(path4))")
        try keep(path4, "issue_edit")
        checks.append("issue_edit_doc=" + (try docLine(doc4)))
        checks.append("issue_edit_layout=" + layout())
        try levels("after_edit")
        let again = try q.read { try Issues.load($0, docId: doc4) }
        checks.append("edit_load_again=" + headOf(again.data) + "|" + linesOf(again.data))
        checks.append("new_code_after_edit=" + (try q.read { try Issues.newCode($0) }))
        try scan("after_edit")

        // a yuan note (user, 21/11/2026): the prices as typed, the file in CNY, the document CNY with the window's rate
        let cnyDoc = try issueSave("issue_cny", Issues.Input(
            date: "2026-11-17", customerName: "Công ty A", phone: "0900 000 001", lines: [
                Issues.LineInput(productId: 1, qtyMain: 1, qtyOffice: 0, unitPrice: 101.5, note: ""),
                Issues.LineInput(productId: 2, qtyMain: 2, qtyOffice: 0, unitPrice: 12.25, note: "")],
            currency: "CNY", fxRate: 3800))
        let money = try q.read { db in
            try Row.fetchOne(db, sql: "SELECT currency, fx_rate FROM documents WHERE id = ?", arguments: [cnyDoc])!
        }
        checks.append("issue_cny_money=\(money["currency"] as String? ?? "")|\(c.canon(money["fx_rate"] as Double?))")
        let cnyLoaded = try q.read { try Issues.load($0, docId: cnyDoc) }.data
        checks.append("issue_cny_load=\(cnyLoaded.currency)|\(c.canon(cnyLoaded.fxRate))|\(linesOf(cnyLoaded))")
        let cnyAsks: [(Int64, String, Double?)] = [(1, "CNY", nil), (1, "VND", nil), (1, "VND", 4000), (3, "CNY", 4000), (3, "CNY", nil)]
        let cnyPrices = try q.read { db in
            try cnyAsks.map { try Issues.lastPrice(db, customerName: "Công ty A", productId: $0.0, currency: $0.1, vndPerCny: $0.2) }
        }
        checks.append("last_price_cny=" + cnyPrices.map { c.canon($0) }.joined(separator: ","))
        checks.append("cny_words=" + [0, 0.07, 12, 1250.5, 2376000.99].map { IssueNote.cnyWords($0) }.joined(separator: ","))
        try levels("after_cny")

        // the customer's own details (Sửa thông tin khách hàng)
        func customerLine(_ id: Int64) throws -> String {
            try q.read { db in
                let r = try Row.fetchOne(db, sql: "SELECT * FROM customers WHERE id = ?", arguments: [id])!
                return ["name", "phone", "phone_norm", "contact", "address", "tax_code", "email"]
                    .map { r[$0] as String? ?? "" }.joined(separator: "|")
            }
        }
        func owner(_ phone: String, _ other: Int64? = nil) throws -> String {
            try q.read { db in (try Catalog.customerOwningPhone(db, phone, otherThan: other)).map { $0["name"] as String? ?? "" } ?? "-" }
        }
        func named(_ name: String, _ other: Int64? = nil) throws -> String {
            try q.read { db in (try Catalog.customerNamed(db, name, otherThan: other)).map { $0["name"] as String? ?? "" } ?? "-" }
        }
        checks.append("cust_owning=\(try owner("0900 000 001")),\(try owner("+84 900 000 002", 2)),\(try owner("0900 000 002", 2)),\(try owner(""))")
        checks.append("cust_named=\(try named("cong ty a")),\(try named("Công ty A", 1)),\(try named("Không có"))")
        run("cust_update") {
            try write { try Catalog.updateCustomer($0, id: 3, ["name": "  Đại lý Hải Phòng ", "phone": "091 111 2222",
                                                              "tax_code": "0100000003", "email": " hp@example.com "]) }
            return "None"
        }
        checks.append("cust_after=" + (try customerLine(3)))
        run("cust_update_empty_name") {
            try write { try Catalog.updateCustomer($0, id: 3, ["name": "  "]) }
            return "None"
        }
        checks.append("cust_after_empty=" + (try customerLine(3)))

        // 4. goods receipts and their files
        let r1 = try receiptSave("receipt_1", Receipts.Input(
            date: "2026-11-15", source: "supplier", supplierName: "Công ty mẹ", note: "đợt 4", lines: [
                Receipts.LineInput(20, 1), Receipts.LineInput(10.5, 2, note: "móp"),
                Receipts.LineInput(7, new: NewProduct("Băng keo X", nameZh: "胶带", spec: "10cm", variant: "Đỏ", unit: "cuộn", category: "Keo"))]))
        _ = try receiptSave("receipt_2", Receipts.Input(
            date: "2026-11-16", source: "return", customerName: "Công ty A", customerId: 1, refCode: "076", lines: [
                Receipts.LineInput(2, 1, unitPrice: 380000), Receipts.LineInput(1, 2, note: "trả 1 can")]))
        _ = try receiptSave("receipt_3", Receipts.Input(
            date: "2026-11-17", source: "other", supplierName: "Nhà X 供应商", lines: [Receipts.LineInput(4, 3)],
            locationId: Ledger.office))
        _ = try receiptSave("receipt_4", Receipts.Input(
            date: "2026-11-15", source: "supplier", supplierName: "Công ty mẹ", note: "đợt 4 (sửa)", lines: [
                Receipts.LineInput(25, 1), Receipts.LineInput(10.5, 2, note: "móp")]), replaces: r1)
        checks.append("receipt_layout=" + layout())
        try levels("after_receipts")
        checks.append("next_receipt_code=" + (try q.read { try Receipts.nextCode($0, outputFolder: folders.output) }))
        func readText(_ name: String, warnings: Bool) throws -> String {
            let read = try ReceiptFile.read(folders.output.appendingPathComponent("hang-ve").appendingPathComponent(name))
            return "\(read.date)|\(read.note)|" + read.lines.map { "\($0.row):\($0.code):\(c.canon($0.qty))" }.joined(separator: ",")
                + (warnings ? "|" + read.warnings.joined(separator: "/") : "")
        }
        checks.append("read_receipt_1=" + (try readText("HangVe_HV003_2026-11-15.xlsx", warnings: true)))
        checks.append("read_receipt_HV004=" + (try readText("HangVe_HV004_2026-11-16.xlsx", warnings: false)))
        checks.append("read_receipt_HV005=" + (try readText("HangVe_HV005_2026-11-17.xlsx", warnings: false)))

        // 5. files of input/
        for name in ["hangve-dien.xlsx", "hangve-ma-la.xlsx", "hangve-khong-ngay.xlsx", "hangve-trong.xlsx", "hangve-ngay-sai.xlsx"] {
            try fm.copyItem(at: fixtures.appendingPathComponent(name), to: folders.input.appendingPathComponent(name))
        }
        try fm.copyItem(at: notes.appendingPathComponent("n201.xlsx"), to: folders.input.appendingPathComponent("phieu-giao-hang.xlsx"))
        try fm.copyItem(at: notes.appendingPathComponent("broken.xlsx"), to: folders.input.appendingPathComponent("hong.xlsx"))
        try "ghi chú".write(to: folders.input.appendingPathComponent("ghi-chu.txt"), atomically: true, encoding: .utf8)
        try Data("lock".utf8).write(to: folders.input.appendingPathComponent("~$khoa.xlsx"))
        try Data("hidden".utf8).write(to: folders.input.appendingPathComponent(".an.xlsx"))
        let hangVe = folders.output.appendingPathComponent("hang-ve")
        try fm.copyItem(at: hangVe.appendingPathComponent("HangVe_HV003_2026-11-15.xlsx"), to: folders.input.appendingPathComponent("hangve-da-nhap.xlsx"))
        try fm.copyItem(at: hangVe.appendingPathComponent("HangVe_HV003_2026-11-15_2.xlsx"), to: folders.input.appendingPathComponent("hangve-da-sua.xlsx"))

        func inboxText(_ item: InboxItem) -> String {
            var message = item.message
            if message.hasPrefix("Không phải file hàng về hay") {
                message = "NOT_RECEIPT"
            } else if message.hasPrefix("Không mở được file Excel") {
                message = "Không mở được file Excel"
            }
            var detail = ""
            if let receipt = item.receipt {
                detail = "\(receipt.date)|\(receipt.note)|" + item.resolved.map {
                    "\($0.line.row):\($0.line.code):\(c.canon($0.line.qty)):\($0.product.map { String($0.id) } ?? "-")"
                }.joined(separator: ",") + "|" + receipt.warnings.joined(separator: "/")
            }
            return "\(item.name)|\(item.kind == .receipt ? "receipt" : "error")|\(message)|\(detail)"
        }
        func listing(_ label: String) throws {
            checks.append("inbox_\(label)=" + (try q.read { try Inbox.items($0, folders) }).map(inboxText).joined(separator: " ;; "))
            checks.append("inbox_\(label)_layout=" + layout())
        }
        func read(_ url: URL) throws -> InboxItem { try q.read { try Inbox.readItem($0, url) } }

        try listing("start")
        let item = try read(folders.input.appendingPathComponent("hangve-dien.xlsx"))
        let applied = try write { try Inbox.applyReceipt($0, item) }
        Inbox.done(folders, item.url)
        checks.append("apply_doc=" + (try docLine(applied)))
        try levels("after_apply")
        try listing("applied")
        let bad = try read(folders.input.appendingPathComponent("hangve-ma-la.xlsx"))
        try write { try Inbox.hide($0, bad) }
        try listing("hidden")
        let empty = try read(folders.input.appendingPathComponent("hangve-trong.xlsx"))
        try write { try Inbox.hide($0, empty) }
        Inbox.discard(folders, try read(folders.input.appendingPathComponent("hangve-da-sua.xlsx")))
        try listing("end")
        let elsewhere = temp.appendingPathComponent("elsewhere")
        try fm.createDirectory(at: elsewhere, withIntermediateDirectories: true)
        // the good file, as it was before it moved
        try fm.copyItem(at: fixtures.appendingPathComponent("hangve-dien.xlsx"), to: elsewhere.appendingPathComponent("hangve-khac.xlsx"))
        checks.append("elsewhere=" + inboxText(try read(elsewhere.appendingPathComponent("hangve-khac.xlsx"))))
        Inbox.done(folders, elsewhere.appendingPathComponent("hangve-khac.xlsx"))
        checks.append("elsewhere_stays=" + (fm.fileExists(atPath: elsewhere.appendingPathComponent("hangve-khac.xlsx").path) ? "True" : "False"))

        // merging customers (Gộp khách hàng)
        func customersState() throws -> String {
            try q.read { db in
                let rows = try Row.fetchAll(db, sql: "SELECT id, name, tax_code, email FROM customers ORDER BY id")
                    .map { "\($0["id"] as Int64):\($0["name"] as String? ?? ""):\($0["tax_code"] as String? ?? ""):\($0["email"] as String? ?? "")" }
                let docs = try Row.fetchAll(db, sql: "SELECT customer_id, COUNT(*) AS n FROM documents WHERE customer_id IS NOT NULL GROUP BY customer_id ORDER BY customer_id")
                    .map { "\($0["customer_id"] as Int64)x\($0["n"] as Int64)" }
                return rows.joined(separator: ";") + "#" + docs.joined(separator: ",")
            }
        }
        checks.append("merge_before=" + (try customersState()))
        run("merge_one") { String(try write { try Catalog.mergeCustomers($0, ids: [1], name: "X") }) }
        run("merge_no_name") { String(try write { try Catalog.mergeCustomers($0, ids: [1, 2], name: "  ") }) }
        run("merge_existing_name") { String(try write { try Catalog.mergeCustomers($0, ids: [2, 3], name: " dai ly hai phong ") }) }
        checks.append("merge_after_1=" + (try customersState()))
        run("merge_new_name") { String(try write { try Catalog.mergeCustomers($0, ids: [1, 3], name: " Văn phòng DiBeKho ") }) }
        checks.append("merge_after_2=" + (try customersState()))
        checks.append("merge_phone_owner=" + (try owner("091 111 2222")))

        // ---- compare
        XCTAssertEqual(checks.count, GoldenIssue.checks.count)
        for (got, expected) in zip(checks, GoldenIssue.checks) where got != expected {
            XCTFail("\n  Swift  \(got)\n  Python \(expected)")
        }
        XCTAssertEqual(kept, GoldenIssue.files)
        XCTAssertEqual(readbacks.count, GoldenIssue.readback.count)
        for (got, expected) in zip(readbacks, GoldenIssue.readback) where got != expected {
            XCTFail("a note read back differs:\n  Swift  \(got)\n  Python \(expected)")
        }
        try q.read { db in
            for (table, expected) in GoldenIssue.tables {
                let got = try Self.dump(db, table)
                XCTAssertEqual(got.count, expected.count, table)
                for (i, (a, b)) in zip(got, expected).enumerated() where a != b {
                    XCTFail("\(table) row \(i + 1):\n  Swift  \(a)\n  Python \(b)")
                }
            }
        }
    }

    /// Every column but the times, rows in rowid order, hashes as H, as the generator prints them.
    static func dump(_ db: Database, _ table: String) throws -> [String] {
        let skip: Set<String> = ["created_at", "closed_at", "at", "first_seen", "last_seen"]
        let cols = try Row.fetchAll(db, sql: "PRAGMA table_info(\(table))").map { $0["name"] as String }.filter { !skip.contains($0) }
        return try Row.fetchAll(db, sql: "SELECT \(cols.joined(separator: ", ")) FROM \(table) ORDER BY rowid").map { row in
            let key: String? = table == "meta" ? row["key"] : nil
            return cols.map { col -> String in
                let value: DatabaseValue = row[col]
                if col == "source_hash" || col == "hash" {
                    let text = String.fromDatabaseValue(value)
                    return "\(col)=" + (text == nil || text == "" ? "∅" : "H")
                }
                if key == "last_change_at" && col == "value" || key == "count_checked" && col == "value" { return "\(col)=T" }
                switch value.storage {
                case .null: return "\(col)=∅"
                case let .int64(i): return "\(col)=\(String(format: "%.4f", Double(i)))"
                case let .double(d): return "\(col)=\(String(format: "%.4f", d))"
                case let .string(s): return "\(col)=" + s.replacingOccurrences(of: #"__\d{8}-\d{6}"#, with: "__T", options: .regularExpression)
                case .blob: return "\(col)=<blob>"
                }
            }.joined(separator: "|")
        }
    }

    // ---- the written files stay inside the folders, and what Excel needs is there

    func testTheWrittenFileIsAWorkbookExcelOpens() throws {
        let url = temp.appendingPathComponent("one.xlsx")
        let head = IssueNote.Head(code: "A1", date: "2026-11-14", customer: "Khách & <Mẫu>", letterhead: ["CÔNG TY", "Hà Nội"])
        try IssueNote.write(url, head, [IssueNote.Row(code: "SP001", nameVi: "Sơn", nameZh: "涂料", spec: "20KG", qty: 2,
                                                         places: [(1, 2)], unitPrice: 100, amount: 200, note: "a\u{1}b")])
        let sheets = try Xlsx.read(url)
        XCTAssertEqual(sheets.count, 1)
        XCTAssertEqual(sheets[0].name, IssueNote.sheetName)
        XCTAssertTrue(sheets[0].rows[4][0]?.pythonText.contains("Khách & <Mẫu>") == true)
        // 'a\u{1}b': a character XML cannot hold is dropped, the rest stays
        XCTAssertEqual(sheets[0].rows[9][6]?.pythonText, "ab")  // the header is row 9 (index 8), the one line follows
    }
}
