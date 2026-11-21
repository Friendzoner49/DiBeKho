import AppKit
import DiBeKhoCore
import GRDB
import SwiftUI

@MainActor
enum Forms {
    /// Chuyển hàng… (count_page.TransferDialog); docId: edit that transfer (the old one is marked replaced).
    @discardableResult
    static func transfer(_ model: AppModel, docId: Int64? = nil) -> Bool {
        guard model.writable else { UI.error(Texts.notOpen); return false }
        let title = t(docId == nil ? "transfer.title" : "transfer.title_edit")
        return Windows.show(title, width: 1000, height: 620, modal: true) { _ in
            MoveDialog(model: model, mode: .transfer, docId: docId)
        }
    }

    /// Xuất dùng thử… (count_page.TrialUseDialog)
    @discardableResult
    static func trial(_ model: AppModel) -> Bool {
        guard model.writable else { UI.error(Texts.notOpen); return false }
        return Windows.show(t("trial.title"), width: 1000, height: 620, modal: true) { _ in
            MoveDialog(model: model, mode: .trial, docId: nil)
        }
    }

    /// Chọn mặt hàng khác… (pending_page.ProductPicker): the product chosen, or nil.
    static func pickProduct(_ model: AppModel, title: String = t("pending.other_title")) -> Int64? {
        var chosen: Int64?
        Windows.show(title, width: 1000, height: 600, modal: true) { _ in
            ProductPicker(model: model) { chosen = $0 }
        }
        return chosen
    }

    /// Sửa thông tin khách hàng… (details.CustomerDialog.edit_info): true when saved. A phone number or name that is
    /// another customer's asks first (the user may merge them instead).
    @discardableResult
    static func editCustomer(_ model: AppModel, id: Int64) -> Bool {
        guard model.writable else { UI.error(Texts.notOpen); return false }
        guard let row = model.read({ try Row.fetchOne($0, sql: "SELECT * FROM customers WHERE id = ?", arguments: [id]) }) ?? nil else { return false }
        var values: [String: String] = [:]
        for key in Catalog.customerFields { values[key] = Details.text(row, key) }
        let before = values
        while true {
            guard let typed = customerInfo(model, title: t("cust.edit_title"), hint: t("cust.edit_hint"), values: values) else { return false }
            if Catalog.customerFields.allSatisfy({ (typed[$0] ?? "") == (before[$0] ?? "") }) { return false }  // unchanged
            values = typed
            let phone = typed["phone"] ?? "", name = typed["name"] ?? ""
            if let other = model.read({ try Catalog.customerOwningPhone($0, phone, otherThan: id) }) ?? nil,
               !UI.ask(t("cust.phone_taken", ["name": Details.text(other, "name")])) { continue }
            if let other = model.read({ try Catalog.customerNamed($0, name, otherThan: id) }) ?? nil,
               !UI.ask(t("cust.name_taken", ["name": Details.text(other, "name")])) { continue }
            let final = typed
            return model.write("customer_edit", { try Catalog.updateCustomer($0, id: id, final) }) != nil
        }
    }

    /// Gộp khách hàng… (orders_page.CustomersPage.merge_selected): the customers selected (id, name, order count) into one.
    static func mergeCustomers(_ model: AppModel, picked: [(id: Int64, name: String, orders: Int)]) {
        guard model.writable else { UI.error(Texts.notOpen); return }
        guard picked.count >= 2 else { UI.error(t("cust.merge_select_first")); return }
        var chosen: String?
        Windows.show(t("cust.merge_title"), width: 640, height: 320, modal: true) { _ in
            MergeCustomersEditor(picked: picked) { chosen = $0 }
        }
        guard let name = chosen else { return }
        if TextRules.clean(name).isEmpty { return UI.error(t("cust.merge_need_name")) }
        let listing = picked.map { "• \($0.name) (\(t("cust.merge_order_count", ["count": String($0.orders)])))" }.joined(separator: "\n")
        guard UI.ask(t("cust.merge_confirm", ["count": String(picked.count), "name": name, "names": listing])) else { return }
        let ids = picked.map(\.id)
        if model.write("customers_merged", { try Catalog.mergeCustomers($0, ids: ids, name: name) }) != nil {
            UI.info(t("cust.merge_saved"))
        }
    }

    /// The six boxes of a customer (customer_form.CustomerInfoDialog): the values typed, or nil when cancelled.
    static func customerInfo(_ model: AppModel, title: String, hint: String, values: [String: String]) -> [String: String]? {
        var result: [String: String]?
        Windows.show(title, width: 720, height: 380, modal: true) { _ in
            CustomerInfoEditor(title: title, hint: hint, values: values) { result = $0 }
        }
        return result
    }

    /// ★ Mặt hàng mới… (receipt_form.NewProductDialog): the product's details, created when the form is saved.
    static func newProduct(_ model: AppModel, draft: NewProduct?) -> NewProduct? {
        var result: NewProduct?
        Windows.show(t("receipt_form.new_product_title"), width: 760, height: 360, modal: true) { _ in
            NewProductEditor(model: model, draft: draft) { result = $0 }
        }
        return result
    }
}

/// Chuyển hàng and Xuất dùng thử: the active products, what each place has, a yellow column to type quantities.
struct MoveDialog: View {
    enum Mode { case transfer, trial }

    @ObservedObject var model: AppModel
    let mode: Mode
    let docId: Int64?
    @EnvironmentObject var box: WindowBox

    @State private var date = Dates.today
    @State private var from = Ledger.main
    @State private var to = Ledger.office
    @State private var note = ""
    @State private var typed: [Int64: String] = [:]
    @State private var products: [Product] = []
    @State private var levels: [Ledger.PlaceKey: Double] = [:]
    @State private var loaded = false

    static let qtyCol = 8

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Hint(t(mode == .transfer ? "transfer.hint" : "trial.hint"))
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 6) {
                GridRow {
                    Text(t(mode == .transfer ? "transfer.date" : "trial.date") + ":")
                    DateBox(iso: $date)
                }
                GridRow {
                    Text(t(mode == .transfer ? "transfer.from" : "trial.location") + ":")
                    LocationPicker(selection: Binding(get: { from }, set: { value in
                        from = value
                        if mode == .transfer && to == value { to = Ledger.locations.first { $0 != value }! }
                    }), wide: true)
                }
                if mode == .transfer {
                    GridRow {
                        Text(t("transfer.to") + ":")
                        LocationPicker(selection: Binding(get: { to }, set: { value in
                            to = value
                            if from == value { from = Ledger.locations.first { $0 != value }! }
                        }), wide: true)
                    }
                }
                GridRow {
                    Text(t("col.note") + ":")
                    TextField("", text: $note).textFieldStyle(.roundedBorder)
                }
            }
            DataTable(
                columns: [Column(title: t("col.code"), width: 70), Column(title: t("col.product"), width: 220),
                          Column(title: t("col.name_zh"), width: 120), Column(title: t("col.spec"), width: 100),
                          Column(title: t("col.variant"), width: 90), Column(title: t("col.unit"), width: 60),
                          Column(title: t("col.category"), width: 100),
                          Column(title: oneLine(mode == .transfer ? "transfer.available" : "trial.available"), width: 130, numeric: true),
                          Column(title: oneLine(mode == .transfer ? "transfer.qty" : "trial.qty"), width: 120, numeric: true, editable: true)],
                rows: products.map { p in
                    [p.code, p.nameVi, p.nameZh, p.spec, p.variant, p.unit, p.category,
                     Format.quantity(levels[.init(p.id, from)] ?? 0), typed[p.id] ?? ""]
                },
                onEdit: { row, _, text in
                    let clean = text.trimmingCharacters(in: .whitespaces)
                    typed[products[row].id] = parseNumber(clean) != nil ? clean : ""
                },
                sortable: false)  // row r is products[r]
            HStack {
                // Lưu phiếu… then Huỷ bỏ, at the right (count_page.py QDialogButtonBox)
                Spacer()
                Button(t(mode == .transfer ? "transfer.save" : "trial.save")) { save() }
                Button(t("btn.cancel")) { box.close() }
            }
        }
        .onAppear(perform: load)
    }

    private func oneLine(_ key: String) -> String { t(key).replacingOccurrences(of: "\n", with: " ") }

    private func load() {
        guard !loaded else { return }
        loaded = true
        var list = model.read { try Catalog.products($0) } ?? []
        levels = model.read { try Ledger.levelsByPlace($0) } ?? [:]
        guard let docId, let head = model.read({ try Lookup.documentHead($0, id: docId) }) ?? nil else {
            products = list
            return
        }
        // as if this transfer had not happened yet, so editing its own quantities never looks short
        let src: Int64 = head["location_id"] ?? Ledger.main
        let dst: Int64 = head["to_location_id"] ?? Ledger.office
        from = src
        to = dst
        date = head["doc_date"] ?? Dates.today
        note = head["note"] ?? ""
        let lines = model.read { try OrderQueries.lines($0, docId: docId) } ?? []
        for ln in lines {
            let pid: Int64 = ln["product_id"]
            let qty: Double = ln["qty"] ?? 0
            levels[.init(pid, src), default: 0] += qty
            levels[.init(pid, dst), default: 0] -= qty
            typed[pid] = Format.quantity(qty)
        }
        // a product the old transfer carried but since set to Ngừng dùng must still show up to edit
        let have = Set(list.map(\.id))
        let all = model.read { try Catalog.products($0, includeInactive: true) } ?? []
        list += all.filter { typed[$0.id] != nil && !have.contains($0.id) }
        products = list
    }

    private func save() {
        let quantities = products.compactMap { p -> (Product, Double)? in
            guard let v = typed[p.id].flatMap(parseNumber), v != 0 else { return nil }
            return (p, v)
        }
        if quantities.isEmpty || quantities.contains(where: { $0.1 < 0 }) {
            return UI.error(t(mode == .transfer ? "transfer.nothing" : "trial.nothing"))
        }
        let lines = quantities.map { p, q in "• \(p.longLabel): \(Format.quantity(q)) \(p.unit)".trimmingCharacters(in: .whitespaces) }
            .joined(separator: "\n")
        let short = quantities.filter { $0.1 > (levels[.init($0.0.id, from)] ?? 0) + 1e-9 }.map(\.0.longLabel)
        var text: String
        if mode == .transfer {
            text = t("transfer.confirm", ["src": UI.locationName(from), "dst": UI.locationName(to), "lines": lines])
            if !short.isEmpty {
                text += "\n\n" + t("transfer.confirm_short", ["place": UI.locationName(from), "names": short.joined(separator: ", ")])
            }
        } else {
            text = t("trial.confirm", ["place": UI.locationName(from), "lines": lines])
            if !short.isEmpty {
                text += "\n\n" + t("trial.confirm_short", ["place": UI.locationName(from), "names": short.joined(separator: ", ")])
            }
        }
        guard UI.ask(text) else { return }
        let ledger = quantities.map { LedgerLine($0.0.id, $0.1) }
        let (day, src, dst, memo, replaces) = (date, from, to, note.trimmingCharacters(in: .whitespaces), docId)
        let done: Int64?
        if mode == .transfer {
            done = model.write(replaces == nil ? "transfer" : "transfer_edit") {
                try Ledger.transfer($0, date: day, from: src, to: dst, lines: ledger, note: memo, replaces: replaces)
            }
        } else {
            done = model.write("trial_use") { try Ledger.trialUse($0, date: day, locationId: src, lines: ledger, note: memo) }
        }
        if done != nil {
            UI.info(t(mode == .transfer ? "transfer.saved" : "trial.saved"))
            box.close(accepted: true)
        }
    }
}

/// The whole catalog with a search box (Vietnamese, Chinese, code, no accents, any words in any order).
struct ProductPicker: View {
    @ObservedObject var model: AppModel
    let done: (Int64?) -> Void
    @EnvironmentObject var box: WindowBox
    @State private var search = ""
    @State private var selected: Int?
    @State private var products: [Product] = []
    @State private var levels: [Int64: Double] = [:]

    var body: some View {
        let shown = products.filter { search.isEmpty || TextRules.matchesWords(search, $0.haystack) }
        VStack(alignment: .leading, spacing: 8) {
            TextField(t("pending.other_search"), text: $search)
                .textFieldStyle(.roundedBorder)
                .onSubmit { if shown.count == 1 { finish(shown[0].id) } }
            DataTable(
                columns: [Column(title: t("col.code"), width: 70), Column(title: t("col.product"), width: 300),
                          Column(title: t("col.spec"), width: 120), Column(title: t("col.variant"), width: 100),
                          Column(title: t("col.name_zh"), width: 160), Column(title: t("col.stock"), width: 80, numeric: true)],
                rows: shown.map { [$0.code, $0.nameVi, $0.spec, $0.variant, $0.nameZh, Format.quantity(levels[$0.id] ?? 0)] },
                onOpen: { finish(shown[$0].id) },
                onSelect: { selected = $0 })
            HStack {
                Spacer()
                Button(t("btn.ok")) {
                    if let i = selected, i < shown.count { finish(shown[i].id) }
                }
                .keyboardShortcut(.defaultAction)
                Button(t("btn.cancel")) { box.close() }
            }
        }
        .onAppear {
            products = (model.read { try Catalog.products($0) } ?? [])
                .sorted { ($0.code.count, $0.code) < ($1.code.count, $1.code) }
            levels = model.read { try Ledger.levels($0) } ?? [:]
        }
    }

    private func finish(_ id: Int64) {
        done(id)
        box.close(accepted: true)
    }
}

/// The product editor of Cài đặt without saving (receipt_form.NewProductDialog).
struct NewProductEditor: View {
    @ObservedObject var model: AppModel
    let draft: NewProduct?
    let done: (NewProduct) -> Void
    @EnvironmentObject var box: WindowBox
    @State private var p = NewProduct("")
    @State private var categories: [String] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 6) {
                row("col.product", $p.nameVi)
                row("col.name_zh", $p.nameZh)
                row("col.spec", $p.spec)
                row("col.variant", $p.variant)
                row("col.unit", $p.unit)
                GridRow {
                    Text(t("col.category") + ":")
                    HStack {
                        TextField("", text: $p.category).textFieldStyle(.roundedBorder)
                        Menu {
                            ForEach(categories, id: \.self) { c in Button(c) { p.category = c } }
                        } label: { Image(systemName: "chevron.down") }
                        .fixedSize()
                    }
                }
            }
            HStack {
                Spacer()
                Button(t("btn.save")) {
                    guard !TextRules.clean(p.nameVi).isEmpty else { return }
                    var trimmed = p
                    trimmed.nameVi = p.nameVi.trimmingCharacters(in: .whitespaces)
                    trimmed.nameZh = p.nameZh.trimmingCharacters(in: .whitespaces)
                    trimmed.spec = p.spec.trimmingCharacters(in: .whitespaces)
                    trimmed.variant = p.variant.trimmingCharacters(in: .whitespaces)
                    trimmed.unit = p.unit.trimmingCharacters(in: .whitespaces)
                    trimmed.category = p.category.trimmingCharacters(in: .whitespaces)
                    done(trimmed)
                    box.close(accepted: true)
                }
                .keyboardShortcut(.defaultAction)
                Button(t("btn.cancel")) { box.close() }
            }
            Spacer()
        }
        .onAppear {
            if let draft { p = draft }
            categories = model.read { try Catalog.categories($0) } ?? []
        }
    }

    private func row(_ key: String, _ text: Binding<String>) -> some View {
        GridRow {
            Text(t(key) + ":")
            TextField("", text: text).textFieldStyle(.roundedBorder).frame(minWidth: 520)
        }
    }
}

/// Name, phone, contact, address, tax code and e-mail of one customer.
/// Pick the shared name the selected customers are merged into (_MergeCustomersDialog): one of theirs, or a new one.
struct MergeCustomersEditor: View {
    let picked: [(id: Int64, name: String, orders: Int)]
    let done: (String) -> Void
    @EnvironmentObject var box: WindowBox
    @State private var name = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Hint(t("cust.merge_hint"))
            ForEach(picked, id: \.id) { c in
                Text("• \(c.name) (\(t("cust.merge_order_count", ["count": String(c.orders)])))")
            }
            HStack {
                Text(t("cust.merge_name_label"))
                TextField(t("cust.merge_name_placeholder"), text: $name).textFieldStyle(.roundedBorder)
                Menu {
                    ForEach(picked, id: \.id) { c in Button(c.name) { name = c.name } }
                } label: {
                    Image(systemName: "chevron.down")
                }
                .fixedSize()
            }
            Spacer()
            HStack {
                Spacer()
                Button(t("btn.save")) {
                    done(name)
                    box.close(accepted: true)
                }
                .keyboardShortcut(.defaultAction)
                Button(t("btn.cancel")) { box.close() }
            }
        }
    }
}

struct CustomerInfoEditor: View {
    let title: String
    let hint: String
    let done: ([String: String]) -> Void
    @EnvironmentObject var box: WindowBox
    @State private var values: [String: String]

    private static let rows: [(key: String, label: String)] = [
        ("name", "cust.field_name"), ("phone", "col.phone"), ("contact", "col.contact"),
        ("address", "col.address"), ("tax_code", "col.tax_code"), ("email", "col.email")]

    init(title: String, hint: String, values: [String: String], done: @escaping ([String: String]) -> Void) {
        self.title = title
        self.hint = hint
        self.done = done
        _values = State(initialValue: values)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.system(size: UI.baseSize + 5, weight: .bold))
            if !hint.isEmpty { Hint(hint) }
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 6) {
                ForEach(Self.rows, id: \.key) { r in
                    GridRow {
                        Text(t(r.label) + (r.key == "name" ? " *" : "") + ":")
                        TextField(r.key == "email" ? "ten@congty.vn" : "",
                                  text: Binding(get: { values[r.key] ?? "" }, set: { values[r.key] = $0 }))
                            .textFieldStyle(.roundedBorder).frame(minWidth: 480)
                    }
                }
            }
            HStack {
                Spacer()
                Button(t("btn.save")) {
                    // what was typed, cleaned (CustomerInfoDialog.values)
                    let typed = values.mapValues { TextRules.clean($0) }
                    if (typed["name"] ?? "").isEmpty { return UI.error(t("cust.need_name")) }
                    done(typed)
                    box.close(accepted: true)
                }
                .keyboardShortcut(.defaultAction)
                Button(t("btn.cancel")) { box.close() }
            }
        }
    }
}
