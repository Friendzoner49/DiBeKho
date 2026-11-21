import AppKit
import SwiftUI

/// A column of a DataTable: title, width, numbers right-aligned; editable columns are yellow, as in the Python app.
struct Column {
    let title: String
    let width: CGFloat
    var numeric = false
    var editable = false
    /// at most this wide once fitted to the contents (stock_page: long real names must not push Tồn out of sight);
    /// the rest is elided, hover to read it
    var cap: CGFloat? = nil
    /// always `width`, whatever the contents (stock_page: setColumnWidth(NOTE, 160))
    var fixed = false
    /// the cells in bold (Tồn kho: the stock column stands out, the owner's request 21/11/2026)
    var bold = false
}

/// header: a row in bold (an order over its lines in the customer window)
enum RowTone { case normal, low, negative, grey, header }

/// An AppKit NSTableView (fast with thousands of rows, columns the user can drag wider) inside SwiftUI.
/// Editable cells: typed text is handed to onEdit(row, column, text) when the cell is left; Enter goes on to the
/// same cell of the next row (as Enter moves down the quantities in the Python app).
struct DataTable: NSViewRepresentable {
    let columns: [Column]
    let rows: [[String]]
    var tones: [RowTone] = []
    /// a double click on a row (its index in rows)
    var onOpen: ((Int) -> Void)? = nil
    var onSelect: ((Int?) -> Void)? = nil
    /// more than one row can be selected (⌘ or Shift click); the rows chosen, as indexes in rows, go to onSelectMany
    var onSelectMany: (([Int]) -> Void)? = nil
    var onEdit: ((Int, Int, String) -> Void)? = nil
    /// cells of one row painted red (a difference after a count)
    var redCells: Set<[Int]> = []
    /// columns shrink to the window's width when the table has cells to type in
    var fitWidth = true
    /// a click on a column title sorts by it (qt: setSortingEnabled); off for the tables whose rows are typed into
    var sortable = true
    /// the column that takes the room left once the others fit their contents (common.make_table stretch=1);
    /// nil: none. Tables with cells to type in share the width instead (fitWidth).
    var stretch: Int? = 1
    /// right click on a row (its index in rows): the menu's items, title and action; none: no menu for that row
    var rowMenu: ((Int) -> [(String, () -> Void)])? = nil

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> NSScrollView {
        let table = NSTableView()
        // rows from edge to edge under their titles, as QTableWidget (the macOS 11+ default 'inset' style pads the
        // rows but not the header, so the columns looked shifted under their titles)
        table.style = .fullWidth
        table.usesAlternatingRowBackgroundColors = true
        table.columnAutoresizingStyle = .noColumnAutoresizing
        table.allowsColumnReordering = false
        table.rowHeight = UI.rowHeight
        table.intercellSpacing = NSSize(width: 6, height: 2)
        // QTableWidget draws its grid lines
        table.gridStyleMask = [.solidVerticalGridLineMask, .solidHorizontalGridLineMask]
        table.gridColor = UI.themed(0xD8D8D8, 0x444444)
        for (i, column) in columns.enumerated() {
            let tableColumn = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("c\(i)"))
            tableColumn.title = column.title
            tableColumn.width = column.width * UI.scale
            tableColumn.minWidth = 40
            tableColumn.headerCell.alignment = .center
            tableColumn.headerCell.font = UI.font(bold: true)
            if sortable {
                tableColumn.sortDescriptorPrototype = NSSortDescriptor(key: "c\(i)", ascending: true)
            }
            table.addTableColumn(tableColumn)
        }
        table.dataSource = context.coordinator
        table.delegate = context.coordinator
        table.target = context.coordinator
        table.doubleAction = #selector(Coordinator.doubleClicked(_:))
        context.coordinator.table = table
        if rowMenu != nil {
            let menu = NSMenu()
            menu.delegate = context.coordinator
            table.menu = menu
        }
        let scroll = SoftScrollView()  // rounded corners (UI.swift)
        scroll.documentView = table
        scroll.hasVerticalScroller = true
        scroll.hasHorizontalScroller = true
        scroll.autohidesScrollers = false
        if fitWidth && columns.contains(where: \.editable) {
            // a table with yellow cells to type in shares the visible width between its columns, so those cells are
            // always in sight (the Python app pins them to the right edge)
            context.coordinator.baseWidths = columns.map { $0.width * UI.scale }
            scroll.contentView.postsFrameChangedNotifications = true
            NotificationCenter.default.addObserver(context.coordinator, selector: #selector(Coordinator.fit),
                                                   name: NSView.frameDidChangeNotification, object: scroll.contentView)
            scroll.hasHorizontalScroller = false
        } else if stretch != nil {
            // the stretch column takes what the window gives beyond the contents (common.Table.fill_spare)
            context.coordinator.stretch = stretch
            context.coordinator.columns = columns
            scroll.contentView.postsFrameChangedNotifications = true
            NotificationCenter.default.addObserver(context.coordinator, selector: #selector(Coordinator.fillSpare),
                                                   name: NSView.frameDidChangeNotification, object: scroll.contentView)
        }
        return scroll
    }

    func updateNSView(_ view: NSScrollView, context: Context) {
        let coordinator = context.coordinator
        coordinator.columns = columns
        coordinator.onOpen = onOpen
        coordinator.onSelect = onSelect
        coordinator.onSelectMany = onSelectMany
        (view.documentView as? NSTableView)?.allowsMultipleSelection = onSelectMany != nil
        coordinator.onEdit = onEdit
        coordinator.rowMenu = rowMenu
        if coordinator.rows != rows || coordinator.tones != tones || coordinator.redCells != redCells {
            let sameShape = coordinator.rows.count == rows.count
            // widths follow the contents when data first arrives, not at each letter typed in a filter box (the
            // Python pages hide rows there, so their columns keep their widths)
            let measure = coordinator.rows.isEmpty || coordinator.natural.isEmpty
            let changed = sameShape ? IndexSet(rows.indices.filter { coordinator.rows[$0] != rows[$0] }) : IndexSet()
            coordinator.rows = rows
            coordinator.tones = tones
            coordinator.redCells = redCells
            if sameShape && coordinator.table?.currentEditor() != nil {
                // typing in a cell: the order stays and only the rows that changed are drawn again, so the cell being
                // typed in keeps the keyboard
                let shown = changed.compactMap { coordinator.order.isEmpty ? $0 : coordinator.order.firstIndex(of: $0) }
                coordinator.table?.reloadData(forRowIndexes: IndexSet(shown), columnIndexes: IndexSet(columns.indices))
            } else {
                coordinator.reloadKeepingSelection()
                if measure && !rows.isEmpty { coordinator.fitContents() }
            }
        }
    }

    @MainActor
    final class Coordinator: NSObject, NSTableViewDataSource, NSTableViewDelegate, NSTextFieldDelegate, NSMenuDelegate {
        var rowMenu: ((Int) -> [(String, () -> Void)])?
        private var menuActions: [() -> Void] = []

        /// The right-click menu of the row under the mouse (orders_page._context_menu)
        func menuNeedsUpdate(_ menu: NSMenu) {
            menu.removeAllItems()
            menuActions = []
            guard let table, let rowMenu, table.clickedRow >= 0, table.clickedRow < rows.count else { return }
            for (title, action) in rowMenu(dataRow(table.clickedRow)) {
                let item = NSMenuItem(title: title, action: #selector(menuPicked(_:)), keyEquivalent: "")
                item.target = self
                item.tag = menuActions.count
                menuActions.append(action)
                menu.addItem(item)
            }
        }

        @objc func menuPicked(_ sender: NSMenuItem) {
            guard sender.tag >= 0, sender.tag < menuActions.count else { return }
            let action = menuActions[sender.tag]
            // after the menu has closed (the action may open a message box)
            UI.later { action() }  // also inside a dialog's modal session
        }

        var columns: [Column] = []
        var rows: [[String]] = []
        var tones: [RowTone] = []
        var redCells: Set<[Int]> = []
        var baseWidths: [CGFloat] = []
        var stretch: Int?
        /// the widths that fit the contents (common.fill_table: resizeColumnsToContents, at most 520)
        var natural: [CGFloat] = []
        weak var table: NSTableView?
        /// the row of `rows` shown at each place of the table (the order the query gave until a title is clicked)
        var order: [Int] = []

        func dataRow(_ displayed: Int) -> Int { displayed < order.count ? order[displayed] : displayed }

        /// What a cell is sorted by: a date as year-month-day, a number as its value ('—' and empty first), else the text.
        enum Key: Equatable, Comparable {
            case number(Double)
            case text(String)

            static func < (a: Key, b: Key) -> Bool {
                switch (a, b) {
                case let (.number(x), .number(y)): return x < y
                case let (.text(x), .text(y)): return x.localizedStandardCompare(y) == .orderedAscending
                case (.number, .text): return true
                case (.text, .number): return false
                }
            }
        }

        static func key(_ text: String, numeric: Bool) -> Key {
            let t = text.trimmingCharacters(in: .whitespaces)
            if let m = t.range(of: #"^(\d{2})/(\d{2})/(\d{4})"#, options: .regularExpression) {
                let d = t[m].split(separator: "/").compactMap { Double($0) }
                if d.count == 3 { return .number(d[2] * 10000 + d[1] * 100 + d[0]) }
            }
            guard numeric else { return .text(t) }
            if t.isEmpty || t == "—" { return .number(-Double.greatestFiniteMagnitude) }
            if let m = t.range(of: #"^-?[\d.]+(,\d+)?"#, options: .regularExpression) {
                let plain = t[m].replacingOccurrences(of: ".", with: "").replacingOccurrences(of: ",", with: ".")
                if let v = Double(plain) { return .number(v) }
            }
            return .text(t)
        }

        /// The order of the rows after the title last clicked (its arrow); ties keep the order of the query.
        func resort() {
            guard let descriptor = table?.sortDescriptors.first, let key = descriptor.key,
                  let column = Int(key.dropFirst()), column < columns.count else {
                order = []
                return
            }
            let numeric = columns[column].numeric
            let keys = rows.map { Self.key(column < $0.count ? $0[column] : "", numeric: numeric) }
            order = rows.indices.sorted { a, b in
                if keys[a] == keys[b] { return a < b }
                return descriptor.ascending ? keys[a] < keys[b] : keys[b] < keys[a]
            }
        }

        /// Sorts again and draws every row; the row that was selected stays selected wherever the sort puts it (the parent
        /// holds its index in `rows`, and a button such as 'Sửa phiếu đã chọn…' acts on it).
        func reloadKeepingSelection() {
            guard let table else { return }
            let before = table.selectedRow >= 0 ? dataRow(table.selectedRow) : nil
            resort()
            table.reloadData()
            guard let before, before < rows.count else { return }
            let shown = order.isEmpty ? before : (order.firstIndex(of: before) ?? before)
            if table.selectedRow != shown {
                // not while SwiftUI is updating its views (the selection tells the parent)
                UI.later { [weak table] in
                    table?.selectRowIndexes(IndexSet(integer: shown), byExtendingSelection: false)
                }
            }
        }

        func tableView(_ tableView: NSTableView, sortDescriptorsDidChange oldDescriptors: [NSSortDescriptor]) {
            reloadKeepingSelection()
        }

        /// The columns in proportion to their widths, together as wide as the visible part of the table.
        @objc func fit() {
            guard let table, let clip = table.enclosingScrollView?.contentView, !baseWidths.isEmpty else { return }
            let spacing = table.intercellSpacing.width * CGFloat(baseWidths.count)
            let available = clip.bounds.width - spacing - 2
            let total = baseWidths.reduce(0, +)
            guard available > 100, total > 0 else { return }
            let factor = available / total
            for (column, base) in zip(table.tableColumns, baseWidths) {
                column.minWidth = 20
                column.width = floor(base * factor)
            }
        }

        /// Every column as wide as its title and cells (at most 520, as MAX_COLUMN_WIDTH), then fillSpare.
        func fitContents() {
            guard let table, baseWidths.isEmpty, table.tableColumns.count == columns.count else { return }
            let font = UI.font(), bold = UI.font(bold: true)
            let sample = rows.prefix(1000)  // as Qt's resize-to-contents precision
            natural = columns.indices.map { c in
                var width = (columns[c].title as NSString).size(withAttributes: [.font: bold]).width + 26  // sort arrow
                for row in sample where c < row.count && !row[c].isEmpty {
                    width = max(width, (row[c] as NSString).size(withAttributes: [.font: columns[c].bold ? bold : font]).width + 14)
                }
                if columns[c].fixed { return columns[c].width * UI.scale }
                return min(ceil(width), 520, (columns[c].cap ?? 520) * UI.scale)
            }
            for (column, width) in zip(table.tableColumns, natural) {
                column.minWidth = 30
                column.width = width
            }
            fillSpare()
        }

        @objc func fillSpare() {
            guard let table, let stretch, stretch < table.tableColumns.count,
                  let clip = table.enclosingScrollView?.contentView else { return }
            // before any row has come (an empty Tra cứu), the width the screen gave the column; the table is still
            // filled to its right edge, as a Qt table with a stretched section
            let least: CGFloat
            if stretch < natural.count {
                least = natural[stretch]
            } else if stretch < columns.count {
                least = columns[stretch].width * UI.scale
            } else {
                least = 40
            }
            let spacing = table.intercellSpacing.width * CGFloat(table.tableColumns.count)
            let others = table.tableColumns.enumerated().filter { $0.offset != stretch }.reduce(CGFloat(0)) { $0 + $1.element.width }
            table.tableColumns[stretch].width = max(least, floor(clip.bounds.width - others - spacing - 2))
        }

        var onOpen: ((Int) -> Void)?
        var onSelect: ((Int?) -> Void)?
        var onSelectMany: (([Int]) -> Void)?
        var onEdit: ((Int, Int, String) -> Void)?

        @objc func doubleClicked(_ sender: NSTableView) {
            let row = sender.clickedRow
            let column = sender.clickedColumn
            if column >= 0 && column < columns.count && columns[column].editable { return }
            if row >= 0 && row < rows.count { onOpen?(dataRow(row)) }
        }

        func numberOfRows(in tableView: NSTableView) -> Int { rows.count }

        func tableViewSelectionDidChange(_ notification: Notification) {
            guard let table else { return }
            onSelect?(table.selectedRow >= 0 ? dataRow(table.selectedRow) : nil)
            onSelectMany?(table.selectedRowIndexes.map { dataRow($0) })
        }

        func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
            guard let identifier = tableColumn?.identifier,
                  let index = Int(identifier.rawValue.dropFirst()), index < columns.count, row < rows.count else { return nil }
            let column = columns[index]
            let field: NSTextField
            if let reused = tableView.makeView(withIdentifier: identifier, owner: self) as? NSTextField {
                field = reused
            } else {
                field = column.editable ? NSTextField(string: "") : NSTextField(labelWithString: "")
                field.identifier = identifier
                field.lineBreakMode = .byTruncatingTail
                field.font = UI.font()
                if column.editable {
                    field.isBordered = false
                    field.drawsBackground = true
                    field.backgroundColor = UI.yellow
                    field.focusRingType = .none
                    field.delegate = self
                    field.cell?.isScrollable = true
                }
            }
            let shown = dataRow(row)
            let text = index < rows[shown].count ? rows[shown][index] : ""
            field.stringValue = text
            field.toolTip = !text.isEmpty && (text.count > 18 || column.cap != nil) ? text : nil
            field.alignment = column.numeric ? .right : .left
            if column.editable {
                // a note cell in a low / negative row takes the row's colour (Python: the whole row), else yellow
                let tone = shown < tones.count ? tones[shown] : .normal
                field.backgroundColor = redCells.contains([shown, index]) ? UI.red
                    : tone == .negative ? UI.red : tone == .low ? UI.orange : UI.yellow
            } else if redCells.contains([shown, index]) {
                field.drawsBackground = true
                field.backgroundColor = UI.red
            } else {
                field.drawsBackground = false
            }
            let rowTone = shown < tones.count ? tones[shown] : .normal
            field.textColor = rowTone == .grey ? .secondaryLabelColor : .labelColor
            field.font = UI.font(bold: rowTone == .header || column.bold)
            return field
        }

        /// Rows running low are orange, below zero red: the whole row's background, as in the Python app.
        func tableView(_ tableView: NSTableView, didAdd rowView: NSTableRowView, forRow row: Int) {
            let shown = dataRow(row)
            switch shown < tones.count ? tones[shown] : .normal {
            case .negative: rowView.backgroundColor = UI.red
            case .low: rowView.backgroundColor = UI.orange
            default: rowView.backgroundColor = .clear  // row views are reused: drop the colour of the previous row
            }
        }

        // ---- typing in a yellow cell

        func controlTextDidEndEditing(_ notification: Notification) {
            guard let field = notification.object as? NSTextField, let table else { return }
            let row = table.row(for: field)
            let column = table.column(for: field)
            guard row >= 0, column >= 0, row < rows.count else { return }
            let text = field.stringValue
            let shown = dataRow(row)
            if column < rows[shown].count && rows[shown][column] != text {
                onEdit?(shown, column, text)
            }
            let movement = notification.userInfo?["NSTextMovement"] as? Int
            if movement == NSTextMovement.return.rawValue, row + 1 < rows.count {
                // Enter: the same column of the next row, never a button of the window
                UI.later {
                    table.scrollRowToVisible(row + 1)
                    if let next = table.view(atColumn: column, row: row + 1, makeIfNecessary: true) as? NSTextField {
                        table.window?.makeFirstResponder(next)
                    }
                }
            }
        }
    }
}
