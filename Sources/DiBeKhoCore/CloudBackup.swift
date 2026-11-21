import Compression
import Foundation
import GRDB

/// Python core/cloud/backup.py (upload side): a consistent copy of kho.sqlite, gzip-compressed, in the private Storage
/// bucket 'backups' (the newest 10 kept), and the kept delivery notes (data/phieu-goc/<sha256>.xlsx) under phieu-goc/,
/// each file once. Restoring from the cloud: CloudRestore.swift.
public enum CloudBackup {
    static let keep = 10
    static let originalsFolder = "phieu-goc"

    static func safeDevice(_ name: String) -> String {
        let kept = name.filter { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" }
        return kept.isEmpty ? "may" : kept
    }

    /// 2026-11-11T09-30-00Z__FRIENDZONER__s9.sqlite.gz  (UTC time, machine name, schema version)
    static func makeName(deviceName: String, schemaVersion: Int, now: Date = Date()) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyy-MM-dd'T'HH-mm-ss'Z'"
        return "\(f.string(from: now))__\(safeDevice(deviceName))__s\(schemaVersion).sqlite.gz"
    }

    static func isBackupName(_ name: String) -> Bool {
        name.range(of: #"^\d{4}-\d\d-\d\dT\d\d-\d\d-\d\dZ__.+__s\d+\.sqlite(\.gz)?$"#, options: .regularExpression) != nil
    }

    // ---- gzip (the Compression framework gives raw deflate; the gzip header and trailer are written here)

    static let crcTable: [UInt32] = (0..<256).map { n -> UInt32 in
        var c = UInt32(n)
        for _ in 0..<8 { c = (c & 1) != 0 ? 0xEDB8_8320 ^ (c >> 1) : c >> 1 }
        return c
    }

    static func crc32(_ data: Data) -> UInt32 {
        var c: UInt32 = 0xFFFF_FFFF
        for b in data { c = crcTable[Int((c ^ UInt32(b)) & 0xFF)] ^ (c >> 8) }
        return c ^ 0xFFFF_FFFF
    }

    static func gzip(_ data: Data) throws -> Data {
        guard let deflated = try? (data as NSData).compressed(using: .zlib) as Data else { throw CloudError("Không nén được bản sao lưu.") }
        var out = Data([0x1F, 0x8B, 8, 0, 0, 0, 0, 0, 0, 0xFF])
        out.append(deflated)
        var crc = crc32(data).littleEndian
        var size = UInt32(truncatingIfNeeded: data.count).littleEndian
        out.append(Data(bytes: &crc, count: 4))
        out.append(Data(bytes: &size, count: 4))
        return out
    }

    // ---- the database

    /// Upload a consistent copy of the database, then drop the oldest beyond `keep`. Returns the cloud file name.
    public static func uploadSnapshot(_ queue: DatabaseQueue, deviceName: String, _ client: CloudClient, _ token: String) async throws -> String {
        let schema = try await queue.read { try Int.fetchOne($0, sql: "PRAGMA user_version") ?? 0 }
        let name = makeName(deviceName: deviceName, schemaVersion: schema)
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("dibekho-cloud-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tmp) }
        let copy = tmp.appendingPathComponent("kho.sqlite")
        try Backups.snapshot(queue, to: copy)
        let data = try gzip(try Data(contentsOf: copy))
        try await client.storageUpload(name, data, token)
        _ = try await prune(client, token)
        return name
    }

    /// Names of our backups, newest first (names start with the UTC time). Files that are not ours are ignored.
    public static func list(_ client: CloudClient, _ token: String) async throws -> [String] {
        try await client.storageList(token).compactMap { $0["name"] as? String }.filter(isBackupName).sorted(by: >)
    }

    @discardableResult
    static func prune(_ client: CloudClient, _ token: String) async throws -> Int {
        let old = Array(try await list(client, token).dropFirst(keep))
        if !old.isEmpty { try await client.storageDelete(old, token) }
        return old.count
    }

    // ---- the kept delivery notes

    static func isOriginalName(_ name: String) -> Bool { name.range(of: "^[0-9a-f]{64}\\.xlsx$", options: .regularExpression) != nil }

    static func cloudOriginals(_ client: CloudClient, _ token: String) async throws -> Set<String> {
        var found: Set<String> = []
        var offset = 0
        while true {
            let rows = try await client.storageList(token, prefix: originalsFolder, limit: 1000, offset: offset)
            if rows.isEmpty { return found }  // read on until an empty page: the server may hand out fewer per page
            for r in rows { if let n = r["name"] as? String, isOriginalName(n) { found.insert(n) } }
            offset += rows.count
        }
    }

    /// Upload the kept notes the bucket does not have yet, stopping after `maxSeconds` (the rest go next time).
    /// -> (uploaded, still to upload)
    public static func uploadOriginals(_ originals: URL, _ client: CloudClient, _ token: String, maxSeconds: TimeInterval? = nil) async throws -> (Int, Int) {
        let names = ((try? FileManager.default.contentsOfDirectory(atPath: originals.path)) ?? []).filter(isOriginalName).sorted()
        if names.isEmpty { return (0, 0) }
        let have = try await cloudOriginals(client, token)
        let todo = names.filter { !have.contains($0) }
        let started = Date()
        var done = 0
        for name in todo {
            if let limit = maxSeconds, Date().timeIntervalSince(started) > limit { break }
            let data = try Data(contentsOf: originals.appendingPathComponent(name))
            try await client.storageUpload("\(originalsFolder)/\(name)", data, token)
            done += 1
        }
        return (done, todo.count - done)
    }
}
