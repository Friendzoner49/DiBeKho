import Foundation

/// Python core/fx: CNY ⇄ VND for the ₫ | ¥ switch. The market rate comes from FXRatesAPI (no key), else from the free
/// ExchangeRate-API (once a day); the last rate is kept in fx.json next to config.json so the switch works offline.
/// Nothing about the user or the data is sent: one plain GET. The data and every file stay in VND; only the text on
/// screen changes (FX.inCny).
public enum FX {
    public static let url = URL(string: "https://api.fxratesapi.com/latest?base=CNY&currencies=VND")!
    public static let source = "FXRatesAPI"
    public static let dailyURL = URL(string: "https://open.er-api.com/v6/latest/CNY")!
    public static let dailySource = "ExchangeRate-API"
    public static let timeout: TimeInterval = 8
    public static let freshSeconds: TimeInterval = 600

    public struct Rate: Equatable {
        public var vndPerCny: Double
        public var updated: Date  // when the provider computed it
        public var fetched: Date  // when this computer got it
        public var source: String
        public init(vndPerCny: Double, updated: Date, fetched: Date, source: String = FX.source) {
            self.vndPerCny = vndPerCny
            self.updated = updated
            self.fetched = fetched
            self.source = source
        }
    }

    public struct FXError: Error, LocalizedError {
        public let message: String
        public var errorDescription: String? { message }
    }

    /// What the screens show money in ("vnd" | "cny") and the rate they use.
    public static var currency = "vnd"
    public static var rate: Rate?
    public static var inCny: Bool { currency == "cny" && rate != nil }

    /// A provider's JSON -> Rate: FXRatesAPI or ExchangeRate-API. Throws when it is not a usable answer.
    public static func parse(_ data: Data, fetched: Date = Date()) throws -> Rate {
        let bad = FXError(message: "Trang tỷ giá trả lời không đúng.")
        guard let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { throw bad }
        let stamp: Any?, src: String
        if (object["success"] as? Bool) == true, (object["base"] as? String) == "CNY" {
            stamp = object["timestamp"]
            src = source
        } else if (object["result"] as? String) == "success", (object["base_code"] as? String) == "CNY" {
            stamp = object["time_last_update_unix"]
            src = dailySource
        } else {
            throw bad
        }
        guard let rates = object["rates"] as? [String: Any], let number = rates["VND"] as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID(), number.doubleValue > 0 else {
            throw FXError(message: "Trang tỷ giá không có tỷ giá VND.")
        }
        let seconds = (stamp as? NSNumber)?.doubleValue ?? 0
        return Rate(vndPerCny: number.doubleValue, updated: Date(timeIntervalSince1970: seconds), fetched: fetched, source: src)
    }

    /// Asks the provider of the minute's rate, then the once-a-day one; the rate got is cached.
    public static func fetch() async throws -> Rate {
        func get(_ url: URL) async throws -> Data {
            var request = URLRequest(url: url, timeoutInterval: timeout)
            request.setValue("DiBeKho", forHTTPHeaderField: "User-Agent")
            request.setValue("application/json", forHTTPHeaderField: "Accept")
            return try await URLSession.shared.data(for: request).0
        }
        let rate: Rate
        do { rate = try parse(try await get(url)) } catch { rate = try parse(try await get(dailyURL)) }
        save(rate)
        return rate
    }

    /// The rate to keep with a note priced in yuan when it is read: the one the switch got, else the cached one.
    public static func known() -> Rate? { rate ?? cached() }

    public static func isFresh(_ r: Rate?, now: Date = Date()) -> Bool {
        guard let r else { return false }
        return now.timeIntervalSince(r.fetched) < freshSeconds
    }

    // ---- fx.json (as Python writes it: local time, ISO)

    public static var cacheFile: URL { Workspace.configFile.deletingLastPathComponent().appendingPathComponent("fx.json") }

    private static func isoLocal(_ d: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f.string(from: d)
    }

    private static func parseLocal(_ s: String) -> Date? {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f.date(from: String(s.prefix(19)))  // Python may add microseconds
    }

    public static func save(_ r: Rate, to file: URL? = nil) {
        let target = file ?? cacheFile
        let object: [String: Any] = ["vnd_per_cny": r.vndPerCny, "updated": isoLocal(r.updated), "fetched": isoLocal(r.fetched), "source": r.source]
        guard let data = try? JSONSerialization.data(withJSONObject: object) else { return }
        try? FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? data.write(to: target)  // only a cache
    }

    public static func cached(from file: URL? = nil) -> Rate? {
        guard let data = try? Data(contentsOf: file ?? cacheFile),
              let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let value = (object["vnd_per_cny"] as? NSNumber)?.doubleValue, value > 0,
              let updated = (object["updated"] as? String).flatMap(parseLocal),
              let fetched = (object["fetched"] as? String).flatMap(parseLocal) else { return nil }
        let src = (object["source"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? dailySource
        return Rate(vndPerCny: value, updated: updated, fetched: fetched, source: src)
    }
}
