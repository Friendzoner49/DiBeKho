import AppKit
import DiBeKhoCore
import GRDB
import SwiftUI

/// Settings → Sao lưu (ui/settings_page.py): back up now. Restoring and resetting the shop's data (shared on the
/// Cloud) are not in this app yet.
@MainActor
enum ResetScreens {
    private static func backupsFolder(_ model: AppModel) -> URL? {
        model.folders?.root.appendingPathComponent("sao-luu", isDirectory: true)
    }

    static func backupNow(_ model: AppModel) {
        guard let queue = model.queue, let folder = backupsFolder(model), model.writable else { return UI.error(Texts.notOpen) }
        do {
            let url = try Backups.named(queue, folder: folder, label: "thu-cong")
            UI.info(tr("Đã sao lưu: \(url.lastPathComponent)", "Backed up: \(url.lastPathComponent)", "已备份：\(url.lastPathComponent)"))
        } catch { UI.error(tr("Không sao lưu được: \(UI.message(error))", "Could not back up: \(UI.message(error))", "无法备份：\(UI.message(error))")) }
    }

}

/// Settings → Gói dữ liệu .dibekho: hand all data to another machine (taking a package in is not in this app yet).
@MainActor
enum TransferScreens {
    static func export(_ model: AppModel) {
        guard let queue = model.queue, let folders = model.folders, model.writable else { return UI.error(Texts.notOpen) }
        let device = Workspace.device()
        do {
            let url = try Transfer.exportPackage(queue, folders, deviceName: device.name, deviceId: device.id)
            model.changed()
            UI.info(tr("Đã tạo gói dữ liệu:\n\(url.lastPathComponent)\n\nNó nằm trong thư mục output. Chép sang máy kia rồi bấm «Nhập gói dữ liệu».", "The data package was made:\n\(url.lastPathComponent)\n\nIt is in the output folder. Copy it to the other computer and click “Import a data package”.", "数据包已创建：\n\(url.lastPathComponent)\n\n它在 output 文件夹中。复制到另一台电脑后点击“导入数据包”。"))
            UI.open(url.deletingLastPathComponent())
        } catch { UI.error(tr("Không tạo được gói dữ liệu: \(UI.message(error))", "Could not make the data package: \(UI.message(error))", "无法创建数据包：\(UI.message(error))")) }
    }

}
