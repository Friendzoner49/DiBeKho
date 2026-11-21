import AppKit
import DiBeKhoCore
import GRDB
import SwiftUI
import UniformTypeIdentifiers

/// Settings → Sao lưu và đặt lại (ui/settings_page.py): back up now, restore, reset the stock, reset everything.
/// Only the practice copy can be reset or restored here; each step takes a backup first.
@MainActor
enum ResetScreens {
    private static func backupsFolder(_ model: AppModel) -> URL? {
        model.folders?.root.appendingPathComponent("sao-luu", isDirectory: true)
    }

    static func backupNow(_ model: AppModel) {
        guard let queue = model.queue, let folder = backupsFolder(model), model.writable else { return UI.error(Texts.readOnly) }
        do {
            let url = try Backups.named(queue, folder: folder, label: "thu-cong")
            UI.info(tr("Đã sao lưu: \(url.lastPathComponent)", "Backed up: \(url.lastPathComponent)", "已备份：\(url.lastPathComponent)"))
        } catch { UI.error(tr("Không sao lưu được: \(UI.message(error))", "Could not back up: \(UI.message(error))", "无法备份：\(UI.message(error))")) }
    }

    static func resetStock(_ model: AppModel) {
        guard model.practice, let queue = model.queue, let folders = model.folders, let folder = backupsFolder(model) else {
            return UI.error(tr("Chỉ đặt lại được trên bản thử.", "Reset works only on the practice copy.", "只能在试用版上重置。"))
        }
        guard UI.ask(tr("Xoá toàn bộ phiếu, tồn kho và khách hàng, giữ lại danh mục mặt hàng?\n\nApp tự sao lưu trước khi xoá. Các phiếu đã đọc được đưa lại để đọc từ đầu.", "Delete all notes, stock and customers, keeping the product catalog?\n\nThe app backs up first. Notes that were read are put back to be read again.", "删除全部单据、库存和客户，保留商品目录？\n\n删除前应用会先备份。已读取的单据会放回，以便重新读取。")) else { return }
        do {
            let moved = try Reset.resetStock(queue, folders, backups: folder)
            model.changed()
            model.rescan(quiet: true)
            UI.info(tr("Đã đặt lại tồn kho. \(moved) phiếu được đưa lại để đọc từ đầu.", "The stock was reset. \(moved) notes were put back to be read again.", "库存已重置。\(moved) 份单据已放回，等待重新读取。"))
        } catch { UI.error(tr("Không đặt lại được: \(UI.message(error))", "Could not reset: \(UI.message(error))", "无法重置：\(UI.message(error))")) }
    }

    static func resetAll(_ model: AppModel) {
        guard model.practice, let queue = model.queue, let folders = model.folders, let folder = backupsFolder(model) else {
            return UI.error(tr("Chỉ xoá toàn bộ được trên bản thử.", "Delete everything works only on the practice copy.", "只能在试用版上全部删除。"))
        }
        guard UI.ask(tr("Xoá TOÀN BỘ dữ liệu của bản thử (cả danh mục mặt hàng) và các phiếu gốc đã giữ?\n\nApp tự sao lưu trước khi xoá.", "Delete ALL the data of the practice copy (the product catalog too) and the original notes kept?\n\nThe app backs up first.", "删除试用版的全部数据（包括商品目录）和已保留的原始单据？\n\n删除前应用会先备份。")) else { return }
        do {
            try Reset.resetAll(queue, folders, backups: folder)
            model.changed()
            UI.info(tr("Đã xoá toàn bộ dữ liệu của bản thử.", "All data of the practice copy was deleted.", "试用版的全部数据已删除。"))
        } catch { UI.error(tr("Không xoá được: \(UI.message(error))", "Could not delete: \(UI.message(error))", "无法删除：\(UI.message(error))")) }
    }

    /// Khôi phục bản đã chọn: the backup picked in the list of Cài đặt → Chuyển dữ liệu và sao lưu
    static func restore(_ model: AppModel, url: URL) {
        guard model.practice, let queue = model.queue, let folder = backupsFolder(model) else {
            return UI.error(tr("Chỉ khôi phục được trên bản thử.", "Restore works only on the practice copy.", "只能在试用版上恢复。"))
        }
        // only a backup of this sao-luu/ folder, as listed (no path from elsewhere)
        guard Reset.backupsList(folder).contains(where: { $0.standardizedFileURL == url.standardizedFileURL }) else {
            return UI.error(tr("Chỉ khôi phục được bản sao lưu trong thư mục sao-luu.", "Only a backup of the sao-luu folder can be restored.", "只能恢复 sao-luu 文件夹中的备份。"))
        }
        guard UI.ask(tr("Thay dữ liệu của bản thử bằng bản sao lưu \(url.lastPathComponent)?\n\nDữ liệu hiện tại sẽ mất (app sao lưu lại trước).", "Replace the data of the practice copy with the backup \(url.lastPathComponent)?\n\nThe current data is lost (the app backs it up first).", "用备份 \(url.lastPathComponent) 替换试用版的数据？\n\n当前数据将丢失（应用会先备份）。")) else { return }
        do {
            try Backups.named(queue, folder: folder, label: "truoc-khoi-phuc")
            try Reset.restore(queue, from: url)
            model.changed()
            UI.info(tr("Đã khôi phục từ \(url.lastPathComponent).", "Restored from \(url.lastPathComponent).", "已从 \(url.lastPathComponent) 恢复。"))
        } catch { UI.error(tr("Không khôi phục được: \(UI.message(error))", "Could not restore: \(UI.message(error))", "无法恢复：\(UI.message(error))")) }
    }
}

/// Settings → Gói dữ liệu .dibekho: hand all data to another machine, or take a package in (practice copy only).
@MainActor
enum TransferScreens {
    static func export(_ model: AppModel) {
        guard let queue = model.queue, let folders = model.folders, model.writable else { return UI.error(Texts.readOnly) }
        let device = Workspace.device()
        do {
            let url = try Transfer.exportPackage(queue, folders, deviceName: device.name, deviceId: device.id)
            model.changed()
            UI.info(tr("Đã tạo gói dữ liệu:\n\(url.lastPathComponent)\n\nNó nằm trong thư mục output. Chép sang máy kia rồi bấm «Nhập gói dữ liệu».", "The data package was made:\n\(url.lastPathComponent)\n\nIt is in the output folder. Copy it to the other computer and click “Import a data package”.", "数据包已创建：\n\(url.lastPathComponent)\n\n它在 output 文件夹中。复制到另一台电脑后点击“导入数据包”。"))
            UI.open(url.deletingLastPathComponent())
        } catch { UI.error(tr("Không tạo được gói dữ liệu: \(UI.message(error))", "Could not make the data package: \(UI.message(error))", "无法创建数据包：\(UI.message(error))")) }
    }

    private static func fail(_ text: String) -> Bool {
        UI.error(text)
        return false
    }

    /// url: a package already chosen (the Inbox); nil = ask. True when imported.
    @discardableResult
    static func importPackage(_ model: AppModel, url chosen: URL? = nil) -> Bool {
        guard model.practice, let queue = model.queue, let folders = model.folders else {
            return fail(tr("Chỉ nhập gói dữ liệu được trên bản thử.", "A data package can be imported only into the practice copy.", "只能把数据包导入试用版。"))
        }
        var picked = chosen
        if picked == nil {
            let panel = NSOpenPanel()
            panel.title = tr("Chọn gói dữ liệu .dibekho", "Choose a .dibekho data package", "选择 .dibekho 数据包")
            panel.allowedContentTypes = [UTType(filenameExtension: Transfer.ext) ?? .data]
            panel.canChooseDirectories = false
            panel.allowsMultipleSelection = false
            panel.directoryURL = folders.input
            guard panel.runModal() == .OK else { return false }
            picked = panel.url
        }
        guard let url = picked else { return false }
        let manifest: Transfer.Manifest
        do { manifest = try Transfer.readManifest(url) } catch { return fail(UI.message(error)) }
        var text = tr("Nhập gói của máy «\(manifest.deviceName)» (tạo lúc \(manifest.exportedAt), \(manifest.deliveries) phiếu giao, \(manifest.products) mặt hàng)?\n\nDữ liệu của bản thử sẽ được thay bằng gói này. App sao lưu trước.", "Import the package of the computer “\(manifest.deviceName)” (made at \(manifest.exportedAt), \(manifest.deliveries) delivery notes, \(manifest.products) products)?\n\nThe data of the practice copy is replaced by this package. The app backs up first.", "导入电脑“\(manifest.deviceName)”的数据包（创建于 \(manifest.exportedAt)，\(manifest.deliveries) 份送货单，\(manifest.products) 种商品）？\n\n试用版的数据将被这个数据包替换。应用会先备份。")
        if (try? queue.read { try Transfer.hasUnsentChanges($0) }) == true {
            text = tr("⚠ Bản thử có thay đổi chưa gửi đi sau lần xuất gần nhất. Nhập gói sẽ làm mất các thay đổi đó.\n\n", "⚠ The practice copy has changes that were not sent since the last export. Importing the package loses them.\n\n", "⚠ 自上次导出以来，试用版中有尚未发送的更改。导入数据包会丢失这些更改。\n\n") + text
        }
        if Transfer.isOlder(manifest) { text += tr("\n\nGói này từ bản cũ hơn, app sẽ nâng cấp khi nhập.", "\n\nThis package is from an older version; the app upgrades it while importing.", "\n\n这个数据包来自旧版本，导入时应用会自动升级。") }
        guard UI.ask(text) else { return false }
        do {
            try Backups.named(queue, folder: folders.root.appendingPathComponent("sao-luu", isDirectory: true), label: "truoc-nhap-goi")
            let got = try Transfer.importPackage(queue, folders, url)
            try queue.write { try Transfer.afterImport($0, got) }
            _ = try? Transfer.moveToProcessed(folders, url)
            model.changed()
            model.rescan(quiet: true)
            UI.info(tr("Đã nhập dữ liệu từ máy «\(got.deviceName)».", "Imported the data of the computer “\(got.deviceName)”.", "已导入电脑“\(got.deviceName)”的数据。"))
            return true
        } catch { return fail(tr("Không nhập được: \(UI.message(error))", "Could not import: \(UI.message(error))", "无法导入：\(UI.message(error))")) }
    }
}
