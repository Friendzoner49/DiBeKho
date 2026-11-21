import Foundation
import GRDB
import XCTest

@testable import DiBeKhoCore

/// core/cloud/twoway.py + replica.py replayed on the made-up shop (Generated/GoldenCloud.swift, tools/gen_cloud.py):
/// the first push, pulls (new rows, echo, conflict, renumbering, duplicates, deletions, shared meta), resolving, and
/// starting from the cloud. The network is not part of it (⚠ the Cloud client and sign-in have no golden).
final class CloudMergeTests: XCTestCase {
    private static let skip: Set<String> = ["created_at", "closed_at", "at", "first_seen", "last_seen"]
    private static let dumped = SyncSchema.tables.map(\.name) + ["scanned_files"]

    private var counter = 0

    override func setUp() {
        counter = 0
        Replica.newUID = { [unowned self] in
            self.counter += 1
            return "00000000-0000-0000-0000-" + String(format: "%012x", self.counter)
        }
        TwoWay.clockOffset = { 420 }
    }

    override func tearDown() {
        Replica.newUID = { UUID().uuidString.lowercased() }
        TwoWay.clockOffset = { TimeZone.current.secondsFromGMT() / 60 }
    }

    // ---- the same text as tools/gen_cloud.py writes

    private func cj(_ v: DatabaseValue) -> String {
        switch v.storage {
        case .null: return "∅"
        case .int64(let i): return String(format: "%.4f", Double(i))
        case .double(let d): return String(format: "%.4f", d)
        case .string(let s): return s
        case .blob: return "blob"
        }
    }

    private func cj(_ v: CloudValue) -> String {
        switch v {
        case .null: return "∅"
        case .bool(let b): return b ? "true" : "false"
        case .int(let i): return String(format: "%.4f", Double(i))
        case .double(let d): return String(format: "%.4f", d)
        case .text(let s): return s
        }
    }

    private func crow(_ row: CloudRow) -> String {
        row.keys.sorted().filter { !Self.skip.contains($0) }.map { "\($0)=\(cj(row[$0] ?? .null))" }.joined(separator: "|")
    }

    private func batchLines(_ batch: [String: [CloudRow]]) -> [String] {
        var out: [String] = []
        for t in SyncSchema.tables { for r in batch[t.name] ?? [] { out.append("\(t.name): \(crow(r))") } }
        return out
    }

    private func dump(_ db: Database) throws -> [String] {
        var out: [String] = []
        for name in Self.dumped {
            let cols = try Row.fetchAll(db, sql: "PRAGMA table_info(\(name))").map { $0["name"] as String }.filter { !Self.skip.contains($0) }
            let only = name == "meta" ? " WHERE key != 'sync_conflicts'" : ""  // its JSON text differs in key order between the languages
            for r in try Row.fetchAll(db, sql: "SELECT \(cols.joined(separator: ", ")) FROM \(name)\(only) ORDER BY rowid") {
                out.append("\(name): " + cols.map { "\($0)=\(cj(r[$0] as DatabaseValue))" }.joined(separator: "|"))
            }
        }
        for r in try Row.fetchAll(db, sql: "SELECT tbl, local_id, uid FROM sync_map ORDER BY tbl, local_id") {
            out.append("sync_map: \(cj(r[0] as DatabaseValue))|\(cj(r[1] as DatabaseValue))|\(cj(r[2] as DatabaseValue))")
        }
        for r in try Row.fetchAll(db, sql: "SELECT tbl, local_id, op, uid FROM sync_outbox ORDER BY seq") {
            out.append("outbox: " + (0..<4).map { cj(r[$0] as DatabaseValue) }.joined(separator: "|"))
        }
        for r in try Row.fetchAll(db, sql: "SELECT key, value FROM sync_flags ORDER BY key") {
            out.append("flag: \(cj(r[0] as DatabaseValue))=\(cj(r[1] as DatabaseValue))")
        }
        return out
    }

    // ---- the shop, as tools/gen_cloud.py builds it

    private func build() throws -> (DatabaseQueue, [String]) {
        counter = 0
        let q = try DatabaseQueue(configuration: Store.configuration())
        try Schema.migrate(q)
        let lines = try q.write { db -> [String] in
            for statement in Schema.split(Golden.shop) { try db.execute(sql: statement) }
            for t in SyncSchema.tables {
                let cols = try Replica.columns(db, t)
                for col in ["created_at", "closed_at"] where cols.contains(col) {
                    try db.execute(sql: "UPDATE \(t.name) SET \(col) = '2026-11-01 09:00:00' WHERE \(col) IS NOT NULL")
                }
            }
            try Sync.ensureTriggers(db)
            try TwoWay.startFromThisMachine(db)
            let (batch, seq, hold) = try TwoWay.prepare(db)
            try TwoWay.finish(db, seq: seq, maxRev: 100, hold: hold)
            return batchLines(batch)
        }
        return (q, lines)
    }

    func testTheFirstPushIsWhatPythonSends() throws {
        let (_, lines) = try build()
        XCTAssertEqual(lines, GoldenCloud.firstPush)
    }

    func testScenariosMatchPython() throws {
        for s in GoldenCloud.scenarios {
            let (q, _) = try build()
            let lines = try q.write { db -> [String] in
                for statement in s.sql { try db.execute(sql: statement) }
                var lines: [String] = []
                if s.op == "start_from_cloud" {
                    try TwoWay.startFromCloud(db)
                } else if !s.pulled.isEmpty {
                    let json = try JSONSerialization.jsonObject(with: Data(s.pulled.utf8))
                    let m = try TwoWay.merge(db, CloudJSON.pulled(json))
                    lines.append("merged: applied=\(m.applied)|renamed=\(m.renamed.map { "\($0.table):\($0.old)>\($0.new)" }.joined(separator: ";"))"
                        + "|duplicates=\(m.duplicates)|separated=\(m.separated.joined(separator: ";"))"
                        + "|conflicts=\(m.conflicts.map { "\($0.table):\($0.uid)" }.joined(separator: ";"))"
                        + "|export=\(m.receiptsToExport.map(String.init).joined(separator: ","))"
                        + "|files=\(m.receiptFiles.map { "\($0.id):\($0.file)" }.joined(separator: ";"))")
                    if !s.resolve.isEmpty, let first = try TwoWay.conflicts(db).first {
                        try TwoWay.resolve(db, first, keepMine: s.resolve == "mine")
                    }
                }
                if s.op != "start_from_cloud" {
                    let (batch, seq, hold) = try TwoWay.prepare(db)
                    lines += batchLines(batch).map { "batch: \($0)" }
                    lines.append("seq: \(seq)")
                    lines.append("hold: " + hold.map { "\($0.table):\($0.id)" }.sorted().joined(separator: ","))
                }
                lines.append("cursor: \(try TwoWay.cursor(db))")
                for c in try TwoWay.conflicts(db) { lines.append("conflict: \(c.table)|\(c.uid)|\(crow(c.local))|\(crow(c.cloud))") }
                for r in try Row.fetchAll(db, sql: "SELECT key, value FROM meta WHERE key NOT IN ('last_change_at', 'sync_conflicts') ORDER BY key") {
                    lines.append("meta: \(r[0] as String)=\(r[1] as String)")
                }
                for p in s.probes {
                    let row = try Row.fetchOne(db, sql: p)
                    let value: DatabaseValue = row?[0] ?? .null
                    lines.append("probe: \(cj(value))")
                }
                let state = try dump(db)
                return lines + state
            }
            if lines != s.expected {
                let n = zip(lines, s.expected).enumerated().first { $0.element.0 != $0.element.1 }?.offset ?? min(lines.count, s.expected.count)
                XCTFail("\(s.name): line \(n) differs\n  swift : \(n < lines.count ? lines[n] : "(none)")\n  python: \(n < s.expected.count ? s.expected[n] : "(none)")")
            }
        }
    }
}
