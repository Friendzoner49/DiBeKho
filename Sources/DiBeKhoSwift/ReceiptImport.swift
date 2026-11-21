import AppKit
import DiBeKhoCore
import GRDB
import SwiftUI
import UniformTypeIdentifiers

/// A goods-receipt file from anywhere (input/, input/da-xu-ly/, the desktop…): 'Chọn file để nhập…' of Hàng về and the
/// 'Xem và nhập' button of Cần xử lý (ui/receipt_page.import_excel_file, review_receipt).
@MainActor
enum ReceiptImport {
    /// Hàng về → Chọn file để nhập…
    static func pickFile(_ model: AppModel) {
        guard model.writable, let folders = model.folders else { return UI.error(Texts.notOpen) }
        let panel = NSOpenPanel()
        panel.title = t("receipts.pick_file")
        panel.allowedContentTypes = [UTType(filenameExtension: "xlsx") ?? .data]
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = folders.input
        guard panel.runModal() == .OK, let url = panel.url else { return }
        if importFile(model, url) { UI.info(t("receipts.picked_done")) }
    }

    /// A goods-in file, a master-data workbook or a catalog sheet from anywhere (receipt_page.import_excel_file).
    /// True when something was recorded; a file of input/ then moves to input/da-xu-ly/.
    static func importFile(_ model: AppModel, _ url: URL) -> Bool {
        guard let item = model.read({ try Inbox.readItem($0, url) }) else { return false }
        switch item.kind {
        case .receipt:
            return review(model, item)
        case .master:
            guard MasterDataScreen.importFile(model, url) else { return false }
            if let folders = model.folders { Inbox.done(folders, url) }
            return true
        case .catalog:
            guard CatalogImport.importFile(model, url) else { return false }
            if let folders = model.folders { Inbox.done(folders, url) }
            model.changed()
            return true
        default:
            UI.error(item.message)
            return false
        }
    }

    /// The lines of the file and a button to record them. True when recorded.
    static func review(_ model: AppModel, _ item: InboxItem) -> Bool {
        Windows.show(t("inbox.receipt"), width: 820, height: 520, modal: true) { _ in
            ReceiptReviewView(model: model, item: item)
        }
    }
}

struct ReceiptReviewView: View {
    @ObservedObject var model: AppModel
    let item: InboxItem
    @EnvironmentObject var box: WindowBox

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(t("inbox.receipt_preview", ["date": dmy(item.receipt?.date ?? "")]))
            if let note = item.receipt?.note, !note.isEmpty { Text("\(t("col.note")): \(note)") }
            DataTable(columns: [Column(title: t("col.code"), width: 80), Column(title: t("col.product"), width: 260),
                                Column(title: t("col.name_zh"), width: 140), Column(title: t("col.spec"), width: 100),
                                Column(title: t("col.variant"), width: 110), Column(title: t("col.qty"), width: 80, numeric: true),
                                Column(title: t("col.unit"), width: 60)],
                      rows: item.resolved.map { r -> [String] in
                          let p = r.product
                          return [p?.code ?? "", p?.nameVi ?? "", p?.nameZh ?? "", p?.spec ?? "", p?.variant ?? "",
                                  Format.quantity(r.line.qty), p?.unit ?? ""]
                      })
            ForEach(item.receipt?.warnings ?? [], id: \.self) { Hint("⚠ " + $0) }
            HStack {
                Spacer()
                Button(t("btn.confirm_receipt")) { confirm() }.bold()
                Button(t("btn.cancel")) { box.close() }
            }
        }
    }

    private func confirm() {
        guard let folders = model.folders else { return UI.error(Texts.notOpen) }
        let it = item
        guard model.write("receipt", { try Inbox.applyReceipt($0, it) }) != nil else { return }
        Inbox.done(folders, item.url)  // a file chosen from elsewhere stays where it is
        box.close(accepted: true)
    }
}
