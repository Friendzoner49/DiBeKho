import AppKit
import DiBeKhoCore
import SwiftUI

/// Cài đặt → Chung (ui/settings_page.py): language, size of letters and buttons, device, version (3 clicks show the
/// log), licenses, and removing the app. The Python app keeps these in config.json; the Swift app never writes that
/// file, so its choices live in the app's own preferences (UserDefaults). A language or size change applies after the
/// app is opened again, as in the Python app.
enum GeneralSettings {
    static let languageKey = "language"
    static let scaleKey = "uiScale"
    static let languageNames = ["vi": "Tiếng Việt", "en": "English", "zh": "中文"]
    static let scales = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5]

    static func savedLanguage(_ defaults: UserDefaults = .standard) -> String {
        let saved = defaults.string(forKey: languageKey) ?? "vi"
        return L10n.languages.contains(saved) ? saved : "vi"
    }

    static func version() -> String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
    }

    /// The app bundle to remove (nil when the app runs from `swift run` or Xcode, not from a .app)
    static func bundleToRemove() -> URL? {
        let url = Bundle.main.bundleURL
        return url.pathExtension == "app" ? url : nil
    }

    /// Gỡ app: confirm, forget the preferences, optionally the practice copy, move the app to the Trash. The shop's
    /// real data folder is never touched.
    @MainActor
    static func uninstall() {
        guard UI.ask(t("settings.confirm_uninstall")) else { return }
        if Practice.exists, UI.ask(t("settings.confirm_delete_data", ["path": Practice.folder.path])) {
            try? FileManager.default.removeItem(at: Practice.folder)
        }
        if let id = Bundle.main.bundleIdentifier { UserDefaults.standard.removePersistentDomain(forName: id) }
        guard let bundle = bundleToRemove() else {
            return UI.info(t("settings.uninstall_done_mac"))
        }
        NSWorkspace.shared.recycle([bundle]) { _, error in
            let moved = error == nil
            DispatchQueue.main.async {
                MainActor.assumeIsolated {
                    if moved {
                        UI.info(t("settings.uninstall_done_mac_auto", ["path": bundle.path]))
                        NSApp.terminate(nil)
                    } else {
                        UI.info(t("settings.uninstall_done_mac"))
                    }
                }
            }
        }
    }
}

/// "Chung": the box of Settings.
struct GeneralBox: View {
    @ObservedObject var model: AppModel
    @State private var language = GeneralSettings.savedLanguage()
    @State private var scale: Double
    @State private var showLog = false
    @State private var autoUpdate = Updater.auto

    init(model: AppModel) {
        self.model = model
        // the nearest size on offer, so the picker always shows one (a size from the Python config may be 1.25)
        let current = Double(UI.scale)
        _scale = State(initialValue: GeneralSettings.scales.min { abs($0 - current) < abs($1 - current) } ?? 1.2)
    }

    var body: some View {
        GroupBox(t("settings.general")) {
            VStack(alignment: .leading, spacing: 8) {
                row(t("settings.language")) {
                    Picker("", selection: $language) {
                        ForEach(L10n.languages, id: \.self) { Text(GeneralSettings.languageNames[$0] ?? $0).tag($0) }
                    }
                    .labelsHidden()
                    .frame(maxWidth: .infinity)
                    .onChange(of: language) { value in
                        UserDefaults.standard.set(value, forKey: GeneralSettings.languageKey)
                        ActivityLog.write("setting", "language \(value)")
                        UI.info(t("settings.restart_needed"))
                    }
                }
                row(t("settings.ui_scale")) {
                    Picker("", selection: $scale) {
                        ForEach(GeneralSettings.scales, id: \.self) { Text("\(Int(($0 * 100).rounded()))%").tag($0) }
                    }
                    .labelsHidden()
                    .frame(maxWidth: .infinity)
                    .onChange(of: scale) { value in
                        UserDefaults.standard.set(value, forKey: GeneralSettings.scaleKey)
                        ActivityLog.write("setting", "ui_scale \(value)")
                        UI.info(t("settings.restart_needed"))
                    }
                }
                row(t("update.row")) {
                    Toggle(t("update.auto"), isOn: Binding(get: { autoUpdate }, set: { autoUpdate = $0; Updater.auto = $0 }))
                    Button(t("update.check_now")) { Task { await Updater.check(explicit: true) } }
                }
                row(t("settings.workspace")) {
                    if let folder = model.folders?.root {
                        Text(folder.path).foregroundColor(.secondary).lineLimit(1).truncationMode(.middle)
                        Spacer()
                        Button(t("settings.open_folder")) { UI.open(folder) }
                    }
                    Button(t("settings.change_folder")) { changeFolder() }.disabled(!model.live)
                }
                row(t("settings.device")) { Text(Workspace.device().name) }
                row(t("settings.version")) {
                    // three clicks in a row show the log button, as in the Python app
                    Text(GeneralSettings.version()).onTapGesture(count: 3) { showLog = true }
                    if showLog { Button(t("log.button")) { LogScreen.open(model) } }
                    Button(t("license.button")) { LicenseScreen.open() }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(6)
        }
    }

    private func row<Content: View>(_ label: String, @ViewBuilder _ content: () -> Content) -> some View {
        HStack(spacing: 10) {
            Text(label + ":").frame(width: 170 * UI.scale, alignment: .leading)
            content()
            Spacer()
        }
    }
}

extension GeneralBox {
    /// settings_page.change_folder: config.json points at the chosen folder from the next start
    @MainActor fileprivate func changeFolder() {
        let panel = NSOpenPanel()
        panel.title = t("settings.change_folder")
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        panel.directoryURL = model.folders?.root.deletingLastPathComponent()
        guard panel.runModal() == .OK, let url = panel.url,
              UI.ask(t("settings.confirm_folder", ["path": url.path])) else { return }
        do {
            try FirstRun.changeWorkspace(to: url)
            ActivityLog.write("setting", "workspace " + url.path)
            UI.info(t("settings.restart_needed"))
        } catch {
            UI.error(UI.message(error))
        }
    }
}

/// «Đặt lại dữ liệu» (settings_page.py, tab Chung). ⚠ Swift: only on the practice copy for now.
struct ResetBox: View {
    @ObservedObject var model: AppModel

    var body: some View {
        GroupBox(t("reset.title")) {
            VStack(alignment: .leading, spacing: 8) {
                Hint(t("reset.hint"))
                HStack {
                    Button(t("reset.stock")) { ResetScreens.resetStock(model) }.disabled(!model.practice)
                    Button(t("reset.all")) { ResetScreens.resetAll(model) }.disabled(!model.practice)
                    Spacer()
                }
                if !model.practice {
                    Hint(tr("Bản Swift đang thử nên hai nút này chỉ dùng được trên bản thử.", "This Swift build is still being tried: these two buttons work on the practice copy only.", "Swift 版仍在试用中：这两个按钮只能在试用版上使用。"))
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(6)
        }
    }
}

/// "Gỡ app khỏi máy này"
struct UninstallBox: View {
    var body: some View {
        GroupBox(t("settings.uninstall_title")) {
            VStack(alignment: .leading, spacing: 8) {
                Hint(t("settings.uninstall_hint"))
                HStack {
                    Button(t("settings.uninstall")) { GeneralSettings.uninstall() }
                    Spacer()
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(6)
        }
    }
}

// MARK: log window (ui/log_dialog.py)

@MainActor
enum LogScreen {
    static func open(_ model: AppModel) {
        let dataFolder = model.workFolder?.root.appendingPathComponent("data")
            ?? (model.practice ? Practice.folder.appendingPathComponent("data") : nil)
        Windows.show(t("log.title"), width: 1000, height: 640, modal: false) { _ in
            LogView(model: model, dataFolder: dataFolder)
        }
    }
}

private struct LogView: View {
    let model: AppModel
    let dataFolder: URL?
    @EnvironmentObject var box: WindowBox
    @State private var others: [URL] = []
    @State private var chosen: URL?  // nil = this machine's own log
    @State private var text = ""

    private var current: URL? { chosen ?? ActivityLog.file }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(t("log.which"))
                Picker("", selection: $chosen) {
                    Text(t("log.this_device", ["name": Workspace.device().name])).tag(URL?.none)
                    ForEach(others, id: \.self) { url in
                        Text(t("log.other_device", ["name": String(url.deletingPathExtension().lastPathComponent.dropFirst("nhat-ky-".count))]))
                            .tag(URL?.some(url))
                    }
                }
                .labelsHidden()
                .onChange(of: chosen) { _ in show() }
                Spacer()
            }
            Hint(t("log.hint", ["path": current?.path ?? "", "size": String(ActivityLog.maxBytes / 1000)]))
            LogText(text: text, atEnd: true, wrap: false)
            HStack {
                Button(t("log.refresh")) { refresh() }
                Button(t("log.copy")) { copy() }
                Button(t("log.save")) { save() }
                Button(t("log.open_folder")) { if let folder = ActivityLog.file?.deletingLastPathComponent() { UI.open(folder) } }
                Button(t("log.clear")) { clear() }
                Spacer()
                Button(t("btn.close")) { box.close() }
            }
        }
        .onAppear { refresh() }
    }

    private func refresh() {
        others = dataFolder.map { ActivityLog.otherDevices(dataFolder: $0) } ?? []
        if let chosen, !others.contains(chosen) { self.chosen = nil }
        show()
    }

    private func show() {
        let body = ActivityLog.read(current)
        text = body.isEmpty ? t("log.empty") : body
    }

    private func copy() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        UI.info(t("log.copied"))
    }

    /// A copy in output/, to send to whoever looks after the app
    private func save() {
        guard let source = current, FileManager.default.fileExists(atPath: source.path), let output = model.folders?.output else {
            return UI.info(t("log.empty"))
        }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd_HHmm"
        let dest = output.appendingPathComponent("NhatKy_\(f.string(from: Date())).log")
        do {
            try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
            try? FileManager.default.removeItem(at: dest)
            try FileManager.default.copyItem(at: source, to: dest)
        } catch {
            return UI.error(UI.message(error))
        }
        if UI.ask(t("log.saved", ["path": dest.path])) { UI.open(output) }
    }

    private func clear() {
        guard UI.ask(t("log.confirm_clear")) else { return }
        if chosen == nil {
            ActivityLog.clear()
            ActivityLog.write("log", "cleared")
        } else if let url = chosen {
            try? Data().write(to: url)
        }
        refresh()
    }
}

/// Read-only monospaced text that starts at its end (the newest lines).
private struct LogText: NSViewRepresentable {
    let text: String
    var atEnd = true
    var wrap = false

    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSTextView.scrollableTextView()
        if let view = scroll.documentView as? NSTextView {
            view.isEditable = false
            view.isSelectable = true
            view.font = .monospacedSystemFont(ofSize: UI.baseSize - 1, weight: .regular)
            if !wrap {
                view.textContainer?.widthTracksTextView = false
                view.textContainer?.containerSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
                view.isHorizontallyResizable = true
            }
        }
        scroll.hasHorizontalScroller = !wrap
        return scroll
    }

    func updateNSView(_ scroll: NSScrollView, context: Context) {
        guard let view = scroll.documentView as? NSTextView, view.string != text else { return }
        view.string = text
        if atEnd { view.scrollToEndOfDocument(nil) } else { view.scrollToBeginningOfDocument(nil) }
    }
}

// MARK: licenses (ui/license_dialog)

@MainActor
enum LicenseScreen {
    static func open() {
        Windows.show(t("license.title"), width: 900, height: 680, modal: false) { _ in LicenseView() }
    }

    /// The software the Swift app is built from (the Python app's list is another one: Python, Qt, openpyxl…)
    static let notice = """
    DiBeKho Swift — licenses
    ========================

    DiBeKho is open-source software under the MIT License. The Swift version for the Mac also contains the software \
    below, each under its own license (all MIT):

    - GRDB.swift (SQLite access) — Copyright (c) Gwendal Roué. https://github.com/groue/GRDB.swift
    - ZIPFoundation (.dibekho packages are zip files) — Copyright (c) Thomas Zoechling. https://github.com/weichsel/ZIPFoundation
    - SQLite itself is in the public domain (it comes with macOS).

    MIT License

    Copyright (c) 2026 Friendzoner49

    Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated \
    documentation files (the "Software"), to deal in the Software without restriction, including without limitation \
    the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and \
    to permit persons to whom the Software is furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all copies or substantial portions of \
    the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO \
    THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE \
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF \
    CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS \
    IN THE SOFTWARE.
    """
}

private struct LicenseView: View {
    @EnvironmentObject var box: WindowBox

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            // license_dialog.py's hint line; the Python one names Qt, which this app does not contain
            Hint(tr("DiBeKho là phần mềm mã nguồn mở theo giấy phép MIT. App có dùng các phần mềm dưới đây, mỗi phần mềm theo giấy phép riêng.",
                    "DiBeKho is open-source software under the MIT License. The app uses the software below, each under its own license.",
                    "DiBeKho 是采用 MIT 许可证的开源软件。本应用使用了下列软件，各自遵循其许可证。"))
            LogText(text: LicenseScreen.notice, atEnd: false, wrap: true)
            HStack {
                Spacer()
                Button(t("btn.close")) { box.close() }
            }
        }
    }
}
