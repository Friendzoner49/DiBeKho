import Foundation
import GRDB

/// The first start on a Mac that has no work folder yet (core/workspace.py `Workspace.ensure`, `Config.create`, app.py's
/// first-run box). Only used when config.json does not exist: an existing config.json or database is never rewritten.
public enum FirstRun {
    /// The folder the Python app offers: Documents/DiBeKho.
    public static var defaultFolder: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Documents/DiBeKho")
    }

    /// true while this Mac has neither config.json nor data
    public static var needed: Bool { !FileManager.default.fileExists(atPath: Workspace.configFile.path) }

    /// The cloud services whose folders damage an open database (the Python app warns about them).
    public static func syncService(_ folder: URL) -> String? {
        let path = folder.path.lowercased()
        for (needle, name) in [("onedrive", "OneDrive"), ("icloud", "iCloud"), ("mobile documents", "iCloud"),
                               ("google drive", "Google Drive"), ("googledrive", "Google Drive"), ("dropbox", "Dropbox")]
        where path.contains(needle) { return name }
        return nil
    }

    /// Makes the work folder (the same sub-folders as the Python app), an empty database at the current schema and
    /// config.json (workspace, language, device id and name; the other keys keep the Python defaults).
    /// Refuses when config.json exists or the folder already holds a database.
    public static func create(folder: URL, language: String, config configFile: URL = Workspace.configFile) throws {
        let fm = FileManager.default
        let database = folder.appendingPathComponent("data/kho.sqlite")
        guard !fm.fileExists(atPath: database.path) else { throw FirstRunError.dataExists }
        if fm.fileExists(atPath: configFile.path) {
            // a config.json whose work folder still holds its database is live: never replaced. One left behind by an
            // old install whose folder is gone points at nothing: it is set aside (config.json.cu), not deleted.
            guard !pointsAtDatabase(configFile) else { throw FirstRunError.configExists }
            let aside = configFile.appendingPathExtension("cu")
            try? fm.removeItem(at: aside)
            try fm.moveItem(at: configFile, to: aside)
        }
        for sub in ["phieu-giao-hang/da-xu-ly", "input/da-xu-ly", "output", "sao-luu", "data", "phieu-goc"] {
            try fm.createDirectory(at: folder.appendingPathComponent(sub), withIntermediateDirectories: true)
        }
        let queue = try DatabaseQueue(path: database.path, configuration: Store.configuration())
        try Schema.migrate(queue)
        try queue.close()
        let host = Workspace.shortHostName()
        let config: [String: Any] = [
            "workspace": folder.path,
            "language": ["vi", "en", "zh"].contains(language) ? language : "vi",
            "device_id": String(UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased().prefix(12)),
            "device_name": host,
            "ui_scale": 1.2,
        ]
        let data = try JSONSerialization.data(withJSONObject: config, options: [.prettyPrinted, .sortedKeys])
        try fm.createDirectory(at: configFile.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: configFile, options: .atomic)
    }

    /// true when the config file names a work folder that has data/kho.sqlite
    static func pointsAtDatabase(_ configFile: URL) -> Bool {
        guard let data = try? Data(contentsOf: configFile),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let folder = object["workspace"] as? String, !folder.isEmpty else { return false }
        return FileManager.default.fileExists(atPath: URL(fileURLWithPath: folder).appendingPathComponent("data/kho.sqlite").path)
    }

    /// Cài đặt → Đổi thư mục… (settings_page.change_folder): config.json points at another folder from the next start;
    /// every other key stays as it was. The folder gets the sub-folders and an empty database when it has none
    /// (the Python app's Workspace.ensure on the next start); a database already there is opened as it is. The data of
    /// the old folder does not move.
    public static func changeWorkspace(to folder: URL, config configFile: URL = Workspace.configFile) throws {
        let fm = FileManager.default
        // read-modify-write as CloudConfig.save: a config.json that cannot be read is never replaced
        var config: [String: Any] = [:]
        if fm.fileExists(atPath: configFile.path) {
            guard let object = try JSONSerialization.jsonObject(with: Data(contentsOf: configFile)) as? [String: Any] else {
                throw WriteError("Không đọc được config.json.")
            }
            config = object
        }
        for sub in ["phieu-giao-hang/da-xu-ly", "input/da-xu-ly", "output", "sao-luu", "data", "phieu-goc"] {
            try fm.createDirectory(at: folder.appendingPathComponent(sub), withIntermediateDirectories: true)
        }
        let database = folder.appendingPathComponent("data/kho.sqlite")
        if !fm.fileExists(atPath: database.path) {
            let queue = try DatabaseQueue(path: database.path, configuration: Store.configuration())
            try Schema.migrate(queue)
            try queue.close()
        }
        config["workspace"] = folder.path
        let data = try JSONSerialization.data(withJSONObject: config, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
        try fm.createDirectory(at: configFile.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: configFile, options: .atomic)
    }
}

public enum FirstRunError: Error, LocalizedError {
    case configExists, dataExists

    public var errorDescription: String? {
        switch self {
        case .configExists: return "Máy này đã có config.json của DiBeKho; không tạo thư mục mới đè lên."
        case .dataExists: return "Thư mục này đã có dữ liệu của DiBeKho. Hãy mở nó bằng bản DiBeKho đang dùng thay vì tạo mới."
        }
    }
}
