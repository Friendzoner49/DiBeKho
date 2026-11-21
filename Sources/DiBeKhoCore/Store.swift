import Foundation
import GRDB

/// Phase 0 reads a private COPY of the data: the original kho.sqlite is opened read-only and copied with SQLite's
/// backup (it works while the Python app has the file open), the copy is brought to the current schema, and the
/// original is never written. The copies hold customer data, so they are removed when another one is made and when
/// the app quits.
public enum Store {
    public static var copiesFolder: URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("DiBeKhoSwift", isDirectory: true)
    }

    /// Fails when the file is not DiBeKho data or is from a newer app.
    static func check(_ db: Database) throws {
        let version = try Schema.version(db)
        let tables = try Int.fetchOne(db, sql: """
            SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name IN ('products', 'documents', 'stock_movements')
            """) ?? 0
        if version < 1 || tables < 3 { throw DataError.notDiBeKho }
        if version > Schema.supportedVersion {
            throw DataError.newer(found: version, supported: Schema.supportedVersion)
        }
    }

    /// The connection settings of every database this app reads: the Python app registers unaccent() and
    /// matches_words() in SQLite (db.connect); the search queries use them.
    public static func configuration(readonly: Bool = false) -> Configuration {
        var config = Configuration()
        config.readonly = readonly
        config.prepareDatabase { db in
            db.add(function: DatabaseFunction("unaccent", argumentCount: 1, pure: true) { values in
                TextRules.unaccent(sqlText(values[0]))
            })
            db.add(function: DatabaseFunction("matches_words", argumentCount: 2, pure: true) { values in
                TextRules.matchesWords(sqlText(values[0]) ?? "", sqlText(values[1]) ?? "")
            })
        }
        return config
    }

    /// A value given to an SQL function as Python's str() would see it (NULL -> nil).
    static func sqlText(_ value: DatabaseValue) -> String? {
        switch value.storage {
        case .null: return nil
        case let .int64(i): return String(i)
        case let .double(d): return String(d)
        case let .string(s): return s
        case let .blob(data): return String(data: data, encoding: .utf8)
        }
    }

    public static func openCopy(of source: URL) throws -> (queue: DatabaseQueue, file: URL) {
        var readOnly = Configuration()
        readOnly.readonly = true
        let original = try DatabaseQueue(path: source.path, configuration: readOnly)
        defer { try? original.close() }
        try original.read { try check($0) }

        removeCopies()
        try FileManager.default.createDirectory(at: copiesFolder, withIntermediateDirectories: true)
        let file = copiesFolder.appendingPathComponent("kho-\(UUID().uuidString).sqlite")
        let copy = try DatabaseQueue(path: file.path, configuration: configuration())
        try original.backup(to: copy)
        try Schema.migrate(copy)
        try copy.write { try Sync.ensureTriggers($0) }
        return (copy, file)
    }

    public static func removeCopies() {
        try? FileManager.default.removeItem(at: copiesFolder)
    }
}

/// Where the Python app keeps its data on this Mac. Only read: config.json is never written here.
public enum Workspace {
    public static var configFile: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/DiBeKho/config.json")
    }

    /// The machine's name as core/workspace.py gives it: socket.gethostname() up to the first dot. Not
    /// ProcessInfo.hostName: that one asks the network (DNS / Bonjour) and macOS 15 then shows "Allow … to find devices
    /// on local networks?" when the app opens, which also blocked the CI screenshots.
    public static func shortHostName() -> String {
        var buffer = [CChar](repeating: 0, count: 256)
        guard gethostname(&buffer, buffer.count) == 0 else { return "may" }
        let name = String(cString: buffer).split(separator: ".").first.map(String.init) ?? ""
        return name.isEmpty ? "may" : name
    }

    /// This machine's name and id for a package: from config.json when the Python app made them, else the host name.
    public static func device() -> (name: String, id: String) {
        let object = (try? Data(contentsOf: configFile)).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
        let host = Workspace.shortHostName()
        let name = (object?["device_name"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? host
        let id = (object?["device_id"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "swift"
        return (name, id)
    }

    /// data/kho.sqlite of the work folder named in config.json, when it is there.
    public static func liveDatabase() -> URL? {
        guard let data = try? Data(contentsOf: configFile),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let folder = object["workspace"] as? String, !folder.isEmpty else { return nil }
        let file = URL(fileURLWithPath: folder).appendingPathComponent("data/kho.sqlite")
        return FileManager.default.fileExists(atPath: file.path) ? file : nil
    }
}
