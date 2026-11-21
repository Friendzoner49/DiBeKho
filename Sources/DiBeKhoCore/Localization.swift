import Foundation
import GRDB

/// Python db/sync_schema.ensure_triggers: the triggers that queue every change for the cloud (sync_outbox), made
/// on every open after the migrations (a migration that rebuilt a table dropped its triggers). The SQL is the Python
/// app's own (Generated/SyncTriggers.swift). No-op before migration 010.
public enum Sync {
    public static func ensureTriggers(_ db: Database) throws {
        let hasOutbox = try Bool.fetchOne(db, sql: "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sync_outbox'") ?? false
        if !hasOutbox { return }
        var stored: [String: String] = [:]
        for r in try Row.fetchAll(db, sql: "SELECT name, sql FROM sqlite_master WHERE type = 'trigger'") {
            stored[r["name"]] = r["sql"]
        }
        for statement in SyncTriggers.statements {
            let name = statement.split(separator: " ")[5]  // CREATE TRIGGER IF NOT EXISTS <name> ...
            if let old = stored[String(name)],
               old != statement.replacingOccurrences(of: "IF NOT EXISTS ", with: "", options: [], range: statement.range(of: "IF NOT EXISTS ")) {
                try db.execute(sql: "DROP TRIGGER \(name)")  // an older version
            }
            try db.execute(sql: statement)
        }
    }
}

/// The screen texts of the Python app (i18n/{vi,en,zh}.json), with its rule: the current language, else
/// Vietnamese, else the key itself; {name} filled in from the values.
public enum L10n {
    public static let languages = ["vi", "en", "zh"]
    public static var language = "vi"

    static let tables: [String: [String: String]] = {
        var out: [String: [String: String]] = [:]
        for (lang, json) in StringFiles.json {
            if let data = json.data(using: .utf8),
               let object = try? JSONSerialization.jsonObject(with: data) as? [String: String] {
                out[lang] = object
            }
        }
        return out
    }()

    public static func has(_ key: String) -> Bool { tables["vi"]?[key] != nil }

    public static func t(_ key: String, _ values: [String: String] = [:]) -> String {
        var text = tables[language]?[key] ?? tables["vi"]?[key] ?? key
        for (name, value) in values {
            text = text.replacingOccurrences(of: "{\(name)}", with: value)
        }
        return text
    }
}

/// Short form for the screens.
public func t(_ key: String, _ values: [String: String] = [:]) -> String { L10n.t(key, values) }
