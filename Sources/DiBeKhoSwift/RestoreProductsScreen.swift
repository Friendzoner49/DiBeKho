import DiBeKhoCore
import GRDB
import SwiftUI

/// Sao lưu → «Khôi phục mặt hàng đã xoá…» (ui/transfer_page.py restore_products, RestoreProductDialog, MergeDuplicateDialog):
/// products that are in a backup but not in the catalog any more, brought back with their old code; a copy made after the
/// mistaken delete is offered for merging.
@MainActor
enum RestoreProductsScreen {
    static func start(_ model: AppModel) {
        guard model.writable, let backups = model.folders?.root.appendingPathComponent("sao-luu", isDirectory: true) else {
            return UI.error(Texts.notOpen)
        }
        let found = model.read { try Catalog.deletedProducts($0, backups: backups) } ?? []
        if found.isEmpty { return UI.info(t("restore.none")) }
        var chosen: [DeletedProduct] = []
        Windows.show(t("restore.title"), width: 1000, height: 560, modal: true) { box in
            RestoreProductsView(found: found, box: box) { chosen = $0 }
        }
        guard !chosen.isEmpty else { return }
        ActivityLog.write("restore_product", "")
        var merged = 0
        for data in chosen {
            guard let outcome = model.write("restore_product", { db -> (Int64, [Product], Int) in
                let id = try Catalog.restoreProduct(db, data)
                try Meta.log(db, "product_restored", data.code)
                let (candidates, aliasMatches) = try Catalog.findMergeCandidates(db, newId: id, data)
                return (id, candidates, aliasMatches)
            }) else { return }
            let (newId, candidates, aliasMatches) = outcome
            guard !candidates.isEmpty, let restored = model.read({ try Catalog.product($0, id: newId) }) ?? nil else { continue }
            var pick: Product?
            let rows = [restored] + candidates
            let (levels, docs) = model.read { db -> ([Int64: Double], [Int64: Int]) in
                var d: [Int64: Int] = [:]
                for p in rows { d[p.id] = try Catalog.productDocuments(db, id: p.id) }
                return (try Ledger.levels(db), d)
            } ?? ([:], [:])
            Windows.show(t("restore.duplicate_title"), width: 1000, height: 360, modal: true) { box in
                MergeDuplicateView(rows: rows, levels: levels, docs: docs, aliasMatches: aliasMatches, box: box) { pick = $0 }
            }
            if let other = pick {
                let done = model.write("product_merge") { db -> Bool in
                    try Catalog.mergeProducts(db, newId, other.id)
                    try Meta.log(db, "product_merged", "\(data.code) <-> \(other.code)")
                    return true
                }
                if done != nil { merged += 1 }
            }
        }
        UI.info(t("restore.done", ["restored": String(chosen.count), "merged": String(merged)]))
    }
}

private struct RestoreProductsView: View {
    let found: [DeletedProduct]
    let box: WindowBox
    let done: ([DeletedProduct]) -> Void
    @State private var ticked: Set<Int> = []

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Hint(t("restore.hint"))
            // a table with its column titles, as transfer_page.RestoreProductDialog
            VStack(spacing: 0) {
            TableHeader(cells: [("", 28), (t("col.code"), 70), (t("col.product"), 240), (t("col.name_zh"), 130),
                                (t("col.spec"), 110), (t("col.variant"), 90), (t("col.unit"), 60),
                                (t("col.category"), 90), (t("restore.col_backup"), 130)])
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(found.enumerated()), id: \.offset) { i, d in
                        HStack(spacing: 8) {
                            Toggle("", isOn: Binding(get: { ticked.contains(i) },
                                                     set: { if $0 { ticked.insert(i) } else { ticked.remove(i) } }))
                                .labelsHidden().frame(width: 28)
                            Text(d.code).frame(width: 70, alignment: .leading)
                            Text(d.nameVi).frame(width: 240, alignment: .leading)
                            Text(d.nameZh).frame(width: 130, alignment: .leading)
                            Text(d.spec).frame(width: 110, alignment: .leading)
                            Text(d.variant).frame(width: 90, alignment: .leading)
                            Text(d.unit).frame(width: 60, alignment: .leading)
                            Text(d.category).frame(width: 90, alignment: .leading)
                            Text(Self.when(d.backupAt)).frame(width: 130, alignment: .leading)
                        }
                        .lineLimit(1)
                        .padding(.vertical, 4)
                        .contentShape(Rectangle())
                        .onTapGesture { if ticked.contains(i) { ticked.remove(i) } else { ticked.insert(i) } }
                        Divider().opacity(0.4)
                    }
                }
            }
            }
            .tableBox()
            HStack {
                Spacer()
                Button(t("restore.restore")) {
                    guard !ticked.isEmpty else { return UI.error(t("restore.pick_first")) }
                    done(ticked.sorted().map { found[$0] })
                    box.close(accepted: true)
                }
                .keyboardShortcut(.defaultAction)
                Button(t("btn.cancel")) { box.close() }
            }
        }
    }

    private static func when(_ date: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "dd/MM/yyyy HH:mm"
        return f.string(from: date)
    }
}

/// The restored product first, then the ones that might be the same item; tick one, «Gộp», or «Giữ riêng».
private struct MergeDuplicateView: View {
    let rows: [Product]
    let levels: [Int64: Double]
    let docs: [Int64: Int]
    let box: WindowBox
    let done: (Product) -> Void
    @State private var pick: Int?

    init(rows: [Product], levels: [Int64: Double], docs: [Int64: Int], aliasMatches: Int, box: WindowBox, done: @escaping (Product) -> Void) {
        self.rows = rows; self.levels = levels; self.docs = docs; self.box = box; self.done = done
        // a candidate from the product's own old note name is near certain: pre-ticked
        _pick = State(initialValue: aliasMatches > 0 ? 1 : nil)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Hint(t("restore.duplicate_hint"))
            VStack(spacing: 0) {
            TableHeader(cells: [("", 28), (t("col.code"), 70), (t("col.product"), 240), (t("col.name_zh"), 130),
                                (t("col.spec"), 110), (t("col.variant"), 90), (t("col.stock"), 60),
                                (t("restore.col_docs"), 80), (t("col.stock_note"), nil)])
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(rows.enumerated()), id: \.offset) { i, p in
                        HStack(spacing: 8) {
                            if i == 0 {
                                Image(systemName: "arrow.uturn.backward.circle").frame(width: 28).help(t("restore.duplicate_restored"))
                            } else {
                                Image(systemName: pick == i ? "checkmark.circle.fill" : "circle").frame(width: 28)
                            }
                            Text(p.code).frame(width: 70, alignment: .leading)
                            Text(p.nameVi).frame(width: 240, alignment: .leading)
                            Text(p.nameZh).frame(width: 130, alignment: .leading)
                            Text(p.spec).frame(width: 110, alignment: .leading)
                            Text(p.variant).frame(width: 90, alignment: .leading)
                            Text(Format.quantity(levels[p.id] ?? 0)).frame(width: 60, alignment: .trailing)
                            Text(String(docs[p.id] ?? 0)).frame(width: 80, alignment: .trailing)
                            Text(p.stockNote).frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .lineLimit(1)
                        .padding(.vertical, 4)
                        .background(i == 0 ? Color.secondary.opacity(0.10) : Color.clear)
                        .contentShape(Rectangle())
                        .onTapGesture { if i > 0 { pick = pick == i ? nil : i } }
                        Divider().opacity(0.4)
                    }
                }
            }
            }
            .tableBox()
            HStack {
                Spacer()
                Button(t("restore.duplicate_keep_both")) { box.close() }
                Button(t("restore.duplicate_merge")) {
                    guard let i = pick else { return UI.error(t("restore.duplicate_pick_first")) }
                    done(rows[i])
                    box.close(accepted: true)
                }
                .keyboardShortcut(.defaultAction)
            }
        }
    }
}
