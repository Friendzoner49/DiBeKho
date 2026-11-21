import Darwin
import Foundation
import GRDB
import IOKit

/// data/dibekho.lock, the same file the Python app holds (ui/single_instance.py with Qt's QLockFile), so the two
/// apps never have the shop's data open at the same time. Written as Qt 6 writes it:
///   pid \n process name \n host name \n machine id \n boot id \n
/// created with O_EXCL and held with flock (Qt then cannot remove it as stale while this app runs). A lock left by a
/// copy that is gone (process ended, machine restarted) or written on another computer (the folder was copied) is
/// taken over, as the Python app does.
public final class LockFile {
    public let path: String
    private var fd: Int32 = -1

    private init(path: String) { self.path = path }

    /// The lock, kept until release() (or the app ends); nil when another copy of DiBeKho holds it.
    public static func acquire(_ url: URL) -> LockFile? {
        let lock = LockFile(path: url.path)
        for _ in 0..<2 {
            if lock.tryCreate() { return lock }
            guard let info = LockInfo.read(url.path) else { return nil }  // being written by the other app this instant
            if info.isLive { return nil }
            if !removeStale(url.path) { return nil }
        }
        return nil
    }

    private func tryCreate() -> Bool {
        let fd = open(path, O_RDWR | O_CREAT | O_EXCL, 0o666)
        if fd < 0 { return false }
        _ = flock(fd, LOCK_EX | LOCK_NB)
        let text = LockInfo.mine().contents
        _ = text.withCString { write(fd, $0, strlen($0)) }
        self.fd = fd
        return true
    }

    /// Qt's removeStaleLock: only when nobody holds it with flock.
    private static func removeStale(_ path: String) -> Bool {
        let fd = open(path, O_RDWR)
        if fd < 0 { return errno == ENOENT }
        defer { close(fd) }
        guard flock(fd, LOCK_EX | LOCK_NB) == 0 else { return false }
        return unlink(path) == 0
    }

    public func release() {
        guard fd >= 0 else { return }
        unlink(path)
        flock(fd, LOCK_UN)
        close(fd)
        fd = -1
    }

    deinit { release() }
}

/// What a lock file says (Qt LockFileInfo).
public struct LockInfo: Equatable {
    public var pid: Int32
    public var appName: String
    public var host: String
    public var machineId: String
    public var bootId: String

    public var contents: String { "\(pid)\n\(appName)\n\(host)\n\(machineId)\n\(bootId)\n" }

    public static func parse(_ text: String) -> LockInfo? {
        let lines = text.components(separatedBy: "\n")
        guard lines.count >= 3, let pid = Int32(lines[0].trimmingCharacters(in: .whitespaces)) else { return nil }
        return LockInfo(pid: pid, appName: lines[1], host: lines[2], machineId: lines.count > 3 ? lines[3] : "",
                        bootId: lines.count > 4 ? lines[4] : "")
    }

    static func read(_ path: String) -> LockInfo? {
        guard let data = FileManager.default.contents(atPath: path), let text = String(data: data, encoding: .utf8) else {
            return nil
        }
        return parse(text)
    }

    public static func mine() -> LockInfo {
        let pid = getpid()
        return LockInfo(pid: pid, appName: processName(pid), host: hostName(), machineId: machineUniqueId(),
                        bootId: bootUniqueId())
    }

    /// Still held by a running copy on this computer (Qt isApparentlyStale, the other way round). A lock written on
    /// another computer counts as gone, as in the Python app (the folder was copied with the lock in it).
    public var isLive: Bool {
        if host != LockInfo.hostName() { return false }
        if !bootId.isEmpty && bootId != LockInfo.bootUniqueId() { return false }  // the Mac was restarted since
        if kill(pid, 0) != 0 && errno == ESRCH { return false }
        return appName.isEmpty || LockInfo.processName(pid) == appName
    }

    static func processName(_ pid: Int32) -> String {
        var buffer = [CChar](repeating: 0, count: 1024)
        let n = proc_name(pid, &buffer, UInt32(buffer.count))
        return n > 0 ? String(cString: buffer) : ""
    }

    /// QSysInfo::machineHostName (gethostname)
    static func hostName() -> String {
        var buffer = [CChar](repeating: 0, count: 256)
        return gethostname(&buffer, buffer.count) == 0 ? String(cString: buffer) : ""
    }

    /// QSysInfo::machineUniqueId on macOS: IOPlatformUUID
    static func machineUniqueId() -> String {
        let service = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("IOPlatformExpertDevice"))
        guard service != 0 else { return "" }
        defer { IOObjectRelease(service) }
        let value = IORegistryEntryCreateCFProperty(service, "IOPlatformUUID" as CFString, kCFAllocatorDefault, 0)
        return (value?.takeRetainedValue() as? String) ?? ""
    }

    /// QSysInfo::bootUniqueId on macOS: kern.bootsessionuuid
    static func bootUniqueId() -> String {
        var size = 0
        guard sysctlbyname("kern.bootsessionuuid", nil, &size, nil, 0) == 0, size > 0 else { return "" }
        var buffer = [CChar](repeating: 0, count: size)
        guard sysctlbyname("kern.bootsessionuuid", &buffer, &size, nil, 0) == 0 else { return "" }
        return String(cString: buffer)
    }
}

/// The shop's work folder named in the Python app's config.json (Documents/DiBeKho by default): the Swift app works
/// on the very same data/kho.sqlite. The cloud is left to the Python app for now: what this app writes is queued by
/// the sync triggers (sync_outbox) and sent the next time the Python app syncs, as any change made offline.
public final class WorkFolder {
    public let root: URL
    public let queue: DatabaseQueue
    private let lock: LockFile

    public var database: URL { root.appendingPathComponent("data/kho.sqlite") }
    public var deliveries: URL { root.appendingPathComponent("phieu-giao-hang", isDirectory: true) }
    public var input: URL { root.appendingPathComponent("input", isDirectory: true) }
    public var output: URL { root.appendingPathComponent("output", isDirectory: true) }
    public var backups: URL { root.appendingPathComponent("sao-luu", isDirectory: true) }

    public enum OpenError: Error, LocalizedError {
        case alreadyOpen
        case missing(String)

        public var errorDescription: String? {
            switch self {
            case .alreadyOpen: return L10n.t("app.already_running")
            case let .missing(path): return L10n.t("app.workspace_missing", ["path": path])
            }
        }
    }

    /// Opens the folder: the shared lock first, then the database (brought to the current schema, with the sync
    /// triggers), then the day's backup in sao-luu/ as the Python app takes it.
    public init(root: URL) throws {
        self.root = root
        let db = root.appendingPathComponent("data/kho.sqlite")
        guard FileManager.default.fileExists(atPath: db.path) else { throw OpenError.missing(root.path) }
        guard let lock = LockFile.acquire(root.appendingPathComponent("data/dibekho.lock")) else {
            throw OpenError.alreadyOpen
        }
        self.lock = lock
        do {
            queue = try DatabaseQueue(path: db.path, configuration: Store.configuration())
            try queue.read { try Store.check($0) }
            try Schema.migrate(queue)
            try queue.write { try Sync.ensureTriggers($0) }
        } catch {
            lock.release()
            throw error
        }
        ActivityLog.setup(root.appendingPathComponent("data/app.log"))
        _ = try? Backups.daily(queue, folder: backups)
    }

    /// The folder of the Python app's config.json, when it has data.
    public static var configured: URL? {
        Workspace.liveDatabase()?.deletingLastPathComponent().deletingLastPathComponent()
    }

    public func close() {
        try? queue.close()
        lock.release()
    }
}

/// Python core/backup: one copy a day in sao-luu/ (DiBeKho_<date>.sqlite), the newest 10 kept in all, nothing older
/// than 30 days except the newest 3; a named copy before a big change.
public enum Backups {
    static let keep = 10, maxAgeDays = 30.0, keepFloor = 3

    static func snapshot(_ queue: DatabaseQueue, to dest: URL) throws {
        try FileManager.default.createDirectory(at: dest.deletingLastPathComponent(), withIntermediateDirectories: true)
        let tmp = dest.deletingPathExtension().appendingPathExtension("tmp")
        try? FileManager.default.removeItem(at: tmp)
        let target = try DatabaseQueue(path: tmp.path)
        try queue.backup(to: target)
        try target.close()
        _ = try? FileManager.default.removeItem(at: dest)
        try FileManager.default.moveItem(at: tmp, to: dest)
    }

    @discardableResult
    public static func daily(_ queue: DatabaseQueue, folder: URL, today: String = Dates.today) throws -> URL? {
        let dest = folder.appendingPathComponent("DiBeKho_\(today).sqlite")
        if FileManager.default.fileExists(atPath: dest.path) { return nil }
        try snapshot(queue, to: dest)
        prune(folder)
        return dest
    }

    @discardableResult
    public static func named(_ queue: DatabaseQueue, folder: URL, label: String) throws -> URL {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd_HHmmss"
        let dest = folder.appendingPathComponent("\(label)_\(f.string(from: Date())).sqlite")
        try snapshot(queue, to: dest)
        return dest
    }

    static func prune(_ folder: URL) {
        let fm = FileManager.default
        let files = ((try? fm.contentsOfDirectory(at: folder, includingPropertiesForKeys: [.contentModificationDateKey])) ?? [])
            .filter { $0.pathExtension == "sqlite" }
            .map { ($0, (try? $0.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast) }
            .sorted { $0.1 > $1.1 }
        let cutoff = Date().addingTimeInterval(-maxAgeDays * 86400)
        for (i, (url, modified)) in files.enumerated() where i >= keepFloor && (i >= keep || modified < cutoff) {
            try? fm.removeItem(at: url)
        }
    }
}
