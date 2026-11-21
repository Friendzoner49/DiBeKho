import CryptoKit
import Foundation
import GRDB

/// The folders of a shop's work folder (Python core/workspace.Workspace).
public struct ShopFolders {
    public let root: URL
    public init(root: URL) { self.root = root }
    public var deliveries: URL { root.appendingPathComponent("phieu-giao-hang", isDirectory: true) }
    public var deliveriesDone: URL { deliveries.appendingPathComponent(Deliveries.processed, isDirectory: true) }
    public var input: URL { root.appendingPathComponent("input", isDirectory: true) }
    public var output: URL { root.appendingPathComponent("output", isDirectory: true) }
    public var originals: URL { root.appendingPathComponent("data/phieu-goc", isDirectory: true) }
}

public struct ScanResult: Equatable {
    public var imported: [String] = []
    public var pending = 0
    /// files with the same content as another one: counted once
    public var copies: [String] = []
}

/// A line of a waiting note the app does not know yet (Python deliveries.UnknownLine).
public struct UnknownLine: Equatable {
    public let key: String
    public let nameVi: String
    public let nameZh: String
    public let spec: String
    public var files: [String]
    public let suggestion: Int64?
    public let rawName: String
    /// "76 · Khách A · SL 2" for each note containing the line
    public var orders: [String]
    /// looks like 'Phí vận chuyển' -> the screen pre-selects "not goods"
    public let isFee: Bool
    /// earliest delivery date among the notes containing the line
    public var firstDate: String?

    public var label: String { Deliveries.lineLabel(name: nameVi, raw: rawName, spec: spec) }
}

public struct NoteLineInfo: Equatable {
    public let row: Int
    public let rawName: String
    public let nameVi: String
    public let nameZh: String
    public let spec: String
    public let qty: Double
    public let key: String
    /// known (learned) product; nil = waiting for a decision, or 'not goods'
    public let productId: Int64?
    public let ignored: Bool
}

/// A delivery note in "Cần xử lý" with all its lines, so the user checks a whole order at once.
public struct WaitingNote: Equatable {
    public let relPath: String
    public let code: String
    public let docDate: String?
    public let customer: String
    public let lines: [NoteLineInfo]
    public var unknown: [NoteLineInfo] { lines.filter { $0.productId == nil && !$0.ignored } }
}

public struct PendingFile {
    public let hash: String
    public let relPath: String
    public let status: String
    public let message: String
    public let documentId: Int64?
    public let docCode: String?
}

public struct UnplacedOrder {
    public let id: Int64
    public let code: String
    public let docDate: String
    public let customer: String
    public let lineCount: Int
    public let totalQty: Double
}

/// An order dated before a stock count but read into the app after it (Python count_conflicts rows).
public struct CountConflict {
    public let id: Int64
    public let code: String
    public let docDate: String
    public let customer: String
    public let countDate: String
}

/// The rate of the last yuan conversion the Python app kept on this computer (config folder, fx.json), for a note
/// in yuan read while no rate is known. Never the network.
public enum FXCache {
    public static func rate() -> Double? {
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/DiBeKho/fx.json")
        guard let data = try? Data(contentsOf: url),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let rate = (json["vnd_per_cny"] as? NSNumber)?.doubleValue, rate > 0 else { return nil }
        return rate
    }
}

/// Python core/deliveries: the delivery notes folder -> documents. The database is the source of truth, files are
/// only input: a file is its SHA-256, so renaming or moving it changes nothing; the same content is never imported
/// twice; deleting a file never changes stock (the user is asked what to do); every imported file is copied to
/// data/phieu-goc/<hash>.xlsx; a note fully recorded goes to phieu-giao-hang/da-xu-ly/ and back out when it needs a
/// decision again.
///
/// Every path comes from a name in the database or the folder, so each is checked to lie inside the work folder
/// (no "..", no link leading out of it) before it is read, copied or moved.
public enum Deliveries {
    public static let processed = "da-xu-ly"
    public static let pendingStatuses = ["error", "needs_mapping", "changed", "missing"]
    static let otherOrderDays = 31
    public static let letterheadKey = "note_letterhead"
    static let letterheadTriedKey = "letterhead_backfilled"
    static let countCheckedKey = "count_checked"
    public static let oldExcelMessage = "File Excel đời cũ (.xls), app chỉ đọc được .xlsx. Hãy mở file bằng Excel, chọn Lưu thành "
        + "(Save As) kiểu 'Excel Workbook (.xlsx)', rồi bấm Quét lại."
    /// the rate kept with a note in yuan (tests replace it)
    public static var knownRate: () -> Double? = { FXCache.rate() }

    // MARK: files

    public static func fileHash(_ url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        while let chunk = try handle.read(upToCount: 1 << 16), !chunk.isEmpty { hasher.update(data: chunk) }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    static func nfc(_ text: String) -> String { text.precomposedStringWithCanonicalMapping }

    static func scalarsLess(_ a: String, _ b: String) -> Bool {
        a.unicodeScalars.lexicographicallyPrecedes(b.unicodeScalars) { $0.value < $1.value }
    }

    /// A relative name from the database that stays inside the folder it is joined to.
    static func validRel(_ rel: String) -> Bool {
        if rel.isEmpty || rel.hasPrefix("/") || rel.contains("\\") || rel.contains("\0") { return false }
        return !rel.split(separator: "/", omittingEmptySubsequences: false).contains { $0 == ".." || $0.isEmpty }
    }

    /// True when the file (links followed) lies inside the folder.
    static func inside(_ url: URL, _ folder: URL) -> Bool {
        let base = folder.resolvingSymlinksInPath().standardizedFileURL.path
        let path = url.resolvingSymlinksInPath().standardizedFileURL.path
        return path == base || path.hasPrefix(base.hasSuffix("/") ? base : base + "/")
    }

    static func isFile(_ url: URL) -> Bool {
        var dir: ObjCBool = false
        return FileManager.default.fileExists(atPath: url.path, isDirectory: &dir) && !dir.boolValue
    }

    /// Every .xlsx note of the folder and its sub-folders (da-xu-ly included), not Excel's lock files ("~$") nor
    /// macOS metadata (".x"), in the order Python sorts them: name by name.
    public static func deliveryFiles(_ f: ShopFolders) -> [(url: URL, rel: String)] {
        notes(f, ext: "xlsx")
    }

    static func notes(_ f: ShopFolders, ext: String) -> [(url: URL, rel: String)] {
        guard let names = FileManager.default.enumerator(atPath: f.deliveries.path) else { return [] }
        var found: [(URL, String, [String])] = []
        for case let name as String in names {
            let url = f.deliveries.appendingPathComponent(name)
            let last = url.lastPathComponent
            guard url.pathExtension.lowercased() == ext, !last.hasPrefix("~$"), !last.hasPrefix("."),
                  isFile(url), inside(url, f.deliveries) else { continue }
            found.append((url, nfc(name), name.split(separator: "/").map(String.init)))
        }
        found.sort { l, r in
            for (a, b) in zip(l.2, r.2) where a != b { return scalarsLess(a, b) }
            return l.2.count < r.2.count
        }
        return found.map { ($0.0, $0.1) }
    }

    /// The file of a stored name. The name is kept in NFC but a file that went through a Mac or a chat app may carry
    /// it in NFD, which Windows treats as another name: then it is looked up among the notes. nil when the name is
    /// not a plain name inside the folder.
    public static func notePath(_ f: ShopFolders, _ rel: String) -> URL? {
        guard validRel(rel) else { return nil }
        let path = f.deliveries.appendingPathComponent(rel)
        if isFile(path) { return inside(path, f.deliveries) ? path : nil }
        for candidate in deliveryFiles(f) where candidate.rel == rel { return candidate.url }
        return path
    }

    public static func originalCopy(_ f: ShopFolders, _ hash: String) -> URL? {
        guard hash.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil else { return nil }
        let url = f.originals.appendingPathComponent("\(hash).xlsx")
        return isFile(url) ? url : nil
    }

    /// A read-only copy of the stored original in the system's temp folder, to open in Excel: the stored copy is
    /// never opened itself, so Excel leaves no lock file in data/phieu-goc and cannot save over it.
    public static func viewingCopy(_ f: ShopFolders, hash: String, name: String = "") -> URL? {
        guard let source = originalCopy(f, hash) else { return nil }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("DiBeKho/\(hash.prefix(12))", isDirectory: true)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let last = URL(fileURLWithPath: name).lastPathComponent
        let target = folder.appendingPathComponent(last.lowercased().hasSuffix(".xlsx") ? last : "\(hash.prefix(12)).xlsx")
        do {
            if FileManager.default.fileExists(atPath: target.path) {
                try? FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: target.path)
                try FileManager.default.removeItem(at: target)
            }
            try FileManager.default.copyItem(at: source, to: target)
            try FileManager.default.setAttributes([.posixPermissions: 0o444], ofItemAtPath: target.path)
        } catch {
            return FileManager.default.fileExists(atPath: target.path) ? target : source
        }
        return target
    }

    static func readNote(_ url: URL?) -> DeliveryNote? {
        guard let url else { return nil }
        return try? DeliveryNoteReader.read(url)
    }

    // MARK: scan

    /// allowPartial only right after the user pressed "Áp dụng": waiting notes are then imported with the lines that
    /// are known; the rest is added to the same document once decided. Each file is one transaction.
    public static func scan(_ queue: DatabaseQueue, _ f: ShopFolders, allowPartial: Bool = false) throws -> ScanResult {
        var result = ScanResult()
        var seen = Set<String>()
        var found: [(URL, String, String)] = []
        var unreadable = false
        for old in notes(f, ext: "xls") {
            guard let h = try? fileHash(old.url) else {
                unreadable = true
                continue
            }
            seen.insert(h)
            try queue.write { db in
                let status = try String.fetchOne(db, sql: "SELECT status FROM scanned_files WHERE hash = ?", arguments: [h])
                if status == nil || status == "error" { try record(db, h, old.rel, "error", oldExcelMessage) }
            }
        }
        for file in deliveryFiles(f) {
            guard let h = try? fileHash(file.url) else {
                unreadable = true  // being written / locked / not downloaded yet; the next scan will get it
                continue
            }
            if seen.contains(h) {  // a copy of a file met in this scan: the same note, once
                result.copies.append(file.rel)
                found.append((file.url, file.rel, h))  // still sorted into da-xu-ly/ like the note it copies
                continue
            }
            seen.insert(h)
            found.append((file.url, file.rel, h))
            try queue.write { db in
                if let row = try Row.fetchOne(db, sql: "SELECT * FROM scanned_files WHERE hash = ?", arguments: [h]),
                   ["imported", "missing", "missing_ignored", "ignored"].contains(row["status"] as String) {
                    var status: String = row["status"]
                    if status == "missing" || status == "missing_ignored" {  // the file is back: resume where it was
                        status = (row["message"] as String) == "needs_mapping" ? "needs_mapping" : "imported"
                    }
                    try db.execute(sql: """
                        UPDATE scanned_files SET rel_path = ?, status = ?, last_seen = datetime('now','localtime') WHERE hash = ?
                        """, arguments: [file.rel, status, h])
                    if status != "needs_mapping" { return }  // done, or hidden by the user
                }
                if try processFile(db, f, file.url, file.rel, h, allowPartial) { result.imported.append(file.rel) }
            }
        }
        try queue.write { db in
            // Imported (or partly imported) files that disappeared; their document is still active. message keeps
            // the previous status so a restored partial note asks for its remaining lines again. A file that could
            // not be read this time may be one of them: wait for a scan that sees every file.
            for hash in try String.fetchAll(db, sql: """
                SELECT s.hash FROM scanned_files s JOIN documents d ON d.id = s.document_id
                WHERE s.status IN ('imported', 'needs_mapping') AND d.status = 'active'
                """) where !seen.contains(hash) && !unreadable {
                try db.execute(sql: "UPDATE scanned_files SET message = status, status = 'missing' WHERE hash = ?", arguments: [hash])
            }
            // The old version of a note edited in Excel (its document replaced), or of a cancelled order: nothing is
            // left to decide about it. If it comes back it counts as done.
            for hash in try String.fetchAll(db, sql: """
                SELECT s.hash FROM scanned_files s JOIN documents d ON d.id = s.document_id
                WHERE s.status IN ('missing', 'needs_mapping') AND d.status <> 'active'
                """) where !seen.contains(hash) {
                try db.execute(sql: "UPDATE scanned_files SET message = '', status = 'missing_ignored' WHERE hash = ?", arguments: [hash])
            }
            // Waiting files that are not in the folder any more (rows that came with a data package from another
            // computer): nothing was imported from them, so forget them. If the file is put back, the next scan asks.
            for hash in try String.fetchAll(db, sql: """
                SELECT hash FROM scanned_files WHERE status IN ('error', 'needs_mapping', 'changed') AND document_id IS NULL
                """) where !seen.contains(hash) {
                try db.execute(sql: "DELETE FROM scanned_files WHERE hash = ?", arguments: [hash])
            }
        }
        try sortFiles(queue, f, found)
        try queue.write { db in
            try backfillCustomers(db, f)
            try backfillPrices(db, f)
            try backfillLetterhead(db, f)
            try backfillReturnPrices(db)  // after the notes have their prices: a return takes its price from them
            result.pending = try pendingCount(db)
        }
        return result
    }

    static func inDone(_ rel: String) -> Bool {
        (rel.split(separator: "/", maxSplits: 1).first.map(String.init) ?? "").lowercased() == processed
    }

    static func isDone(status: String?, documentId: Int64?) -> Bool {
        status == "imported" || (status == "ignored" && documentId != nil)
    }

    /// Finished notes go into da-xu-ly/ and notes that wait for a decision come back out; sub-folders are kept.
    /// A file that cannot be moved now (open in Excel on Windows) is moved on a later scan.
    static func sortFiles(_ queue: DatabaseQueue, _ f: ShopFolders, _ found: [(URL, String, String)]) throws {
        let fm = FileManager.default
        for (url, rel, h) in found {
            let row = try queue.read { try Row.fetchOne($0, sql: "SELECT status, document_id FROM scanned_files WHERE hash = ?", arguments: [h]) }
            let inside = inDone(rel)
            if isDone(status: row?["status"], documentId: row?["document_id"]) == inside { continue }
            guard validRel(rel) else { continue }
            let target0 = inside
                ? f.deliveries.appendingPathComponent(String(rel.split(separator: "/", maxSplits: 1)[1]))
                : f.deliveriesDone.appendingPathComponent(rel)
            let target = freeName(target0)
            do {
                try fm.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
                // a sub-folder that is a link leading out of the work folder is no place to move a note to
                guard Deliveries.inside(target.deletingLastPathComponent(), f.deliveries) else { continue }
                try fm.moveItem(at: url, to: target)
            } catch {
                continue
            }
            let moved = nfc(String(target.path.dropFirst(f.deliveries.path.count + 1)))
            try queue.write { db in
                try db.execute(sql: "UPDATE scanned_files SET rel_path = ? WHERE hash = ? AND rel_path = ?", arguments: [moved, h, rel])
            }
            removeEmptyFolders(url.deletingLastPathComponent(), f)
        }
    }

    static func freeName(_ target: URL) -> URL {
        var n = 2
        var candidate = target
        let stem = target.deletingPathExtension().lastPathComponent
        let ext = target.pathExtension
        while FileManager.default.fileExists(atPath: candidate.path) {
            candidate = target.deletingLastPathComponent().appendingPathComponent("\(stem) (\(n))" + (ext.isEmpty ? "" : ".\(ext)"))
            n += 1
        }
        return candidate
    }

    /// Sub-folders emptied by a move (never phieu-giao-hang/ or da-xu-ly/ themselves).
    static func removeEmptyFolders(_ start: URL, _ f: ShopFolders) {
        var folder = start.standardizedFileURL
        let top = f.deliveries.standardizedFileURL.path, done = f.deliveriesDone.standardizedFileURL.path
        while folder.path != top && folder.path != done && folder.path.hasPrefix(top + "/") {
            guard (try? FileManager.default.contentsOfDirectory(atPath: folder.path))?.isEmpty == true,
                  (try? FileManager.default.removeItem(at: folder)) != nil else { return }  // only succeeds when empty
            folder = folder.deletingLastPathComponent()
        }
    }

    // MARK: one file

    /// Try to import one file. True when a document was created.
    /// deliveries.DRAFT_REFUSED
    static let draftRefused = "Đây là đơn nháp (NHÁP): không tính vào tồn kho và doanh thu. Muốn thành phiếu thật: Phiếu xuất kho… → Xuất từ phiếu nháp…"

    static func processFile(_ db: Database, _ f: ShopFolders, _ url: URL, _ rel: String, _ h: String,
                            _ allowPartial: Bool) throws -> Bool {
        let note: DeliveryNote
        do {
            note = try DeliveryNoteReader.read(url)
        } catch {
            try record(db, h, rel, "error", error.localizedDescription)
            return false
        }
        if IssueNote.isDraftTitle(note.title) {  // a draft order counts in neither stock nor revenue (21/11/2026)
            try record(db, h, rel, "error", draftRefused)
            return false
        }
        let goods = try goodsLines(db, note)
        let unknown = try goods.filter { try lineProduct(db, $0) == nil }
        let waiting = "\(unknown.count) dòng hàng chưa nhận ra"

        var existing = try activeDelivery(db, codeNorm: note.codeNorm, hash: h, note: note)
        if let doc = existing, (doc["source_hash"] as String) != h, try !separateCode(db, h).isEmpty {
            existing = nil  // recorded before as another order with this code, now read again: it stays apart
            _ = doc
        }
        if let doc = existing, (doc["source_hash"] as String).isEmpty, isIssueCode(note.code) {
            // a stock issue note the owner saved on the web: already recorded, stock already taken; its file dropped
            // here only links to it
            try record(db, h, rel, "imported", "", doc["id"])
            return false
        }
        if let doc = existing, (doc["source_hash"] as String) != h {
            var message = "Mã đơn \(note.code) đã có từ file '\(doc["source_file"] as String)'"
            let reason = otherOrderReason(doc, note)
            if !reason.isEmpty { message += " — nhưng \(reason): có thể là ĐƠN KHÁC trùng mã" }
            try record(db, h, rel, "changed", message, doc["id"])
            return false
        }
        if let doc = existing {  // this very file was imported before, maybe only partly: add what is known now
            try addKnownLines(db, doc["id"], note)
            try setMoney(db, doc["id"], note)
            try record(db, h, rel, unknown.isEmpty ? "imported" : "needs_mapping", unknown.isEmpty ? "" : waiting, doc["id"])
            return false
        }
        if !unknown.isEmpty && !(allowPartial && unknown.count < goods.count) {
            try record(db, h, rel, "needs_mapping", waiting)
            return false
        }
        let docId = try importNote(db, f, url, rel, h, note)
        if !unknown.isEmpty { try record(db, h, rel, "needs_mapping", waiting, docId) }
        return true
    }

    static func isIssueCode(_ code: String) -> Bool {
        code.range(of: #"^\s*[AaWw]\d+\s*$"#, options: .regularExpression) != nil
    }

    static func noteLines(_ db: Database, _ note: DeliveryNote, skipRows: Set<Int> = []) throws -> [LedgerLine] {
        var lines: [LedgerLine] = []
        for ln in try goodsLines(db, note) {
            guard let pid = try lineProduct(db, ln), !skipRows.contains(ln.row) else { continue }
            var line = LedgerLine(pid, ln.qty, note: ln.note, unitPrice: ln.unitPrice, amount: ln.amount)
            line.rawName = ln.rawName
            line.rawSpec = ln.spec
            line.lineNo = ln.row
            line.locationId = ln.places.count == 1 ? Int64(ln.places[0].0) : nil
            line.places = ln.places.map { (Int64($0.0), $0.1) }
            lines.append(line)
        }
        return lines
    }

    static func withoutPlaces(_ lines: [LedgerLine]) -> [LedgerLine] {
        lines.map { var l = $0; l.locationId = nil; l.places = []; return l }
    }

    static func notePlaces(_ note: DeliveryNote) -> Bool {
        !note.lines.isEmpty && note.lines.allSatisfy { !$0.places.isEmpty }
    }

    static func addKnownLines(_ db: Database, _ docId: Int64, _ note: DeliveryNote) throws {
        let rows = Set(try Int.fetchAll(db, sql: "SELECT line_no FROM document_lines WHERE document_id = ?", arguments: [docId]))
        var new = try noteLines(db, note, skipRows: rows)
        if !notePlaces(note) { new = withoutPlaces(new) }
        if !new.isEmpty {
            try Ledger.addLines(db, docId: docId, lines: new)
            try Meta.log(db, "delivery_lines_added", "\(note.code): \(new.count)")
        }
    }

    /// The matching key of a note recorded earlier as another order with a reused code ("76#2"), if that order was
    /// read again (replaced) and the key is free; "" otherwise.
    static func separateCode(_ db: Database, _ h: String) throws -> String {
        guard let code = try String.fetchOne(db, sql: """
            SELECT code_norm FROM documents WHERE kind = 'delivery' AND source_hash = ? AND status = 'replaced'
            ORDER BY id DESC LIMIT 1
            """, arguments: [h]), code.contains("#") else { return "" }
        let taken = try Row.fetchOne(db, sql: "SELECT 1 FROM documents WHERE kind = 'delivery' AND status = 'active' AND code_norm = ?",
                                     arguments: [code])
        return taken != nil ? "" : code
    }

    static func freeSeparateCode(_ db: Database, _ codeNorm: String) throws -> String {
        var n = 2
        while try Row.fetchOne(db, sql: "SELECT 1 FROM documents WHERE kind = 'delivery' AND code_norm = ?",
                               arguments: ["\(codeNorm)#\(n)"]) != nil { n += 1 }
        return "\(codeNorm)#\(n)"
    }

    static func importNote(_ db: Database, _ f: ShopFolders, _ url: URL, _ rel: String, _ h: String, _ note: DeliveryNote,
                           replaces: Int64? = nil, separate: String = "") throws -> Int64 {
        let fm = FileManager.default
        try fm.createDirectory(at: f.originals, withIntermediateDirectories: true)
        let copy = f.originals.appendingPathComponent("\(h).xlsx")
        if !fm.fileExists(atPath: copy.path) { try fm.copyItem(at: url, to: copy) }
        // the same file read again keeps its customer (the user may have renamed them since: no twin under the old name)
        let known = try Int64.fetchOne(db, sql: """
            SELECT customer_id FROM documents WHERE kind = 'delivery' AND source_hash = ? AND customer_id IS NOT NULL
            ORDER BY id DESC LIMIT 1
            """, arguments: [h])
        let customerId = try Catalog.upsertCustomer(db, name: note.customerName, phone: note.phone, contact: note.contact,
                                                    address: note.address, taxCode: note.taxCode, email: note.email,
                                                    known: known)
        var lines = try noteLines(db, note)
        // a note read again (same file) or its edited version keeps the place chosen for it; a new one waits for the
        // user in Cần xử lý, its goods taken from Kho tổng meanwhile, so the total is right at once. Not by order code
        // alone: a code may come back years later on another order.
        let prev: Row?
        if let replaces {
            prev = try Row.fetchOne(db, sql: "SELECT location_id, location_set, code_norm FROM documents WHERE id = ?", arguments: [replaces])
        } else {
            prev = try Row.fetchOne(db, sql: """
                SELECT location_id, location_set FROM documents WHERE kind = 'delivery' AND source_hash = ?
                AND status = 'replaced' ORDER BY id DESC LIMIT 1
                """, arguments: [h])
        }
        // another order that reused a code keeps its own matching key ("76#2"); the code shown stays "76"
        var codeNorm = separate
        if codeNorm.isEmpty {
            codeNorm = replaces != nil ? (prev.flatMap { $0["code_norm"] as String? } ?? "") : try separateCode(db, h)
        }
        if codeNorm.isEmpty { codeNorm = note.codeNorm }
        var locationId: Int64 = prev.flatMap { $0["location_id"] as Int64? } ?? Ledger.main
        var locationSet = prev.map { (($0["location_set"] as Int?) ?? 0) != 0 } ?? false
        if notePlaces(note) {  // a stock issue note says the place of each line itself: nothing to choose
            let places = Set(note.lines.flatMap { $0.places.map { Int64($0.0) } })
            locationId = places.count == 1 ? places.first! : Ledger.main
            locationSet = true
        } else {
            lines = withoutPlaces(lines)  // some lines only: the note's place
            if let replaces, try Ledger.isMixed(db, replaces) { locationSet = false }  // took from both places, split lost: ask again
        }
        let docId = try Ledger.insertDocument(db, kind: "delivery", date: note.docDate, lines: lines, code: note.code,
                                              codeNorm: codeNorm, customerId: customerId, sourceFile: rel, sourceHash: h,
                                              locationId: locationId, locationSet: locationSet)
        for ln in note.lines where try Catalog.isIgnored(db, key: ln.key) {
            try db.execute(sql: "INSERT INTO document_skipped_lines(document_id, key, raw_name) VALUES(?,?,?)",
                           arguments: [docId, ln.key, ln.rawName])
        }
        try setMoney(db, docId, note)
        try keepLetterhead(db, note)
        try record(db, h, rel, "imported", "", docId)
        try Meta.log(db, "delivery_imported", "\(note.code) (\(rel))")
        return docId
    }

    /// Prices of a recorded delivery note, from the note itself: each document line gets the unit price and amount
    /// of its line on the note, the document its fees (rows that are not goods) and the printed total. A line is
    /// matched by name + packing + quantity (the Excel row only breaks ties); one that matches nothing keeps NULL.
    static func setMoney(_ db: Database, _ docId: Int64, _ note: DeliveryNote) throws {
        let priced = !note.fees.isEmpty || note.lines.contains { $0.amount != nil }  // a printed 0 over empty cells is no price
        var fees = note.fees.reduce(0.0) { $0 + $1.1 }
        for ln in note.lines where try Catalog.isIgnored(db, key: ln.key) { fees += ln.amount ?? 0 }
        try db.execute(sql: "UPDATE documents SET fee_amount = ?, note_total = ?, prices_read = 1 WHERE id = ?",
                       arguments: [priced ? fees : nil, note.total, docId])
        try setCurrency(db, docId, priced ? note.currency : "VND")
        var free = note.lines
        for row in try Row.fetchAll(db, sql: """
            SELECT id, line_no, qty, raw_name, raw_spec FROM document_lines WHERE document_id = ? ORDER BY line_no
            """, arguments: [docId]) {
            let key = TextRules.matchKey(row["raw_name"] ?? "", row["raw_spec"] ?? "")
            let qty: Double = row["qty"]
            let same = free.filter { $0.key == key && abs($0.qty - qty) < 1e-9 }
            if same.isEmpty { continue }
            let lineNo: Int = row["line_no"] ?? 0
            let ln = same.first { $0.row == lineNo } ?? same[0]
            if let i = free.firstIndex(of: ln) { free.remove(at: i) }
            try db.execute(sql: "UPDATE document_lines SET unit_price = ?, amount = ? WHERE id = ?",
                           arguments: [ln.unitPrice, ln.amount, row["id"] as Int64])
        }
    }

    /// The currency the note is priced in; a note in yuan keeps the rate of the moment it is read (only to show
    /// "about … dong" next to its amounts), once.
    static func setCurrency(_ db: Database, _ docId: Int64, _ currency: String) throws {
        try db.execute(sql: "UPDATE documents SET currency = ? WHERE id = ? AND currency <> ?", arguments: [currency, docId, currency])
        if currency == "CNY",
           try Double.fetchOne(db, sql: "SELECT fx_rate FROM documents WHERE id = ?", arguments: [docId]) == nil,
           let rate = knownRate() {
            try db.execute(sql: "UPDATE documents SET fx_rate = ? WHERE id = ?", arguments: [rate, docId])
        }
    }

    // MARK: backfills (notes recorded by older versions)

    /// Notes recorded before prices were read: read their stored copies once. One without a copy is marked so it is
    /// not tried again.
    @discardableResult
    static func backfillPrices(_ db: Database, _ f: ShopFolders) throws -> Int {
        var done = 0
        for d in try Row.fetchAll(db, sql: "SELECT id, source_hash FROM documents WHERE kind = 'delivery' AND prices_read = 0") {
            let hash: String = d["source_hash"] ?? ""
            let note = hash.isEmpty ? nil : readNote(originalCopy(f, hash))
            if let note {
                try setMoney(db, d["id"], note)
                done += 1
            } else {
                try db.execute(sql: "UPDATE documents SET prices_read = -1 WHERE id = ?", arguments: [d["id"] as Int64])
            }
        }
        return done
    }

    /// Notes recorded without a customer name (or named by the phone number): read their stored copies again.
    @discardableResult
    static func backfillCustomers(_ db: Database, _ f: ShopFolders) throws -> Int {
        var fixed = 0
        for d in try Row.fetchAll(db, sql: """
            SELECT d.id, d.source_hash, c.name, c.phone_norm FROM documents d LEFT JOIN customers c ON c.id = d.customer_id
            WHERE d.kind = 'delivery' AND d.source_hash <> ''
            """) {
            let name: String? = d["name"]
            let phoneNorm: String = d["phone_norm"] ?? ""
            if let name, !(!phoneNorm.isEmpty && Catalog.normalizePhone(name) == phoneNorm) { continue }  // has a real name
            guard let note = readNote(originalCopy(f, d["source_hash"])), !note.customerName.isEmpty else { continue }
            let id = try Catalog.upsertCustomer(db, name: note.customerName, phone: note.phone, contact: note.contact, address: note.address,
                                                  taxCode: note.taxCode, email: note.email)
            try db.execute(sql: "UPDATE documents SET customer_id = ? WHERE id = ?", arguments: [id, d["id"] as Int64])
            fixed += 1
        }
        return fixed
    }

    static func backfillLetterhead(_ db: Database, _ f: ShopFolders) throws {
        if try !Meta.get(db, letterheadKey).isEmpty || !Meta.get(db, letterheadTriedKey).isEmpty { return }
        try Meta.set(db, letterheadTriedKey, "1")  // once per machine: a scan never re-reads old files for nothing
        for d in try Row.fetchAll(db, sql: """
            SELECT source_hash FROM documents WHERE kind = 'delivery' AND source_hash <> ''
            ORDER BY doc_date DESC, id DESC LIMIT 20
            """) {
            guard let note = readNote(originalCopy(f, d["source_hash"])), !note.letterhead.isEmpty else { continue }
            try keepLetterhead(db, note)
            if try !Meta.get(db, letterheadKey).isEmpty { return }
        }
    }

    /// Returns saved before they carried a price: give each line the price return_price finds, once.
    @discardableResult
    static func backfillReturnPrices(_ db: Database) throws -> Int {
        let docs = try Row.fetchAll(db, sql: """
            SELECT id, customer_id, ref_code, doc_date FROM documents WHERE kind = 'receipt' AND receipt_source = 'return' AND prices_read = 0
            """)
        if docs.isEmpty { return 0 }
        var done = 0
        for d in docs {
            for ln in try Row.fetchAll(db, sql: "SELECT id, product_id, qty FROM document_lines WHERE document_id = ? AND unit_price IS NULL",
                                       arguments: [d["id"] as Int64]) {
                let price = try Receipts.returnPrice(db, customerId: d["customer_id"], productId: ln["product_id"],
                                                     refCode: d["ref_code"] ?? "", on: d["doc_date"])
                if let price {
                    try db.execute(sql: "UPDATE document_lines SET unit_price = ?, amount = ? WHERE id = ?",
                                   arguments: [price, Receipts.lineAmount(ln["qty"], price), ln["id"] as Int64])
                    done += 1
                }
            }
            try db.execute(sql: "UPDATE documents SET prices_read = 1 WHERE id = ?", arguments: [d["id"] as Int64])
        }
        try Meta.touch(db)
        return done
    }

    // MARK: letterhead

    /// The company name and address printed above the title of the shop's own delivery notes, kept for the stock
    /// issue notes to print the same way. Never taken from an issue note.
    static func keepLetterhead(_ db: Database, _ note: DeliveryNote) throws {
        guard !note.letterhead.isEmpty,
              ["phieu giao hang", "销售单"].contains(where: { TextRules.unaccent(note.title).contains($0) || note.title.contains($0) })
        else { return }
        let value = jsonList(Array(note.letterhead.prefix(3)))
        if try Meta.get(db, letterheadKey) != value { try Meta.set(db, letterheadKey, value) }
    }

    /// Python json.dumps(list, ensure_ascii=False)
    static func jsonList(_ items: [String]) -> String {
        func quote(_ s: String) -> String {
            var out = "\""
            for u in s.unicodeScalars {
                switch u {
                case "\"": out += "\\\""
                case "\\": out += "\\\\"
                case "\n": out += "\\n"
                case "\r": out += "\\r"
                case "\t": out += "\\t"
                case "\u{08}": out += "\\b"
                case "\u{0C}": out += "\\f"
                default:
                    if u.value < 0x20 { out += String(format: "\\u%04x", u.value) } else { out.unicodeScalars.append(u) }
                }
            }
            return out + "\""
        }
        return "[" + items.map(quote).joined(separator: ", ") + "]"
    }

    public static func letterhead(_ db: Database) throws -> [String] {
        guard let data = try Meta.get(db, letterheadKey).data(using: .utf8),
              let list = try? JSONSerialization.jsonObject(with: data) as? [Any] else { return [] }
        return Array(list.compactMap { $0 as? String }.prefix(3))
    }

    // MARK: matching a note to what is recorded

    static func goodsLines(_ db: Database, _ note: DeliveryNote) throws -> [DeliveryLine] {
        try note.lines.filter { try !Catalog.isIgnored(db, key: $0.key) }
    }

    /// The product of a note line: by its "Mã hàng" (stock issue notes written by the app), else by the name + spec
    /// learned before. A code that is not in the catalog (merged away) falls back to the name.
    static func lineProduct(_ db: Database, _ ln: DeliveryLine) throws -> Int64? {
        if !ln.productCode.isEmpty,
           let id = try Int64.fetchOne(db, sql: "SELECT id FROM products WHERE code = ?", arguments: [ln.productCode]) { return id }
        return try Catalog.aliasProduct(db, key: ln.key)
    }

    static let orderColumns = """
        SELECT d.*, COALESCE(c.name, '') AS customer_name, COALESCE(c.phone_norm, '') AS customer_phone
        FROM documents d LEFT JOIN customers c ON c.id = d.customer_id
        """

    /// The active order with this code. A code reused by another customer may have been imported as a separate order,
    /// so prefer the one from this very file, then the one of the same customer.
    static func activeDelivery(_ db: Database, codeNorm: String, hash: String = "", note: DeliveryNote? = nil) throws -> Row? {
        let rows = try Row.fetchAll(db, sql: orderColumns + """
             WHERE d.kind = 'delivery' AND d.status = 'active'
            AND (d.code_norm = :code OR substr(d.code_norm, 1, length(:code) + 1) = :code || '#') ORDER BY d.id DESC
            """, arguments: ["code": codeNorm])
        var best: Row?, bestScore = (false, false)
        for r in rows {
            let score = (!hash.isEmpty && (r["source_hash"] as String) == hash, note != nil && !otherCustomer(r, note!))
            if best == nil || (score.0 ? 1 : 0, score.1 ? 1 : 0) > (bestScore.0 ? 1 : 0, bestScore.1 ? 1 : 0) {
                best = r
                bestScore = score
            }
        }
        return best
    }

    static func otherCustomer(_ doc: Row, _ note: DeliveryNote) -> Bool {
        let a = TextRules.unaccent(TextRules.clean(doc["customer_name"])), b = TextRules.unaccent(TextRules.clean(note.customerName))
        let pa: String = doc["customer_phone"] ?? "", pb = Catalog.normalizePhone(note.phone)
        return (!a.isEmpty && !b.isEmpty && a != b) || (!pa.isEmpty && !pb.isEmpty && pa != pb)
    }

    /// Days between two ISO dates, counted on the calendar (not clock hours, so a daylight-saving night changes nothing).
    static func dayDifference(_ a: String, _ b: String) -> Int {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        func number(_ iso: String) -> Int? {
            let p = iso.split(separator: "-").compactMap { Int($0) }
            guard p.count == 3, let date = calendar.date(from: DateComponents(year: p[0], month: p[1], day: p[2])) else { return nil }
            return Int(date.timeIntervalSince1970 / 86400)
        }
        guard let x = number(a), let y = number(b) else { return 0 }
        return y - x
    }

    /// Why an edited-looking note (same order code, other content) may in fact be another order: another customer,
    /// or a date far from the recorded one. "" when it looks like an edit of the same order.
    static func otherOrderReason(_ doc: Row, _ note: DeliveryNote) -> String {
        var reasons: [String] = []
        if otherCustomer(doc, note) {
            reasons.append("khác khách hàng (\(doc["customer_name"] as String) ≠ \(note.customerName.isEmpty ? note.phone : note.customerName))")
        }
        if abs(dayDifference(doc["doc_date"], note.docDate)) > otherOrderDays {
            reasons.append("khác ngày (\(Format.date(doc["doc_date"])) ≠ \(Format.date(note.docDate)))")
        }
        return reasons.joined(separator: ", ")
    }

    /// For Cần xử lý: offer "Nhập thành đơn riêng" on a "changed" note only when it looks like another order.
    public static func looksLikeOtherOrder(_ db: Database, _ f: ShopFolders, hash: String) throws -> Bool {
        guard let row = try Row.fetchOne(db, sql: "SELECT * FROM scanned_files WHERE hash = ?", arguments: [hash]),
              let note = readNote(notePath(f, row["rel_path"])),
              let old = try changedTarget(db, row, note) else { return false }
        return !otherOrderReason(old, note).isEmpty
    }

    /// The recorded order an edited note is compared with: the one found when it was scanned, if still active.
    static func changedTarget(_ db: Database, _ row: Row, _ note: DeliveryNote) throws -> Row? {
        if let id: Int64 = row["document_id"],
           let doc = try Row.fetchOne(db, sql: orderColumns + " WHERE d.id = ? AND d.status = 'active'", arguments: [id]) { return doc }
        return try activeDelivery(db, codeNorm: note.codeNorm, hash: row["hash"], note: note)
    }

    static func record(_ db: Database, _ h: String, _ rel: String, _ status: String, _ message: String,
                       _ documentId: Int64? = nil) throws {
        try db.execute(sql: """
            INSERT INTO scanned_files(hash, rel_path, document_id, status, message) VALUES(?,?,?,?,?)
            ON CONFLICT(hash) DO UPDATE SET
                rel_path = COALESCE(excluded.rel_path, scanned_files.rel_path),
                document_id = COALESCE(excluded.document_id, scanned_files.document_id),
                status = excluded.status, message = excluded.message,
                last_seen = datetime('now','localtime')
            """, arguments: [h, rel, documentId, status, message])
    }

    // MARK: what waits for the user

    public static func pendingCount(_ db: Database) throws -> Int {
        let marks = pendingStatuses.map { _ in "?" }.joined(separator: ",")
        return try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM scanned_files WHERE status IN (\(marks))",
                                arguments: StatementArguments(pendingStatuses)) ?? 0
    }

    /// Recorded delivery notes whose place (Kho tổng / Văn phòng) the user has not chosen yet, oldest first.
    public static func unplaced(_ db: Database) throws -> [UnplacedOrder] {
        try Row.fetchAll(db, sql: """
            SELECT d.id, d.code, d.doc_date, COALESCE(c.name, '') AS customer,
            (SELECT COUNT(*) FROM document_lines x WHERE x.document_id = d.id) AS line_count,
            (SELECT COALESCE(SUM(x.qty), 0) FROM document_lines x WHERE x.document_id = d.id) AS total_qty
            FROM documents d LEFT JOIN customers c ON c.id = d.customer_id
            WHERE d.kind = 'delivery' AND d.status = 'active' AND d.location_set = 0 ORDER BY d.doc_date, d.id
            """).map {
            UnplacedOrder(id: $0["id"], code: $0["code"] ?? "", docDate: $0["doc_date"], customer: $0["customer"],
                          lineCount: $0["line_count"], totalQty: $0["total_qty"])
        }
    }

    public static func pendingFiles(_ db: Database) throws -> [PendingFile] {
        let marks = pendingStatuses.map { _ in "?" }.joined(separator: ",")
        return try Row.fetchAll(db, sql: """
            SELECT s.*, d.code AS doc_code FROM scanned_files s LEFT JOIN documents d ON d.id = s.document_id
            WHERE s.status IN (\(marks)) ORDER BY s.status, s.rel_path
            """, arguments: StatementArguments(pendingStatuses)).map {
            PendingFile(hash: $0["hash"], relPath: $0["rel_path"], status: $0["status"], message: $0["message"] ?? "",
                        documentId: $0["document_id"], docCode: $0["doc_code"])
        }
    }

    /// Files lying in input/ that wait for the user (hàng về kiểu cũ, gói dữ liệu, danh mục…): the Swift app does not
    /// import them yet, it only counts them (Python core/inbox.items: files of the folder itself, not the hidden ones).
    public static func inboxCount(_ db: Database, _ f: ShopFolders) throws -> Int {
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: f.input.path) else { return 0 }
        let hidden = Set(try String.fetchAll(db, sql: "SELECT hash FROM hidden_inputs"))
        var count = 0
        for name in names where !name.hasPrefix("~$") && !name.hasPrefix(".") {
            let url = f.input.appendingPathComponent(name)
            guard isFile(url) else { continue }
            if !hidden.isEmpty {
                guard let hash = try? fileHash(url) else { continue }
                if hidden.contains(hash) { continue }
            }
            count += 1
        }
        return count
    }

    static func waitingRows(_ db: Database) throws -> [Row] {
        try Row.fetchAll(db, sql: "SELECT * FROM scanned_files WHERE status = 'needs_mapping'")
    }

    public static func lineLabel(name: String, raw: String, spec: String) -> String {
        [name.isEmpty ? raw : name, spec].filter { !$0.isEmpty }.joined(separator: " ")
    }

    /// Distinct unrecognised lines across all files waiting for mapping.
    public static func unknownLines(_ db: Database, _ f: ShopFolders) throws -> [UnknownLine] {
        var order: [String] = []
        var found: [String: UnknownLine] = [:]
        for row in try waitingRows(db) {
            guard let note = readNote(notePath(f, row["rel_path"])) else { continue }
            for ln in try goodsLines(db, note) where try lineProduct(db, ln) == nil {
                if found[ln.key] == nil {
                    let fee = Catalog.looksLikeFee(ln.rawName)
                    found[ln.key] = UnknownLine(
                        key: ln.key, nameVi: ln.nameVi, nameZh: ln.nameZh, spec: ln.spec, files: [],
                        suggestion: fee ? nil : try Catalog.suggestProduct(db, name: ln.rawName, spec: ln.spec),
                        rawName: ln.rawName, orders: [], isFee: fee, firstDate: nil)
                    order.append(ln.key)
                }
                let rel: String = row["rel_path"]
                if !found[ln.key]!.files.contains(rel) { found[ln.key]!.files.append(rel) }
                if !note.docDate.isEmpty, found[ln.key]!.firstDate.map({ note.docDate < $0 }) ?? true {
                    found[ln.key]!.firstDate = note.docDate
                }
                found[ln.key]!.orders.append([note.code, note.customerName, "SL \(Format.quantity(ln.qty))"]
                    .filter { !$0.isEmpty }.joined(separator: " · "))
            }
        }
        return order.compactMap { found[$0] }
    }

    /// Notes waiting for a decision, oldest first, each with every line (known ones too, to compare).
    public static func waitingNotes(_ db: Database, _ f: ShopFolders) throws -> [WaitingNote] {
        var result: [WaitingNote] = []
        for row in try waitingRows(db) {
            guard let note = readNote(notePath(f, row["rel_path"])) else { continue }
            let lines = try note.lines.map {
                NoteLineInfo(row: $0.row, rawName: $0.rawName, nameVi: $0.nameVi, nameZh: $0.nameZh, spec: $0.spec, qty: $0.qty,
                             key: $0.key, productId: try lineProduct(db, $0), ignored: try Catalog.isIgnored(db, key: $0.key))
            }
            let waiting = WaitingNote(relPath: row["rel_path"], code: note.code, docDate: note.docDate.isEmpty ? nil : note.docDate,
                                      customer: note.customerName, lines: lines)
            if !waiting.unknown.isEmpty { result.append(waiting) }
        }
        return result.sorted {
            let a = ($0.docDate ?? "9999-99-99", Lookup.normalizeCode($0.code), $0.relPath)
            let b = ($1.docDate ?? "9999-99-99", Lookup.normalizeCode($1.code), $1.relPath)
            return a < b
        }
    }

    // MARK: the user's decisions

    public static func mapLine(_ db: Database, key: String, productId: Int64, label: String = "") throws {
        try Catalog.setAlias(db, key: key, productId: productId, label: label)
    }

    /// "Not goods": drop this line from every note, now and later.
    public static func ignoreUnknown(_ db: Database, _ line: UnknownLine) throws {
        try Catalog.ignoreLine(db, key: line.key, label: line.label)
    }

    /// opening: the stock on hand before the first note containing this line (a new product has no history yet);
    /// recorded as a stock count on the day before that note, so the note is subtracted from it.
    @discardableResult
    public static func createProduct(_ db: Database, for line: UnknownLine, category: String = "", opening: Double? = nil,
                                     note: String = "") throws -> Int64 {
        let id = try Catalog.createProduct(db, nameVi: line.nameVi, nameZh: line.nameZh, spec: line.spec, category: category)
        try Catalog.setAlias(db, key: line.key, productId: id, label: line.label)
        if let opening {
            let first = line.firstDate.flatMap(Dates.parse) ?? Date()
            let day = Calendar(identifier: .gregorian).date(byAdding: .day, value: -1, to: first) ?? first
            try Ledger.stockCount(db, date: Dates.iso(day), counted: [.init(id, nil, opening)], note: note)
        }
        return id
    }

    // MARK: edited, lost and unreadable files

    /// "Use the new version" for an edited delivery note.
    public static func replaceChanged(_ db: Database, _ f: ShopFolders, hash: String) throws {
        guard let row = try Row.fetchOne(db, sql: "SELECT * FROM scanned_files WHERE hash = ?", arguments: [hash]),
              let path = notePath(f, row["rel_path"]), let note = readNote(path) else {
            throw WriteError("Không đọc được file phiếu.")
        }
        let goods = try goodsLines(db, note)
        let unknown = try goods.filter { try lineProduct(db, $0) == nil }
        if !goods.isEmpty && unknown.count == goods.count { throw WriteError("Phiếu mới có dòng hàng chưa nhận ra.") }
        let old = try changedTarget(db, row, note)
        if let old { try Ledger.close(db, docId: old["id"], status: "replaced") }
        let docId = try importNote(db, f, path, row["rel_path"], hash, note, replaces: old?["id"])
        if !unknown.isEmpty { try record(db, hash, row["rel_path"], "needs_mapping", "\(unknown.count) dòng hàng chưa nhận ra", docId) }
    }

    /// "Another order with the same code": record it as a new order next to the old one, which is left as it is.
    public static func importSeparately(_ db: Database, _ f: ShopFolders, hash: String) throws {
        guard let row = try Row.fetchOne(db, sql: "SELECT * FROM scanned_files WHERE hash = ?", arguments: [hash]),
              let path = notePath(f, row["rel_path"]), let note = readNote(path) else {
            throw WriteError("Không đọc được file phiếu.")
        }
        // unknown lines wait in Cần xử lý and are added to this order once decided (it is found by its file then)
        let unknown = try goodsLines(db, note).filter { try lineProduct(db, $0) == nil }
        let docId = try importNote(db, f, path, row["rel_path"], hash, note, separate: try freeSeparateCode(db, note.codeNorm))
        if !unknown.isEmpty { try record(db, hash, row["rel_path"], "needs_mapping", "\(unknown.count) dòng hàng chưa nhận ra", docId) }
        try Meta.log(db, "delivery_separate", "\(note.code) (\(row["rel_path"] as String))")
    }

    public static func keepOld(_ db: Database, hash: String) throws {
        try db.execute(sql: "UPDATE scanned_files SET status = 'ignored', message = '' WHERE hash = ?", arguments: [hash])
    }

    /// Put the stored copy back where the file was.
    @discardableResult
    public static func restoreMissing(_ db: Database, _ f: ShopFolders, hash: String) throws -> URL {
        guard let row = try Row.fetchOne(db, sql: "SELECT * FROM scanned_files WHERE hash = ?", arguments: [hash]) else {
            throw WriteError("Không thấy phiếu này.")
        }
        guard let original = originalCopy(f, hash) else {
            throw WriteError("Không còn bản sao của phiếu này trong data/phieu-goc để khôi phục. "
                + "Nếu còn file phiếu ở nơi khác, hãy chép lại vào thư mục phiếu giao hàng.")
        }
        guard var target = notePath(f, row["rel_path"]) else { throw WriteError("Tên file phiếu không hợp lệ.") }
        if FileManager.default.fileExists(atPath: target.path) {
            let ext = target.pathExtension
            target = target.deletingLastPathComponent().appendingPathComponent(
                target.deletingPathExtension().lastPathComponent + " (khoi phuc)" + (ext.isEmpty ? "" : ".\(ext)"))
        }
        try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
        try FileManager.default.copyItem(at: original, to: target)
        let rel = nfc(String(target.path.dropFirst(f.deliveries.path.count + 1)))
        try db.execute(sql: """
            UPDATE scanned_files SET status = CASE WHEN message = 'needs_mapping' THEN 'needs_mapping' ELSE 'imported' END,
            message = '', rel_path = ? WHERE hash = ?
            """, arguments: [rel, hash])
        return target
    }

    public static func cancelMissing(_ db: Database, hash: String) throws {
        guard let id = try Int64.fetchOne(db, sql: "SELECT document_id FROM scanned_files WHERE hash = ?", arguments: [hash]) else {
            throw WriteError("Phiếu này chưa có đơn nào để huỷ.")
        }
        try Ledger.close(db, docId: id, status: "cancelled")
        try db.execute(sql: "UPDATE scanned_files SET status = 'missing_ignored' WHERE hash = ?", arguments: [hash])
    }

    public static func ignoreMissing(_ db: Database, hash: String) throws {
        try db.execute(sql: "UPDATE scanned_files SET status = 'missing_ignored' WHERE hash = ?", arguments: [hash])
    }

    /// Hide a file that is not a delivery note (stays hidden until its content changes).
    public static func dismissError(_ db: Database, hash: String) throws {
        try db.execute(sql: "UPDATE scanned_files SET status = 'ignored' WHERE hash = ?", arguments: [hash])
    }

    // MARK: a wrong choice: read a note again

    /// Undo the import of one delivery note so the next scan reads it again with the current names. The old document
    /// is kept as "replaced" (stock reversed); nothing is deleted.
    public static func rereadDocument(_ db: Database, _ f: ShopFolders, docId: Int64) throws {
        let row = try Row.fetchOne(db, sql: "SELECT * FROM scanned_files WHERE document_id = ?", arguments: [docId])
        guard let doc = try Row.fetchOne(db, sql: "SELECT * FROM documents WHERE id = ?", arguments: [docId]),
              (doc["kind"] as String) == "delivery", (doc["status"] as String) == "active",
              !(doc["source_hash"] as String).isEmpty else {
            throw WriteError("Chỉ đọc lại được phiếu giao hàng đang hiệu lực.")
        }
        let rel: String = row?["rel_path"] ?? doc["source_file"]
        guard let target = notePath(f, rel) else { throw WriteError("Không còn file phiếu để đọc lại.") }
        if !FileManager.default.fileExists(atPath: target.path) {  // file deleted or moved away: put the stored copy back
            guard let original = originalCopy(f, doc["source_hash"]) else { throw WriteError("Không còn file phiếu để đọc lại.") }
            try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
            try FileManager.default.copyItem(at: original, to: target)
        }
        try Ledger.close(db, docId: docId, status: "replaced")
        try db.execute(sql: "DELETE FROM scanned_files WHERE hash = ?", arguments: [doc["source_hash"] as String])
        try Meta.log(db, "delivery_reread", "\(doc["code"] as String) (\(rel))")
    }

    static func orderKeys(_ db: Database, _ docId: Int64) throws -> Set<String> {
        Set(try Row.fetchAll(db, sql: "SELECT raw_name, raw_spec FROM document_lines WHERE document_id = ?", arguments: [docId])
            .map { TextRules.matchKey($0["raw_name"] ?? "", $0["raw_spec"] ?? "") })
    }

    /// Notes recorded before migration 004 have no record of their dropped lines: read their stored copies once.
    static func backfillSkippedLines(_ db: Database, _ f: ShopFolders) throws {
        if try !Meta.get(db, "skipped_lines_backfilled").isEmpty { return }
        let ignored = Set(try Catalog.ignoredLines(db).map { $0["key"] as String })
        if !ignored.isEmpty {
            for d in try Row.fetchAll(db, sql: """
                SELECT id, source_hash FROM documents WHERE kind = 'delivery' AND status = 'active' AND source_hash <> ''
                AND id NOT IN (SELECT document_id FROM document_skipped_lines)
                """) {
                guard let note = readNote(originalCopy(f, d["source_hash"])) else { continue }
                for ln in note.lines where ignored.contains(ln.key) {
                    try db.execute(sql: "INSERT INTO document_skipped_lines(document_id, key, raw_name) VALUES(?,?,?)",
                                   arguments: [d["id"] as Int64, ln.key, ln.rawName])
                }
            }
        }
        try Meta.set(db, "skipped_lines_backfilled", "1")
    }

    /// Before forgetting anything: every note that will be read again must still have its file or its stored copy.
    static func checkRereadable(_ db: Database, _ f: ShopFolders, _ ids: [Int64]) throws {
        var lost: [String] = []
        for id in ids.sorted() {
            let doc = try Row.fetchOne(db, sql: "SELECT * FROM documents WHERE id = ?", arguments: [id])
            let rel = try String.fetchOne(db, sql: "SELECT rel_path FROM scanned_files WHERE document_id = ?", arguments: [id])
                ?? (doc?["source_file"] ?? "")
            let hash: String = doc?["source_hash"] ?? ""
            let haveFile = !rel.isEmpty && (notePath(f, rel).map { FileManager.default.fileExists(atPath: $0.path) } ?? false)
            if doc == nil || hash.isEmpty || !(haveFile || originalCopy(f, hash) != nil) {
                lost.append(doc?["code"] ?? "#\(id)")
            }
        }
        if !lost.isEmpty {
            throw WriteError("Không đọc lại được vì không còn file phiếu của đơn \(lost.joined(separator: ", ")). Không có gì bị thay đổi.")
        }
    }

    /// Forget every name learned from this note's goods lines ("not goods" lines are left alone) and read THIS note
    /// again. Other notes that use the same names stay exactly as they were recorded.
    public static func forgetOrder(_ db: Database, _ f: ShopFolders, docId: Int64) throws {
        try backfillSkippedLines(db, f)
        guard try Row.fetchOne(db, sql: "SELECT 1 FROM documents WHERE id = ? AND kind = 'delivery' AND status = 'active'",
                               arguments: [docId]) != nil else {
            throw WriteError("Chỉ đọc lại được phiếu giao hàng đang hiệu lực.")
        }
        try checkRereadable(db, f, [docId])
        for key in try orderKeys(db, docId) { try Catalog.forgetAlias(db, key: key) }
        try rereadDocument(db, f, docId: docId)
    }

    // MARK: orders read after a stock count

    static let firstIn = """
        (SELECT MIN(x.created_at) FROM documents x WHERE x.kind = 'delivery' AND x.code_norm = d.code_norm
         AND (x.source_hash = d.source_hash OR x.customer_id IS d.customer_id))
        """

    static func checked(_ db: Database) throws -> [String] {
        try Meta.get(db, countCheckedKey).split(separator: ",").map(String.init)
    }

    static func conflictRows(_ db: Database, docId: Int64?) throws -> [Row] {
        try Row.fetchAll(db, sql: """
            SELECT d.id, d.code, d.doc_date, d.source_hash, COALESCE(cu.name, '') AS customer,
                   c.id AS count_id, c.doc_date AS count_date
            FROM documents d
            JOIN documents c ON c.kind = 'stock_count' AND c.status = 'active' AND c.doc_date >= d.doc_date
            LEFT JOIN customers cu ON cu.id = d.customer_id
            WHERE d.kind = 'delivery' AND d.status = 'active' AND d.location_set = 1
              AND c.created_at < \(firstIn)
              AND EXISTS (SELECT 1 FROM stock_movements m JOIN document_lines cl ON cl.product_id = m.product_id
                          AND (cl.location_id IS NULL OR cl.location_id = m.location_id)
                          WHERE m.document_id = d.id AND m.kind = 'delivery_out' AND cl.document_id = c.id)
              AND (? IS NULL OR d.id = ?)
            ORDER BY d.doc_date, d.id, c.doc_date DESC, c.id DESC
            """, arguments: [docId, docId])
    }

    /// Orders dated on or before a stock count but first read into the app after that count. If their goods had
    /// already left when the shelf was counted, the count includes them and the order subtracts them a second time.
    /// One row per order, with the latest such count; orders the user already decided about are left out.
    public static func countConflicts(_ db: Database) throws -> [CountConflict] {
        let done = Set(try checked(db))
        var seen = Set<Int64>(), result: [CountConflict] = []
        for r in try conflictRows(db, docId: nil) {
            let id: Int64 = r["id"]
            let hash: String = r["source_hash"] ?? ""
            if seen.contains(id) || done.contains(hash.isEmpty ? "#\(id)" : hash) { continue }
            seen.insert(id)
            result.append(CountConflict(id: id, code: r["code"] ?? "", docDate: r["doc_date"], customer: r["customer"],
                                        countDate: r["count_date"]))
        }
        return result
    }

    static func markChecked(_ db: Database, _ docId: Int64) throws {
        let hash = try String.fetchOne(db, sql: "SELECT source_hash FROM documents WHERE id = ?", arguments: [docId]) ?? ""
        let key = hash.isEmpty ? "#\(docId)" : hash
        let list = try checked(db)
        if !list.contains(key) { try Meta.set(db, countCheckedKey, (list + [key]).joined(separator: ",")) }
    }

    /// "The count was right": give back exactly this order's quantities, product by product and place by place,
    /// wherever a count made before the order came in already saw the goods gone. The correction is a count
    /// adjustment dated on the earliest such count, so receipts, other orders and decisions made since stay.
    public static func keepCounted(_ db: Database, docId: Int64) throws {
        let code = try String.fetchOne(db, sql: "SELECT code FROM documents WHERE id = ?", arguments: [docId]) ?? ""
        let rows = try Row.fetchAll(db, sql: """
            SELECT m.product_id, m.location_id, SUM(m.qty) AS qty,
                   (SELECT MIN(c.doc_date) FROM documents c JOIN document_lines cl ON cl.document_id = c.id
                    WHERE c.kind = 'stock_count' AND c.status = 'active' AND c.doc_date >= d.doc_date
                      AND c.created_at < \(firstIn) AND cl.product_id = m.product_id
                      AND (cl.location_id IS NULL OR cl.location_id = m.location_id)) AS day
            FROM stock_movements m JOIN documents d ON d.id = m.document_id
            WHERE m.document_id = ? AND m.kind = 'delivery_out'
            GROUP BY m.product_id, m.location_id
            """, arguments: [docId])
        var byDay: [String: [Row]] = [:]
        for r in rows {
            if let day: String = r["day"], (r["qty"] as Double? ?? 0) != 0 { byDay[day, default: []].append(r) }
        }
        for day in byDay.keys.sorted() {
            let placed = try Ledger.levelsByPlace(db, asOf: day)
            let counted = byDay[day]!.map { r -> Ledger.Counted in
                let key = Ledger.PlaceKey(r["product_id"], r["location_id"])
                return .init(r["product_id"], r["location_id"], (placed[key] ?? 0.0) - (r["qty"] as Double))
            }
            try Ledger.stockCount(db, date: day, counted: counted, note: "Giữ số kiểm kê ngày \(Format.date(day)) (đơn \(code))")
        }
        try markChecked(db, docId)
    }

    /// "The goods left after the count": the order stays subtracted, nothing to change.
    public static func subtractToo(_ db: Database, docId: Int64) throws {
        try markChecked(db, docId)
        try Meta.touch(db)
    }
}
