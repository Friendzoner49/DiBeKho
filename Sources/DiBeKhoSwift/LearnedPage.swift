import DiBeKhoCore
import GRDB
import SwiftUI

/// Cài đặt → «Tên trên phiếu đã học» (ui/settings_page.py learned tree): what the user chose in Cần xử lý, grouped by
/// delivery note (newest first), each line with «Quên và đọc lại…»; right click on a note: «Đọc lại cả phiếu».
@MainActor
enum LearnedScreen {
    /// Forget one learned name and read again the notes that have it (settings_page.forget)
    static func forget(_ model: AppModel, _ line: Deliveries.LearnedLine, then: @escaping () -> Void) {
        guard let folders = model.folders else { return UI.error(Texts.readOnly) }
        let orders = model.read { db -> [String] in
            guard !line.documents.isEmpty else { return [] }
            let marks = line.documents.map { _ in "?" }.joined(separator: ",")
            return try String.fetchAll(db, sql: "SELECT code FROM documents WHERE id IN (\(marks)) ORDER BY doc_date",
                                       arguments: StatementArguments(line.documents))
        } ?? []
        guard UI.ask(t("settings.confirm_forget", ["name": line.label, "docs": String(orders.count),
                                                   "orders": orders.isEmpty ? "—" : orders.joined(separator: ", ")])) else { return }
        ActivityLog.write("forget", line.label)
        guard let count = model.write("forget", { try Deliveries.forgetName($0, folders, key: line.key) }) else { return }
        model.rescan { _ in
            UI.info(t("settings.forgotten", ["docs": String(count)]))
            then()
        }
    }

    /// Đọc lại cả phiếu (common.reread_whole_note)
    static func rereadOrder(_ model: AppModel, docId: Int64, then: @escaping () -> Void) {
        guard let folders = model.folders, UI.ask(t("doc.confirm_reread")) else { return }
        guard model.write("reread", { try Deliveries.forgetOrder($0, folders, docId: docId) }) != nil else { return }
        model.rescan { result in
            guard let result else { return }
            UI.info(t(result.imported.isEmpty ? "doc.reread_pending" : "doc.reread_done"))
            then()
        }
    }
}

struct LearnedPage: View {
    @ObservedObject var model: AppModel
    @State private var orders: [Deliveries.LearnedOrder] = []
    @State private var products: [Int64: String] = [:]
    @State private var open: Set<Int64> = []  // doc ids expanded; 0 = the heading of names no note has any more

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Hint(t("settings.learned_hint"))
            HStack(spacing: 8) {
                Text(t("settings.learned_order")).frame(maxWidth: .infinity, alignment: .leading)
                Text(t("col.qty")).frame(width: 70, alignment: .trailing)
                Text(t("settings.learned_as")).frame(width: 320, alignment: .leading)
                Spacer().frame(width: 170)
            }
            .font(.system(size: UI.baseSize, weight: .semibold))
            .padding(.horizontal, 8)
            Divider()
            ScrollView {
                // one flat list with unique ids: a nested ForEach under an `if` inside LazyVStack drew the opened
                // groups blank on macOS 13
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(items, id: \.id) { item in
                        switch item.kind {
                        case .order(let order): header(order)
                        case .line(let line): row(line)
                        }
                    }
                }
            }
        }
        .onAppear { load() }
        .onChange(of: model.version) { _ in load() }
    }

    private enum ItemKind { case order(Deliveries.LearnedOrder), line(Deliveries.LearnedLine) }
    private struct Item { let id: String; let kind: ItemKind }

    private var items: [Item] {
        var out: [Item] = []
        for (n, order) in orders.enumerated() {
            let group = order.docId.map(String.init) ?? "none-" + String(n)
            out.append(Item(id: "o" + group, kind: .order(order)))
            guard open.contains(order.docId ?? 0) else { continue }
            for (i, line) in order.lines.enumerated() {
                out.append(Item(id: "l" + group + "-" + String(i) + "-" + line.key, kind: .line(line)))
            }
        }
        return out
    }

    private func header(_ order: Deliveries.LearnedOrder) -> some View {
        let id = order.docId ?? 0
        let title = order.docId == nil
            ? t("settings.learned_no_order", ["count": String(order.lines.count)])
            : t("settings.learned_order_title", ["code": order.code, "date": Format.date(order.docDate),
                                                 "customer": order.customer.isEmpty ? "—" : order.customer,
                                                 "count": String(order.lines.count)])
        return HStack(spacing: 6) {
            Image(systemName: open.contains(id) ? "chevron.down" : "chevron.right").frame(width: 14)
            Text(title).fontWeight(.semibold)
            Spacer()
        }
        .padding(.vertical, 5)
        .padding(.horizontal, 8)
        .background(Color.secondary.opacity(0.10))
        .contentShape(Rectangle())
        .onTapGesture { if open.contains(id) { open.remove(id) } else { open.insert(id) } }
        .contextMenu {
            if let docId = order.docId, model.writable {
                Button(t("btn.reread_doc")) { LearnedScreen.rereadOrder(model, docId: docId) { load() } }
            }
        }
    }

    private func row(_ line: Deliveries.LearnedLine) -> some View {
        let learned = line.productId.flatMap { products[$0] } ?? (line.productId == nil ? t("pending.skip_short") : "")
        return VStack(spacing: 0) {
            HStack(spacing: 8) {
                Text(line.label).lineLimit(1).truncationMode(.tail).frame(maxWidth: .infinity, alignment: .leading)
                    .help(line.label)
                Text(line.qty != 0 ? Format.quantity(line.qty) : "").frame(width: 70, alignment: .trailing)
                Text(learned).lineLimit(1).truncationMode(.tail).frame(width: 320, alignment: .leading).help(learned)
                Button(t("settings.forget")) { LearnedScreen.forget(model, line) { load() } }
                    .frame(width: 170)
                    .disabled(!model.writable)
            }
            .padding(.vertical, 3)
            .padding(.leading, 30)
            .padding(.trailing, 8)
            Divider().opacity(0.4)
        }
    }

    private func load() {
        guard let queue = model.queue, let folders = model.folders else { return }
        do {
            // the first look at an old shop records the dropped lines of its notes, which writes
            let found = model.writable
                ? try queue.write { try fetch($0, folders, backfill: true) }
                : try queue.read { try fetch($0, folders, backfill: false) }
            orders = found.orders
            products = found.names
            // the screenshots of the build workflow show one group opened
            if open.isEmpty, ProcessInfo.processInfo.environment["DIBEKHO_LEARNED_OPEN"] != nil, let first = orders.first {
                open.insert(first.docId ?? 0)
            }
        } catch {
            UI.error(UI.message(error))
        }
    }

    private func fetch(_ db: Database, _ folders: ShopFolders, backfill: Bool) throws
        -> (orders: [Deliveries.LearnedOrder], names: [Int64: String]) {
        let list = try Deliveries.learnedByOrder(db, folders, backfill: backfill)
        var names: [Int64: String] = [:]
        for p in try Catalog.products(db, includeInactive: true) { names[p.id] = p.longLabel }
        return (list, names)
    }
}
