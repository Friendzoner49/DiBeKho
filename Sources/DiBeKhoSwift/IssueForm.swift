import AppKit
import DiBeKhoCore
import GRDB
import SwiftUI
import UniformTypeIdentifiers

/// 'Phiếu xuất kho…' (ui/issue_form.py): goods out to a customer, typed in the app instead of written in Excel. The
/// customer (picked from the list, or typed), the date, and the lines: each product says how many are taken from Kho
/// tổng and how many from Văn phòng (both may be filled), with the price (the customer's last one is filled in). The
/// same product may stand on several lines. 'Lưu phiếu' writes the Excel file (output/phieu-xuat/) and lowers the stock
/// at once (Issues.save). A row may be '★ Mặt hàng mới': a product not in the catalog yet, made on save.
/// While the ₫ | ¥ switch shows yuan, the note is a yuan note (as in Python, user 21/11/2026): prices typed and saved in
/// yuan, the file in yuan (CNY); a note being edited keeps its own currency.
/// Đơn nháp (customer's request 21/11/2026): «Lưu nháp» writes the file only (NHÁP in the title, Issues.saveDraft);
/// «Xuất từ phiếu nháp…» opens a draft file in a fresh window, whose «Lưu phiếu» makes the real note.
@MainActor
enum IssueForm {
    /// docId: a recorded note (A… / W…) being corrected, with its own code (customer's request 19/11/2026);
    /// draft: a draft order file opened again (Xuất từ phiếu nháp…)
    static func open(_ model: AppModel, docId: Int64? = nil, draft: URL? = nil) {
        guard model.writable else { return UI.error(Texts.notOpen) }
        var code = "", old: Issues.Input?, draftCode = "", draftData: Issues.Input?
        if let docId {
            guard let loaded = model.read({ try Issues.load($0, docId: docId) }) else { return }
            (code, old) = (loaded.code, loaded.data)
        } else if let draft {
            var problem = ""
            let loaded = model.read { db -> (code: String, data: Issues.Input)? in
                do { return try Issues.loadDraft(db, draft) } catch { problem = UI.message(error); return nil }
            } ?? nil
            guard let loaded else { return UI.error(t("issue.draft_bad", ["error": problem])) }
            (draftCode, draftData) = (loaded.code, loaded.data)
        }
        // opened on the next turn of the run loop: a modal loop started inside the button's own click handling
        // can leave the new window's buttons (Hủy bỏ, Lưu phiếu) dead
        let title = docId != nil ? t("issue.edit_title", ["code": code])
            : draftData != nil ? t("issue.draft_title", ["code": draftCode]) : t("issue.title")
        DispatchQueue.main.async {
            Windows.show(title, width: 1400, height: 760, modal: true) { _ in
                IssueFormView(model: model, editDoc: docId, editCode: code, old: old, draftURL: draftData == nil ? nil : draft,
                              draftCode: draftCode, draftData: draftData)
            }
        }
    }
}

struct IssueFormRow: Identifiable {
    let id = UUID()
    var productId: Int64?
    var new: NewProduct?
    var main = ""
    var office = ""
    var price = ""
    /// typed by the user: the app no longer fills it in
    var priceTyped = false
    var note = ""

    var mainValue: Double { max(0, pythonRound2(parseNumber(main) ?? 0)) }
    var officeValue: Double { max(0, pythonRound2(parseNumber(office) ?? 0)) }
    var qty: Double { mainValue + officeValue }
    var priceValue: Double? {
        guard let v = IssueFormView.parsePrice(price), v > 0 else { return nil }
        return pythonRound2(v)
    }
}

struct IssueFormView: View {
    @ObservedObject var model: AppModel
    /// a recorded note being corrected (same code), else a new one
    var editDoc: Int64? = nil
    var editCode = ""
    var old: Issues.Input? = nil
    /// a draft order opened again: its file, code and lines (nothing of it is recorded)
    var draftURL: URL? = nil
    var draftCode = ""
    var draftData: Issues.Input? = nil
    @EnvironmentObject var box: WindowBox

    @State private var date = Dates.today
    @State private var customerText = ""
    @State private var phone = ""
    @State private var contact = ""
    @State private var address = ""
    @State private var taxCode = ""
    @State private var email = ""
    @State private var customers: [Issues.CustomerChoice] = []
    /// the old customer whose details are in the boxes (typedCustomer)
    @State private var filledFrom: Issues.CustomerChoice?
    @State private var rows: [IssueFormRow] = []
    @State private var products: [Int64: Product] = [:]
    @State private var levels: [Ledger.PlaceKey: Double] = [:]
    @State private var saved = false
    @State private var loaded = false
    /// the switch and the rate when the window opened (Python issue_form.py: a new note while the switch shows yuan is a
    /// yuan note)
    @State private var openedInCny = FX.inCny
    @State private var openedRate: Double? = FX.rate?.vndPerCny

    static let startRows = 3

    /// a yuan note: new while the switch showed yuan, or an edited note recorded in yuan
    private var cny: Bool { (old ?? draftData).map { $0.currency == "CNY" } ?? openedInCny }
    /// dong for one yuan: only to show '≈ … ₫' (and to turn a last price of the other currency)
    private var vndPerCny: Double? {
        if let old, old.currency == "CNY", let own = old.fxRate { return own }
        return openedRate
    }

    /// the row's price as typed and saved: dong, or yuan on a yuan note
    private func rowPrice(_ row: IssueFormRow) -> Double? { row.priceValue }

    private func moneyText(_ amount: Double) -> String { cny ? Format.yuan(amount) : Format.dong(amount) }

    /// before saving the user sees dong, or the yuan of the note and about how many dong
    private func both(_ amount: Double) -> String {
        guard cny, let rate = vndPerCny else { return moneyText(amount) }
        return "\(moneyText(amount)) ≈ \(Format.dong((amount * rate).rounded())) ₫"
    }

    /// 390000, 390.000 (dots between thousands), 512500.5 or 512500,5
    static func parsePrice(_ text: String) -> Double? {
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        if trimmed.range(of: #"^\d{1,3}(\.\d{3})+$"#, options: .regularExpression) != nil {
            return Double(trimmed.replacingOccurrences(of: ".", with: ""))
        }
        return parseNumber(trimmed)
    }

    private static func plain(_ value: Double) -> String {
        value == value.rounded() && abs(value) < 1e15 ? String(Int(value)) : String(value)
    }

    private func customerLabel(_ c: Issues.CustomerChoice) -> String { Issues.customerLabel(c) }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(editDoc != nil ? t("issue.edit_title", ["code": editCode])
                 : draftData != nil ? t("issue.draft_title", ["code": draftCode]) : t("issue.title"))
                .font(.system(size: UI.baseSize + 5, weight: .bold))
            Hint(editDoc != nil ? t("issue.edit_hint", ["code": editCode])
                 : draftData != nil ? t("issue.draft_hint", ["code": draftCode]) : t("issue.hint"))
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 6) {
                GridRow {
                    Text(t("issue.date") + ":")
                    DateBox(iso: $date)
                }
                GridRow {
                    Text(t("issue.customer") + ":")
                    HStack {
                        ComboField(text: Binding(get: { customerText }, set: { typedCustomer($0) }),
                                   placeholder: t("issue.customer_placeholder"), items: customers.map(customerLabel))
                        Button(t("issue.new_customer")) { newCustomer() }.help(t("issue.new_customer_tip"))
                    }
                }
                GridRow {
                    Text(t("issue.phone") + ":")
                    TextField("", text: $phone).textFieldStyle(.roundedBorder)
                }
                GridRow {
                    Text(t("issue.contact") + ":")
                    TextField("", text: $contact).textFieldStyle(.roundedBorder)
                }
                GridRow {
                    Text(t("issue.address") + ":")
                    TextField("", text: $address).textFieldStyle(.roundedBorder)
                }
                GridRow {
                    Text(t("col.tax_code") + ":")
                    TextField("", text: $taxCode).textFieldStyle(.roundedBorder)
                }
                GridRow {
                    Text(t("col.email") + ":")
                    TextField("", text: $email).textFieldStyle(.roundedBorder)
                }
            }
            if cny { Hint(t("issue.cny_hint", ["rate": vndPerCny.map { Format.dong($0.rounded()) } ?? "—"])) }
            Text(t("issue.step_lines"))
            lines
            HStack {
                Button(t("receipt_form.add_row")) { rows.append(IssueFormRow()) }
                Spacer()
                let filled = data().filled
                let money = filled.reduce(0.0) { $0 + $1.qty * ($1.unitPrice ?? 0) }
                Text(t("issue.summary", ["lines": String(filled.count),
                                         "qty": Format.quantity(filled.reduce(0) { $0 + $1.qty }), "money": moneyText(money)]))
            }
            HStack {
                if editDoc == nil {  // draft orders: count in neither stock nor revenue
                    Button(t("issue.from_draft")) { pickDraft() }.help(t("issue.from_draft_tip"))
                    Button(t("issue.save_draft")) { saveDraft() }.help(t("issue.save_draft_tip"))
                }
                Spacer()
                Button(t("btn.cancel")) { if mayClose() { box.close() } }
                Button(t("issue.save")) { save() }.bold()
            }
        }
        .onAppear(perform: load)
    }

    // ---- the lines

    // ui/issue_form.py column widths (px); the product takes the room left
    private enum W {
        static let spec: CGFloat = 100, unit: CGFloat = 60, have: CGFloat = 80, take: CGFloat = 100
        static let price: CGFloat = 120, amount: CGFloat = 110, note: CGFloat = 130, remove: CGFloat = 44
        static var all: CGFloat { FormTable.numberWidth + 200 * UI.scale + spec + unit + 2 * (have + take) + price + amount + note + remove + 12 }
    }

    private var lines: some View {
        FormTableBox(minWidth: W.all) { grid }
    }

    private var grid: some View {
            FormGrid {
                GridRow {
                    Text("").formCell(FormTable.numberWidth, header: true)
                    Text(t("col.product")).formHeader(nil)
                    Text(t("col.spec")).formHeader(W.spec)
                    Text(t("col.unit")).formHeader(W.unit)
                    Text(t("issue.have", ["place": t("loc.main")])).formHeader(W.have)
                    Text(t("issue.take", ["place": t("loc.main")])).formHeader(W.take)
                    Text(t("issue.have", ["place": t("loc.office")])).formHeader(W.have)
                    Text(t("issue.take", ["place": t("loc.office")])).formHeader(W.take)
                    Text(t(cny ? "issue.price_cny" : "issue.price")).formHeader(W.price)
                    Text(t(cny ? "issue.amount_cny" : "issue.amount")).formHeader(W.amount)
                    Text(t("col.note")).formHeader(W.note)
                    Text("").formHeader(W.remove)
                }
                ForEach($rows) { $row in
                    GridRow {
                        FormRowNumber(number: (rows.firstIndex(where: { $0.id == row.id }) ?? -1) + 1)
                        Menu {
                            Button(t("receipt_form.pick_existing")) { pick(row.id) }
                            Button(t("receipt_form.pick_new")) { newProduct(row.id, draft: nil) }
                            if row.new != nil { Button(t("receipt_form.edit_new")) { newProduct(row.id, draft: row.new) } }
                            if row.productId != nil || row.new != nil {
                                Button(t("receipt_form.clear_row")) { clear(row.id) }
                            }
                        } label: {
                            Text(label(row).isEmpty ? t("receipt_form.pick") : label(row))
                                .foregroundColor(label(row).isEmpty ? UI.hint : .primary)
                                .lineLimit(1)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .help(label(row))
                        .formCell(nil, padded: false)
                        Text(spec(row)).lineLimit(1).formCell(W.spec, grey: true)
                        Text(unit(row)).lineLimit(1).formCell(W.unit, grey: true)
                        Text(haveText(row, Ledger.main)).foregroundColor(over(row, Ledger.main) ? Color.red : .primary)
                            .formCell(W.have, .trailing, grey: true)
                        StepField(text: $row.main).formCell(W.take, padded: false)
                        Text(haveText(row, Ledger.office)).foregroundColor(over(row, Ledger.office) ? Color.red : .primary)
                            .formCell(W.have, .trailing, grey: true)
                        StepField(text: $row.office).formCell(W.take, padded: false)
                        StepField(text: Binding(get: { row.price }, set: { row.price = $0; row.priceTyped = true }),
                                  parse: { Self.parsePrice($0) })
                            .formCell(W.price, padded: false)
                        Text(amountText(row)).lineLimit(1).formCell(W.amount, .trailing, grey: true)
                        TextField("", text: $row.note).textFieldStyle(.roundedBorder).formCell(W.note, padded: false)
                        Button("✕") { remove(row.id) }.help(t("receipt_form.remove_row")).formCell(W.remove, .center, padded: false)
                    }
                }
            }
    }

    private func label(_ row: IssueFormRow) -> String {
        if let new = row.new { return "★ " + new.label }
        if let id = row.productId, let p = products[id] { return p.longLabel }
        return ""
    }

    private func spec(_ row: IssueFormRow) -> String { row.new?.spec ?? row.productId.flatMap { products[$0]?.spec } ?? "" }
    private func unit(_ row: IssueFormRow) -> String { row.new?.unit ?? row.productId.flatMap { products[$0]?.unit } ?? "" }

    private func amountText(_ row: IssueFormRow) -> String {
        guard let price = rowPrice(row), row.qty > 0 else { return "" }
        return moneyText(pythonRound2(row.qty * price))
    }

    /// 'Đang có' of a row: what the place has; a new product has nothing yet.
    private func have(_ row: IssueFormRow, _ place: Int64) -> Double? {
        if row.new != nil { return 0 }
        guard let id = row.productId, products[id] != nil else { return nil }
        return levels[Ledger.PlaceKey(id, place)] ?? 0
    }

    private func haveText(_ row: IssueFormRow, _ place: Int64) -> String { have(row, place).map { Format.quantity($0) } ?? "" }

    /// red when the rows of that product together take more than the place has
    private func over(_ row: IssueFormRow, _ place: Int64) -> Bool {
        guard let have = have(row, place) else { return false }
        let taken: Double
        if row.new != nil {
            taken = place == Ledger.main ? row.mainValue : row.officeValue
        } else {
            taken = rows.filter { $0.productId == row.productId }.reduce(0) { $0 + (place == Ledger.main ? $1.mainValue : $1.officeValue) }
        }
        return taken > have
    }

    private func index(_ id: UUID) -> Int? { rows.firstIndex { $0.id == id } }

    private func remove(_ id: UUID) {
        guard let i = index(id) else { return }
        if rows[i].qty > 0 && !UI.ask(t("receipt_form.confirm_remove", ["product": label(rows[i])])) { return }
        rows.remove(at: i)
    }

    private func clear(_ id: UUID) {
        guard let i = index(id) else { return }
        rows[i].productId = nil
        rows[i].new = nil
        rows[i].price = ""
        rows[i].priceTyped = false
    }

    private func pick(_ id: UUID) {
        guard let chosen = Forms.pickProduct(model) else { return }
        if products[chosen] == nil, let p = model.read({ try Catalog.product($0, id: chosen) }) ?? nil { products[chosen] = p }
        setExisting(id, chosen)
        afterPick(id)
    }

    private func newProduct(_ id: UUID, draft: NewProduct?) {
        guard let made = Forms.newProduct(model, draft: draft), let i = index(id) else { return }
        rows[i].productId = nil
        rows[i].new = made
        rows[i].price = ""
        rows[i].priceTyped = false
        afterPick(id)
    }

    private func setExisting(_ id: UUID, _ productId: Int64) {
        guard let i = index(id) else { return }
        if rows[i].productId != productId || rows[i].new != nil { rows[i].priceTyped = false }
        rows[i].productId = productId
        rows[i].new = nil
        fillPrice(i)
    }

    /// the customer's last price of the product, until the user types one
    private func fillPrice(_ i: Int) {
        guard !rows[i].priceTyped, let pid = rows[i].productId else { return }
        let name = customerName()
        let currency = cny ? "CNY" : "VND", rate = vndPerCny
        let price = model.read { try Issues.lastPrice($0, customerName: name, productId: pid, currency: currency, vndPerCny: rate) } ?? nil
        rows[i].price = price.map { Self.plain($0) } ?? ""
    }

    /// the next empty row is there when the last one was just filled
    private func afterPick(_ id: UUID) {
        if rows.last?.id == id { rows.append(IssueFormRow()) }
    }

    // ---- the customer

    /// the name as the list has it when the text names an old customer (typed in another letter case), else as typed
    private func customerName() -> String {
        if let i = Issues.pickedCustomer(customerText, customers) { return customers[i].name }
        return customerText.components(separatedBy: " · ")[0].trimmingCharacters(in: .whitespaces)
    }

    private func typedCustomer(_ text: String) {
        if text == customerText, filledFrom != nil { return }  // the box only wrote back what it shows: nothing to redo
        customerText = text
        // a pick from the list, or an old customer's name typed, fills the other boxes and the prices of the customer
        let picked = Issues.pickedCustomer(text, customers)
        if picked != nil || filledFrom != nil {  // no names in the log: only what happened
            ActivityLog.write("issue", "customer box: \(picked == nil ? "no longer an old customer" : "old customer filled")")
        }
        guard let i = picked else {
            // typed on past an old customer's name («Đại lý Mẫu» → «Đại lý Mẫu Hai»): the boxes that customer filled
            // are emptied again, or the new customer would go out with the old one's phone (and be merged with them)
            if let old = filledFrom {
                let left = Issues.unfilled((name: "", phone: phone, contact: contact, address: address, taxCode: taxCode, email: email),
                                           from: old)
                (phone, contact, address, taxCode, email) = (left.phone, left.contact, left.address, left.taxCode, left.email)
                filledFrom = nil
                for i in rows.indices { fillPrice(i) }
            }
            return
        }
        let c = customers[i]
        filledFrom = c
        phone = c.phone
        contact = c.contact
        address = c.address
        taxCode = c.taxCode
        email = c.email
        for i in rows.indices { fillPrice(i) }
    }

    /// '＋ Khách hàng mới…': every field of a customer not in the list yet, saved with the note. One already in the list
    /// (same name or phone) is picked instead.
    private func newCustomer() {
        var values: [String: String] = [:]
        while true {
            guard let typed = Forms.customerInfo(model, title: t("cust.new_title"), hint: t("issue.new_customer_hint"),
                                                 values: values) else { return }
            values = typed
            let name = typed["name"] ?? "", typedPhone = typed["phone"] ?? ""
            let phoneNorm = Catalog.normalizePhone(typedPhone)
            let existing = customers.first { c in
                TextRules.unaccent(TextRules.clean(c.name)) == TextRules.unaccent(TextRules.clean(name))
                    || (!phoneNorm.isEmpty && Catalog.normalizePhone(c.phone) == phoneNorm)
            }
            if let existing {
                if UI.ask(t("issue.customer_exists", ["name": existing.name])) { typedCustomer(customerLabel(existing)) ; return }
                continue
            }
            customerText = TextRules.clean(name)
            filledFrom = nil  // these boxes are the new customer's own
            phone = typedPhone
            contact = typed["contact"] ?? ""
            address = typed["address"] ?? ""
            taxCode = typed["tax_code"] ?? ""
            email = typed["email"] ?? ""
            for i in rows.indices { fillPrice(i) }
            return
        }
    }

    // ---- state

    private func data() -> Issues.Input {
        Issues.Input(date: date, customerName: customerName(), phone: phone, contact: contact, address: address,
                     taxCode: taxCode, email: email,
                     lines: rows.map { r in
                         Issues.LineInput(productId: r.productId, qtyMain: r.mainValue, qtyOffice: r.officeValue,
                                          unitPrice: rowPrice(r), note: r.note, new: r.new)
                     },
                     currency: cny ? "CNY" : "VND", fxRate: cny ? vndPerCny : nil)
    }

    private func load() {
        guard !loaded else { return }
        loaded = true
        products = Dictionary(uniqueKeysWithValues: (model.read { try Catalog.products($0, includeInactive: true) } ?? []).map { ($0.id, $0) })
        levels = model.read { try Ledger.levelsByPlace($0) } ?? [:]
        for ln in old?.filled ?? [] {  // the note being corrected has taken its goods: they are free again for the new one
            guard let pid = ln.productId else { continue }
            for (loc, qty) in [(Ledger.main, ln.qtyMain), (Ledger.office, ln.qtyOffice)] {
                levels[Ledger.PlaceKey(pid, loc), default: 0] += qty
            }
        }
        customers = model.read { try Issues.customerChoices($0) } ?? []
        if let shown = old ?? draftData {
            showOld(shown)
        } else {
            rows = (0..<Self.startRows).map { _ in IssueFormRow() }
        }
        box.shouldClose = { mayClose() }
    }

    /// the note being corrected (or the draft): its date, customer and lines (prices as written, not looked up again)
    private func showOld(_ old: Issues.Input) {
        date = old.date
        customerText = old.customerName
        phone = old.phone
        contact = old.contact
        address = old.address
        taxCode = old.taxCode
        email = old.email
        rows = old.lines.map { ln in
            var r = IssueFormRow()
            r.productId = ln.productId
            r.new = ln.new
            r.main = ln.qtyMain == 0 ? "" : Self.plain(ln.qtyMain)
            r.office = ln.qtyOffice == 0 ? "" : Self.plain(ln.qtyOffice)
            r.price = ln.unitPrice.map { Self.plain($0) } ?? ""
            r.priceTyped = true
            r.note = ln.note
            return r
        }
        rows.append(IssueFormRow())
    }

    // ---- save / close

    /// What is missing, said once (true: the note cannot be saved yet).
    private func refused(_ d: Issues.Input) -> Bool {
        let found = Issues.problems(d)
        if found.isEmpty { return false }
        var texts: [String] = []
        for (key, values) in found {
            var v = values
            if let id = values["id"].flatMap({ Int64($0) }), let p = products[id] { v = ["product": p.longLabel] }
            let line = "• " + t(key, v)
            if !texts.contains(line) { texts.append(line) }
        }
        UI.error(t("issue.cannot_save") + "\n\n" + texts.joined(separator: "\n"))
        return true
    }

    /// Lưu nháp: the file only (NHÁP in the title), nothing recorded; the draft opened again keeps its code.
    private func saveDraft() {
        let d = data()
        if refused(d) { return }
        guard let folders = model.folders else { return UI.error(Texts.notOpen) }
        ActivityLog.write("issue_draft", "\(d.filled.count) mặt hàng")
        var problem = ""
        let over = draftURL
        let written = model.read { db -> URL? in
            do { return try Issues.saveDraft(db, folders, d, over: over) } catch { problem = UI.message(error); return nil }
        } ?? nil
        guard let url = written else { return UI.error(t("issue.draft_failed", ["error": problem])) }
        self.saved = true
        if UI.ask(t("issue.draft_saved", ["path": url.path])) { UI.open(url) }
        box.close(accepted: true)
    }

    /// Xuất từ phiếu nháp…: choose a draft file; it opens in a fresh window.
    private func pickDraft() {
        guard let folders = model.folders else { return UI.error(Texts.notOpen) }
        let folder = Issues.draftsFolder(folders)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let panel = NSOpenPanel()
        panel.title = t("issue.draft_pick")
        panel.directoryURL = folder
        panel.allowedContentTypes = [.init(filenameExtension: "xlsx") ?? .data]
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        var problem = ""
        let ok = model.read { db -> Bool in
            do { _ = try Issues.loadDraft(db, url); return true } catch { problem = UI.message(error); return false }
        } ?? false
        guard ok else { return UI.error(t("issue.draft_bad", ["error": problem])) }
        if rows.contains(where: { $0.qty > 0 }) && !UI.ask(t("issue.draft_replace")) { return }
        ActivityLog.write("click", "issue_from_draft")
        saved = true  // closing asks nothing: the draft opens in its own window
        box.close()
        IssueForm.open(model, draft: url)
    }

    private func save() {
        var d = data()
        if refused(d) { return }
        // a new product that may already be in the catalog: the user should pick that one (else the next Hàng về goes to
        // the existing product and the new one stays below zero)
        for found in model.read({ try Issues.sameAsExisting($0, d) }) ?? [] {
            let existing = found.existing
            guard let n = d.lines[found.index].new else { continue }
            if UI.ask(t("receipt_form.already_in_catalog", ["new": n.label, "code": existing.code, "product": existing.longLabel])) {
                products[existing.id] = existing
                for j in rows.indices where rows[j].new?.key == n.key { setExisting(rows[j].id, existing.id) }
            }
        }
        d = data()
        let short = model.read { try Issues.shortOf($0, d, old: old) } ?? []
        if !short.isEmpty {
            let text = short.map { s in
                t("issue.short_line", ["product": products[s.productId]?.longLabel ?? "", "place": UI.locationName(s.locationId),
                                       "asked": Format.quantity(s.asked), "have": Format.quantity(s.have)])
            }.joined(separator: "\n")
            if !UI.ask(t("issue.short", ["lines": text])) { return }
        }
        if d.date > Dates.today && !UI.ask(t("receipt_form.future_date")) { return }
        guard UI.ask(confirmText(d), title: editDoc == nil ? t("issue.confirm_title") : t("issue.confirm_edit_title")) else { return }
        ActivityLog.write(editDoc == nil ? "issue" : "issue_edit", "\(d.filled.count) mặt hàng")
        guard let folders = model.folders else { return UI.error(Texts.notOpen) }
        let input = d
        let target = editDoc
        guard let (doc, file) = model.write(target == nil ? "issue_note" : "issue_edit",
                                            failed: { t("issue.failed", ["error": $0]) }, { db in
            if let target { return try Issues.edit(db, folders, docId: target, input) }
            return try Issues.save(db, folders, input)
        }) else { return }
        saved = true
        if let draftURL { try? Issues.closeDraft(folders, draftURL) }  // the draft became this note: its file goes to da-chot/
        let code = model.read { try String.fetchOne($0, sql: "SELECT code FROM documents WHERE id = ?", arguments: [doc]) } ?? nil
        if UI.ask(t(editDoc == nil ? "issue.saved" : "issue.saved_edit", ["code": code ?? "", "path": file.path])) { UI.open(file) }
        box.close(accepted: true)
    }

    private func confirmText(_ d: Issues.Input) -> String {
        let lines = d.filled.map { ln -> String in
            let name: String, unit: String
            if let n = ln.new {
                (name, unit) = ("★ " + n.label, n.unit)
            } else {
                let p = ln.productId.flatMap { products[$0] }
                (name, unit) = (p?.longLabel ?? "", p?.unit ?? "")
            }
            let parts = [(Ledger.main, ln.qtyMain), (Ledger.office, ln.qtyOffice)].filter { $0.1 != 0 }
                .map { "\(UI.locationName($0.0)) \(Format.quantity($0.1))" }
            let money = ln.unitPrice.map { $0 != 0 ? " × \(both($0))" : "" } ?? ""
            return "• \(name): \(parts.joined(separator: " + ")) \(unit)".trimmingCharacters(in: .whitespaces) + money
        }
        let total = d.filled.reduce(0.0) { $0 + $1.qty * ($1.unitPrice ?? 0) }
        var text = t(editDoc == nil ? "issue.confirm" : "issue.confirm_edit", ["code": editCode, "date": dmy(d.date), "customer": d.customerName, "lines": lines.joined(separator: "\n"),
                                       "money": both(total)])
        if d.filled.contains(where: { $0.new != nil }) { text += "\n\n" + t("issue.confirm_new") }
        return text
    }

    private func mayClose() -> Bool {
        if !saved && rows.contains(where: { $0.qty > 0 }) && !UI.ask(t("issue.confirm_close")) { return false }
        return true
    }
}
