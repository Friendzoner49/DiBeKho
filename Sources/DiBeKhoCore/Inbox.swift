import Foundation
import GRDB

extension ShopFolders {
    /// input/da-xu-ly: where a used file goes
    public var inputDone: URL { input.appendingPathComponent(Deliveries.processed, isDirectory: true) }
}

/// One file of input/ (or one the user picked): what it is and what can be done with it (core/inbox.py).
public struct InboxItem {
    public enum Kind: String { case receipt, master, catalog, package, error }
    public let url: URL
    public var kind: Kind
    public var message = ""
    public var receipt: ReceiptFile.Parsed?
    /// the receipt's lines joined with the products of the catalog (nil = not in the catalog)
    public var resolved: [(line: ReceiptFile.Line, product: Product?)] = []
    /// what a 'dữ liệu gốc' workbook holds
    public var master: MasterData.Contents?
    /// how many products a monthly stock sheet (a catalog file) lists
    public var catalogCount = 0
    public var manifest: Transfer.Manifest?
    public var name: String { url.lastPathComponent }
    public var totalQty: Double { resolved.reduce(0) { $0 + $1.line.qty } }
}

/// The input/ folder: goods receipt files. A used file is moved to input/da-xu-ly/ only after it was used (or the user
/// discarded a usable file). A file the app cannot use is never moved: it can only be hidden.
/// Catalog sheets, the 'dữ liệu gốc' workbook and data packages (.dibekho) are listed with their own import button.
public enum Inbox {
    public static func items(_ db: Database, _ f: ShopFolders) throws -> [InboxItem] {
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: f.input.path) else { return [] }
        let hidden = Set(try String.fetchAll(db, sql: "SELECT hash FROM hidden_inputs"))
        var out: [InboxItem] = []
        for name in names.sorted(by: Deliveries.scalarsLess) {
            let url = f.input.appendingPathComponent(name)
            guard !name.hasPrefix("~$"), !name.hasPrefix("."), Deliveries.isFile(url) else { continue }
            if !hidden.isEmpty {
                guard let hash = try? Deliveries.fileHash(url) else { continue }
                if hidden.contains(hash) { continue }
            }
            switch url.pathExtension.lowercased() {
            case "dibekho":
                do {
                    out.append(InboxItem(url: url, kind: .package, manifest: try Transfer.readManifest(url)))
                } catch {
                    out.append(InboxItem(url: url, kind: .error, message: error.localizedDescription))
                }
            case "xlsx":
                out.append(try readItem(db, url))
            default:
                out.append(InboxItem(url: url, kind: .error, message: "Chỉ nhận file hàng về (.xlsx) hoặc gói dữ liệu (.dibekho)."))
            }
        }
        return out
    }

    /// Recognise one Excel file: a goods receipt, or something unusable (with the reason).
    public static func readItem(_ db: Database, _ url: URL) throws -> InboxItem {
        let parsed: ReceiptFile.Parsed
        do {
            parsed = try ReceiptFile.read(url)
        } catch ReceiptFile.Failure.notReceipt {
            if let master = try? MasterData.read(url) { return InboxItem(url: url, kind: .master, master: master) }
            if let items = try? CatalogSheet.read(url), !items.isEmpty {
                return InboxItem(url: url, kind: .catalog, catalogCount: items.count)
            }
            if (try? DeliveryNoteReader.read(url)) != nil {
                return InboxItem(url: url, kind: .error,
                                 message: "Đây là phiếu giao hàng — hãy để nó trong thư mục phieu-giao-hang/, không phải input/.")
            }
            return InboxItem(url: url, kind: .error, message: "Không phải file hàng về hay file danh mục. Hàng về: dùng nút 'Nhập hàng về…' trong app.")
        } catch ReceiptFile.Failure.invalid(let reason) {
            return InboxItem(url: url, kind: .error, message: reason)
        }
        var item = InboxItem(url: url, kind: .receipt, receipt: parsed)
        for line in parsed.lines {
            let product = try Row.fetchOne(db, sql: "SELECT * FROM products WHERE code = ?", arguments: [line.code]).map(Product.init)
            item.resolved.append((line, product))
        }
        let unknown = item.resolved.filter { $0.product == nil }.map(\.line.code)
        if !unknown.isEmpty {
            item.kind = .error
            item.message = "Mã hàng không có trong danh mục: " + unknown.joined(separator: ", ")
        } else if try alreadyImported(db, try Deliveries.fileHash(url)) {
            item.kind = .error
            item.message = "File hàng về này đã được nhập trước đó."
        }
        return item
    }

    static func alreadyImported(_ db: Database, _ hash: String) throws -> Bool {
        // 'replaced': a receipt edited in the app; its old file must not come in again either
        try Row.fetchOne(db, sql: "SELECT 1 FROM documents WHERE kind = 'receipt' AND status IN ('active', 'replaced') AND source_hash = ?",
                         arguments: [hash]) != nil
    }

    /// Record the receipt of a file (the caller's transaction); the file is moved by `done` afterwards.
    @discardableResult
    public static func applyReceipt(_ db: Database, _ item: InboxItem) throws -> Int64 {
        guard item.kind == .receipt, let receipt = item.receipt else { throw WriteError(item.message) }
        let hash = try Deliveries.fileHash(item.url)
        let docId = try Ledger.insertDocument(db, kind: "receipt", date: receipt.date,
                                              lines: item.resolved.compactMap { r in r.product.map { LedgerLine($0.id, r.line.qty) } },
                                              note: receipt.note, sourceFile: item.name, sourceHash: hash)
        try Meta.log(db, "receipt_imported", item.name)
        return docId
    }

    /// A used file leaves input/ (to input/da-xu-ly/). Files chosen from elsewhere are not touched.
    public static func done(_ f: ShopFolders, _ url: URL) {
        let fm = FileManager.default
        guard url.deletingLastPathComponent().resolvingSymlinksInPath().standardizedFileURL.path
                == f.input.resolvingSymlinksInPath().standardizedFileURL.path,
              fm.fileExists(atPath: url.path) else { return }
        let stamp = DateFormatter()
        stamp.locale = Locale(identifier: "en_US_POSIX")
        stamp.dateFormat = "yyyyMMdd-HHmmss"
        let name = url.deletingPathExtension().lastPathComponent + "__" + stamp.string(from: Date())
            + (url.pathExtension.isEmpty ? "" : "." + url.pathExtension)
        try? fm.createDirectory(at: f.inputDone, withIntermediateDirectories: true)
        try? fm.moveItem(at: url, to: f.inputDone.appendingPathComponent(name))
    }

    /// The user does not want a usable file: move it out of input/.
    public static func discard(_ f: ShopFolders, _ item: InboxItem) { done(f, item.url) }

    /// An unusable file: hide it from 'Cần xử lý' but leave it where it is.
    public static func hide(_ db: Database, _ item: InboxItem) throws {
        try db.execute(sql: "INSERT OR REPLACE INTO hidden_inputs(hash, name) VALUES(?, ?)",
                       arguments: [try Deliveries.fileHash(item.url), item.name])
    }
}
