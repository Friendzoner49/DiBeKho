import AppKit
import SwiftUI

/// The windows of the app besides the main one: the Python app's dialogs (modal: the rest of the app waits, as
/// QDialog.exec) and its page windows (Đơn hàng, Khách hàng, Thống kê, Phiếu chuyển hàng… open beside the main one).
@MainActor
final class WindowBox: ObservableObject {
    weak var window: NSWindow?
    var modal = false
    var accepted = false
    /// set by the window's content: asked when the user closes the window (false = it stays open)
    var shouldClose: (() -> Bool)?

    func close(accepted: Bool = false) {
        self.accepted = accepted
        guard let window else { return }
        window.close()
        // a modal window must also end its modal session, or the close can leave the app waiting on it
        if modal && NSApp.modalWindow === window { NSApp.stopModal() }
    }
}

@MainActor
enum Windows {
    private static var open: [ObjectIdentifier: (NSWindow, WindowDelegate)] = [:]

    @MainActor
    final class WindowDelegate: NSObject, NSWindowDelegate {
        let box: WindowBox
        /// asked before the window closes with its close button (false = stays open)
        var shouldClose: (() -> Bool)?
        init(box: WindowBox) { self.box = box }

        func windowShouldClose(_ sender: NSWindow) -> Bool { (box.shouldClose ?? shouldClose)?() ?? true }

        func windowWillClose(_ notification: Notification) {
            guard let window = notification.object as? NSWindow else { return }
            if box.modal { NSApp.stopModal() }
            Windows.open[ObjectIdentifier(window)] = nil
        }
    }

    @discardableResult
    static func show<V: View>(_ title: String, width: CGFloat, height: CGFloat, modal: Bool,
                              shouldClose: (() -> Bool)? = nil, content: (WindowBox) -> V) -> Bool {
        let box = WindowBox()
        box.modal = modal
        let host = NSHostingController(rootView: content(box).environmentObject(box)
            .font(.system(size: UI.baseSize)).buttonStyle(AppButtonStyle()).padding(14))
        host.sizingOptions = []  // the window keeps the size given here, not the content's ideal size
        let window = NSWindow(contentViewController: host)
        window.title = title
        window.styleMask = [.titled, .closable, .resizable, .miniaturizable]
        // ui/common.fit_window: the size asked, never bigger than the screen
        let screen = (NSApp.keyWindow?.screen ?? NSScreen.main)?.visibleFrame.size ?? NSSize(width: 1440, height: 900)
        window.setContentSize(NSSize(width: min(width * UI.scale, screen.width * 0.95),
                                     height: min(height * UI.scale, screen.height * 0.92)))
        window.isReleasedWhenClosed = false
        let delegate = WindowDelegate(box: box)
        delegate.shouldClose = shouldClose
        window.delegate = delegate
        box.window = window
        open[ObjectIdentifier(window)] = (window, delegate)
        window.center()
        if modal {
            NSApp.runModal(for: window)
            return box.accepted
        }
        window.makeKeyAndOrderFront(nil)
        return false
    }
}
