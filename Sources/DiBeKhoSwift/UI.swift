import AppKit
import DiBeKhoCore
import SwiftUI

/// What every screen shares, as ui/common.py of the Python app: the size of letters and buttons (120% by default),
/// the colours, the message boxes, the page title and hint.
enum UI {
    /// Cài đặt → cỡ chữ và nút (100–150%, the Python app's default 120%)
    static var scale: CGFloat = {
        let saved = UserDefaults.standard.double(forKey: "uiScale")
        if saved >= 1 && saved <= 1.5 { return CGFloat(saved) }
        return CGFloat(Workspace.uiScale() ?? 1.2)
    }()

    static var baseSize: CGFloat { 13 * scale }
    /// table rows as tall as the Python app's on a Mac (about 36 pt from row to row at 120%, 21/11/2026)
    static var rowHeight: CGFloat { ceil(baseSize * 2.15) }
    /// push buttons about 10% bigger than the macOS ones at the same letter size (the owner, 20/11/2026: users know
    /// the bigger buttons of the Python app); see AppButtonStyle
    static var buttonHeight: CGFloat { ceil(baseSize * 1.85) }
    static func font(bold: Bool = false) -> NSFont {
        bold ? .boldSystemFont(ofSize: baseSize) : .systemFont(ofSize: baseSize)
    }

    // ui/common._THEMES: light and dark, following the system appearance as the Python app does
    static func themed(_ light: Int, _ dark: Int) -> NSColor {
        NSColor(name: nil) { $0.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? NSColor(hex: dark) : NSColor(hex: light) }
    }
    static let red = themed(0xFDE2E1, 0x6E2A2A)
    static let yellow = themed(0xFFF4CC, 0x5E4C14)
    static let orange = themed(0xFFD9A8, 0x6E4210)
    static let banner = Color(nsColor: themed(0xEEF5FF, 0x1F3550))
    static let hint = Color(nsColor: themed(0x666666, 0xA0A0A0))
    static let warn = Color(nsColor: themed(0xB35900, 0xFFB066))

    // ---- message boxes (ui/common ask / info / error): the app's name as title, Có / Không

    @MainActor
    static func ask(_ text: String, title: String? = nil) -> Bool {
        let alert = NSAlert()
        alert.messageText = title ?? t("app.name")
        alert.informativeText = text
        alert.alertStyle = .informational
        alert.addButton(withTitle: t("btn.yes"))
        alert.addButton(withTitle: t("btn.no"))
        let answer = alert.runModal() == .alertFirstButtonReturn
        ActivityLog.write("ask", "\(text) → \(answer ? "yes" : "no")")
        return answer
    }

    @MainActor
    static func info(_ text: String) {
        ActivityLog.write("info", text)
        let alert = NSAlert()
        alert.messageText = t("app.name")
        alert.informativeText = text
        alert.addButton(withTitle: t("btn.ok"))
        alert.runModal()
    }

    @MainActor
    static func error(_ text: String) {
        ActivityLog.write("error", text)
        let alert = NSAlert()
        alert.messageText = t("app.name")
        alert.informativeText = text
        alert.alertStyle = .warning
        alert.addButton(withTitle: t("btn.ok"))
        alert.runModal()
    }

    static func message(_ error: Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? "\(error)"
    }

    static func locationName(_ id: Int64?) -> String {
        t(id == Ledger.office ? "loc.office" : "loc.main")
    }

    static func open(_ url: URL) { NSWorkspace.shared.open(url) }
}

extension NSColor {
    convenience init(hex: Int) {
        self.init(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                  blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
    }
}

/// The page title (bigger, bold) and its grey hint, at the top of every page.
struct PageHeader: View {
    let title: String
    var hint: String = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.system(size: UI.baseSize + 5, weight: .bold))
            if !hint.isEmpty {
                Text(hint).foregroundColor(UI.hint).fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

/// A grey hint line.
struct Hint: View {
    let text: String
    init(_ text: String) { self.text = text }
    var body: some View { Text(text).foregroundColor(UI.hint).fixedSize(horizontal: false, vertical: true) }
}

/// A text box with the round ✕ that empties it while something is typed (QLineEdit.setClearButtonEnabled).
struct ClearableField: View {
    let placeholder: String
    @Binding var text: String
    var size: CGFloat = 0

    var body: some View {
        TextField(placeholder, text: $text)
            .textFieldStyle(.roundedBorder)
            .font(.system(size: size > 0 ? size : UI.baseSize))
            .overlay(alignment: .trailing) {
                if !text.isEmpty {
                    Button { text = "" } label: {
                        Image(systemName: "xmark.circle.fill").foregroundColor(.secondary)
                    }
                    .buttonStyle(.plain)
                    .padding(.trailing, 6)
                    .help(tr("Xoá chữ đã gõ", "Clear", "清除"))
                }
            }
    }
}

/// The header row of a hand-made table (rows with pickers or tick boxes): bold, centred, on the header colour of
/// the Qt tables. width nil = takes the room left.
struct TableHeader: View {
    let cells: [(String, CGFloat?)]
    var spacing: CGFloat = 8

    var body: some View {
        HStack(spacing: spacing) {
            ForEach(Array(cells.enumerated()), id: \.offset) { _, cell in
                if let width = cell.1 {
                    Text(cell.0).bold().lineLimit(1).frame(width: width, alignment: .center)
                } else {
                    Text(cell.0).bold().lineLimit(1).frame(maxWidth: .infinity, alignment: .center)
                }
            }
        }
        .padding(.vertical, 5)
        .background(Color(nsColor: UI.themed(0xEFEFEF, 0x2E2E2E)))
    }
}

extension View {
    /// The white, framed area of a Qt table around a hand-made one
    func tableBox() -> some View {
        self.background(Color(nsColor: .textBackgroundColor))
            .clipShape(SoftRect())
            .overlay(SoftRect().stroke(Color.primary.opacity(0.2)))
    }
}

/// The corner of a big area (tables, frames, the page list, the chart): 10% of its shorter side, at most 12 pt (the
/// owner, 21/11/2026: rounded areas are easier on the eye). Buttons keep their own corners.
struct SoftRect: InsettableShape {
    var inset: CGFloat = 0
    func path(in rect: CGRect) -> Path {
        let area = rect.insetBy(dx: inset, dy: inset)
        return RoundedRectangle(cornerRadius: UI.softRadius(area.size)).path(in: area)
    }
    func inset(by amount: CGFloat) -> SoftRect {
        var shape = self
        shape.inset += amount
        return shape
    }
}

extension UI {
    static func softRadius(_ size: CGSize) -> CGFloat { min(12, max(0, min(size.width, size.height)) * 0.1) }
}

/// Every GroupBox of the app (set with AppButtonStyle): its title, then its contents on a light frame with SoftRect
/// corners, as the macOS group box but rounder.
struct SoftGroupBoxStyle: GroupBoxStyle {
    func makeBody(configuration: Configuration) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            configuration.label
            configuration.content
                .padding(8)
                .frame(maxWidth: .infinity, alignment: .topLeading)
                .background(SoftRect().fill(Color.primary.opacity(0.04)))
                .overlay(SoftRect().stroke(Color.primary.opacity(0.14)))
        }
    }
}

/// The scroll view of a DataTable: its corners rounded as SoftRect, with a thin frame (an AppKit view: a layer, not
/// a SwiftUI shape, so the radius is set again whenever its size changes).
final class SoftScrollView: NSScrollView {
    override func layout() {
        super.layout()
        wantsLayer = true
        layer?.cornerRadius = UI.softRadius(bounds.size)
        layer?.masksToBounds = true
        layer?.borderWidth = 1
        effectiveAppearance.performAsCurrentDrawingAppearance {
            self.layer?.borderColor = UI.themed(0xC8C8C8, 0x4A4A4A).cgColor
        }
    }

    override func viewDidChangeEffectiveAppearance() {
        super.viewDidChangeEffectiveAppearance()
        needsLayout = true  // the frame colour follows light / dark mode
    }
}

/// The tabs of Cài đặt (QTabWidget): a row of joined choices, the chosen one in the accent colour. About 10% bigger
/// than the push buttons (the owner, 21/11/2026: the macOS segmented control looked too small).
struct TabBar: View {
    let titles: [String]
    @Binding var selection: Int

    var body: some View {
        HStack(spacing: 0) {
            ForEach(titles.indices, id: \.self) { i in
                if i > 0 && selection != i && selection != i - 1 {
                    Rectangle().fill(Color.primary.opacity(0.2)).frame(width: 1, height: UI.buttonHeight * 0.6)
                }
                Button { selection = i } label: {
                    Text(titles[i])
                        .font(.system(size: ceil(UI.baseSize * 1.1), weight: selection == i ? .semibold : .regular))
                        .lineLimit(1)
                        .padding(.horizontal, ceil(16 * UI.scale))
                        .frame(height: ceil(UI.buttonHeight * 1.1))
                        .foregroundColor(selection == i ? .white : .primary)
                        .background(RoundedRectangle(cornerRadius: 6)
                            .fill(selection == i ? Color.accentColor : Color.clear))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(2)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlColor)))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color(nsColor: UI.themed(0xBDBDBD, 0x5C5C5C)), lineWidth: 1))
        .fixedSize()
    }
}

/// Kho tổng / Văn phòng.
struct LocationPicker: View {
    @Binding var selection: Int64
    /// the whole width of a form row (Nhập vào in Nhập hàng về, as the Qt combo box)
    var wide = false
    var body: some View {
        Picker("", selection: $selection) {
            ForEach(Ledger.locations, id: \.self) { Text(UI.locationName($0)).tag($0) }
        }
        .labelsHidden()
        .frame(minWidth: 200 * UI.scale, maxWidth: wide ? .infinity : 200 * UI.scale)
    }
}

/// A date box shown dd/MM/yyyy (the calendar of the system), bound to the ISO text the database keeps.
struct DateBox: View {
    @Binding var iso: String
    var body: some View {
        DatePicker("", selection: Binding(
            get: { Dates.parse(iso) ?? Date() },
            set: { iso = Dates.iso($0) }), displayedComponents: .date)
            .labelsHidden()
            .datePickerStyle(.field)
            .environment(\.locale, Locale(identifier: "vi_VN"))
            .frame(width: 140 * UI.scale)
    }
}

/// 2026-11-17 -> 17/11/2026.
func dmy(_ iso: String) -> String { Format.date(iso) }

/// Every push button of the app (set once on the main window and on each window of Windows.show): the same place,
/// text and action as before, only bigger (UI.buttonHeight) with a frame like the macOS button. Buttons that set
/// their own style (.plain: the page list, the radio choices) keep it; menus and message boxes stay macOS ones.
struct AppButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    private static let fill = Color(nsColor: .controlColor)
    private static let pressed = Color(nsColor: UI.themed(0xDCDCDC, 0x505050))
    private static let border = Color(nsColor: UI.themed(0xBDBDBD, 0x5C5C5C))

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .lineLimit(1)
            .padding(.horizontal, ceil(11 * UI.scale))
            .frame(minHeight: UI.buttonHeight)
            .background(RoundedRectangle(cornerRadius: 6).fill(configuration.isPressed ? Self.pressed : Self.fill))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Self.border, lineWidth: 1))
            .shadow(color: Color.black.opacity(0.10), radius: 0.5, x: 0, y: 0.5)
            .foregroundColor(.primary)
            .opacity(enabled ? 1 : 0.45)
            .contentShape(Rectangle())
    }
}


/// A button that pops up a menu of the Mac's own (NSMenu). SwiftUI's Menu never ran the item picked inside a dialog
/// (Windows.show with modal: true runs NSApp.runModal, as QDialog.exec): picking «Chọn mặt hàng có sẵn…» or an old
/// customer did nothing (user, 21–22/11/2026). An NSMenu item runs at once, inside the modal session too.
struct PopMenuButton<Label: View>: View {
    let items: () -> [PopMenu.Item]
    @ViewBuilder let label: () -> Label

    var body: some View {
        Button(action: { PopMenu.show(items()) }, label: label)
    }
}

@MainActor
enum PopMenu {
    struct Item {
        let title: String
        let run: () -> Void
        init(_ title: String, _ run: @escaping () -> Void) {
            self.title = title
            self.run = run
        }
    }

    private final class Target: NSObject {
        let run: () -> Void
        init(_ run: @escaping () -> Void) { self.run = run }
        @objc func fire() { run() }
    }

    /// the menu opens where the mouse was pressed; returns once an item ran or the menu was dismissed
    static func show(_ items: [Item]) {
        guard !items.isEmpty, let window = NSApp.keyWindow, let view = window.contentView else { return }
        let menu = NSMenu()
        menu.autoenablesItems = false
        let targets = items.map { Target($0.run) }
        for (item, target) in zip(items, targets) {
            let entry = NSMenuItem(title: item.title, action: #selector(Target.fire), keyEquivalent: "")
            entry.target = target
            menu.addItem(entry)
        }
        let inWindow = NSApp.currentEvent?.locationInWindow ?? window.mouseLocationOutsideOfEventStream
        menu.popUp(positioning: nil, at: view.convert(inWindow, from: nil), in: view)
        withExtendedLifetime(targets) {}
    }
}
