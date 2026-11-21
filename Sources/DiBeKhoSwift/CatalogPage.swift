import AppKit
import DiBeKhoCore
import GRDB
import SwiftUI

/// Tra cứu → Danh mục mặt hàng (in the Python app Cài đặt → Mặt hàng, ui/settings_page.py: the product list, ProductEditor, delete, merge, the alarm level).
@MainActor
enum CatalogScreens {
    /// Thêm / Sửa mặt hàng: true when saved. A new product that looks like one already there asks first (the user may edit that one).
    @discardableResult
    static func edit(_ model: AppModel, product: Product?) -> Bool {
        guard model.writable else { UI.error(Texts.notOpen); return false }
        var typed: ProductValues?
        let categories = model.read { try Catalog.categories($0) } ?? []
        Windows.show(t(product == nil ? "settings.add_product" : "settings.edit_product"), width: 760, height: 420, modal: true) { _ in
            ProductEditor(product: product, categories: categories) { typed = $0 }
        }
        guard let v = typed else { return false }
        if product == nil {
            let dups = model.read { try Catalog.findPossibleDuplicates($0, nameVi: v.nameVi, nameZh: v.nameZh, spec: v.spec, variant: v.variant) } ?? []
            if let first = dups.first,
               UI.ask(t("settings.product_duplicate", ["code": first.code, "product": first.longLabel])) {
                return edit(model, product: first)
            }
        }
        let action = product == nil ? "product_add" : "product_edit"
        return model.write(action) { db -> Bool in
            if let product {
                try Catalog.updateProduct(db, id: product.id, .init(nameVi: v.nameVi, nameZh: v.nameZh, spec: v.spec, unit: v.unit,
                                                                    category: v.category, variant: v.variant, active: v.active))
            } else {
                try Catalog.createProduct(db, nameVi: v.nameVi, nameZh: v.nameZh, spec: v.spec, unit: v.unit,
                                          category: v.category, variant: v.variant)
            }
            return true
        } != nil
    }

    /// Xoá: a product no document uses goes; one that is in documents can only be set inactive.
    static func delete(_ model: AppModel, _ p: Product) {
        let used = model.read { try Catalog.productDocuments($0, id: p.id) } ?? 0
        if used > 0 {
            if !p.active {
                UI.error(t("settings.delete_used_inactive", ["name": p.label, "docs": String(used)]))
            } else if UI.ask(t("settings.delete_used", ["name": p.label, "docs": String(used)])) {
                model.write("product_edit") { try Catalog.updateProduct($0, id: p.id, .init(active: false)) }
            }
            return
        }
        guard UI.ask(t("settings.confirm_delete_product", ["name": p.label])) else { return }
        model.write("product_delete") { db in
            try Catalog.deleteProduct(db, id: p.id)
            try Meta.log(db, "product_deleted", p.label)
        }
    }

    /// Gộp: the selected product and another one picked from the list.
    static func merge(_ model: AppModel, first: Product) {
        guard let otherId = Forms.pickProduct(model, title: t("settings.merge_pick_other")) else { return }
        if otherId == first.id { return UI.error(t("settings.merge_same")) }
        guard let other = model.read({ try Catalog.product($0, id: otherId) }) ?? nil else { return }
        let (keep, drop) = Catalog.codeNum(first.code) <= Catalog.codeNum(other.code) ? (first, other) : (other, first)
        guard UI.ask(t("settings.merge_confirm", ["keep": keep.longLabel, "drop": drop.longLabel])) else { return }
        let done = model.write("product_merge") { db -> Bool in
            try Catalog.mergeProducts(db, first.id, other.id)
            try Meta.log(db, "product_merged", "\(drop.code) -> \(keep.code)")
            return true
        }
        if done != nil { UI.info(t("settings.merge_done", ["keep": keep.code, "drop": drop.code])) }
    }

    static func setLowDefault(_ model: AppModel, _ value: Double) {
        guard let current = model.read({ try StockQueries.lowStockDefault($0) }), abs(current - value) >= 1e-9 else { return }
        model.write("low_default") { db in
            try Meta.set(db, "low_stock_default", String(Int(value)))
            try Meta.log(db, "low_stock_default", Format.quantity(value))
        }
    }
}

struct ProductValues {
    var nameVi = "", nameZh = "", spec = "", variant = "", unit = "", category = ""
    var active = true
}

struct ProductEditor: View {
    let product: Product?
    let categories: [String]
    let done: (ProductValues) -> Void
    @EnvironmentObject var box: WindowBox
    @State private var v = ProductValues()

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 6) {
                if let product {
                    GridRow { Text(t("col.code") + ":"); Text(product.code) }
                }
                field("col.product", $v.nameVi)
                field("col.name_zh", $v.nameZh)
                field("col.spec", $v.spec)
                field("col.variant", $v.variant)
                field("col.unit", $v.unit)
                GridRow {
                    Text(t("col.category") + ":")
                    HStack {
                        TextField("", text: $v.category).textFieldStyle(.roundedBorder).frame(minWidth: 440)
                        Menu {
                            ForEach(categories, id: \.self) { c in Button(c) { v.category = c } }
                        } label: { Image(systemName: "chevron.down") }
                        .fixedSize()
                    }
                }
                GridRow { Text(""); Toggle(t("settings.active"), isOn: $v.active) }
            }
            // Lưu then Huỷ bỏ right under the form (QDialogButtonBox)
            HStack {
                Spacer()
                Button(t("btn.save")) {
                    if TextRules.clean(v.nameVi).isEmpty { return }
                    var out = v
                    for path in [\ProductValues.nameVi, \.nameZh, \.spec, \.variant, \.unit, \.category] {
                        out[keyPath: path] = TextRules.clean(out[keyPath: path])
                    }
                    done(out)
                    box.close(accepted: true)
                }
                .keyboardShortcut(.defaultAction)
                Button(t("btn.cancel")) { box.close() }
            }
            Spacer()
        }
        .onAppear {
            guard let p = product else { return }
            v = ProductValues(nameVi: p.nameVi, nameZh: p.nameZh, spec: p.spec, variant: p.variant, unit: p.unit,
                              category: p.category, active: p.active)
        }
    }

    private func field(_ key: String, _ text: Binding<String>) -> some View {
        GridRow {
            Text(t(key) + ":")
            TextField("", text: text).textFieldStyle(.roundedBorder).frame(minWidth: 480)
        }
    }
}

struct CatalogPage: View {
    @ObservedObject var model: AppModel
    /// off in Tra cứu, whose page title already carries the hint
    var showsHint = true
    @State private var products: [Product] = []
    @State private var selected: Int?
    @State private var low = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if showsHint { Hint(t("settings.products_hint")) }
            HStack {
                Text(t("settings.low_default") + ":")
                TextField("", text: $low, onCommit: { CatalogScreens.setLowDefault(model, Double(low.replacingOccurrences(of: ",", with: ".")) ?? 0); load() })
                    .textFieldStyle(.roundedBorder).frame(width: 90)
                Hint(t("settings.low_default_hint"))
            }
            DataTable(
                columns: [Column(title: t("col.code"), width: 70), Column(title: t("col.product"), width: 260),
                          Column(title: t("col.name_zh"), width: 160), Column(title: t("col.spec"), width: 130),
                          Column(title: t("col.variant"), width: 100), Column(title: t("col.unit"), width: 70),
                          Column(title: t("col.category"), width: 110), Column(title: t("settings.active"), width: 60)],
                rows: products.map { [$0.code, $0.nameVi, $0.nameZh, $0.spec, $0.variant, $0.unit, $0.category,
                                      t($0.active ? "btn.yes" : "btn.no")] },
                tones: products.map { $0.active ? .normal : .grey },
                onOpen: { i in if CatalogScreens.edit(model, product: products[i]) { load() } },
                onSelect: { selected = $0 })
            HStack {
                Button(t("settings.add_product")) { if CatalogScreens.edit(model, product: nil) { load() } }
                Button(t("settings.edit_product_btn")) {
                    guard let p = current else { return UI.error(t("settings.pick_first")) }
                    if CatalogScreens.edit(model, product: p) { load() }
                }
                Button(t("settings.delete_product")) {
                    guard let p = current else { return UI.error(t("settings.pick_first")) }
                    CatalogScreens.delete(model, p)
                    load()
                }
                Button(t("settings.merge_button")) {
                    guard let p = current else { return UI.error(t("settings.merge_pick_first")) }
                    CatalogScreens.merge(model, first: p)
                    load()
                }
                .help(t("settings.merge_tip"))
                Button(t("catalog.import_btn")) { CatalogImport.start(model); load() }
                Spacer()
            }
        }
        .onAppear { load() }
    }

    private var current: Product? {
        guard let i = selected, i < products.count else { return nil }
        return products[i]
    }

    private func load() {
        products = model.read { try Catalog.products($0, includeInactive: true) } ?? []
        selected = nil
        low = Format.quantity(model.read { try StockQueries.lowStockDefault($0) } ?? 30)
    }
}
