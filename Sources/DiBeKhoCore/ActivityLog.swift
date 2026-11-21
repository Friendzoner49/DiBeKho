import Foundation

/// Python core/activity: data/app.log of the work folder, when one is set (nothing is written otherwise).
/// One line per event: "2026-10-17 14:48:02 [click] text"; a following line is indented by 4 spaces. The file never
/// grows past `maxBytes` (the oldest lines go, cut at a line) and lines older than `maxAgeDays` go once at start.
public enum ActivityLog {
    public static var file: URL?
    public static let maxBytes = 1_000_000
    public static let keepBytes = 720_000
    public static let maxAgeDays = 7

    /// Set the file and drop the lines older than a week (core.activity.setup).
    public static func setup(_ url: URL?, today: Date = Date()) {
        file = url
        if let url { trimOld(url, today: today) }
    }

    public static func format(_ kind: String, _ text: String, now: Date = Date()) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        var line = "\(f.string(from: now)) [\(kind)] \(text)"
        while line.hasSuffix(" ") || line.hasSuffix("\n") { line.removeLast() }
        return line.replacingOccurrences(of: "\r\n", with: "\n").replacingOccurrences(of: "\n", with: "\n    ") + "\n"
    }

    public static func write(_ kind: String, _ text: String) {
        guard let file, let data = format(kind, text).data(using: .utf8) else { return }
        if let handle = try? FileHandle(forWritingTo: file) {
            defer { try? handle.close() }
            _ = try? handle.seekToEnd()
            try? handle.write(contentsOf: data)
        } else {
            try? data.write(to: file)
        }
        let size = ((try? FileManager.default.attributesOfItem(atPath: file.path))?[.size] as? Int) ?? 0
        if size > maxBytes { trim(file) }
    }

    /// Keep about `keepBytes` of the newest lines, starting at a whole line and never inside a traceback.
    static func trim(_ url: URL) {
        guard let data = try? Data(contentsOf: url) else { return }
        var tail = Data(data.suffix(keepBytes))
        func dropLine() {
            if let nl = tail.firstIndex(of: 0x0A) { tail = Data(tail[(nl + 1)...]) } else { tail = Data() }
        }
        dropLine()
        while tail.starts(with: Array("    ".utf8)) { dropLine() }
        try? tail.write(to: url, options: .atomic)
    }

    /// Drop every line older than `maxAgeDays`, with the indented lines that follow it.
    public static func trimOld(_ url: URL, today: Date = Date()) {
        guard let text = try? String(contentsOf: url, encoding: .utf8) else { return }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        let calendar = Calendar(identifier: .gregorian)
        guard let cutoff = calendar.date(byAdding: .day, value: -maxAgeDays, to: calendar.startOfDay(for: today)) else { return }
        let lines = text.components(separatedBy: "\n")
        var keepFrom = lines.count  // nothing recent enough found: drop everything
        for (i, line) in lines.enumerated() {
            if line.isEmpty || line.hasPrefix("    ") { continue }
            guard let day = f.date(from: String(line.prefix(10))) else { continue }
            if day >= cutoff { keepFrom = i; break }
        }
        if keepFrom == 0 { return }
        try? lines[keepFrom...].joined(separator: "\n").write(to: url, atomically: true, encoding: .utf8)
    }

    public static func read(_ url: URL? = file) -> String {
        guard let url, let text = try? String(contentsOf: url, encoding: .utf8) else { return "" }
        return text
    }

    public static func clear() {
        if let file { try? Data().write(to: file) }
    }

    /// The logs of other machines that came with a data package (data/nhat-ky-<machine>.log).
    public static func otherDevices(dataFolder: URL) -> [URL] {
        let all = (try? FileManager.default.contentsOfDirectory(at: dataFolder, includingPropertiesForKeys: nil)) ?? []
        return all.filter { $0.lastPathComponent.hasPrefix("nhat-ky-") && $0.pathExtension == "log" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
    }
}
