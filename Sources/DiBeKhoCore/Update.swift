import CryptoKit
import Foundation

/// Looking for a newer version and fetching it (Python core/update.py). The app asks GitHub's releases API (no account,
/// a generic User-Agent). A release is offered only when its tag is newer than this build AND the file for this Mac is
/// already attached. The download resumes with HTTP Range and is used only when its size (and sha256, when GitHub gives
/// one) is the announced one. Since 21/11/2026 the Swift app's file DiBeKho-Swift-mac-arm64.dmg is attached to the public
/// release of the Python app (same tag, same version), built from the branch Mac_swift (DIBEKHO_UPDATE_URL replaces the
/// address).
public enum Update {
    public static let releasesURL = "https://api.github.com/repos/Friendzoner49/DiBeKho/releases/latest"
    public static let assetName = "DiBeKho-Swift-mac-arm64.dmg"
    public static let userAgent = "DiBeKho-app"

    public struct Release: Equatable {
        public var version: String
        public var asset: String
        public var url: String
        public var size: Int
        public var sha256: String
        public var notes: String
    }

    /// 'v0.5.7' / '0.5.7' -> [0, 5, 7]; anything else -> nil
    public static func parseVersion(_ text: String) -> [Int]? {
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        guard trimmed.range(of: #"^v?\d+(\.\d+){0,3}$"#, options: .regularExpression) != nil else { return nil }
        let digits = trimmed.hasPrefix("v") ? String(trimmed.dropFirst()) : trimmed
        return digits.split(separator: ".").compactMap { Int($0) }
    }

    public static func isNewer(_ remote: String, than local: String) -> Bool {
        guard var r = parseVersion(remote), var l = parseVersion(local) else { return false }
        let width = max(r.count, l.count)
        r += Array(repeating: 0, count: width - r.count)
        l += Array(repeating: 0, count: width - l.count)
        return r.lexicographicallyPrecedes(l) == false && r != l
    }

    /// The release to offer from GitHub's answer, or nil (not newer, a draft or pre-release, no file for this Mac yet).
    public static func pick(_ json: Any, local: String) -> Release? {
        guard let object = json as? [String: Any], object["draft"] as? Bool != true, object["prerelease"] as? Bool != true else { return nil }
        let tag = object["tag_name"] as? String ?? ""
        guard isNewer(tag, than: local) else { return nil }
        for asset in (object["assets"] as? [[String: Any]]) ?? [] {
            guard asset["name"] as? String == assetName, (asset["state"] as? String ?? "uploaded") == "uploaded",
                  let size = (asset["size"] as? NSNumber)?.intValue, size > 0 else { continue }
            let digest = asset["digest"] as? String ?? ""
            return Release(version: tag.trimmingCharacters(in: CharacterSet(charactersIn: "vV")), asset: assetName,
                           url: asset["browser_download_url"] as? String ?? "", size: size,
                           sha256: digest.lowercased().hasPrefix("sha256:") ? String(digest.dropFirst(7)).lowercased() : "",
                           notes: object["body"] as? String ?? "")
        }
        return nil
    }

    private static func address() -> URL? {
        URL(string: ProcessInfo.processInfo.environment["DIBEKHO_UPDATE_URL"] ?? releasesURL)
    }

    private static func request(_ url: URL, timeout: TimeInterval, range: Int = 0) -> URLRequest {
        var req = URLRequest(url: url, timeoutInterval: timeout)
        req.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        if range > 0 { req.setValue("bytes=\(range)-", forHTTPHeaderField: "Range") }
        return req
    }

    /// The newer release for this Mac, or nil. Throws when GitHub cannot be read.
    public static func latest(local: String, timeout: TimeInterval = 8) async throws -> Release? {
        guard let url = address() else { throw URLError(.badURL) }
        var req = request(url, timeout: timeout)
        req.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        let (data, response) = try await URLSession.shared.data(for: req)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
        return pick(try JSONSerialization.jsonObject(with: data), local: local)
    }

    public static var downloadFolder: URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("DiBeKho-update")
    }

    public static func digestOK(_ file: URL, _ rel: Release) -> Bool {
        guard !rel.sha256.isEmpty, let handle = try? FileHandle(forReadingFrom: file) else { return rel.sha256.isEmpty }
        defer { try? handle.close() }
        var hasher = SHA256()
        while let block = try? handle.read(upToCount: 1 << 20), !block.isEmpty { hasher.update(data: block) }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined() == rel.sha256
    }

    public struct DownloadError: Error { public var notTheAnnouncedFile = false }

    /// Fetch the release's file (resuming a part left by an earlier try). progress(done, total) is called as it goes.
    /// Returns the finished file; throws when it cannot be fetched whole or is not the announced file.
    public static func download(_ rel: Release, progress: @escaping @Sendable (Int, Int) -> Void = { _, _ in }) async throws -> URL {
        let folder = downloadFolder
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let final = folder.appendingPathComponent("\(rel.version)-\(rel.asset)")
        let part = final.appendingPathExtension("part")
        func size(_ url: URL) -> Int { ((try? FileManager.default.attributesOfItem(atPath: url.path))?[.size] as? NSNumber)?.intValue ?? 0 }
        if size(final) == rel.size, digestOK(final, rel) { return final }
        guard let url = URL(string: rel.url) else { throw URLError(.badURL) }
        var last: Error = URLError(.unknown)
        for attempt in 0..<6 {
            try Task.checkCancellation()
            var done = size(part)
            if done > rel.size { try? FileManager.default.removeItem(at: part); done = 0 }
            do {
                if done < rel.size {
                    let (bytes, response) = try await URLSession.shared.bytes(for: request(url, timeout: 30, range: done))
                    let status = (response as? HTTPURLResponse)?.statusCode ?? 0
                    if done > 0 && status != 206 { done = 0 }  // the server ignored Range: start over
                    if done == 0 { FileManager.default.createFile(atPath: part.path, contents: nil) }
                    let out = try FileHandle(forWritingTo: part)
                    defer { try? out.close() }
                    try out.seekToEnd()
                    var buffer = Data()
                    for try await byte in bytes {
                        buffer.append(byte)
                        if buffer.count >= 256 * 1024 {
                            try out.write(contentsOf: buffer)
                            done += buffer.count
                            buffer.removeAll(keepingCapacity: true)
                            progress(done, rel.size)
                            try Task.checkCancellation()
                        }
                    }
                    if !buffer.isEmpty { try out.write(contentsOf: buffer); done += buffer.count; progress(done, rel.size) }
                }
                guard size(part) == rel.size else { throw URLError(.networkConnectionLost) }
                guard digestOK(part, rel) else {
                    try? FileManager.default.removeItem(at: part)
                    throw DownloadError(notTheAnnouncedFile: true)
                }
                try? FileManager.default.removeItem(at: final)
                try FileManager.default.moveItem(at: part, to: final)
                return final
            } catch is CancellationError {
                throw CancellationError()
            } catch let error as DownloadError {
                throw error
            } catch {
                last = error
                if attempt < 5 { try await Task.sleep(nanoseconds: UInt64(2_000_000_000 * (attempt + 1))) }
            }
        }
        throw last
    }
}
