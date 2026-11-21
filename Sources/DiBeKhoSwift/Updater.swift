import AppKit
import DiBeKhoCore
import SwiftUI

/// Asking about a newer version and fetching it (Python ui/updater.py). On by default: looked for a few seconds after the
/// app opens, silently when nothing is found or the check fails; "Kiểm tra bản mới ngay" says what happened. The new
/// .dmg is downloaded and opened; the user drags DiBeKho onto Applications (the same steps as the Python app on a Mac).
/// ⚠ Not compiled, not tried against a real release.
@MainActor
enum Updater {
    static let key = "checkUpdates"
    static var auto: Bool {
        get { UserDefaults.standard.object(forKey: key) as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: key) }
    }

    /// An app started straight from the opened .dmg (/Volumes/...) cannot replace itself there.
    static var runsFromDiskImage: Bool { Bundle.main.bundlePath.hasPrefix("/Volumes/") }

    /// Only an installed copy (a .app) updates itself, not `swift run` or Xcode.
    static var canInstall: Bool { Bundle.main.bundleURL.pathExtension == "app" }

    /// Called once the main window shows.
    static func checkOnStart() {
        guard auto, canInstall else { return }
        Task {
            try? await Task.sleep(nanoseconds: 8_000_000_000)
            await check(explicit: false)
        }
    }

    static func check(explicit: Bool) async {
        guard canInstall else {
            if explicit { UI.info(t("update.source_only")) }
            return
        }
        let current = GeneralSettings.version()
        do {
            guard let release = try await Update.latest(local: current) else {
                if explicit { UI.info(t("update.newest", ["version": current])) }
                return
            }
            ActivityLog.write("update", "offered \(release.version)")
            offer(release, current: current)
        } catch {
            ActivityLog.write("update", "check failed: \(error)")
            if explicit { UI.error(t("update.check_failed")) }
        }
    }

    private static func offer(_ release: Update.Release, current: String) {
        let text = t("update.ask", ["new": release.version, "current": current])
        if runsFromDiskImage {
            return UI.info(text.components(separatedBy: "\n\n")[0] + "\n\n" + t("update.mac_from_dmg"))
        }
        guard UI.ask(text, title: t("update.title")) else { return }
        Task { await install(release) }
    }

    private static func install(_ release: Update.Release) async {
        let progress = UpdateProgress(version: release.version)
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 420, height: 90), styleMask: [.titled], backing: .buffered, defer: false)
        window.title = t("update.title")
        window.contentView = NSHostingView(rootView: UpdateProgressView(progress: progress))
        window.center()
        window.makeKeyAndOrderFront(nil)
        defer { window.close() }
        do {
            let file = try await Update.download(release) { done, total in
                Task { @MainActor in progress.set(done, total) }
            }
            ActivityLog.write("update", "downloaded \(release.version)")
            window.close()
            guard NSWorkspace.shared.open(file) else {
                ActivityLog.write("update", "install failed: could not open \(file.lastPathComponent)")
                UI.error(t("update.install_failed"))
                return
            }
            UI.info(t("update.mac_steps"))
            NSApp.terminate(nil)
        } catch is CancellationError {
            return
        } catch {
            ActivityLog.write("update", "download failed: \(error)")
            window.close()
            UI.error(t("update.download_failed"))
        }
    }
}

@MainActor
final class UpdateProgress: ObservableObject {
    @Published var text: String
    @Published var fraction = 0.0
    let version: String

    init(version: String) {
        self.version = version
        text = t("update.downloading", ["version": version])
    }

    func set(_ done: Int, _ total: Int) {
        fraction = Double(done) / Double(max(total, 1))
        text = t("update.downloading_mb", ["version": version, "done": String(format: "%.1f", Double(done) / 1e6),
                                           "total": String(format: "%.1f", Double(total) / 1e6)])
    }
}

private struct UpdateProgressView: View {
    @ObservedObject var progress: UpdateProgress

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(progress.text)
            ProgressView(value: progress.fraction)
        }
        .padding(16)
    }
}
