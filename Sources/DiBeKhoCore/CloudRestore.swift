import CryptoKit
import Foundation
import GRDB

/// A full backup kept on the cloud (core/cloud/backup.py CloudBackup).
public struct CloudBackupItem: Equatable {
    public let name: String
    public let at: Date  // shown in local time
    public let device: String
    public let schema: Int
    public let size: Int
}

/// What 'Tải file gốc từ Cloud' did, by file name (Python backup.Download).
public struct OriginalsDownload: Sendable {
    public var got: [String] = []
    /// not on the cloud: the computer that made the order has not sent it yet
    public var absent: [String] = []
    /// on the cloud but did not arrive whole (the line dropped)
    public var failed: [String] = []
    public init() {}
}

/// Python core/cloud/backup.py, the restore side: list the backups, download one and check it, mark the notes of
/// another machine as not missing here, and download the kept delivery notes this machine lacks.
extension CloudBackup {
    /// 2026-11-11T09-30-00Z__FRIENDZONER__s9.sqlite(.gz) -> its parts (parse_name)
    public static func parse(_ name: String, size: Int = 0) -> CloudBackupItem? {
        let pattern = #"^(\d{4}-\d\d-\d\dT\d\d-\d\d-\d\dZ)__(.+)__s(\d+)\.sqlite(\.gz)?$"#
        guard let regex = try? NSRegularExpression(pattern: pattern),
              let m = regex.firstMatch(in: name, range: NSRange(name.startIndex..., in: name)),
              let atRange = Range(m.range(at: 1), in: name), let deviceRange = Range(m.range(at: 2), in: name),
              let schemaRange = Range(m.range(at: 3), in: name), let schema = Int(name[schemaRange]) else { return nil }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyy-MM-dd'T'HH-mm-ss'Z'"
        guard let at = f.date(from: String(name[atRange])) else { return nil }
        return CloudBackupItem(name: name, at: at, device: String(name[deviceRange]), schema: schema, size: size)
    }

    /// Newest first (names start with the UTC time). Files that are not ours are ignored. (list_backups)
    public static func listBackups(_ client: CloudClient, _ token: String) async throws -> [CloudBackupItem] {
        var found: [CloudBackupItem] = []
        for row in try await client.storageList(token) {
            let metadata = row["metadata"] as? [String: Any]
            let size = (metadata?["size"] as? NSNumber)?.intValue ?? 0
            if let name = row["name"] as? String, let item = parse(name, size: size) { found.append(item) }
        }
        return found.sorted { $0.name > $1.name }
    }

    /// The gzip file of Python's gzip.compress back to its bytes (header fields skipped, then raw deflate).
    static func gunzip(_ data: Data) throws -> Data {
        let bytes = [UInt8](data)
        guard bytes.count >= 18, bytes[0] == 0x1F, bytes[1] == 0x8B, bytes[2] == 8 else {
            throw CloudError("Bản sao lưu trên Cloud bị hỏng: Not a gzipped file")
        }
        let flags = bytes[3]
        var pos = 10
        if flags & 4 != 0 {  // FEXTRA
            guard pos + 2 <= bytes.count else { throw CloudError("Bản sao lưu trên Cloud bị hỏng: truncated") }
            pos += 2 + Int(bytes[pos]) + Int(bytes[pos + 1]) << 8
        }
        for flag: UInt8 in [8, 16] where flags & flag != 0 {  // FNAME, FCOMMENT: text up to a zero byte
            while pos < bytes.count && bytes[pos] != 0 { pos += 1 }
            pos += 1
        }
        if flags & 2 != 0 { pos += 2 }  // FHCRC
        guard pos <= bytes.count - 8 else { throw CloudError("Bản sao lưu trên Cloud bị hỏng: truncated") }
        let body = Data(bytes[pos..<(bytes.count - 8)])
        guard let out = try? (body as NSData).decompressed(using: .zlib) as Data else {
            throw CloudError("Bản sao lưu trên Cloud bị hỏng: invalid data")
        }
        let tail = bytes.count - 8
        let crc = UInt32(bytes[tail]) | UInt32(bytes[tail + 1]) << 8 | UInt32(bytes[tail + 2]) << 16 | UInt32(bytes[tail + 3]) << 24
        if crc32(out) != crc { throw CloudError("Bản sao lưu trên Cloud bị hỏng: CRC check failed") }
        return out
    }

    /// Download one backup into `folder` as kho.sqlite and check it (fetch). Nothing local is touched.
    public static func fetch(_ client: CloudClient, _ token: String, name: String, into folder: URL) async throws -> URL {
        var data = try await client.storageDownload(name, token)
        if name.hasSuffix(".gz") { data = try gunzip(data) }
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let path = folder.appendingPathComponent("kho.sqlite")
        try data.write(to: path)
        _ = try validate(path)
        return path
    }

    /// Schema version of the file when it is safe to restore, else CloudError (validate): a real DiBeKho database,
    /// healthy, not from a newer app; an older one is upgraded (it is a copy in a temporary folder).
    @discardableResult
    public static func validate(_ path: URL) throws -> Int {
        var version = 0, tables = 0, healthy = false
        do {
            let check = try DatabaseQueue(path: path.path, configuration: Store.configuration(readonly: true))
            defer { try? check.close() }
            try check.read { db in
                version = try Int.fetchOne(db, sql: "PRAGMA user_version") ?? 0
                tables = try Int.fetchOne(db, sql: """
                    SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name IN ('products', 'documents', 'stock_movements')
                    """) ?? 0
                healthy = try String.fetchOne(db, sql: "PRAGMA quick_check") == "ok"
            }
        } catch {
            throw CloudError("Bản sao lưu trên Cloud bị hỏng: \(error)")
        }
        if version < 1 || tables < 3 || !healthy {
            throw CloudError("Bản sao lưu trên Cloud bị hỏng hoặc không phải dữ liệu DiBeKho. Dữ liệu trên máy "
                + "này không bị thay đổi.")
        }
        if version > Schema.supportedVersion {
            throw CloudError("Bản sao lưu này do phiên bản DiBeKho mới hơn tạo ra. Hãy cập nhật app trước.")
        }
        if version < Schema.supportedVersion {
            do {
                let upgraded = try DatabaseQueue(path: path.path, configuration: Store.configuration())
                try Schema.migrate(upgraded)
                try upgraded.close()
            } catch {
                throw CloudError("Không nâng cấp được bản sao lưu cũ: \(error)")
            }
        }
        return version
    }

    /// Right after the database was replaced by `chosen` (after_restore): a backup made by ANOTHER machine carries that
    /// machine's file list, whose read/missing notes would all show up as lost files here, so they are hidden.
    public static func afterRestore(_ db: Database, deviceName: String, _ chosen: CloudBackupItem) throws {
        if chosen.device != safeDevice(deviceName) {
            try db.execute(sql: "UPDATE scanned_files SET status = 'missing_ignored' WHERE status IN ('imported', 'missing')")
        }
        try Meta.log(db, "cloud_restore", chosen.name)
    }

    /// After a restore: download the kept notes this machine lacks; a file whose content does not match its name is not
    /// written. Never throws for one file. -> (downloaded, failed) (fetch_originals + fetch_named)
    public static func fetchOriginals(_ originals: URL, _ client: CloudClient, _ token: String) async -> (Int, Int) {
        let names: Set<String>
        do { names = try await cloudOriginals(client, token) } catch {
            ActivityLog.write("error", "cloud originals list: \(error)")  // not "nothing to fetch": a denied list shows here
            return (0, 0)
        }
        let have = Set(((try? FileManager.default.contentsOfDirectory(atPath: originals.path)) ?? []).filter(isOriginalName))
        return await fetchNamed(originals, client, token, names.subtracting(have).sorted())
    }

    /// 'Tải file gốc từ Cloud' (download_originals): the notes the user asked for, one by one; progress(done, total, name)
    /// before each. Stops when the task is cancelled. Throws only when the cloud cannot be reached at all.
    public static func downloadOriginals(_ originals: URL, _ client: CloudClient, _ token: String, _ names: [String],
                                         progress: (@MainActor (Int, Int, String) -> Void)? = nil) async throws -> OriginalsDownload {
        let onCloud = try await cloudOriginals(client, token)
        var result = OriginalsDownload()
        result.absent = names.filter { !onCloud.contains($0) }
        let todo = names.filter { onCloud.contains($0) }
        for (i, name) in todo.enumerated() {
            if Task.isCancelled { break }
            await progress?(i, todo.count, name)
            let (got, _) = await fetchNamed(originals, client, token, [name])
            if got > 0 { result.got.append(name) } else { result.failed.append(name) }
        }
        return result
    }

    /// Download these kept notes (<sha256>.xlsx) into data/phieu-goc, stopping after maxSeconds (the rest next time). A
    /// file whose content does not match its name, or that the bucket does not have, counts as failed. -> (downloaded,
    /// failed) (fetch_named)
    public static func fetchNamed(_ originals: URL, _ client: CloudClient, _ token: String, _ names: [String],
                                  maxSeconds: TimeInterval? = nil) async -> (Int, Int) {
        try? FileManager.default.createDirectory(at: originals, withIntermediateDirectories: true)
        let started = Date()
        var done = 0, failed = 0
        for name in names {
            if let maxSeconds, Date().timeIntervalSince(started) > maxSeconds { break }
            guard isOriginalName(name), let data = try? await client.storageDownload("\(originalsFolder)/\(name)", token) else {
                failed += 1
                continue
            }
            let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
            guard digest + ".xlsx" == name else {
                failed += 1
                continue
            }
            let tmp = originals.appendingPathComponent(name + ".tai-ve")
            do {
                try data.write(to: tmp)
                let target = originals.appendingPathComponent(name)
                if FileManager.default.fileExists(atPath: target.path) { try FileManager.default.removeItem(at: target) }
                try FileManager.default.moveItem(at: tmp, to: target)
                done += 1
            } catch {
                try? FileManager.default.removeItem(at: tmp)
                failed += 1
            }
        }
        return (done, failed)
    }
}

/// Python core/cloud/admin.py: replacing the whole shared data while it lives on the cloud. The new database is built as
/// a separate file; one push marks every live cloud row deleted and writes every row of the new database in a single
/// transaction on the server, so a failure leaves the cloud as it was. Only then does the caller put the file in place.
public enum CloudAdmin {
    public struct NotReady: LocalizedError {
        public let message: String
        public var errorDescription: String? { message }
    }

    /// Changes of this machine still waiting, or unresolved conflicts, would be lost (check_ready).
    public static func checkReady(_ db: Database) throws {
        if !(try TwoWay.conflicts(db)).isEmpty {
            throw NotReady(message: "Còn thay đổi bị trùng chưa giải quyết (Cài đặt → Cloud → Xem các thay đổi trùng). "
                + "Giải quyết xong rồi làm lại.")
        }
        if try TwoWay.queuedCount(db) > 0 {
            throw NotReady(message: "Máy này còn thay đổi chưa gửi lên Cloud. Hãy đợi dòng Cloud báo đã đồng bộ "
                + "(cần có mạng) rồi làm lại.")
        }
    }

    static func keyName(_ t: SyncTable) -> String { t.natural ? t.key : "id" }

    static func keyText(_ v: CloudValue) -> String {
        switch v {
        case .text(let s): return s
        case .int(let i): return String(i)
        default: return v.shown
        }
    }

    /// Every live cloud row marked deleted, then every row of the new database (build_batch + live_keys); the server
    /// applies the deletes first, so codes and keys are free again before the rows that take them are written.
    static func buildBatch(_ rows: [String: [CloudRow]], pulled: Pulled) -> [String: [CloudRow]] {
        var batch: [String: [CloudRow]] = [:]
        for t in SyncSchema.tables {
            let key = keyName(t)
            var live: [String: CloudValue] = [:]
            for r in pulled.tables[t.name] ?? [] where !(r["deleted"]?.isTrue ?? false) {
                if let v = r[key] { live[keyText(v)] = v }
            }
            let deletes: [CloudRow] = live.keys.sorted().map { [key: live[$0]!, "deleted": .bool(true)] }
            batch[t.name] = deletes + (rows[t.name] ?? [])
        }
        return batch
    }

    /// Make the cloud hold exactly the database at `newPath`, and prepare that file to carry on from there (cursor, empty
    /// queue, cloud mode on). Returns the cloud's revision. Throws NotReady / CloudError with the cloud unchanged.
    @discardableResult
    public static func replaceShared(_ live: DatabaseQueue, newPath: URL, _ client: CloudClient, _ token: String,
                                     device: String) async throws -> Int {
        try await live.read { try checkReady($0) }
        let pulled = try await CloudAccount.fetch(client, token, after: 0)
        let new = try DatabaseQueue(path: newPath.path, configuration: Store.configuration())
        do {
            let rows: [String: [CloudRow]] = try await new.write { db in
                try db.execute(sql: "DELETE FROM sync_outbox")
                try Replica.setEnabled(db, false)
                return try Replica.snapshot(db)
            }
            let batch = buildBatch(rows, pulled: pulled)
            let answer = try await CloudAccount.send(client, token, device: device, expected: pulled.maxRev, batch: batch)
            guard (answer["ok"] as? Bool) == true else {
                throw CloudError("Có máy khác hoặc trang web vừa ghi dữ liệu trong lúc thay. Chưa có gì bị đổi; "
                    + "hãy làm lại.")
            }
            let rev = (answer["max_rev"] as? NSNumber)?.intValue ?? pulled.maxRev
            try await new.write { db in
                try Meta.set(db, TwoWay.cursorKey, String(rev))
                try Meta.set(db, TwoWay.conflictsKey, "[]")
                try Replica.setEnabled(db, true)
            }
            try new.close()
            return rev
        } catch {
            try? new.close()
            throw error
        }
    }
}
