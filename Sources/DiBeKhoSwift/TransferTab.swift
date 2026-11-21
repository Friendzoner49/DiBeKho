import AppKit
import DiBeKhoCore
import SwiftUI

/// Cài đặt → Chuyển dữ liệu và sao lưu, the three boxes of ui/transfer_page.TransferPanel: hand the data to another
/// computer, the master data in Excel, the backups (a list, back up now, restore the one chosen, restore products).
struct TransferTab: View {
    @ObservedObject var model: AppModel
    @State private var backups: [URL] = []
    @State private var chosen: Int?

    private var backupsFolder: URL? { model.folders?.root.appendingPathComponent("sao-luu", isDirectory: true) }

    var body: some View {
        _ = model.version
        return VStack(alignment: .leading, spacing: 10) {
            GroupBox(t("transfer.export_title")) {
                VStack(alignment: .leading, spacing: 8) {
                    Hint(t("transfer.steps"))
                    Text(status).fixedSize(horizontal: false, vertical: true)
                    HStack {
                        Button(t("transfer.export")) { TransferScreens.export(model) }.disabled(!model.writable)
                        Button(t("transfer.receive")) {
                            model.page = .pending
                            model.rescan()
                        }
                        Spacer()
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading).padding(6)
            }
            GroupBox(t("master.title")) {
                VStack(alignment: .leading, spacing: 8) {
                    Hint(t("master.hint"))
                    HStack {
                        Button(t("master.export")) { MasterDataScreen.export(model) }
                        Button(t("master.import")) { MasterDataScreen.start(model) }.disabled(!model.writable)
                        Spacer()
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading).padding(6)
            }
            GroupBox(t("backup.title")) {
                VStack(alignment: .leading, spacing: 8) {
                    Hint(t("backup.hint"))
                    DataTable(
                        columns: [Column(title: t("backup.file"), width: 360), Column(title: t("backup.time"), width: 140)],
                        rows: backups.map { [$0.lastPathComponent, Self.time($0)] },
                        onSelect: { chosen = $0 },
                        sortable: false,
                        stretch: 0)
                        .frame(height: 170)  // the tab scrolls: a fixed height, as the Python list
                    HStack {
                        Button(t("backup.now")) {
                            ResetScreens.backupNow(model)
                            reload()
                        }
                        .disabled(!model.writable)
                        Button(t("backup.restore")) {
                            guard let i = chosen, i < backups.count else {
                                return UI.error(tr("Chọn một bản sao lưu trong danh sách trước.", "Choose a backup in the list first.", "请先在列表中选择一个备份。"))
                            }
                            ResetScreens.restore(model, url: backups[i])
                            reload()
                        }
                        .disabled(!model.practice)
                        .help(tr("Chỉ làm được trên bản thử.", "Only on the practice copy.", "只能在试用版上进行。"))
                        Button(t("restore.button")) { RestoreProductsScreen.start(model) }.disabled(!model.writable)
                        Button(t("backup.open_folder")) { if let f = backupsFolder { UI.open(f) } }
                        Spacer()
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading).padding(6)
            }
        }
        .onAppear(perform: reload)
    }

    private func reload() {
        backups = backupsFolder.map { Reset.backupsList($0) } ?? []
    }

    /// Máy này, the last export / import, ⚠ changes not handed over yet (TransferPanel.refresh)
    private var status: String {
        var lines = [t("transfer.this_device", ["name": Workspace.device().name])]
        let meta = model.read { db -> (String, String, Bool) in
            let sent = try Meta.get(db, "last_transfer_at")
            let taken = try Meta.get(db, "last_import_from")
            let unsent = try Transfer.hasUnsentChanges(db)
            return (sent, taken, unsent)
        }
        if let meta {
            if !meta.0.isEmpty { lines.append(t("transfer.last_transfer", ["at": meta.0.replacingOccurrences(of: "T", with: " ")])) }
            if !meta.1.isEmpty { lines.append(t("transfer.last_import", ["source": meta.1.replacingOccurrences(of: "T", with: " ")])) }
            if meta.2 { lines.append("⚠ " + t("transfer.has_changes")) }
        }
        return lines.joined(separator: "\n")
    }

    private static let clock: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "dd/MM/yyyy HH:mm"
        return f
    }()

    static func time(_ url: URL) -> String {
        guard let date = try? url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate else { return "" }
        return clock.string(from: date)
    }
}
