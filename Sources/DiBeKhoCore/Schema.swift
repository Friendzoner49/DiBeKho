import Foundation
import GRDB

public enum DataError: Error, LocalizedError, Equatable {
    case newer(found: Int, supported: Int)
    case notDiBeKho

    public var errorDescription: String? {
        switch self {
        case let .newer(found, supported):
            return "Dữ liệu này của bản DiBeKho mới hơn (phiên bản dữ liệu \(found), bản này đọc tới \(supported)). Hãy cập nhật app."
        case .notDiBeKho:
            return "File này không phải dữ liệu DiBeKho."
        }
    }
}

/// The schema, as the Python app's db.migrate: the version is the number in the file name, each file runs in its own
/// transaction with foreign keys off and checked before it commits, then PRAGMA user_version is set. No
/// grdb_migrations table: the Python app and the .dibekho packages must not get anything they do not know.
public enum Schema {
    public static var supportedVersion: Int { Migrations.files.map(\.version).max() ?? 0 }

    /// As Python's _split_sql: comments stripped line by line (they may hold ';'), then split on ';'.
    static func split(_ sql: String) -> [String] {
        let lines = sql.components(separatedBy: "\n").map { line -> String in
            if let r = line.range(of: "--") { return String(line[..<r.lowerBound]) }
            return line
        }
        return lines.joined(separator: "\n").components(separatedBy: ";")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    public static func version(_ db: Database) throws -> Int {
        try Int.fetchOne(db, sql: "PRAGMA user_version") ?? 0
    }

    /// Brings the data up to supportedVersion. Refuses data from a newer app.
    public static func migrate(_ queue: DatabaseQueue) throws {
        try queue.writeWithoutTransaction { db in
            let current = try Schema.version(db)
            if current > supportedVersion { throw DataError.newer(found: current, supported: supportedVersion) }
            for file in Migrations.files.sorted(by: { $0.version < $1.version }) where file.version > current {
                try db.execute(sql: "PRAGMA foreign_keys = OFF")
                defer { try? db.execute(sql: "PRAGMA foreign_keys = ON") }
                try db.inTransaction(.immediate) {
                    for statement in Schema.split(file.sql) {
                        try db.execute(sql: statement)
                    }
                    if try Row.fetchOne(db, sql: "PRAGMA foreign_key_check") != nil {
                        throw DatabaseError(message: "migration \(file.version): foreign key check failed")
                    }
                    try db.execute(sql: "PRAGMA user_version = \(file.version)")
                    return .commit
                }
            }
        }
    }
}
