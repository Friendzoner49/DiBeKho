import AppKit
import DiBeKhoCore
import SwiftUI

/// The box of the first start (app.py FirstRunDialog): the language and the work folder. Shown only on a Mac that has
/// no config.json; creates the folder, an empty database and config.json, then the login follows. Thoát quits.
struct FirstRunSheet: View {
    @ObservedObject var model: AppModel
    @State private var language = GeneralSettings.savedLanguage()
    @State private var folder = FirstRun.defaultFolder

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(t("firstrun.welcome")).fixedSize(horizontal: false, vertical: true)
            HStack {
                Text(t("settings.language"))
                Picker("", selection: $language) {
                    ForEach(L10n.languages, id: \.self) { Text(GeneralSettings.languageNames[$0] ?? $0).tag($0) }
                }
                .labelsHidden()
                .frame(width: 180)
                .onChange(of: language) { L10n.language = $0 }
            }
            HStack {
                Text(folder.path).lineLimit(1).truncationMode(.middle)
                    .padding(6).frame(maxWidth: .infinity, alignment: .leading)
                    .overlay(RoundedRectangle(cornerRadius: 5).stroke(Color.primary.opacity(0.25)))
                Button(t("firstrun.browse")) { choose() }
            }
            Text(t("firstrun.folder_hint")).font(.caption).foregroundColor(.secondary)
            HStack {
                Spacer()
                Button(t("app.quit")) { UI.quit() }
                Button(t("firstrun.start")) { start() }.keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 560)
    }

    private func choose() {
        let panel = NSOpenPanel()
        panel.title = t("firstrun.browse")
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        panel.directoryURL = folder.deletingLastPathComponent()
        if panel.runModal() == .OK, let url = panel.url { folder = url }
    }

    private func start() {
        if let service = FirstRun.syncService(folder),
           !UI.ask(tr("Thư mục này nằm trong \(service). Đồng bộ đám mây có thể làm hỏng database đang mở.\n\nVẫn tạo thư mục làm việc ở đây?", "This folder is inside \(service). Cloud syncing can damage a database that is open.\n\nCreate the work folder here anyway?", "这个文件夹位于 \(service) 内。云同步可能损坏正在打开的数据库。\n\n仍要在这里创建工作文件夹吗？")) { return }
        do {
            try FirstRun.create(folder: folder, language: language)
            UserDefaults.standard.set(language, forKey: GeneralSettings.languageKey)
            L10n.language = language
            model.openAtStart()
        } catch {
            UI.error(UI.message(error))
        }
    }
}
