import Foundation
import GRDB

/// Python core/catalog: the parts the write screens use (new products, customers).
public enum Catalog {
    static let codeMaxKey = "product_code_max"
    static let freedCodesKey = "freed_codes"

    /// '10KG/Thùng' -> 'thùng', '1m*20m/ cuộn' -> 'cuộn', 'Gói' -> 'gói'.
    public static func guessUnit(_ spec: String) -> String {
        var s = TextRules.clean(spec)
        if let slash = s.lastIndex(of: "/") { s = String(s[s.index(after: slash)...]) }
        let pattern = try! NSRegularExpression(pattern: #"[\d.,*]+\s*(kg|m|g|l)?"#, options: [.caseInsensitive])
        s = pattern.stringByReplacingMatches(in: s, range: NSRange(s.startIndex..., in: s), withTemplate: "")
        return s.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    static func freedCodes(_ db: Database) throws -> [String] {
        try Meta.get(db, freedCodesKey).split(separator: ",").map(String.init).filter { !$0.isEmpty }
    }

    static func codeNumber(_ code: String) -> Int { Int(code.dropFirst(2)) ?? 0 }

    /// A code freed by merging is given out first (the smallest), else the next SPxxx.
    public static func nextProductCode(_ db: Database) throws -> String {
        let freed = try freedCodes(db)
        if let smallest = freed.min(by: { codeNumber($0) < codeNumber($1) }) { return smallest }
        let highest = try Int.fetchOne(db, sql: "SELECT MAX(CAST(SUBSTR(code, 3) AS INTEGER)) FROM products WHERE code GLOB 'SP[0-9]*'") ?? 0
        let used = Int(try Meta.get(db, codeMaxKey, "0")) ?? 0
        return "SP" + String(format: "%03d", max(highest, used) + 1)
    }

    @discardableResult
    public static func createProduct(_ db: Database, nameVi: String, nameZh: String = "", spec: String = "",
                                     unit: String = "", category: String = "", variant: String = "") throws -> Int64 {
        let code = try nextProductCode(db)
        let typedUnit = TextRules.clean(unit)
        try db.execute(sql: """
            INSERT INTO products(code, name_vi, name_zh, spec, unit, category, min_stock, variant) VALUES(?,?,?,?,?,?,?,?)
            """, arguments: [code, TextRules.clean(nameVi), TextRules.clean(nameZh), TextRules.clean(spec),
                             typedUnit.isEmpty ? guessUnit(spec) : typedUnit, TextRules.clean(category), 0.0,
                             TextRules.clean(variant)])
        let id = db.lastInsertedRowID
        try Meta.set(db, freedCodesKey, try freedCodes(db).filter { $0 != code }.joined(separator: ","))
        try Meta.touch(db)
        return id
    }

    /// Digits only, +84 / 84 written as 0 (Python core/text.normalize_phone).
    public static func normalizePhone(_ phone: String?) -> String {
        var digits = String(String.UnicodeScalarView((phone ?? "").unicodeScalars.filter {
            $0.properties.numericType == .decimal
        }))
        // Python \d is a decimal digit in any script; int() of it is its value, but the text keeps the character:
        // the shop types ASCII digits, so only those are rewritten
        if digits.hasPrefix("84") && digits.count >= 11 { digits = "0" + digits.dropFirst(2) }
        return digits
    }

    /// Another customer with this phone number (the user is told to merge them instead), or nil.
    public static func customerOwningPhone(_ db: Database, _ phone: String, otherThan: Int64? = nil) throws -> Row? {
        let norm = normalizePhone(phone)
        if norm.isEmpty { return nil }
        return try Row.fetchOne(db, sql: "SELECT * FROM customers WHERE phone_norm = ? AND id IS NOT ? ORDER BY id",
                                arguments: [norm, otherThan])
    }

    /// Another customer with this name (accents and case aside), or nil.
    public static func customerNamed(_ db: Database, _ name: String, otherThan: Int64? = nil) throws -> Row? {
        try Row.fetchOne(db, sql: "SELECT * FROM customers WHERE unaccent(name) = ? AND id IS NOT ? ORDER BY id",
                         arguments: [TextRules.unaccent(TextRules.clean(name)), otherThan])
    }

    public static let customerFields = ["name", "contact", "phone", "address", "tax_code", "email"]

    /// What the user typed in 'Sửa thông tin khách hàng'. The name cannot be empty. A note read later only fills empty
    /// fields (upsertCustomer), so it never undoes an edit.
    public static func updateCustomer(_ db: Database, id: Int64, _ values: [String: String]) throws {
        var fields: [(String, String)] = []
        for key in customerFields {
            if let v = values[key] { fields.append((key, TextRules.clean(v))) }
        }
        if let name = fields.first(where: { $0.0 == "name" }), name.1.isEmpty {
            throw WriteError("Tên khách hàng không được để trống.")
        }
        if let phone = fields.first(where: { $0.0 == "phone" }) { fields.append(("phone_norm", normalizePhone(phone.1))) }
        if fields.isEmpty { return }
        let sets = fields.map { "\($0.0) = ?" }.joined(separator: ", ")
        var args: [DatabaseValueConvertible?] = fields.map { $0.1 }
        args.append(id)
        try db.execute(sql: "UPDATE customers SET \(sets) WHERE id = ?", arguments: StatementArguments(args))
        try Meta.touch(db)
        try Meta.log(db, "customer_edited", "#\(id)")
    }

    /// Gộp khách hàng (Python merge_customers): several customers into one named `name`. A customer already named so
    /// (even one of those merged) is kept, else the smallest id, renamed. Its MST/email, when empty, come from the first
    /// of the others that has one; every document of the others moves onto it, then the others are deleted.
    @discardableResult
    public static func mergeCustomers(_ db: Database, ids: [Int64], name: String) throws -> Int64 {
        let name = TextRules.clean(name)
        if name.isEmpty || ids.count < 2 {
            throw WriteError("Chọn từ 2 khách hàng trở lên và nhập tên khách hàng chung.")
        }
        let existing = try Int64.fetchOne(db, sql: "SELECT id FROM customers WHERE unaccent(name) = ?",
                                          arguments: [TextRules.unaccent(name)])
        let keep = existing ?? ids.min()!
        let marks = ids.map { _ in "?" }.joined(separator: ",")
        for col in ["tax_code", "email"] {
            let current = try String.fetchOne(db, sql: "SELECT \(col) FROM customers WHERE id = ?", arguments: [keep]) ?? ""
            if current.isEmpty,
               let other = try String.fetchOne(db, sql: "SELECT \(col) FROM customers WHERE id IN (\(marks)) AND \(col) <> '' ORDER BY id LIMIT 1",
                                               arguments: StatementArguments(ids)) {
                try db.execute(sql: "UPDATE customers SET \(col) = ? WHERE id = ?", arguments: [other, keep])
            }
        }
        for id in ids where id != keep {
            try db.execute(sql: "UPDATE documents SET customer_id = ? WHERE customer_id = ?", arguments: [keep, id])
            try db.execute(sql: "DELETE FROM customers WHERE id = ?", arguments: [id])
        }
        try db.execute(sql: "UPDATE customers SET name = ? WHERE id = ?", arguments: [name, keep])
        try Meta.touch(db)
        try Meta.log(db, "customers_merged", "\(ids.count) -> #\(keep) \(name)")
        return keep
    }

    /// The customer with this phone (else this name, without accents), filled in; a new one otherwise. nil when
    /// neither is given.
    public static func upsertCustomer(_ db: Database, name: String, phone: String = "", contact: String = "",
                                      address: String = "", taxCode: String = "", email: String = "",
                                      known: Int64? = nil) throws -> Int64? {
        var name = TextRules.clean(name)
        let phoneNorm = normalizePhone(phone)
        if name.isEmpty && phoneNorm.isEmpty { return nil }
        // known: the customer the same file was recorded under before (read again): kept even if the user renamed them
        var row: Row? = nil
        if let known { row = try Row.fetchOne(db, sql: "SELECT * FROM customers WHERE id = ?", arguments: [known]) }
        if let r = row {
            let rn: String = r["phone_norm"] ?? ""
            let rname: String = r["name"] ?? ""
            // their name is the user's now (a name that is only the phone number still gives way below)
            if !(!rn.isEmpty && normalizePhone(rname) == rn) { name = "" }
        }
        if row == nil && !phoneNorm.isEmpty {
            row = try Row.fetchOne(db, sql: "SELECT * FROM customers WHERE phone_norm = ?", arguments: [phoneNorm])
        }
        if row == nil && !name.isEmpty {
            row = try Row.fetchOne(db, sql: "SELECT * FROM customers WHERE unaccent(name) = ?",
                                   arguments: [TextRules.unaccent(name)])
        }
        guard let row else {
            try db.execute(sql: "INSERT INTO customers(name, contact, phone, phone_norm, address, tax_code, email) VALUES(?,?,?,?,?,?,?)",
                           arguments: [name.isEmpty ? phone : name, TextRules.clean(contact), TextRules.clean(phone),
                                       phoneNorm, TextRules.clean(address), TextRules.clean(taxCode), TextRules.clean(email)])
            return db.lastInsertedRowID
        }
        let id: Int64 = row["id"]
        let oldNorm: String = row["phone_norm"] ?? ""
        // a name that is only the phone number (the note had no readable name) gives way to the real name
        if !name.isEmpty && normalizePhone(row["name"]) == oldNorm && !oldNorm.isEmpty {
            try db.execute(sql: "UPDATE customers SET name = ? WHERE id = ?", arguments: [name, id])
        }
        try db.execute(sql: """
            UPDATE customers SET contact = CASE WHEN contact = '' THEN ? ELSE contact END,
            phone = CASE WHEN phone = '' THEN ? ELSE phone END,
            phone_norm = CASE WHEN phone_norm = '' THEN ? ELSE phone_norm END,
            address = CASE WHEN address = '' THEN ? ELSE address END,
            tax_code = CASE WHEN tax_code = '' THEN ? ELSE tax_code END,
            email = CASE WHEN email = '' THEN ? ELSE email END WHERE id = ?
            """, arguments: [TextRules.clean(contact), TextRules.clean(phone), phoneNorm, TextRules.clean(address),
                             TextRules.clean(taxCode), TextRules.clean(email), id])
        return id
    }
}

/// A product not in the catalog yet, created when the form is saved (Python receipts.NewProduct).
public struct NewProduct: Equatable {
    public var nameVi: String
    public var nameZh = ""
    public var spec = ""
    public var variant = ""
    public var unit = ""
    public var category = ""

    public init(_ nameVi: String, nameZh: String = "", spec: String = "", variant: String = "", unit: String = "",
                category: String = "") {
        self.nameVi = nameVi
        self.nameZh = nameZh
        self.spec = spec
        self.variant = variant
        self.unit = unit
        self.category = category
    }

    public var label: String { [nameVi, spec, variant].filter { !$0.isEmpty }.joined(separator: " · ") }

    /// Two rows with the same new product make one product.
    public var key: [String] {
        [nameVi, spec, variant].map { TextRules.unaccent(TextRules.clean($0)).replacingOccurrences(of: " ", with: "") }
    }
}

/// Python core/receipts: goods in typed in the app (from the border gate / parent company, another supplier, or
/// goods a customer sent back).
public enum Receipts {
    public static let supplier = "supplier"
    public static let customerReturn = "return"
    public static let other = "other"
    public static let sources = [supplier, customerReturn, other]
    static let named = [supplier, other]
    public static let folder = "hang-ve"
    public static let suggested = 3
    /// recent other suppliers offered as one-click buttons
    public static let recentCount = 3

    public struct LineInput: Equatable {
        public var qty: Double
        public var productId: Int64?
        public var new: NewProduct?
        public var note = ""
        /// returns only: what the customer gets back per unit; nil = not known (nothing comes off the revenue)
        public var unitPrice: Double?

        public init(_ qty: Double, _ productId: Int64? = nil, new: NewProduct? = nil, note: String = "",
                    unitPrice: Double? = nil) {
            self.qty = qty
            self.productId = productId
            self.new = new
            self.note = note
            self.unitPrice = unitPrice
        }
    }

    public struct Input: Equatable {
        public var date: String
        public var source: String
        public var supplierName = ""
        public var customerName = ""
        public var customerId: Int64?
        public var refCode = ""
        public var note = ""
        public var lines: [LineInput] = []
        public var locationId: Int64 = Ledger.main

        public init(date: String, source: String, supplierName: String = "", customerName: String = "",
                    customerId: Int64? = nil, refCode: String = "", note: String = "", lines: [LineInput] = [],
                    locationId: Int64 = Ledger.main) {
            self.date = date
            self.source = source
            self.supplierName = supplierName
            self.customerName = customerName
            self.customerId = customerId
            self.refCode = refCode
            self.note = note
            self.lines = lines
            self.locationId = locationId
        }

        /// Lines that will be recorded: a product (or a new one) and a quantity above 0.
        public var filled: [LineInput] { lines.filter { ($0.productId != nil || $0.new != nil) && $0.qty > 0 } }
    }

    // ---- what the window offers

    /// Suppliers used before, the most recent first.
    public static func supplierNames(_ db: Database, source: String? = nil, limit: Int? = nil) throws -> [String] {
        var sql: String
        var args: StatementArguments = []
        if let source {
            sql = """
                SELECT s.name FROM suppliers s JOIN documents d ON d.supplier_id = s.id
                WHERE d.kind = 'receipt' AND d.status <> 'replaced' AND d.receipt_source IN (?, ?)
                GROUP BY s.id ORDER BY MAX(d.doc_date) DESC, MAX(d.created_at) DESC, s.name
                """
            args = [source, source == supplier ? "" : source]
        } else {
            sql = """
                SELECT s.name FROM suppliers s LEFT JOIN documents d ON d.supplier_id = s.id
                GROUP BY s.id ORDER BY MAX(COALESCE(d.created_at, s.created_at)) DESC, s.name
                """
        }
        if let limit {
            sql += " LIMIT ?"
            args += [limit]
        }
        return try String.fetchAll(db, sql: sql, arguments: args)
    }

    public static func customerOrders(_ db: Database, customerId: Int64, limit: Int = 20) throws -> [String] {
        try String.fetchAll(db, sql: """
            SELECT code FROM documents WHERE kind = 'delivery' AND status = 'active' AND customer_id = ?
            ORDER BY doc_date DESC, id DESC LIMIT ?
            """, arguments: [customerId, limit])
    }

    static func first(_ ids: [Int64], _ n: Int) -> [Int64] {
        var out: [Int64] = []
        for id in ids where !out.contains(id) {
            out.append(id)
            if out.count == n { break }
        }
        return out
    }

    /// Products to put on the first rows (Python receipts.suggestions).
    public static func suggestions(_ db: Database, source: String, supplierName: String = "", customerId: Int64? = nil,
                                   refCode: String = "", n: Int = suggested) throws -> [Int64] {
        if source == customerReturn {
            guard let customerId else { return [] }
            var sql = """
                SELECT l.product_id FROM document_lines l JOIN documents d ON d.id = l.document_id
                JOIN products p ON p.id = l.product_id
                WHERE d.kind = 'delivery' AND d.status = 'active' AND p.active = 1 AND d.customer_id = ?
                """
            var args: StatementArguments = [customerId]
            if !refCode.isEmpty {
                sql += " AND d.code = ?"
                args += [refCode]
            }
            return first(try Int64.fetchAll(db, sql: sql + " ORDER BY d.doc_date DESC, d.id DESC, l.line_no", arguments: args), n)
        }
        let base = """
            SELECT l.product_id FROM document_lines l JOIN documents d ON d.id = l.document_id
            JOIN products p ON p.id = l.product_id
            WHERE d.kind = 'receipt' AND d.status = 'active' AND p.active = 1
            """
        var found: [Int64] = []
        let level = try StockQueries.lowStockDefault(db)
        if !supplierName.isEmpty {
            found = first(try Int64.fetchAll(db, sql: base + """
                 AND d.supplier_id IN (SELECT id FROM suppliers WHERE unaccent(name) = ?)
                GROUP BY l.product_id ORDER BY COUNT(*) DESC, MAX(d.doc_date) DESC
                """, arguments: [TextRules.unaccent(TextRules.clean(supplierName))]), n)
        }
        let more = [
            base + " GROUP BY l.product_id ORDER BY COUNT(*) DESC, MAX(d.doc_date) DESC",
            """
            SELECT p.id FROM products p LEFT JOIN stock_movements m ON m.product_id = p.id WHERE p.active = 1
            GROUP BY p.id HAVING COALESCE(SUM(m.qty), 0) < \(pythonFloat(level))
            ORDER BY COALESCE(SUM(m.qty), 0), p.code
            """,
            """
            SELECT l.product_id FROM document_lines l JOIN documents d ON d.id = l.document_id
            JOIN products p ON p.id = l.product_id
            WHERE d.kind = 'delivery' AND d.status = 'active' AND p.active = 1 AND d.doc_date >= date('now', '-90 days')
            GROUP BY l.product_id ORDER BY SUM(l.qty) DESC
            """,
        ]
        for sql in more {
            if found.count >= n { break }
            let extra = first(try Int64.fetchAll(db, sql: sql), n + found.count)
            found += Array(extra.filter { !found.contains($0) }.prefix(n - found.count))
        }
        return found
    }

    /// A number as Python writes a float into SQL text (30.0).
    static func pythonFloat(_ value: Double) -> String {
        value == value.rounded() && abs(value) < 1e15 ? String(format: "%.1f", value) : String(value)
    }

    // ---- goods a customer sent back

    /// What this customer paid for this product: on the order the goods came back from when it has a price, else
    /// on their latest order up to the day of the return. nil = never bought with a price.
    public static func returnPrice(_ db: Database, customerId: Int64?, productId: Int64?, refCode: String = "",
                                   on day: String? = nil) throws -> Double? {
        guard let customerId, let productId else { return nil }
        var base = """
            SELECT l.unit_price FROM document_lines l JOIN documents d ON d.id = l.document_id
            WHERE d.kind = 'delivery' AND d.status = 'active' AND d.customer_id = ? AND l.product_id = ?
            AND l.unit_price IS NOT NULL
            """
        let order = " ORDER BY d.doc_date DESC, d.id DESC, l.line_no LIMIT 1"
        let ref = TextRules.clean(refCode)
        if !ref.isEmpty, let price = try Double.fetchOne(db, sql: base + " AND d.code = ?" + order,
                                                          arguments: [customerId, productId, ref]) {
            return price
        }
        var args: StatementArguments = [customerId, productId]
        if let day {
            base += " AND d.doc_date <= ?"
            args += [day]
        }
        return try Double.fetchOne(db, sql: base + order, arguments: args)
    }

    /// (currency, rate) of the money a customer gets back (Python receipts.return_currency).
    public static func returnCurrency(_ db: Database, customerId: Int64?, refCode: String = "",
                                      on day: String? = nil) throws -> (String, Double?) {
        guard let customerId else { return ("VND", nil) }
        var base = """
            SELECT d.currency, d.fx_rate FROM documents d WHERE d.kind = 'delivery' AND d.status = 'active'
            AND d.customer_id = ?
            """
        let order = " ORDER BY d.doc_date DESC, d.id DESC LIMIT 1"
        var row: Row?
        let ref = TextRules.clean(refCode)
        if !ref.isEmpty {
            row = try Row.fetchOne(db, sql: base + " AND d.code = ?" + order, arguments: [customerId, ref])
        }
        if row == nil {
            base += " AND EXISTS (SELECT 1 FROM document_lines l WHERE l.document_id = d.id AND l.unit_price IS NOT NULL)"
            var args: StatementArguments = [customerId]
            if let day {
                base += " AND d.doc_date <= ?"
                args += [day]
            }
            row = try Row.fetchOne(db, sql: base + order, arguments: args)
        }
        guard let row else { return ("VND", nil) }
        return (row["currency"] ?? "", row["fx_rate"])
    }

    public static func lineAmount(_ qty: Double, _ unitPrice: Double?) -> Double? {
        unitPrice.map { pythonRound2(qty * $0) }
    }

    // ---- checks before saving

    /// Why the receipt cannot be saved as it is: (i18n key, values).
    public static func problems(_ data: Input) -> [(String, [String: String])] {
        var found: [(String, [String: String])] = []
        if !sources.contains(data.source) {
            found.append(("receipt_form.need_source", [:]))
        } else if data.source == supplier && TextRules.clean(data.supplierName).isEmpty {
            found.append(("receipt_form.need_supplier", [:]))
        } else if data.source == other && TextRules.clean(data.supplierName).isEmpty {
            found.append(("receipt_form.need_supplier_other", [:]))
        } else if data.source == customerReturn && data.customerId == nil && TextRules.clean(data.customerName).isEmpty {
            found.append(("receipt_form.need_customer", [:]))
        }
        let lines = data.filled
        if lines.isEmpty { found.append(("receipt_form.need_lines", [:])) }
        var seen = Set<Int64>()
        for ln in lines {
            if let id = ln.productId {
                if seen.contains(id) { found.append(("receipt_form.twice", ["id": String(id)])) }
                seen.insert(id)
            }
        }
        var newSeen = Set<[String]>()
        for ln in lines {
            guard let n = ln.new else { continue }
            if TextRules.clean(n.nameVi).isEmpty {
                found.append(("receipt_form.new_needs_name", [:]))
            } else {
                if newSeen.contains(n.key) { found.append(("receipt_form.twice", ["product": n.label])) }
                newSeen.insert(n.key)
            }
        }
        return found
    }

    static let placeWords: Set<String> = ["kho", "kho tong", "van phong", "office", "main warehouse"]

    /// A supplier typed as 'kho', 'kho tổng', 'văn phòng'… is usually where the goods are PUT: the form asks.
    public static func looksLikePlace(_ supplierName: String) -> Bool {
        let n = TextRules.unaccent(TextRules.clean(supplierName))
        return placeWords.contains(n) || n.hasPrefix("kho ")
    }

    // ---- saving

    /// HV001, HV002…; files already in output/hang-ve/ count too.
    public static func nextCode(_ db: Database, outputFolder: URL? = nil) throws -> String {
        var highest = try Int.fetchOne(db, sql: "SELECT MAX(CAST(SUBSTR(code, 3) AS INTEGER)) FROM documents WHERE kind = 'receipt' AND code GLOB 'HV[0-9]*'") ?? 0
        if let outputFolder {
            let names = (try? FileManager.default.contentsOfDirectory(atPath: outputFolder.appendingPathComponent(folder).path)) ?? []
            let pattern = try! NSRegularExpression(pattern: #"^HangVe_HV(\d+)_.*\.xlsx$"#)
            for name in names {
                let range = NSRange(name.startIndex..., in: name)
                if let m = pattern.firstMatch(in: name, range: range), let r = Range(m.range(at: 1), in: name),
                   let number = Int(name[r]) {
                    highest = max(highest, number)
                }
            }
        }
        return "HV" + String(format: "%03d", highest + 1)
    }

    static func supplierId(_ db: Database, _ name: String) throws -> Int64 {
        let name = TextRules.clean(name)
        if let id = try Int64.fetchOne(db, sql: "SELECT id FROM suppliers WHERE unaccent(name) = ?",
                                       arguments: [TextRules.unaccent(name)]) {
            return id
        }
        try db.execute(sql: "INSERT INTO suppliers(name) VALUES(?)", arguments: [name])
        return db.lastInsertedRowID
    }

    /// The new products and the receipt, in the caller's transaction. replaces: the receipt being edited (marked
    /// 'replaced', the new one keeps its code). Returns the new document id.
    @discardableResult
    public static func save(_ db: Database, _ data: Input, replaces: Int64? = nil, outputFolder: URL? = nil) throws -> Int64 {
        if !problems(data).isEmpty { throw WriteError("Phiếu hàng về chưa đủ thông tin.") }
        var code = try nextCode(db, outputFolder: outputFolder)
        if let replaces {
            guard let old = try Row.fetchOne(db, sql: "SELECT code, kind FROM documents WHERE id = ?", arguments: [replaces]),
                  old["kind"] as String == "receipt" else {
                throw WriteError("Chỉ sửa được phiếu hàng về.")
            }
            try Ledger.close(db, docId: replaces, status: "replaced")
            let oldCode: String = old["code"] ?? ""
            if !oldCode.isEmpty { code = oldCode }
        }
        var supplierId: Int64?
        var customerId: Int64?
        if named.contains(data.source) {
            supplierId = try Receipts.supplierId(db, data.supplierName)
        } else {
            customerId = try data.customerId ?? Catalog.upsertCustomer(db, name: data.customerName)
        }
        var lines: [LedgerLine] = []
        for ln in data.filled {
            var productId = ln.productId
            if let n = ln.new {
                productId = try Catalog.createProduct(db, nameVi: n.nameVi, nameZh: n.nameZh, spec: n.spec, unit: n.unit,
                                                      category: n.category, variant: n.variant)
            }
            let price = data.source == customerReturn && (ln.unitPrice ?? -1) >= 0 ? ln.unitPrice : nil
            lines.append(LedgerLine(productId!, ln.qty, note: TextRules.clean(ln.note), unitPrice: price,
                                    amount: lineAmount(ln.qty, price)))
        }
        let docId = try Ledger.insertDocument(db, kind: "receipt", date: data.date, lines: lines, code: code, codeNorm: code,
                                              customerId: customerId, note: TextRules.clean(data.note),
                                              locationId: data.locationId)
        let isReturn = data.source == customerReturn
        try db.execute(sql: "UPDATE documents SET receipt_source = ?, supplier_id = ?, ref_code = ?, prices_read = ? WHERE id = ?",
                       arguments: [data.source, supplierId, isReturn ? TextRules.clean(data.refCode) : "",
                                   isReturn ? 1 : 0, docId])
        if isReturn {
            let (currency, rate) = try returnCurrency(db, customerId: customerId, refCode: data.refCode, on: data.date)
            try db.execute(sql: "UPDATE documents SET currency = ?, fx_rate = ? WHERE id = ?",
                           arguments: [currency, rate, docId])
        }
        try Meta.log(db, replaces == nil ? "receipt_entered" : "receipt_edited", "\(code) #\(docId)")
        return docId
    }

    /// A saved receipt as the form shows it, to edit.
    public static func load(_ db: Database, docId: Int64) throws -> Input? {
        guard let d = try Row.fetchOne(db, sql: """
            SELECT d.*, s.name AS supplier_name, c.name AS customer_name FROM documents d
            LEFT JOIN suppliers s ON s.id = d.supplier_id LEFT JOIN customers c ON c.id = d.customer_id WHERE d.id = ?
            """, arguments: [docId]) else { return nil }
        let lines = try Row.fetchAll(db, sql: "SELECT * FROM document_lines WHERE document_id = ? ORDER BY line_no",
                                     arguments: [docId]).map { r in
            LineInput(r["qty"], r["product_id"], note: r["note"] ?? "", unitPrice: r["unit_price"])
        }
        let source: String = d["receipt_source"] ?? ""
        return Input(date: d["doc_date"], source: source.isEmpty ? supplier : source, supplierName: d["supplier_name"] ?? "",
                     customerName: d["customer_name"] ?? "", customerId: d["customer_id"], refCode: d["ref_code"] ?? "",
                     note: d["note"] ?? "", lines: lines, locationId: d["location_id"])
    }
}
