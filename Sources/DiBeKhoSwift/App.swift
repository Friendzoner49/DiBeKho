import AppKit
import SwiftUI

@main
struct DiBeKhoSwiftApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    var body: some Scene {
        WindowGroup("DiBeKho") {
            ContentView()
        }
    }
}

/// Quitting sends what the Cloud does not have yet (main_window.closeEvent; user, 27/11/2026): the changes still
/// queued and the original files of the orders made here.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    /// s: the app quits after this long whatever the line does; the rest goes at the next opening
    private static let quitCap: TimeInterval = 15
    private var flushing = false
    private var replied = false

    /// The red ✕ quits, as in the Python app: left running without a window, nothing would be sent "on quit".
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if flushing { return .terminateLater }
        UI.endTyping()  // a note still in its cell is saved, and sent with the rest
        guard let cloud = AppModel.running?.cloud, cloud.flushNeeded else { return .terminateNow }
        flushing = true
        let cap = Timer(timeInterval: Self.quitCap, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated { self?.finish() }
        }
        RunLoop.main.add(cap, forMode: .common)
        RunLoop.main.add(cap, forMode: .modalPanel)
        Task { @MainActor in
            await cloud.flushBeforeQuit()
            self.finish()
        }
        return .terminateLater
    }

    private func finish() {
        guard !replied else { return }
        replied = true
        NSApp.reply(toApplicationShouldTerminate: true)
    }
}
