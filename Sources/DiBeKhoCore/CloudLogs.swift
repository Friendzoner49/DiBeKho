import CryptoKit
import Foundation

/// Python core/cloud/logs.py: the activity log (data/app.log) on the cloud, one row per account + machine + day (the
/// server takes the account from the sign-in), replaced while the day lasts, kept 30 days; only the developer's account
/// reads them. Before anything leaves the machine the text goes through anonymize(), which must give exactly what the
/// Python app gives (golden test GoldenLogs, tools/gen_logs.py). The user can switch it off (Cài đặt → Cloud).
public enum CloudLogs {
    public static let every: TimeInterval = 10 * 60
    static let days = 2  // today and yesterday (a machine left on over midnight)
    static let countsOnly: Set<String> = ["scan", "apply", "receipt", "forget", "data"]

    static func regex(_ pattern: String, _ options: NSRegularExpression.Options = []) -> NSRegularExpression {
        // the patterns are fixed text of this file
        try! NSRegularExpression(pattern: pattern, options: options)  // swiftlint:disable:this force_try
    }

    static let logLine = regex(#"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) \[(\w+)\] ?(.*)$"#)
    static let email = regex(#"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"#)
    static let path = regex(#"(?:[A-Za-z]:[\\/]|\\\\|/(?:Users|home|Volumes|private|var|tmp)/)[^\s"'<>|]*"#)
    static let file = regex(#"[^\s"'«»“”/\\:]+\.(?:xlsx|xlsm|xls|dibekho|sqlite|csv|pdf|zip|log|json|txt)\b"#, [.caseInsensitive])
    static let quoted = regex(#"«[^»\n]*»|“[^”\n]*”|"[^"\n]*"|'[^'\n]{2,}'"#)
    static let digits = regex(#"\+?\d[\d .-]{5,}\d"#)
    static let titleCut = regex(#"\s*(?:[:：—–·|(]|\s-\s).*$"#)
    static let afterLabel = regex(#"([:：]\s*)[^·→\n]*?(?=\s*[·→]|$)"#, [.anchorsMatchLines])
    static let frame = regex(#"^(\s*File )"([^"]+)"(.*)$"#)
    static let scanCounts = regex(#"^read (\d+).*?waiting (\d+)"#)
    static let number = regex(#"(?<![\w.])\d+(?![\w.])"#)

    // ---- small helpers over NSRegularExpression

    static func ns(_ s: String) -> NSRange { NSRange(s.startIndex..., in: s) }

    static func group(_ s: String, _ m: NSTextCheckingResult, _ i: Int) -> String {
        guard let r = Range(m.range(at: i), in: s) else { return "" }
        return String(s[r])
    }

    /// re.sub with a function
    static func sub(_ re: NSRegularExpression, _ s: String, _ replace: (NSTextCheckingResult) -> String) -> String {
        var out = ""
        var last = s.startIndex
        for m in re.matches(in: s, range: ns(s)) {
            guard let r = Range(m.range, in: s) else { continue }
            out += s[last..<r.lowerBound]
            out += replace(m)
            last = r.upperBound
        }
        out += s[last...]
        return out
    }

    static func sub(_ re: NSRegularExpression, _ s: String, _ text: String) -> String { sub(re, s) { _ in text } }

    static func strip(_ s: String, _ chars: Set<Character>) -> String {
        var t = Substring(s)
        while let c = t.first, chars.contains(c) { t.removeFirst() }
        while let c = t.last, chars.contains(c) { t.removeLast() }
        return String(t)
    }

    // ---- the parts of logs.py

    static func pathText(_ found: String) -> String {
        let text = found.replacingOccurrences(of: "\\", with: "/")
        for anchor in ["/dibekho/", "/site-packages/", "/_internal/"] {
            if let r = text.range(of: anchor) {
                return anchor.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/" + text[r.upperBound...]
            }
        }
        return "<path>"
    }

    static func scrub(_ text: String) -> String {
        var t = sub(email, text, "<email>")
        t = sub(path, t) { pathText(group(t, $0, 0)) }
        t = sub(file, t, "<file>")
        t = sub(quoted, t, "«…»")
        return sub(digits, t, "<số>")
    }

    /// Every text of the app's own interface, cut like a window title: a title that is not one of them (a dialog
    /// named after a customer or a file) is hidden.
    static let appTitles: Set<String> = {
        var out: Set<String> = []
        for table in L10n.tables.values {
            for value in table.values {
                out.insert(sub(titleCut, value, "").trimmingCharacters(in: .whitespacesAndNewlines))
            }
        }
        out.remove("")
        return out
    }()

    static func title(_ text: String) -> String {
        let cut = sub(titleCut, text, "").trimmingCharacters(in: .whitespacesAndNewlines)
        return appTitles.contains(cut) ? cut : "«…»"
    }

    static func message(_ text: String) -> String {
        let t = scrub(text)
        return sub(afterLabel, t) { m in
            let whole = group(t, m, 0)
            return strip(whole, [":", "：", " "]).isEmpty ? whole : group(t, m, 1) + "«…»"
        }
    }

    static func traceLine(_ line: String) -> String {
        if let m = frame.firstMatch(in: line, range: ns(line)) {
            let inner = group(line, m, 2)
            return group(line, m, 1) + "\"" + sub(path, inner) { pathText(group(inner, $0, 0)) } + "\"" + scrub(group(line, m, 3))
        }
        return scrub(line)
    }

    static func event(_ kind: String, _ text: String) -> String {
        let first: String, rest: String
        if let nl = text.firstIndex(of: "\n") {
            first = String(text[..<nl])
            rest = String(text[text.index(after: nl)...])
        } else {
            first = text
            rest = ""
        }
        if kind == "scan" {  // 'read 2: <file names> · waiting 1'
            guard let m = scanCounts.firstMatch(in: first, range: ns(first)) else { return "" }
            return "read \(group(first, m, 1)) · waiting \(group(first, m, 2))"
        }
        if countsOnly.contains(kind) {
            let plain = sub(digits, sub(file, first, ""), "")
            let numbers = number.matches(in: plain, range: ns(plain)).map { group(plain, $0, 0) }
            let lines = text.filter { $0 == "\n" }.count
            return numbers.prefix(6).joined(separator: " ") + (lines > 0 ? " (+\(lines) dòng)" : "")
        }
        if kind == "window" { return title(first) }
        if kind == "error" || kind == "crash" {  // the message may name a customer; the traceback is code
            let trace = rest.isEmpty ? "" : rest.components(separatedBy: "\n").map(traceLine).joined(separator: "\n")
            return scrub(first) + (trace.isEmpty ? "" : "\n" + trace)
        }
        if kind == "ask" || kind == "info" { return message(text) }
        return scrub(text)
    }

    /// app.log text -> [day: anonymized lines of that day]. Continuation lines (indented by 4) follow their event.
    public static func anonymize(_ text: String) -> [String: String] {
        var days: [String: [String]] = [:]
        var current: (day: String, clock: String, kind: String, parts: [String])?

        func flush() {
            guard let e = current else { return }
            let body = event(e.kind, e.parts.joined(separator: "\n")).replacingOccurrences(of: "\n", with: "\n    ")
            var line = "\(e.day) \(e.clock) [\(e.kind)] \(body)"
            while let c = line.last, c.isWhitespace { line.removeLast() }
            days[e.day, default: []].append(line)
        }

        let normal = text.replacingOccurrences(of: "\r\n", with: "\n").replacingOccurrences(of: "\r", with: "\n")
        var lines = normal.components(separatedBy: "\n")
        if lines.last == "" { lines.removeLast() }
        for l in lines {
            if let m = logLine.firstMatch(in: l, range: ns(l)) {
                flush()
                current = (group(l, m, 1), group(l, m, 2), group(l, m, 3), [group(l, m, 4)])
            } else if current != nil && l.hasPrefix("    ") {
                current?.parts.append(String(l.dropFirst(4)))
            }
        }
        flush()
        return days.mapValues { $0.joined(separator: "\n") + "\n" }
    }

    static func digest(_ text: String) -> String {
        Insecure.SHA1.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    /// Called after the pull of a sync round. A failure goes to the log and never stops a sync (LogUploader).
    public final class Uploader {
        var last: Date?
        var sent: [String: String] = [:]  // day -> hash of what the cloud has

        public init() {}

        public func maybeUpload(logFile: URL?, deviceName: String, deviceId: String, version: String, sendLogs: Bool,
                                _ client: CloudClient, _ token: String) async {
            guard sendLogs, let logFile else { return }
            let now = Date()
            if let last, now.timeIntervalSince(last) < CloudLogs.every { return }
            last = now
            do {
                _ = try await upload(logFile: logFile, deviceName: deviceName, deviceId: deviceId, version: version, client, token)
            } catch {
                ActivityLog.write("error", "uploading the activity log: \(error)")
            }
        }

        /// Send the days that changed; -> how many were sent.
        func upload(logFile: URL, deviceName: String, deviceId: String, version: String,
                    _ client: CloudClient, _ token: String, today: Date = Date()) async throws -> Int {
            guard let data = try? Data(contentsOf: logFile) else { return 0 }
            let days = CloudLogs.anonymize(String(decoding: data, as: UTF8.self))
            let f = DateFormatter()
            f.locale = Locale(identifier: "en_US_POSIX")
            f.dateFormat = "yyyy-MM-dd"
            let wanted = (0..<CloudLogs.days).compactMap { Calendar.current.date(byAdding: .day, value: -$0, to: today) }.map { f.string(from: $0) }
            let device = "\(CloudBackup.safeDevice(deviceName))-\(deviceId)"
            var count = 0
            for day in wanted.sorted() {
                guard let content = days[day] else { continue }
                let hash = CloudLogs.digest(content)
                if sent[day] == hash { continue }
                _ = try await client.rpc("log_send", ["p_device": device, "p_version": version, "p_day": day,
                                                      "p_content": content], token)
                sent[day] = hash
                count += 1
            }
            return count
        }
    }
}
