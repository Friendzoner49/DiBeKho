import AppKit
import DiBeKhoCore
import GRDB
import SwiftUI

/// '＋ Nhập hàng về…' and 'Sửa phiếu hàng về…' (ui/receipt_form.py): where the goods come from, the date, the lines
/// (3 products suggested, ＋ Thêm dòng, a product not in the catalog yet on its row). Nothing is written until
/// 'Lưu phiếu hàng về'. A new receipt closed half typed is kept for the next time.
@MainActor
enum ReceiptForm {
    static func open(_ model: AppModel, docId: Int64? = nil) {
        guard model.writable else { return UI.error(Texts.readOnly) }
        var draft: Receipts.Input?
        var dropped = 0
        if docId == nil, var kept = model.receiptDraft {
            model.receiptDraft = nil
            if UI.ask(t("receipt_form.resume_draft", ["lines": String(kept.filled.count)])) {
                let ids = Set((model.read { try Catalog.products($0, includeInactive: true) } ?? []).map(\.id))
                let before = kept.lines.count
                kept.lines = kept.lines.filter { $0.productId == nil || ids.contains($0.productId!) || $0.new != nil }
                dropped = before - kept.lines.count
                draft = kept
            }
        }
        if dropped > 0 { UI.info(t("receipt_form.draft_dropped", ["count": String(dropped)])) }
        let title = t(docId == nil ? "receipt_form.title" : "receipt_form.title_edit")
        // on the next run-loop turn, as the issue form: a modal session opened from inside a button action
        // left Huỷ bỏ / ✕ dead
        DispatchQueue.main.async {
            Windows.show(title, width: 1150, height: 760, modal: true) { _ in
                ReceiptFormView(model: model, docId: docId, draft: draft, title: title)
            }
        }
    }
}

struct ReceiptRow: Identifiable {
    let id = UUID()
    var productId: Int64?
    var new: NewProduct?
    /// put there by the app; replaced when the supplier/customer changes
    var suggested = false
    var qty = ""
    var price = ""
    /// the user typed the price: the app no longer fills it in
    var priceTyped = false
    var note = ""

    var qtyValue: Double { max(0, pythonRound2(parseNumber(qty) ?? 0)) }
    var priceValue: Double? {
        guard let v = parseNumber(price), v > 0 else { return nil }
        return pythonRound2(v)
    }
    func touched() -> Bool { qtyValue > 0 || !note.trimmingCharacters(in: .whitespaces).isEmpty || !suggested }
}

struct ReceiptFormView: View {
    @ObservedObject var model: AppModel
    let docId: Int64?
    let draft: Receipts.Input?
    let title: String
    @EnvironmentObject var box: WindowBox

    @State private var source = Receipts.supplier
    @State private var date = Dates.today
    @State private var location = Ledger.main
    @State private var supplier = ""
    @State private var supplierNames: [String] = []
    @State private var recent: [String] = []
    @State private var customerText = ""
    @State private var customerId: Int64?
    @State private var customers: [(Int64, String)] = []
    @State private var order = ""
    @State private var orders: [String] = []
    @State private var note = ""
    @State private var rows: [ReceiptRow] = []
    @State private var products: [Int64: Product] = [:]
    @State private var loading = true
    @State private var saved = false

    private var isReturn: Bool { source == Receipts.customerReturn }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.system(size: UI.baseSize + 5, weight: .bold))
            Text(t("receipt_form.step_source"))
            HStack(spacing: 18) {
                ForEach([Receipts.supplier, Receipts.customerReturn, Receipts.other], id: \.self) { s in
                    Button { setSource(s) } label: {
                        HStack(spacing: 6) {
                            Image(systemName: source == s ? "largecircle.fill.circle" : "circle")
                            Text(t("receipt_form.source_\(s)")).font(.system(size: UI.baseSize + 2, weight: .bold))
                        }
                    }
                    .buttonStyle(.plain)
                }
                Spacer()
            }
            Hint(t("receipt_form.fix_stock_hint"))
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 6) {
                GridRow {
                    Text(t("receipt_form.date") + ":")
                    DateBox(iso: Binding(get: { date }, set: { date = $0; contextChanged() }))
                }
                GridRow {
                    Text(t("loc.put_in") + ":")
                    LocationPicker(selection: $location, wide: true)
                }
                if !isReturn {
                    GridRow {
                        Text(t("receipt_form.supplier") + ":")
                        ComboField(text: Binding(get: { supplier }, set: { supplier = $0; contextChanged() }),
                                   placeholder: t("receipt_form.supplier_placeholder"), items: supplierNames)
                    }
                    if source == Receipts.other && !recent.isEmpty {
                        GridRow {
                            Text("")
                            HStack {
                                Text(t("receipt_form.recent_suppliers"))
                                ForEach(recent, id: \.self) { name in
                                    Button(name) { supplier = name; contextChanged() }
                                }
                            }
                        }
                    }
                } else {
                    GridRow {
                        Text(t("receipt_form.customer") + ":")
                        ComboField(text: Binding(get: { customerText }, set: { typedCustomer($0) }),
                                   placeholder: t("receipt_form.customer_placeholder"), items: customers.map(\.1))
                    }
                    GridRow {
                        Text(t("receipt_form.order") + ":")
                        ComboField(text: Binding(get: { order }, set: { order = $0; contextChanged() }),
                                   placeholder: t("receipt_form.order_placeholder"), items: orders)
                    }
                }
                GridRow {
                    Text(t("col.note") + ":")
                    TextField("", text: $note).textFieldStyle(.roundedBorder)
                }
            }
            Text(t("receipt_form.step_lines"))
            Hint(t("receipt_form.lines_hint"))
            lines
            if isReturn { Hint(t("receipt_form.return_price_hint")) }
            HStack {
                Button(t("receipt_form.add_row")) { rows.append(ReceiptRow()) }
                Spacer()
                let filled = data().filled
                Text(t("receipt_form.summary", ["lines": String(filled.count),
                                                "qty": Format.quantity(filled.reduce(0) { $0 + $1.qty })]))
            }
            HStack {
                Spacer()
                Button(t("btn.cancel")) { if mayClose() { box.close() } }
                Button(t("receipt_form.save")) { save() }.bold()
            }
        }
        .onAppear(perform: load)
    }

    // ---- the lines

    // ui/receipt_form.py column widths (px); the product takes the room left
    private enum W {
        static let spec: CGFloat = 120, unit: CGFloat = 80, qty: CGFloat = 130, price: CGFloat = 150
        static let note: CGFloat = 200, remove: CGFloat = 50
        static var all: CGFloat { FormTable.numberWidth + 200 * UI.scale + spec + unit + qty + price + note + remove + 8 }
    }

    private var lines: some View {
        FormTableBox(minWidth: W.all) {
            FormGrid {
                GridRow {
                    Text("").formCell(FormTable.numberWidth, header: true)
                    Text(t("col.product")).formHeader(nil)
                    Text(t("col.spec")).formHeader(W.spec)
                    Text(t("col.unit")).formHeader(W.unit)
                    Text(t("col.qty")).formHeader(W.qty)
                    if isReturn { Text(t("receipt_form.return_price")).formHeader(W.price) }
                    Text(t("col.note")).formHeader(W.note)
                    Text("").formHeader(W.remove)
                }
                ForEach($rows) { $row in
                    GridRow {
                        FormRowNumber(number: (index(row.id) ?? -1) + 1)
                        Menu {
                            Button(t("receipt_form.pick_existing")) { pick(row.id) }
                            Button(t("receipt_form.pick_new")) { newProduct(row.id, draft: nil) }
                            if row.new != nil { Button(t("receipt_form.edit_new")) { newProduct(row.id, draft: row.new) } }
                            if row.productId != nil || row.new != nil {
                                Button(t("receipt_form.clear_row")) { setProduct(row.id, nil, nil, suggested: false) }
                            }
                        } label: {
                            Text(label(row).isEmpty ? t("receipt_form.pick") : label(row))
                                .foregroundColor(label(row).isEmpty ? UI.hint : .primary)
                                .lineLimit(1)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .help(label(row))
                        .formCell(nil, padded: false)
                        Text(spec(row)).lineLimit(1).formCell(W.spec)
                        Text(unit(row)).lineLimit(1).formCell(W.unit)
                        StepField(text: $row.qty).formCell(W.qty, padded: false)
                        if isReturn {
                            StepField(text: Binding(get: { row.price }, set: { row.price = $0; row.priceTyped = true }))
                                .formCell(W.price, padded: false)
                        }
                        TextField("", text: $row.note).textFieldStyle(.roundedBorder).formCell(W.note, padded: false)
                        Button("✕") { remove(row.id) }.help(t("receipt_form.remove_row")).formCell(W.remove, .center, padded: false)
                    }
                }
            }
        }
    }

    private func label(_ row: ReceiptRow) -> String {
        if let new = row.new { return "★ " + new.label }
        if let id = row.productId, let p = products[id] { return p.longLabel }
        return ""
    }

    private func spec(_ row: ReceiptRow) -> String { row.new?.spec ?? row.productId.flatMap { products[$0]?.spec } ?? "" }
    private func unit(_ row: ReceiptRow) -> String { row.new?.unit ?? row.productId.flatMap { products[$0]?.unit } ?? "" }

    private func index(_ id: UUID) -> Int? { rows.firstIndex { $0.id == id } }

    private func remove(_ id: UUID) {
        guard let i = index(id) else { return }
        if rows[i].qtyValue > 0 && !UI.ask(t("receipt_form.confirm_remove", ["product": label(rows[i])])) { return }
        rows.remove(at: i)
    }

    private func setProduct(_ id: UUID, _ productId: Int64?, _ new: NewProduct?, suggested: Bool? = nil) {
        guard let i = index(id) else { return }
        if rows[i].productId != productId || rows[i].new != new { rows[i].priceTyped = false }  // another product
        rows[i].productId = productId
        rows[i].new = new
        if let suggested { rows[i].suggested = suggested }
        fillPrice(i)
    }

    private func pick(_ id: UUID) {
        guard let chosen = Forms.pickProduct(model) else { return }
        if products[chosen] == nil, let p = model.read({ try Catalog.product($0, id: chosen) }) ?? nil { products[chosen] = p }
        if let other = rows.first(where: { $0.id != id && $0.productId == chosen }) {
            if other.qtyValue > 0 {
                // the same product on two rows cannot be saved: say so now, not after the whole receipt is typed
                let n = (index(other.id) ?? 0) + 1
                return UI.info(t("receipt_form.already_on_row", ["product": label(other), "row": String(n)]))
            }
            rows.removeAll { $0.id == other.id }  // an empty row with the same product gives way
        }
        setProduct(id, chosen, nil, suggested: false)
    }

    private func newProduct(_ id: UUID, draft: NewProduct?) {
        if let made = Forms.newProduct(model, draft: draft) { setProduct(id, nil, made, suggested: false) }
    }

    private func fillPrice(_ i: Int) {
        guard !rows[i].priceTyped, !loading else { return }
        var price: Double?
        if isReturn, let pid = rows[i].productId {
            let (cid, ref, day) = (customerId, order.trimmingCharacters(in: .whitespaces), date)
            price = model.read { try Receipts.returnPrice($0, customerId: cid, productId: pid, refCode: ref, on: day) } ?? nil
        }
        rows[i].price = price.map { Format.quantity($0) } ?? ""
    }

    // ---- where from

    private func setSource(_ s: String) {
        guard s != source else { return }
        source = s
        if s != Receipts.customerReturn {
            supplierNames = model.read { try Receipts.supplierNames($0, source: s) } ?? []
            supplier = s == Receipts.supplier ? (supplierNames.first ?? "") : ""
        }
        contextChanged()
    }

    private func typedCustomer(_ text: String) {
        customerText = text
        // an id only while the text is exactly one of the listed customers
        customerId = customers.first { $0.1 == text }?.0
        let cid = customerId
        orders = cid.map { id in model.read { try Receipts.customerOrders($0, customerId: id) } ?? [] } ?? []
        if !orders.contains(order) { order = "" }
        contextChanged()
    }

    private func contextChanged() {
        guard !loading else { return }
        for i in rows.indices { fillPrice(i) }  // another customer or order: other prices
        if docId == nil { suggest() }
    }

    /// Suggested products on the rows the user has not touched.
    private func suggest() {
        let (s, name, cid, ref) = (source, supplier, customerId, order.trimmingCharacters(in: .whitespaces))
        var ids = model.read { try Receipts.suggestions($0, source: s, supplierName: name, customerId: cid, refCode: ref) } ?? []
        let used = Set(rows.filter { $0.touched() }.compactMap(\.productId))
        ids = ids.filter { !used.contains($0) && products[$0] != nil }
        for i in rows.indices where !rows[i].touched() {
            let id = ids.isEmpty ? nil : ids.removeFirst()
            if rows[i].productId != id { rows[i].priceTyped = false }
            rows[i].productId = id
            rows[i].new = nil
            rows[i].suggested = true
            fillPrice(i)
        }
    }

    // ---- state

    private func data() -> Receipts.Input {
        Receipts.Input(date: date, source: source, supplierName: supplier.trimmingCharacters(in: .whitespaces),
                       customerName: customerText.components(separatedBy: " · ")[0].trimmingCharacters(in: .whitespaces),
                       customerId: customerId, refCode: order.trimmingCharacters(in: .whitespaces),
                       note: note.trimmingCharacters(in: .whitespaces),
                       lines: rows.map { r in
                           Receipts.LineInput(r.qtyValue, r.productId, new: r.new, note: r.note,
                                              unitPrice: isReturn ? r.priceValue : nil)
                       },
                       locationId: location)
    }

    private func dirty() -> Bool { rows.contains { $0.qtyValue > 0 } || docId != nil }

    private func load() {
        guard loading else { return }
        products = Dictionary(uniqueKeysWithValues: (model.read { try Catalog.products($0, includeInactive: true) } ?? []).map { ($0.id, $0) })
        supplierNames = model.read { try Receipts.supplierNames($0) } ?? []
        recent = model.read { try Receipts.supplierNames($0, source: Receipts.other, limit: Receipts.recentCount) } ?? []
        customers = (model.read { db in
            try Row.fetchAll(db, sql: "SELECT id, name, phone FROM customers ORDER BY name").map { r -> (Int64, String) in
                let name: String = r["name"] ?? "", phone: String = r["phone"] ?? ""
                return (r["id"], [name, phone].filter { !$0.isEmpty }.joined(separator: " · "))
            }
        }) ?? []
        let loaded = docId.flatMap { id in model.read { try Receipts.load($0, docId: id) } ?? nil } ?? draft
        if let d = loaded {
            source = d.source
            date = d.date
            location = d.locationId
            supplier = d.supplierName
            if let cid = d.customerId, let c = customers.first(where: { $0.0 == cid }) {
                customerText = c.1
                customerId = cid
            } else {
                customerText = d.customerName
            }
            orders = customerId.map { id in model.read { try Receipts.customerOrders($0, customerId: id) } ?? [] } ?? []
            order = d.refCode
            note = d.note
            rows = d.lines.map { ln in
                // a saved receipt or a kept draft: its prices are the user's
                ReceiptRow(productId: ln.productId, new: ln.new, qty: ln.qty > 0 ? Format.quantity(ln.qty) : "",
                           price: ln.unitPrice.map { Format.quantity($0) } ?? "", priceTyped: true, note: ln.note)
            }
            loading = false
        } else {
            source = Receipts.supplier
            supplierNames = model.read { try Receipts.supplierNames($0, source: Receipts.supplier) } ?? []
            supplier = supplierNames.first ?? ""
            rows = (0..<Receipts.suggested).map { _ in ReceiptRow(suggested: true) }
            loading = false
            suggest()
        }
        box.shouldClose = { mayClose() }
    }

    // ---- save / close

    private func save() {
        var d = data()
        let found = Receipts.problems(d)
        if !found.isEmpty {
            var texts: [String] = []
            for (key, values) in found {
                var v = values
                if let id = values["id"].flatMap({ Int64($0) }), let p = products[id] { v = ["product": p.longLabel] }
                let line = "• " + t(key, v)
                if !texts.contains(line) { texts.append(line) }
            }
            return UI.error(t("receipt_form.cannot_save") + "\n\n" + texts.joined(separator: "\n"))
        }
        if [Receipts.supplier, Receipts.other].contains(d.source) && Receipts.looksLikePlace(d.supplierName)
            && !UI.ask(t("receipt_form.supplier_is_place", ["name": d.supplierName])) { return }
        // a new product that may already be in the catalog (exact match, or a close one: receipts.same_as_existing)
        for i in rows.indices {
            guard let n = rows[i].new, rows[i].qtyValue > 0,
                  let same = model.read({
                      try Catalog.findPossibleDuplicates($0, nameVi: n.nameVi, nameZh: n.nameZh, spec: n.spec, variant: n.variant).first
                  }) ?? nil
            else { continue }
            if UI.ask(t("receipt_form.already_in_catalog", ["new": n.label, "code": same.code, "product": same.longLabel])) {
                products[same.id] = same
                rows[i].new = nil
                rows[i].productId = same.id
            }
        }
        d = data()
        if d.date > Dates.today && !UI.ask(t("receipt_form.future_date")) { return }
        let text = confirmText(d)
        guard UI.ask(text, title: t("receipt_form.confirm_title")) else { return }
        ActivityLog.write("receipt", text.components(separatedBy: "\n\n" + t("receipt_form.confirm_new"))[0])
        let (input, replaces, folder) = (d, docId, model.outputFolder)
        guard let doc = model.write(docId == nil ? "receipt" : "receipt_edit", {
            try Receipts.save($0, input, replaces: replaces, outputFolder: folder)
        }) else { return }
        saved = true
        if docId == nil { model.receiptDraft = nil }
        let code = model.read { try String.fetchOne($0, sql: "SELECT code FROM documents WHERE id = ?", arguments: [doc]) } ?? nil
        // the receipt is recorded; the Excel file to keep or print comes after (a file of the same name open in Excel
        // is no reason to lose the receipt)
        do {
            guard let folders = model.folders, let queue = model.queue else { throw WriteError(Texts.readOnly) }
            let path = try queue.write { try Receipts.exportFile($0, folders, docId: doc) }
            model.changed()
            if UI.ask(t("receipt_form.saved", ["code": code ?? "", "path": path.path])) { UI.open(path) }
        } catch {
            UI.info(t("receipt_form.saved_no_file", ["code": code ?? "", "error": UI.message(error)]))
        }
        box.close(accepted: true)
    }

    private func confirmText(_ d: Receipts.Input) -> String {
        var who: String
        if d.source != Receipts.customerReturn {
            who = t("receipt_form.source_\(d.source)") + ": " + d.supplierName
        } else {
            who = t("receipt_form.source_return") + ": " + d.customerName
            if !d.refCode.isEmpty { who += " · " + t("receipt_form.order") + " " + d.refCode }
        }
        who += "\n" + t("loc.put_in") + ": " + UI.locationName(d.locationId)
        let lines = d.filled.map { ln -> String in
            let name = ln.new.map { "★ " + $0.label } ?? products[ln.productId!]?.longLabel ?? ""
            let unit = ln.new?.unit ?? products[ln.productId!]?.unit ?? ""
            var line = "• \(name): \(Format.quantity(ln.qty)) \(unit)".trimmingCharacters(in: .whitespaces)
            if d.source == Receipts.customerReturn, let price = ln.unitPrice, price != 0 {
                line += " × \(Format.dong(price)) = \(Format.dong(Receipts.lineAmount(ln.qty, price) ?? 0))"
            }
            return line
        }
        let skipped = rows.filter { ($0.productId != nil || $0.new != nil) && $0.qtyValue <= 0 }.count
        var text = t("receipt_form.confirm", ["date": dmy(d.date), "who": who, "lines": lines.joined(separator: "\n"),
                                              "total": Format.quantity(d.filled.reduce(0) { $0 + $1.qty })])
        if d.filled.contains(where: { $0.new != nil }) { text += "\n\n" + t("receipt_form.confirm_new") }
        if skipped > 0 { text += "\n\n" + t("receipt_form.confirm_skipped", ["count": String(skipped)]) }
        if docId != nil { text += "\n\n" + t("receipt_form.confirm_edit") }
        return text
    }

    /// Closing without saving: a new receipt is kept (the user often closes it to fix a product first).
    private func mayClose() -> Bool {
        if !saved && docId == nil && dirty() {
            model.receiptDraft = data()
            UI.info(t("receipt_form.draft_kept"))
            return true
        }
        if !saved && dirty() && !UI.ask(t("receipt_form.confirm_close")) { return false }
        return true
    }
}

/// An editable combo box (QComboBox.setEditable): type freely or pick one of the listed texts.
struct ComboField: View {
    @Binding var text: String
    let placeholder: String
    let items: [String]

    var body: some View {
        HStack(spacing: 4) {
            TextField(placeholder, text: $text).textFieldStyle(.roundedBorder)
                .frame(minWidth: 300 * UI.scale, maxWidth: .infinity)
            if !items.isEmpty {
                Menu("▾") {
                    ForEach(items, id: \.self) { item in Button(item) { text = item } }
                }
                .frame(width: 50)
            }
        }
    }
}
