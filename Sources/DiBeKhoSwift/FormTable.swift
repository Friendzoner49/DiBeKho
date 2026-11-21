import AppKit
import DiBeKhoCore
import SwiftUI

/// The lines table of Phiếu xuất kho and Nhập hàng về as the Qt app draws it (QTableWidget): a white box with a
/// grey frame and grid lines, a centred header, numbered rows, ▲▼ on the number cells and a ✕ cell.
enum FormTable {
    // ui/issue_form.py, receipt_form.py: rows 40 px, column widths in px as there
    static var rowHeight: CGFloat { 40 }
    static var headerHeight: CGFloat { ceil(UI.baseSize * 3.2) }
    static var numberWidth: CGFloat { ceil(22 * UI.scale) }
    static let line = Color(nsColor: UI.themed(0xD0D0D0, 0x4A4A4A))
    static let paper = Color(nsColor: .textBackgroundColor)
    /// header, row numbers and the cells nobody types in
    static let grey = Color(nsColor: UI.themed(0xF0F0F0, 0x2E2E2E))
}

/// The framed, scrolling box around the grid; the grid gets the whole width (at least `minWidth`).
struct FormTableBox<Content: View>: View {
    let minWidth: CGFloat
    @ViewBuilder let content: () -> Content

    var body: some View {
        GeometryReader { area in
            ScrollView([.horizontal, .vertical]) {
                content().frame(width: max(area.size.width, minWidth), alignment: .topLeading)
            }
        }
        .background(FormTable.paper)
        .clipShape(SoftRect())
        .overlay(SoftRect().stroke(FormTable.line))
        .frame(minHeight: 200)
    }
}

/// The grid inside the box: 1 pt gaps over the line colour make the grid lines.
struct FormGrid<Content: View>: View {
    @ViewBuilder let content: () -> Content

    var body: some View {
        Grid(alignment: .leading, horizontalSpacing: 1, verticalSpacing: 1) { content() }
            .padding(.bottom, 1)
            .background(FormTable.line)
    }
}

extension View {
    /// One cell: a fixed width, or nil for the column that takes the room left (the product).
    func formCell(_ width: CGFloat?, _ alignment: Alignment = .leading, header: Bool = false,
                  grey: Bool = false, padded: Bool = true) -> some View {
        let height = header ? FormTable.headerHeight : FormTable.rowHeight
        return self
            .padding(.horizontal, padded ? 4 : 1)
            .frame(minWidth: width ?? 200 * UI.scale, maxWidth: width ?? .infinity,
                   minHeight: height, maxHeight: height, alignment: alignment)
            .background(header || grey ? FormTable.grey : FormTable.paper)
    }

    /// A header cell: centred, on two lines when it needs them.
    func formHeader(_ width: CGFloat?) -> some View {
        self.multilineTextAlignment(.center).lineLimit(2).formCell(width, .center, header: true)
    }
}

/// The row number at the left of each line (the vertical header of QTableWidget).
struct FormRowNumber: View {
    let number: Int
    var body: some View {
        Text(number > 0 ? String(number) : "").foregroundColor(.secondary).formCell(FormTable.numberWidth, .center, grey: true, padded: false)
    }
}

/// A number box with ▲▼ (QDoubleSpinBox): type freely; the arrows add or take away `step`, never below 0.
struct StepField: View {
    @Binding var text: String
    var step: Double = 1
    var parse: (String) -> Double? = { parseNumber($0) }

    var body: some View {
        HStack(spacing: 1) {
            TextField("", text: $text).textFieldStyle(.roundedBorder).multilineTextAlignment(.trailing)
            Stepper("", onIncrement: { bump(step) }, onDecrement: { bump(-step) }).labelsHidden()
        }
    }

    private func bump(_ change: Double) {
        let value = max(0, pythonRound2((parse(text) ?? 0) + change))
        // written so that parseNumber reads it back: no thousands dots, a comma before the decimals
        text = value == value.rounded() && abs(value) < 1e15
            ? String(Int(value))
            : String(value).replacingOccurrences(of: ".", with: ",")
    }
}
