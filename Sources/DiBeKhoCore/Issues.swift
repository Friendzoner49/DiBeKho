import Foundation
import GRDB

/// Phiếu xuất kho (core/issues.py): the user picks a customer and the goods, says how many come from Kho tổng and how
/// many from Văn phòng, and the app writes the note (IssueNote) and records it at once through the very path a
/// delivery note dropped into phieu-giao-hang/ takes. So the note is an ordinary delivery: it lowers the stock of each
/// place, its prices count in the customer's revenue, it can be cancelled or read again, and the file put back into
/// the folder later is recognised (same content) and never counted twice.
///
/// Files: output/phieu-xuat/PhieuXuat_<code>.xlsx (the user's copy) and phieu-giao-hang/da-xu-ly/ (the copy the scan sees).
/// A line may be a product not in the catalog yet (★ Mặt hàng mới): it is created on save and its stock goes below zero.
/// Codes: A + the number after the highest order number so far; the web page writes W…, the shop's own notes stay apart.
public enum Issues {
    public static let prefix = "A"
    public static let filePrefix = "PhieuXuat_"
    public static let folder = "phieu-xuat"
    public static let deleted = "da-xoa"
    /// the old version of a corrected note (output/phieu-xuat/da-sua/)
    public static let edited = "da-sua"
    /// draft orders (customer's request 21/11/2026, issues.py): output/phieu-xuat/nhap/PhieuXuat_NHAP_N1.xlsx, nothing
    /// recorded; once a real note, the file goes to nhap/da-chot/
    public static let drafts = "nhap"
    public static let draftsDone = "da-chot"
    public static let draftPrefix = "N"
    public static let draftFilePrefix = "PhieuXuat_NHAP_"

    public struct LineInput {
        public var productId: Int64?
        public var qtyMain = 0.0
        public var qtyOffice = 0.0
        public var unitPrice: Double?
        public var note = ""
        /// not in the catalog yet: created on save
        public var new: NewProduct?
        public init(productId: Int64?, qtyMain: Double = 0, qtyOffice: Double = 0, unitPrice: Double? = nil,
                    note: String = "", new: NewProduct? = nil) {
            self.productId = productId; self.qtyMain = qtyMain; self.qtyOffice = qtyOffice
            self.unitPrice = unitPrice; self.note = note; self.new = new
        }
        public var qty: Double { qtyMain + qtyOffice }
    }

    public struct Input {
        /// yyyy-mm-dd
        public var date: String
        public var customerName: String
        public var phone = ""
        public var contact = ""
        public var address = ""
        public var taxCode = ""
        public var email = ""
        public var lines: [LineInput] = []
        /// "CNY": the prices are yuan, as typed while the ₫ | ¥ switch shows yuan (user, 21/11/2026); the note is
        /// written and recorded in yuan. fxRate: dong for one yuan the window used, kept on the document.
        public var currency = "VND"
        public var fxRate: Double?
        public init(date: String, customerName: String, phone: String = "", contact: String = "", address: String = "",
                    taxCode: String = "", email: String = "", lines: [LineInput] = [], currency: String = "VND",
                    fxRate: Double? = nil) {
            self.date = date; self.customerName = customerName; self.phone = phone; self.contact = contact
            self.address = address; self.taxCode = taxCode; self.email = email; self.lines = lines
            self.currency = currency; self.fxRate = fxRate
        }
        public var filled: [LineInput] { lines.filter { ($0.productId != nil || $0.new != nil) && $0.qty > 0 } }
    }

    // MARK: codes

    /// prefix + 1 + the highest order number among codes ('159', '076', 'A160', 'W161'); other codes are not counted.
    public static func nextCode(_ codes: [String], prefix: String = Issues.prefix) -> String {
        let pattern = try! NSRegularExpression(pattern: #"^\s*[AaWw]?\s*0*(\d{1,9})\s*$"#)
        var highest = 0
        for code in codes {
            let range = NSRange(code.startIndex..., in: code)
            if let m = pattern.firstMatch(in: code, range: range), let r = Range(m.range(at: 1), in: code),
               let n = Int(code[r]) { highest = max(highest, n) }
        }
        return "\(prefix)\(highest + 1)"
    }

    /// Every delivery ever recorded counts, cancelled ones too (a number is never reused).
    public static func newCode(_ db: Database) throws -> String {
        nextCode(try String.fetchAll(db, sql: "SELECT code FROM documents WHERE kind = 'delivery'"))
    }

    /// A160 (made in the app) or W160 (made on the web): a stock issue note, which may be deleted.
    public static func isIssueCode(_ code: String) -> Bool { Deliveries.isIssueCode(code) }

    // MARK: checks

    /// What stops the note from being saved: (i18n key, values).
    public static func problems(_ data: Input) -> [(String, [String: String])] {
        var found: [(String, [String: String])] = []
        if TextRules.clean(data.customerName).isEmpty { found.append(("issue.need_customer", [:])) }
        if data.filled.isEmpty { found.append(("issue.need_lines", [:])) }
        for ln in data.filled {
            if let n = ln.new, TextRules.clean(n.nameVi).isEmpty {
                found.append(("receipt_form.new_needs_name", [:]))
            } else if ln.qtyMain < 0 || ln.qtyOffice < 0 || (ln.unitPrice ?? 0) < 0 {
                found.append(("issue.negative", ln.new.map { ["product": $0.label] } ?? ["id": String(ln.productId ?? 0)]))
            }
        }
        return found
    }

    /// New products that may already be in the catalog: the user should pick those instead.
    public static func sameAsExisting(_ db: Database, _ data: Input) throws -> [(index: Int, existing: Product)] {
        var out: [(index: Int, existing: Product)] = []
        var seen = Set<[String]>()
        for (i, ln) in data.lines.enumerated() where (ln.productId != nil || ln.new != nil) && ln.qty > 0 {
            guard let n = ln.new, !seen.contains(n.key) else { continue }
            seen.insert(n.key)
            if let found = try Catalog.findPossibleDuplicates(db, nameVi: n.nameVi, nameZh: n.nameZh, spec: n.spec,
                                                              variant: n.variant).first {
                out.append((index: i, existing: found))
            }
        }
        return out
    }

    /// Products asked for more than a place has now: (product, place, asked, in stock). Only a warning: stock may go
    /// below zero (the row turns red).
    /// old: the note being replaced, its goods count as free.
    public static func shortOf(_ db: Database, _ data: Input, old: Input? = nil) throws -> [(productId: Int64, locationId: Int64, asked: Double, have: Double)] {
        var levels = try Ledger.levelsByPlace(db)
        for ln in old?.filled ?? [] {
            guard let pid = ln.productId else { continue }
            for (loc, qty) in [(Ledger.main, ln.qtyMain), (Ledger.office, ln.qtyOffice)] {
                levels[Ledger.PlaceKey(pid, loc), default: 0] += qty
            }
        }
        var asked: [Ledger.PlaceKey: Double] = [:]
        var order: [Ledger.PlaceKey] = []  // the order the lines come in, as Python's dict keeps it
        for ln in data.filled {
            guard let pid = ln.productId else { continue }
            for (loc, qty) in [(Ledger.main, ln.qtyMain), (Ledger.office, ln.qtyOffice)] where qty != 0 {
                let key = Ledger.PlaceKey(pid, loc)
                if asked[key] == nil { order.append(key) }
                asked[key, default: 0] += qty
            }
        }
        var out: [(productId: Int64, locationId: Int64, asked: Double, have: Double)] = []
        for key in order {
            let want = asked[key] ?? 0, have = levels[key] ?? 0
            if want > have { out.append((productId: key.productId, locationId: key.locationId, asked: want, have: have)) }
        }
        return out
    }

    /// The price of this product on the customer's latest order with a price, else on anyone's latest order, in
    /// `currency`: a price of a note in the other currency is turned at vndPerCny (else the note's own rate); yuan to
    /// two decimals, dong whole. nil when it cannot be turned (issues.last_price).
    public static func lastPrice(_ db: Database, customerName: String, productId: Int64?, currency: String = "VND",
                                 vndPerCny: Double? = nil) throws -> Double? {
        guard let productId else { return nil }
        let base = """
            SELECT l.unit_price, d.currency, d.fx_rate FROM document_lines l JOIN documents d ON d.id = l.document_id
            LEFT JOIN customers c ON c.id = d.customer_id
            WHERE d.kind = 'delivery' AND d.status = 'active' AND l.product_id = ? AND l.unit_price IS NOT NULL
            """
        let order = " ORDER BY d.doc_date DESC, d.id DESC, l.line_no LIMIT 1"
        let name = TextRules.clean(customerName)
        if !name.isEmpty,
           let row = try Row.fetchOne(db, sql: base + " AND c.name = ?" + order, arguments: [productId, name]) {
            return inCurrency(row, currency, vndPerCny)
        }
        return try Row.fetchOne(db, sql: base + order, arguments: [productId]).flatMap { inCurrency($0, currency, vndPerCny) }
    }

    static func inCurrency(_ row: Row, _ currency: String, _ vndPerCny: Double?) -> Double? {
        let price: Double = row["unit_price"]
        let own = (row["currency"] as String?) == "CNY" ? "CNY" : "VND"
        if own == currency { return price }
        guard let rate = vndPerCny ?? (row["fx_rate"] as Double?), rate != 0 else { return nil }
        return currency == "CNY" ? pythonRound2(price / rate) : (price * rate).rounded(.toNearestOrEven)
    }

    public typealias CustomerChoice = (name: String, phone: String, contact: String, address: String, taxCode: String, email: String)

    /// A customer as the list shows it: «Tên · SĐT»
    public static func customerLabel(_ c: CustomerChoice) -> String {
        [c.name, c.phone].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    /// The customer the typed text names: the list's own label, or the name alone (letter case and extra spaces aside).
    /// The Python form's box completes a typed name to its label and picks it (QComboBox inline completion); here the
    /// box only matched the whole label, so typing an old customer's name filled nothing (user, 21/11/2026).
    public static func pickedCustomer(_ typed: String, _ choices: [CustomerChoice]) -> Int? {
        if let i = choices.firstIndex(where: { customerLabel($0) == typed }) { return i }
        let fold = { (s: String) in s.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ").lowercased() }
        let name = fold(typed)
        guard !name.isEmpty else { return nil }
        return choices.firstIndex { fold($0.name) == name || fold(customerLabel($0)) == name }
    }

    /// The customers to offer while a name is being typed (Python core/issues.suggest_customers, user's request
    /// 24/11/2026), as positions in `labels` (customerLabel, in the list's order). The search boxes' rule: every
    /// word typed must appear somewhere, in any order, accents and punctuation ignored, so «khach mau» finds
    /// «Khách Mẫu» and «0911» finds the phone beside a name. Nothing typed: everyone.
    public static func suggestCustomers(_ labels: [String], _ typed: String) -> [Int] {
        let wanted = TextRules.clean(typed)
        if wanted.isEmpty { return Array(labels.indices) }
        return labels.indices.filter { TextRules.matchesWords(wanted, labels[$0]) }
    }

    /// The boxes after the text stopped naming the customer who filled them: a box still holding that customer's value
    /// is emptied, one the user changed is kept.
    public static func unfilled(_ boxes: CustomerChoice, from c: CustomerChoice) -> CustomerChoice {
        let keep = { (box: String, theirs: String) in box == theirs ? "" : box }
        return (name: boxes.name, phone: keep(boxes.phone, c.phone), contact: keep(boxes.contact, c.contact),
                address: keep(boxes.address, c.address), taxCode: keep(boxes.taxCode, c.taxCode), email: keep(boxes.email, c.email))
    }

    public static func customerChoices(_ db: Database) throws -> [CustomerChoice] {
        var out: [CustomerChoice] = []
        for row in try Row.fetchAll(db, sql: "SELECT name, phone, contact, address, tax_code, email FROM customers ORDER BY name") {
            out.append((name: row["name"] ?? "", phone: row["phone"] ?? "", contact: row["contact"] ?? "",
                        address: row["address"] ?? "", taxCode: row["tax_code"] ?? "", email: row["email"] ?? ""))
        }
        return out
    }

    // MARK: the file

    /// One row per line typed, like a delivery note (a product may come twice, at two prices).
    static func noteRows(_ db: Database, _ data: Input) throws -> [IssueNote.Row] {
        var rows: [IssueNote.Row] = []
        for ln in data.filled {
            if ln.productId == nil, let n = ln.new {  // only on a draft: a real note creates its new products first
                let places = [(Ledger.main, ln.qtyMain), (Ledger.office, ln.qtyOffice)].filter { $0.1 > 0 }
                let name = [TextRules.clean(n.nameVi), TextRules.clean(n.variant)].filter { !$0.isEmpty }.joined(separator: " ")
                rows.append(IssueNote.Row(code: "", nameVi: name, nameZh: TextRules.clean(n.nameZh), spec: TextRules.clean(n.spec),
                                          qty: ln.qty, places: places, unitPrice: ln.unitPrice,
                                          amount: ln.unitPrice.map { pythonRound2(ln.qty * $0) }, note: TextRules.clean(ln.note)))
                continue
            }
            guard let pid = ln.productId, let p = try Catalog.product(db, id: pid) else { continue }
            let name = [p.nameVi, p.variant].filter { !$0.isEmpty }.joined(separator: " ")
            let places = [(Ledger.main, ln.qtyMain), (Ledger.office, ln.qtyOffice)].filter { $0.1 > 0 }
            let amount = ln.unitPrice.map { pythonRound2(ln.qty * $0) }
            rows.append(IssueNote.Row(code: p.code, nameVi: name, nameZh: p.nameZh, spec: p.spec, qty: ln.qty, places: places,
                                      unitPrice: ln.unitPrice, amount: amount, note: TextRules.clean(ln.note)))
        }
        return rows
    }

    static func free(_ url: URL) -> URL {
        var n = 2
        var candidate = url
        let stem = url.deletingPathExtension().lastPathComponent, ext = url.pathExtension
        while FileManager.default.fileExists(atPath: candidate.path) {
            candidate = url.deletingLastPathComponent().appendingPathComponent("\(stem)_\(n).\(ext)")
            n += 1
        }
        return candidate
    }

    // MARK: draft orders

    public static func draftsFolder(_ f: ShopFolders) -> URL {
        f.output.appendingPathComponent(folder).appendingPathComponent(drafts)
    }

    /// the number of a draft file name (PhieuXuat_NHAP_N12.xlsx -> 12)
    static func draftNumber(_ name: String) -> Int? {
        guard name.uppercased().hasPrefix(draftFilePrefix.uppercased() + draftPrefix) else { return nil }
        let rest = name.dropFirst(draftFilePrefix.count + draftPrefix.count)
        return Int(String(rest.prefix { $0.isNumber }))
    }

    /// N + 1 + the highest draft number in the drafts folder and its da-chot/ (a number is never reused).
    public static func newDraftCode(_ f: ShopFolders) -> String {
        let fm = FileManager.default
        let base = draftsFolder(f)
        let names = ((try? fm.contentsOfDirectory(atPath: base.path)) ?? [])
            + ((try? fm.contentsOfDirectory(atPath: base.appendingPathComponent(draftsDone).path)) ?? [])
        let top = names.filter { $0.lowercased().hasSuffix(".xlsx") }.compactMap(draftNumber).max() ?? 0
        return "\(draftPrefix)\(top + 1)"
    }

    /// Write the draft file (a new one, or over `url`: a draft opened again keeps its code). Nothing is recorded.
    public static func saveDraft(_ db: Database, _ f: ShopFolders, _ data: Input, over url: URL? = nil) throws -> URL {
        if !problems(data).isEmpty { throw WriteError("Đơn nháp chưa đủ thông tin.") }
        let code = url.flatMap { draftNumber($0.lastPathComponent) }.map { "\(draftPrefix)\($0)" } ?? newDraftCode(f)
        let head = IssueNote.Head(code: code, date: data.date, customer: TextRules.clean(data.customerName),
                                  phone: TextRules.clean(data.phone), contact: TextRules.clean(data.contact),
                                  address: TextRules.clean(data.address), taxCode: TextRules.clean(data.taxCode),
                                  email: TextRules.clean(data.email), letterhead: try Deliveries.letterhead(db),
                                  currency: data.currency == "CNY" ? "CNY" : "VND", draft: true)
        let target = url ?? free(draftsFolder(f).appendingPathComponent("\(draftFilePrefix)\(code).xlsx"))
        return try IssueNote.write(target, head, try noteRows(db, data))
    }

    /// (draft code, what it holds) read back from a draft file: a product by its code, else a ★ new product.
    public static func loadDraft(_ db: Database, _ url: URL) throws -> (code: String, data: Input) {
        let note = try DeliveryNoteReader.read(url)
        guard IssueNote.isDraftTitle(note.title) else { throw WriteError("File này không phải đơn nháp của DiBeKho.") }
        var lines: [LineInput] = []
        for ln in note.lines {
            let main = ln.places.isEmpty ? ln.qty : ln.places.filter { Int64($0.0) == Ledger.main }.reduce(0) { $0 + $1.1 }
            let office = ln.places.filter { Int64($0.0) == Ledger.office }.reduce(0) { $0 + $1.1 }
            let code = TextRules.clean(ln.productCode)
            if !code.isEmpty, let pid = try Int64.fetchOne(db, sql: "SELECT id FROM products WHERE code = ?", arguments: [code]) {
                lines.append(LineInput(productId: pid, qtyMain: main, qtyOffice: office, unitPrice: ln.unitPrice, note: ln.note))
            } else {
                lines.append(LineInput(productId: nil, qtyMain: main, qtyOffice: office, unitPrice: ln.unitPrice, note: ln.note,
                                       new: NewProduct(TextRules.clean(ln.nameVi.isEmpty ? ln.rawName : ln.nameVi),
                                                       nameZh: TextRules.clean(ln.nameZh), spec: TextRules.clean(ln.spec))))
            }
        }
        return (note.code, Input(date: note.docDate, customerName: note.customerName, phone: note.phone, contact: note.contact,
                                 address: note.address, taxCode: note.taxCode, email: note.email, lines: lines,
                                 currency: note.currency == "CNY" ? "CNY" : "VND"))
    }

    /// The draft became a real note: its file goes to da-chot/ (kept, never counted).
    @discardableResult
    public static func closeDraft(_ f: ShopFolders, _ url: URL) throws -> URL? {
        let fm = FileManager.default
        guard fm.fileExists(atPath: url.path) else { return nil }
        let done = draftsFolder(f).appendingPathComponent(draftsDone)
        try fm.createDirectory(at: done, withIntermediateDirectories: true)
        let target = free(done.appendingPathComponent(url.lastPathComponent))
        try fm.moveItem(at: url, to: target)
        return target
    }

    // MARK: saving

    /// Write the note and record it, in the caller's transaction (the products made for it go with it when it fails).
    /// Returns (document id, the user's copy). Throws when the note cannot be recorded.
    public static func save(_ db: Database, _ f: ShopFolders, _ input: Input) throws -> (docId: Int64, file: URL) {
        if !problems(input).isEmpty { throw WriteError("Phiếu xuất kho chưa đủ thông tin.") }
        return try saveNote(db, f, input, code: nil)
    }

    /// code: a corrected note takes its old code back (edit); nil: the next free one.
    static func saveNote(_ db: Database, _ f: ShopFolders, _ input: Input, code given: String?) throws -> (docId: Int64, file: URL) {
        var data = input
        var made: [[String]: Int64] = [:]
        for i in data.lines.indices {
            guard let n = data.lines[i].new, data.lines[i].productId == nil, data.lines[i].qty > 0 else { continue }
            if made[n.key] == nil {
                made[n.key] = try Catalog.createProduct(db, nameVi: n.nameVi, nameZh: n.nameZh, spec: n.spec, unit: n.unit,
                                                        category: n.category, variant: n.variant)
            }
            data.lines[i].productId = made[n.key]
        }
        let code = try given ?? newCode(db)
        let head = IssueNote.Head(code: code, date: data.date, customer: TextRules.clean(data.customerName),
                                  phone: TextRules.clean(data.phone), contact: TextRules.clean(data.contact),
                                  address: TextRules.clean(data.address), taxCode: TextRules.clean(data.taxCode),
                                  email: TextRules.clean(data.email), letterhead: try Deliveries.letterhead(db),
                                  currency: data.currency == "CNY" ? "CNY" : "VND")
        let fm = FileManager.default
        let userCopy = free(f.output.appendingPathComponent(folder).appendingPathComponent("\(filePrefix)\(code).xlsx"))
        try IssueNote.write(userCopy, head, try noteRows(db, data))
        try fm.createDirectory(at: f.deliveriesDone, withIntermediateDirectories: true)
        let scanned = free(f.deliveriesDone.appendingPathComponent(userCopy.lastPathComponent))
        try fm.copyItem(at: userCopy, to: scanned)
        let rel = Deliveries.nfc(Deliveries.processed + "/" + scanned.lastPathComponent)
        let hash = try Deliveries.fileHash(scanned)
        _ = try Deliveries.processFile(db, f, scanned, rel, hash, false)
        let found = try Row.fetchOne(db, sql: "SELECT document_id, status, message FROM scanned_files WHERE hash = ?",
                                     arguments: [hash])
        guard let row = found, (row["status"] as String?) == "imported", let docId = row["document_id"] as Int64? else {
            let message: String = found?["message"] ?? ""
            try? fm.removeItem(at: scanned)  // not recorded: the scan must not find it either
            try? fm.removeItem(at: userCopy)
            throw WriteError(message.isEmpty ? "Không ghi được phiếu xuất kho." : message)
        }
        if data.currency == "CNY", let rate = data.fxRate {  // the rate the user saw, not the one of the moment the file was read
            try db.execute(sql: "UPDATE documents SET fx_rate = ? WHERE id = ?", arguments: [rate, docId])
        }
        try Meta.log(db, "issue_note", "\(code) (\(data.filled.count) mặt hàng)")
        return (docId, userCopy)
    }

    /// The document, its earlier versions (same code), their lines, movements and scan records. Returns the hashes of
    /// their files.
    static func removeRows(_ db: Database, _ doc: Row) throws -> Set<String> {
        let ids = try Int64.fetchAll(db, sql: "SELECT id FROM documents WHERE kind = 'delivery' AND code_norm = ?",
                                     arguments: [doc["code_norm"] as String])
        var hashes = Set<String>()
        for i in ids {
            hashes.formUnion(try String.fetchAll(db, sql: "SELECT hash FROM scanned_files WHERE document_id = ?", arguments: [i]))
            hashes.formUnion(try String.fetchAll(db, sql: "SELECT source_hash FROM documents WHERE id = ? AND source_hash <> ''",
                                                 arguments: [i]))
        }
        for i in ids {
            for table in ["stock_movements", "document_lines", "document_skipped_lines"] {
                try db.execute(sql: "DELETE FROM \(table) WHERE document_id = ?", arguments: [i])
            }
            try db.execute(sql: "DELETE FROM scanned_files WHERE document_id = ?", arguments: [i])
            try db.execute(sql: "DELETE FROM documents WHERE id = ?", arguments: [i])
        }
        for h in hashes { try db.execute(sql: "DELETE FROM scanned_files WHERE hash = ?", arguments: [h]) }
        try Meta.touch(db)
        return hashes
    }

    /// Move the files of these hashes out of the notes folder and output/phieu-xuat/ into output/phieu-xuat/<folder>/,
    /// otherwise the next scan would record them again. Returns [(from, to)] of what moved.
    static func moveFiles(_ f: ShopFolders, _ hashes: Set<String>, to folder: String) -> [(from: URL, to: URL)] {
        var files = Deliveries.deliveryFiles(f).map(\.url)
        let mine = f.output.appendingPathComponent(Issues.folder)
        files += ((try? FileManager.default.contentsOfDirectory(at: mine, includingPropertiesForKeys: nil)) ?? [])
            .filter { $0.pathExtension.lowercased() == "xlsx" }.sorted { $0.path < $1.path }
        var moved: [(from: URL, to: URL)] = []
        for url in files {
            guard let h = try? Deliveries.fileHash(url), hashes.contains(h) else { continue }
            let target = free(mine.appendingPathComponent(folder).appendingPathComponent(url.lastPathComponent))
            do {
                try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
                try FileManager.default.moveItem(at: url, to: target)
                moved.append((from: url, to: target))
            } catch {
                continue  // open in Excel: the scan will say so
            }
        }
        return moved
    }

    /// Delete a stock issue note entirely (a wrong note must leave no hole in the shop's numbers): the document and its
    /// earlier versions (same code, edited in Excel), their lines and movements, so the stock is as if it never was;
    /// the number is free again. Its files go to output/phieu-xuat/da-xoa/, otherwise the next scan would record it
    /// again; the stored copy in data/phieu-goc/ stays. Run inside a transaction. Returns how many files were moved.
    @discardableResult
    public static func delete(_ db: Database, _ f: ShopFolders, docId: Int64) throws -> Int {
        guard let doc = try Row.fetchOne(db, sql: "SELECT * FROM documents WHERE id = ?", arguments: [docId]),
              (doc["kind"] as String) == "delivery", isIssueCode(doc["code"] ?? "") else {
            throw WriteError("Chỉ xoá được phiếu xuất kho (mã A… hoặc W…).")
        }
        let hashes = try removeRows(db, doc)
        try Meta.log(db, "issue_deleted", "\(doc["code"] as String) #\(docId)")
        return moveFiles(f, hashes, to: deleted).count
    }

    // MARK: editing (customer's request 19/11/2026)

    /// An active stock issue note made by this system (A… in the app, W… on the web). The shop's own notes (160) stay as
    /// their Excel file says.
    public static func canEdit(kind: String, status: String, code: String) -> Bool {
        kind == "delivery" && status == "active" && isIssueCode(code)
    }

    /// A recorded issue note as the form shows it, to edit: (code, data). The split between the two places comes from
    /// the stock movements (a line taken from both places has no place of its own).
    public static func load(_ db: Database, docId: Int64) throws -> (code: String, data: Input) {
        guard let doc = try Row.fetchOne(db, sql: "SELECT * FROM documents WHERE id = ?", arguments: [docId]),
              canEdit(kind: doc["kind"] ?? "", status: doc["status"] ?? "", code: doc["code"] ?? "") else {
            throw WriteError("Chỉ sửa được phiếu xuất kho còn hiệu lực (mã A… hoặc W…).")
        }
        var c: Row?
        if let cid: Int64 = doc["customer_id"] {
            c = try Row.fetchOne(db, sql: "SELECT * FROM customers WHERE id = ?", arguments: [cid])
        }
        var pool: [Ledger.PlaceKey: Double] = [:]
        for r in try Row.fetchAll(db, sql: """
            SELECT product_id, location_id, SUM(-qty) AS q FROM stock_movements WHERE document_id = ?
            GROUP BY product_id, location_id
            """, arguments: [docId]) {
            pool[Ledger.PlaceKey(r["product_id"], r["location_id"])] = r["q"]
        }
        let rows = try Row.fetchAll(db, sql: """
            SELECT * FROM document_lines WHERE document_id = ? AND product_id IS NOT NULL ORDER BY line_no
            """, arguments: [docId])
        var taken: [Int64: [Int64: Double]] = [:]
        for r in rows {  // lines with a place of their own first: the split ones share what is left
            if let loc: Int64 = r["location_id"] {
                let pid: Int64 = r["product_id"], qty: Double = r["qty"]
                pool[Ledger.PlaceKey(pid, loc), default: 0] -= qty
                taken[r["id"]] = [loc: qty]
            }
        }
        var out: [LineInput] = []
        for r in rows {
            let id: Int64 = r["id"], pid: Int64 = r["product_id"]
            if taken[id] == nil {
                var split: [Int64: Double] = [:]
                var left: Double = r["qty"]
                for loc in [Ledger.main, Ledger.office] {
                    let part = min(left, max(pool[Ledger.PlaceKey(pid, loc)] ?? 0, 0))
                    if part != 0 {
                        split[loc] = part
                        pool[Ledger.PlaceKey(pid, loc), default: 0] -= part
                        left -= part
                    }
                }
                if left > 0 {  // no movement to read it from: the document's place
                    let place: Int64 = (doc["location_id"] as Int64?) ?? Ledger.main
                    split[place, default: 0] += left
                }
                taken[id] = split
            }
            out.append(LineInput(productId: pid, qtyMain: taken[id]?[Ledger.main] ?? 0,
                                 qtyOffice: taken[id]?[Ledger.office] ?? 0, unitPrice: r["unit_price"],
                                 note: r["note"] ?? ""))
        }
        let data = Input(date: doc["doc_date"] ?? "", customerName: c?["name"] ?? "", phone: c?["phone"] ?? "",
                         contact: c?["contact"] ?? "", address: c?["address"] ?? "", taxCode: c?["tax_code"] ?? "",
                         email: c?["email"] ?? "", lines: out,
                         currency: (doc["currency"] as String?) == "CNY" ? "CNY" : "VND", fxRate: doc["fx_rate"])
        return (doc["code"] ?? "", data)
    }

    /// Replace a recorded issue note by the corrected one, with the same code: the old note goes as in delete() but its
    /// files to output/phieu-xuat/da-sua/ (the old version can still be looked at); the new one is written and
    /// recorded as in save(). Run inside a transaction (a failure rolls the rows back; the files are put back here).
    public static func edit(_ db: Database, _ f: ShopFolders, docId: Int64, _ input: Input) throws -> (docId: Int64, file: URL) {
        guard let doc = try Row.fetchOne(db, sql: "SELECT * FROM documents WHERE id = ?", arguments: [docId]),
              (doc["kind"] as String) == "delivery", isIssueCode(doc["code"] ?? "") else {
            throw WriteError("Chỉ xoá được phiếu xuất kho (mã A… hoặc W…).")  // Python's _check_issue says so
        }
        guard canEdit(kind: doc["kind"] ?? "", status: doc["status"] ?? "", code: doc["code"] ?? "") else {
            throw WriteError("Chỉ sửa được phiếu xuất kho còn hiệu lực (mã A… hoặc W…).")
        }
        if !problems(input).isEmpty { throw WriteError("Phiếu xuất kho chưa đủ thông tin.") }
        let code: String = doc["code"] ?? ""
        var moved: [(from: URL, to: URL)] = []
        do {
            let hashes = try removeRows(db, doc)
            moved = moveFiles(f, hashes, to: edited)
            let result = try saveNote(db, f, input, code: code)
            try Meta.log(db, "issue_edited", "\(code) #\(result.docId)")
            return result
        } catch {
            for m in moved {  // the old note is back as it was
                try? FileManager.default.createDirectory(at: m.from.deletingLastPathComponent(), withIntermediateDirectories: true)
                try? FileManager.default.moveItem(at: m.to, to: m.from)
            }
            throw error
        }
    }
}
