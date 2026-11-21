import Foundation
import GRDB
import ZIPFoundation

/// Python core/transfer: hand all data to another machine as one ".dibekho" package (a zip: manifest.json, kho.sqlite,
/// phieu-goc/<sha256>.xlsx, data/app.log). Only one machine works at a time: importing REPLACES the local data (the
/// caller takes a backup first); there is no two-way merge.
public enum Transfer {
    public static let ext = "dibekho"
    public static let format = 1
    /// the Python app version whose behaviour this port follows (the manifest says who made the package)
    public static let appVersion = "0.6.2"

    public struct Manifest: Equatable {
        public var deviceName: String
        public var deviceId: String
        public var exportedAt: String
        public var schemaVersion: Int
        public var appVersion: String
        public var deliveries: Int
        public var products: Int
    }

    public struct TransferError: Error, LocalizedError {
        public let message: String
        init(_ message: String) { self.message = message }
        public var errorDescription: String? { message }
    }

    /// Local data changed after the last export/import.
    public static func hasUnsentChanges(_ db: Database) throws -> Bool {
        let changed = try Meta.get(db, "last_change_at"), transferred = try Meta.get(db, "last_transfer_at")
        return !changed.isEmpty && changed > transferred
    }

    // data/phieu-goc/<sha256>.xlsx; anything else there (an Excel lock file, a file the user put there) is not data
    static func isOriginalName(_ name: String) -> Bool {
        name.range(of: #"^[0-9a-f]{64}\.xlsx$"#, options: .regularExpression) != nil
    }

    static func originalFiles(_ f: ShopFolders) -> [URL] {
        let list = (try? FileManager.default.contentsOfDirectory(at: f.originals, includingPropertiesForKeys: nil)) ?? []
        return list.filter { isOriginalName($0.lastPathComponent) }.sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    /// Makes output/DiBeKho_<device>_<date>_<time>.dibekho. When it fails nothing is left and the work stays unsent.
    public static func exportPackage(_ queue: DatabaseQueue, _ f: ShopFolders, deviceName: String, deviceId: String) throws -> URL {
        let previous = try queue.read { try Meta.get($0, "last_transfer_at") }
        let before = Set((try? FileManager.default.contentsOfDirectory(atPath: f.output.path)) ?? [])
        do {
            return try makePackage(queue, f, deviceName, deviceId)
        } catch {
            try? queue.write { try Meta.set($0, "last_transfer_at", previous) }
            for name in ((try? FileManager.default.contentsOfDirectory(atPath: f.output.path)) ?? [])
            where !before.contains(name) && name.hasSuffix(".\(ext)") {
                try? FileManager.default.removeItem(at: f.output.appendingPathComponent(name))
            }
            throw error
        }
    }

    private static func safeDevice(_ name: String) -> String {
        let kept = name.filter { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" }
        return kept.isEmpty ? "may" : kept
    }

    private static func makePackage(_ queue: DatabaseQueue, _ f: ShopFolders, _ deviceName: String, _ deviceId: String) throws -> URL {
        let now = Meta.isoNow()
        let manifest: Manifest = try queue.write { db in
            try Meta.set(db, "last_transfer_at", now)
            try Meta.log(db, "export", deviceName)
            return Manifest(
                deviceName: deviceName, deviceId: deviceId, exportedAt: now, schemaVersion: try Schema.version(db),
                appVersion: appVersion,
                deliveries: try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM documents WHERE kind = 'delivery' AND status = 'active'") ?? 0,
                products: try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM products WHERE active = 1") ?? 0)
        }
        let fm = FileManager.default
        try fm.createDirectory(at: f.output, withIntermediateDirectories: true)
        // 2026-11-19T09:05:00 -> 2026-11-19_0905
        let day = String(now.prefix(10)), clock = String(now.dropFirst(11).prefix(5)).replacingOccurrences(of: ":", with: "")
        let dest = f.output.appendingPathComponent("DiBeKho_\(safeDevice(deviceName))_\(day)_\(clock).\(ext)")
        let tmp = fm.temporaryDirectory.appendingPathComponent("dibekho-export-\(UUID().uuidString)")
        try fm.createDirectory(at: tmp, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: tmp) }
        let snap = tmp.appendingPathComponent("kho.sqlite")
        try Backups.snapshot(queue, to: snap)
        let head: [String: Any] = [
            "device_name": manifest.deviceName, "device_id": manifest.deviceId, "exported_at": manifest.exportedAt,
            "schema_version": manifest.schemaVersion, "app_version": manifest.appVersion, "deliveries": manifest.deliveries,
            "products": manifest.products, "format": format]
        let json = try JSONSerialization.data(withJSONObject: head, options: [.sortedKeys])
        if fm.fileExists(atPath: dest.path) { try fm.removeItem(at: dest) }
        let archive = try Archive(url: dest, accessMode: .create)
        func add(_ path: String, _ data: Data) throws {
            try archive.addEntry(with: path, type: .file, uncompressedSize: Int64(data.count), compressionMethod: .deflate) {
                position, size in data.subdata(in: Data.Index(position)..<(Data.Index(position) + size))
            }
        }
        try add("manifest.json", json)
        try add("kho.sqlite", try Data(contentsOf: snap))
        for file in originalFiles(f) { try add("phieu-goc/\(file.lastPathComponent)", try Data(contentsOf: file)) }
        if let log = ActivityLog.file, let data = fm.contents(atPath: log.path) { try add("data/app.log", data) }
        return dest
    }

    /// The package comes from an earlier version (older schema): it is upgraded when imported.
    public static func isOlder(_ m: Manifest) -> Bool { m.schemaVersion < Schema.supportedVersion }

    public static func readManifest(_ url: URL) throws -> Manifest {
        let archive: Archive
        var data = Data()
        do {
            archive = try Archive(url: url, accessMode: .read)
            guard let entry = archive["manifest.json"] else { throw TransferError("manifest") }
            _ = try archive.extract(entry, consumer: { data.append($0) })
        } catch {
            throw TransferError("File gói dữ liệu bị hỏng: \(error.localizedDescription)")
        }
        if archive["kho.sqlite"] == nil { throw TransferError("Gói dữ liệu thiếu database.") }
        guard let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any], let version = object["schema_version"] as? Int else {
            throw TransferError("File gói dữ liệu bị hỏng: thiếu thông tin phiên bản.")
        }
        func int(_ key: String) -> Int { (object[key] as? Int) ?? 0 }
        func str(_ key: String) -> String { (object[key] as? String) ?? "" }
        let m = Manifest(deviceName: str("device_name"), deviceId: str("device_id"), exportedAt: str("exported_at"),
                         schemaVersion: version, appVersion: str("app_version"), deliveries: int("deliveries"), products: int("products"))
        if m.schemaVersion > Schema.supportedVersion {
            throw TransferError("Gói dữ liệu được tạo bởi phiên bản DiBeKho mới hơn. Hãy cập nhật app trước.")
        }
        return m
    }

    /// Replaces the data of `queue` by the package's (the caller took a backup first); the kept originals are added.
    /// Then call afterImport. When anything is wrong nothing on this computer is changed.
    @discardableResult
    public static func importPackage(_ queue: DatabaseQueue, _ f: ShopFolders, _ url: URL) throws -> Manifest {
        let manifest = try readManifest(url)
        let fm = FileManager.default
        let tmp = fm.temporaryDirectory.appendingPathComponent("dibekho-import-\(UUID().uuidString)")
        try fm.createDirectory(at: tmp, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: tmp) }
        let archive: Archive
        do { archive = try Archive(url: url, accessMode: .read) } catch {
            throw TransferError("File gói dữ liệu bị hỏng: \(error.localizedDescription)")
        }
        let extracted = tmp.appendingPathComponent("kho.sqlite")
        do {
            guard let entry = archive["kho.sqlite"] else { throw TransferError("Gói dữ liệu thiếu database.") }
            _ = try archive.extract(entry, to: extracted)
        } catch let e as TransferError {
            throw e
        } catch {
            throw TransferError("File gói dữ liệu bị hỏng: \(error.localizedDescription)")
        }
        try checkDatabase(extracted, manifest)
        // an older package is brought to this version's schema on the extracted copy: if that fails nothing is replaced
        let copy = try DatabaseQueue(path: extracted.path, configuration: Store.configuration())
        try Schema.migrate(copy)
        try fm.createDirectory(at: f.originals, withIntermediateDirectories: true)
        for entry in archive where entry.path.hasPrefix("phieu-goc/") && isOriginalName((entry.path as NSString).lastPathComponent) {
            let target = f.originals.appendingPathComponent((entry.path as NSString).lastPathComponent)
            if !fm.fileExists(atPath: target.path) { _ = try archive.extract(entry, to: target) }
        }
        try copy.backup(to: queue)
        try queue.write { try Sync.ensureTriggers($0) }
        saveSenderLog(archive, manifest, f)
        return manifest
    }

    /// A DiBeKho database of the version the manifest says; an empty or foreign file would otherwise be "upgraded"
    /// into a brand-new empty database and replace all local data.
    static func checkDatabase(_ file: URL, _ manifest: Manifest) throws {
        let broken = TransferError("File gói dữ liệu bị hỏng hoặc không phải dữ liệu DiBeKho. Dữ liệu trên máy này không bị thay đổi.")
        do {
            let check = try DatabaseQueue(path: file.path, configuration: Store.configuration(readonly: true))
            let (version, tables, quick) = try check.read { db -> (Int, Set<String>, String) in
                (try Schema.version(db),
                 Set(try String.fetchAll(db, sql: "SELECT name FROM sqlite_master WHERE type = 'table'")),
                 try String.fetchOne(db, sql: "PRAGMA quick_check") ?? "")
            }
            if version < 1 || version != manifest.schemaVersion || !Set(["products", "documents"]).isSubset(of: tables) || quick != "ok" {
                throw broken
            }
        } catch let e as TransferError {
            throw e
        } catch {
            throw TransferError("File gói dữ liệu bị hỏng: \(error.localizedDescription)")
        }
    }

    /// The sending machine's own log, saved apart (data/nhat-ky-<máy gửi>.log), never this machine's app.log; the
    /// last 7 days only.
    private static func saveSenderLog(_ archive: Archive, _ m: Manifest, _ f: ShopFolders) {
        guard let entry = archive["data/app.log"] else { return }
        var data = Data()
        guard (try? archive.extract(entry, consumer: { data.append($0) })) != nil else { return }
        let text = String(decoding: data, as: UTF8.self)
        let dest = f.root.appendingPathComponent("data/nhat-ky-\(safeDevice(m.deviceName)).log")
        try? FileManager.default.createDirectory(at: dest.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? trimOld(text).write(to: dest, atomically: true, encoding: .utf8)
    }

    /// Python activity.trim_old: drop lines older than 7 days, with the indented traceback lines that follow them.
    static func trimOld(_ text: String, today: Date = Date()) -> String {
        let cutoff = Dates.iso(today.addingTimeInterval(-7 * 86400))
        var keep = false
        var out: [String] = []
        for line in text.components(separatedBy: "\n") {
            if line.isEmpty || line.hasPrefix("    ") {
                if keep { out.append(line) }
                continue
            }
            keep = String(line.prefix(10)) >= cutoff
            if keep { out.append(line) }
        }
        return out.joined(separator: "\n")
    }

    /// After the data was replaced: paths in the package belong to the other machine, so the "missing" warnings for
    /// them are hidden (the next scan re-links files that exist here with the same content).
    public static func afterImport(_ db: Database, _ m: Manifest) throws {
        try db.execute(sql: "UPDATE scanned_files SET status = 'missing_ignored' WHERE status IN ('imported', 'missing')")
        let now = Meta.isoNow()
        try Meta.set(db, "last_transfer_at", now)
        try Meta.set(db, "last_change_at", now)
        try Meta.set(db, "last_import_from", "\(m.deviceName) (\(m.exportedAt))")
        try acceptCountsAsIs(db, m)
        try Meta.log(db, "import", m.deviceName)
    }

    // The check "order read after a stock count" came with 0.4.4. A package from an older app holds data its user
    // already worked with as it is: those orders are taken as decided (nothing changes in the stock).
    static func version(_ text: String) -> [Int] {
        let parts = text.isEmpty ? ["0"] : text.split(separator: ".").prefix(3).map(String.init)
        let numbers = parts.compactMap { Int($0) }
        return numbers.count == parts.count ? numbers : [0]
    }

    @discardableResult
    static func acceptCountsAsIs(_ db: Database, _ m: Manifest) throws -> Int {
        if !version(m.appVersion).lexicographicallyPrecedes([0, 4, 4]) { return 0 }
        let found = try Deliveries.countConflicts(db)
        for c in found { try Deliveries.markChecked(db, c.id) }
        return found.count
    }

    /// The package moves to input/da-xu-ly/ (as the Python app does after a successful import).
    @discardableResult
    public static func moveToProcessed(_ f: ShopFolders, _ url: URL) throws -> URL {
        let folder = f.input.appendingPathComponent(Deliveries.processed, isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let stamp = Meta.isoNow().replacingOccurrences(of: "-", with: "").replacingOccurrences(of: ":", with: "")
            .replacingOccurrences(of: "T", with: "-")
        let dest = folder.appendingPathComponent("\(url.deletingPathExtension().lastPathComponent)__\(stamp).\(url.pathExtension)")
        try FileManager.default.moveItem(at: url, to: dest)
        return dest
    }
}
