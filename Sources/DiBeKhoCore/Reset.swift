import Foundation
import GRDB

/// Python core/reset + core/backup.restore: reset the stock, reset everything, restore a backup. A backup is always
/// taken first (sao-luu/), so each can be undone. Files the user put in the work folder are never deleted; notes in
/// phieu-giao-hang/da-xu-ly/ go back into phieu-giao-hang/ so they are read again.
public enum Reset {
    // children first (foreign keys)
    static let stockTables = ["stock_movements", "document_skipped_lines", "document_lines", "scanned_files", "documents", "customers"]

    /// Keeps the catalog (with the learned names); removes every document, movement, customer and read file.
    /// Returns the number of note files moved back out of da-xu-ly.
    @discardableResult
    public static func resetStock(_ queue: DatabaseQueue, _ f: ShopFolders, backups: URL) throws -> Int {
        try Backups.named(queue, folder: backups, label: "truoc-dat-lai-ton")
        try queue.write { db in
            for table in stockTables { try db.execute(sql: "DELETE FROM \(table)") }
            try Meta.touch(db)
            try Meta.log(db, "reset_stock", "")
        }
        return moveAllOut(f)  // data/phieu-goc/ is kept: the notes are read again right away
    }

    /// An empty database as right after installing, and the kept originals go. Returns the notes moved back.
    @discardableResult
    public static func resetAll(_ queue: DatabaseQueue, _ f: ShopFolders, backups: URL) throws -> Int {
        try Backups.named(queue, folder: backups, label: "truoc-xoa-toan-bo")
        let moved = moveAllOut(f)
        let empty = try DatabaseQueue(configuration: Store.configuration())
        try Schema.migrate(empty)
        try empty.backup(to: queue)
        try queue.write { try Sync.ensureTriggers($0) }
        wipeOriginals(f)
        return moved
    }

    /// Replaces the open database by a backup of sao-luu/ (older schemas are brought up to date).
    public static func restore(_ queue: DatabaseQueue, from backup: URL) throws {
        let source = try DatabaseQueue(path: backup.path, configuration: Store.configuration())
        try source.read { try Store.check($0) }
        try source.backup(to: queue)
        try Schema.migrate(queue)
        try queue.write { try Sync.ensureTriggers($0) }
    }

    /// The backups of sao-luu/, newest first.
    public static func backupsList(_ folder: URL) -> [URL] {
        let keys: [URLResourceKey] = [.contentModificationDateKey]
        let files = ((try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: keys)) ?? [])
            .filter { $0.pathExtension == "sqlite" }
        func date(_ u: URL) -> Date { (try? u.resourceValues(forKeys: Set(keys)).contentModificationDate) ?? .distantPast }
        return files.sorted { date($0) > date($1) }
    }

    /// Every file of phieu-giao-hang/da-xu-ly/ back into phieu-giao-hang/ (a file open in Excel stays where it is).
    static func moveAllOut(_ f: ShopFolders) -> Int {
        let fm = FileManager.default
        guard fm.fileExists(atPath: f.deliveriesDone.path),
              let walker = fm.enumerator(at: f.deliveriesDone, includingPropertiesForKeys: [.isRegularFileKey]) else { return 0 }
        let base = f.deliveriesDone.standardizedFileURL.path
        let files = (walker.allObjects as? [URL] ?? []).filter { (try? $0.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true }
            .sorted { $0.path < $1.path }
        var moved = 0
        for url in files {
            let rel = String(url.standardizedFileURL.path.dropFirst(base.count + 1))
            let target = Deliveries.freeName(f.deliveries.appendingPathComponent(rel))
            try? fm.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
            do { try fm.moveItem(at: url, to: target) } catch { continue }
            moved += 1
        }
        let folders = ((fm.enumerator(at: f.deliveriesDone, includingPropertiesForKeys: [.isDirectoryKey])?.allObjects as? [URL]) ?? [])
            .filter { (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true }
            .sorted { $0.path > $1.path }
        for folder in folders where ((try? fm.contentsOfDirectory(atPath: folder.path)) ?? ["x"]).isEmpty { try? fm.removeItem(at: folder) }  // like rmdir: a folder with a left-behind file stays
        return moved
    }

    static func wipeOriginals(_ f: ShopFolders) {
        try? FileManager.default.removeItem(at: f.originals)
        try? FileManager.default.createDirectory(at: f.originals, withIntermediateDirectories: true)
    }
}
