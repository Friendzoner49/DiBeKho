import Foundation
import ZIPFoundation

/// What one cell looks like. Only what the shop's files use: a font, thin borders, alignment, a number format.
public struct XStyle: Hashable {
    public var fontName = "Calibri"
    public var fontSize = 11.0
    public var bold = false
    public var italic = false
    /// 'RRGGBB' or nil
    public var fontColor: String?
    public var borderLeft = false, borderRight = false, borderTop = false, borderBottom = false
    /// 'RRGGBB' of the thin border line (nil = automatic)
    public var borderColor: String?
    public var horizontal: String?
    public var vertical: String?
    public var wrap = false
    public var shrink = false
    public var numberFormat: String?
    /// solid background 'RRGGBB' or nil
    public var fill: String?
    public init() {}

    public var box: Bool {
        get { borderLeft && borderRight && borderTop && borderBottom }
        set { borderLeft = newValue; borderRight = newValue; borderTop = newValue; borderBottom = newValue }
    }
}

public enum XValue: Equatable {
    case empty
    case text(String)
    case number(Double)
    /// a date as Excel stores it: the day number since 1899-12-30 (give it a date number format)
    case date(year: Int, month: Int, day: Int)
}

public struct XCell {
    public var value: XValue
    public var style: XStyle
    public init(_ value: XValue, _ style: XStyle = XStyle()) { self.value = value; self.style = style }
}

public struct XSheet {
    public var name: String
    public var cells: [Int: [Int: XCell]] = [:]  // row -> column -> cell (both from 1)
    public var merges: [String] = []
    public var rowHeights: [Int: Double] = [:]
    public var columnWidths: [Double] = []
    public var hiddenColumns: Set<Int> = []
    /// a landscape A4 page at this scale (percent), with these margins in inches (left/right, top/bottom), printing this range
    public var landscapeScale: Int?
    public var sideMargin = 0.75
    public var topMargin = 1.0
    /// nil = the same as topMargin
    public var bottomMargin: Double?
    /// centred on the page when printed
    public var centerHorizontally = false
    public var printArea: String?
    /// rows above and columns left of this cell stay in view when scrolling (openpyxl freeze_panes 'C5' = row 5, column 3)
    public var freeze: (row: Int, column: Int)?
    /// the filter buttons of a header row, e.g. "A4:J20" (openpyxl auto_filter.ref)
    public var autoFilter: String?

    public init(name: String) { self.name = name }

    public mutating func put(_ row: Int, _ column: Int, _ value: XValue, _ style: XStyle = XStyle()) {
        cells[row, default: [:]][column] = XCell(value, style)
    }
}

/// Writes a one-sheet .xlsx (a zip of XML parts) the way Excel does: shared strings, a styles part, no program name.
/// Python wrote these files with openpyxl; tools/check_xlsx.py loads the Swift ones with openpyxl on CI and compares.
public enum XlsxWriter {
    public static func write(_ sheet: XSheet, to url: URL) throws { try write([sheet], to: url) }

    /// Several sheets in one workbook, in this order; the first one is open.
    public static func write(_ sheets: [XSheet], to url: URL) throws {
        let fm = FileManager.default
        try fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let tmp = url.deletingLastPathComponent().appendingPathComponent(".\(UUID().uuidString).tmp")
        defer { try? fm.removeItem(at: tmp) }
        let archive = try Archive(url: tmp, accessMode: .create)
        let made = build(sheets)
        for (path, text) in made {
            let data = Data(text.utf8)
            try archive.addEntry(with: path, type: .file, uncompressedSize: Int64(data.count), compressionMethod: .deflate) {
                position, size in data.subdata(in: Data.Index(position)..<(Data.Index(position) + size))
            }
        }
        if fm.fileExists(atPath: url.path) { try fm.removeItem(at: url) }
        try fm.moveItem(at: tmp, to: url)
    }

    // MARK: parts

    static func build(_ sheet: XSheet) -> [(String, String)] { build([sheet]) }

    static func build(_ sheets: [XSheet]) -> [(String, String)] {
        var strings: [String] = []
        var stringIds: [String: Int] = [:]
        func stringId(_ s: String) -> Int {
            if let i = stringIds[s] { return i }
            strings.append(s)
            stringIds[s] = strings.count - 1
            return strings.count - 1
        }
        var styles: [XStyle] = [XStyle()]  // 0 = the default
        var styleIds: [XStyle: Int] = [XStyle(): 0]
        func styleId(_ s: XStyle) -> Int {
            if let i = styleIds[s] { return i }
            styles.append(s)
            styleIds[s] = styles.count - 1
            return styles.count - 1
        }

        func sheetXml(_ sheet: XSheet, selected: Bool) -> String {
        // a merged range keeps the border of its top-left cell on every outer edge (as Excel and openpyxl do)
        var cells = sheet.cells
        for ref in sheet.merges {
            guard let (r1, c1, r2, c2) = range(ref), let top = cells[r1]?[c1], top.style.borderLeft || top.style.borderTop
            else { continue }
            for r in r1...r2 {
                for c in c1...c2 {
                    var cell = cells[r]?[c] ?? XCell(.empty, top.style)
                    if (r, c) == (r1, c1) { cell.style = top.style }
                    var s = cell.style
                    s.borderLeft = c == c1 && top.style.borderLeft
                    s.borderRight = c == c2 && top.style.borderRight
                    s.borderTop = r == r1 && top.style.borderTop
                    s.borderBottom = r == r2 && top.style.borderBottom
                    s.borderColor = top.style.borderColor
                    cell.style = s
                    if (r, c) != (r1, c1) { cell.value = .empty }
                    cells[r, default: [:]][c] = cell
                }
            }
        }

        var rows: [Int] = Set(cells.keys).union(sheet.rowHeights.keys).sorted()
        rows = rows.filter { $0 >= 1 }
        var data = ""
        var lastColumn = 1
        for r in rows {
            let height = sheet.rowHeights[r].map { " ht=\"\(number($0))\" customHeight=\"1\"" } ?? ""
            data += "<row r=\"\(r)\"\(height)>"
            for c in (cells[r] ?? [:]).keys.sorted() {
                let cell = cells[r]![c]!
                lastColumn = max(lastColumn, c)
                let ref = "\(columnName(c))\(r)"
                let s = styleId(cell.style)
                let attr = s == 0 ? "" : " s=\"\(s)\""
                switch cell.value {
                case .empty:
                    data += "<c r=\"\(ref)\"\(attr)/>"
                case let .text(text):
                    data += "<c r=\"\(ref)\"\(attr) t=\"s\"><v>\(stringId(text))</v></c>"
                case let .number(v):
                    data += "<c r=\"\(ref)\"\(attr)><v>\(number(v))</v></c>"
                case let .date(y, m, d):
                    data += "<c r=\"\(ref)\"\(attr)><v>\(excelDay(y, m, d))</v></c>"
                }
            }
            data += "</row>"
        }
        let lastRow = rows.last ?? 1

        var cols = ""
        for (i, width) in sheet.columnWidths.enumerated() {
            let hidden = sheet.hiddenColumns.contains(i + 1) ? " hidden=\"1\"" : ""
            cols += "<col min=\"\(i + 1)\" max=\"\(i + 1)\" width=\"\(number(width))\" customWidth=\"1\"\(hidden)/>"
        }
        var xml = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        xml += "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">"
        xml += "<sheetPr><pageSetUpPr fitToPage=\"0\"/></sheetPr>"
        xml += "<dimension ref=\"A1:\(columnName(max(lastColumn, sheet.columnWidths.count)))\(lastRow)\"/>"
        let tab = selected ? " tabSelected=\"1\"" : ""
        if let f = sheet.freeze, f.row > 1 || f.column > 1 {
            let corner = "\(columnName(f.column))\(f.row)"
            var pane = "<pane"
            if f.column > 1 { pane += " xSplit=\"\(f.column - 1)\"" }
            if f.row > 1 { pane += " ySplit=\"\(f.row - 1)\"" }
            let active = f.row > 1 && f.column > 1 ? "bottomRight" : (f.row > 1 ? "bottomLeft" : "topRight")
            pane += " topLeftCell=\"\(corner)\" activePane=\"\(active)\" state=\"frozen\"/>"
            xml += "<sheetViews><sheetView\(tab) workbookViewId=\"0\">\(pane)<selection pane=\"\(active)\"/></sheetView></sheetViews>"
        } else {
            xml += "<sheetViews><sheetView\(tab) workbookViewId=\"0\"/></sheetViews>"
        }
        xml += "<sheetFormatPr baseColWidth=\"8\" defaultRowHeight=\"15\"/>"
        if !cols.isEmpty { xml += "<cols>\(cols)</cols>" }
        xml += "<sheetData>\(data)</sheetData>"
        if let filter = sheet.autoFilter { xml += "<autoFilter ref=\"\(filter)\"/>" }
        if !sheet.merges.isEmpty {
            xml += "<mergeCells count=\"\(sheet.merges.count)\">"
            xml += sheet.merges.map { "<mergeCell ref=\"\($0)\"/>" }.joined()
            xml += "</mergeCells>"
        }
        let side = number(sheet.sideMargin), top = number(sheet.topMargin), bottom = number(sheet.bottomMargin ?? sheet.topMargin)
        if sheet.centerHorizontally { xml += "<printOptions horizontalCentered=\"1\"/>" }
        xml += "<pageMargins left=\"\(side)\" right=\"\(side)\" top=\"\(top)\" bottom=\"\(bottom)\" header=\"0.5\" footer=\"0.5\"/>"
        if let scale = sheet.landscapeScale {
            xml += "<pageSetup paperSize=\"9\" scale=\"\(scale)\" orientation=\"landscape\"/>"
        }
        xml += "</worksheet>"
        return xml
        }
        let sheetXmls = sheets.enumerated().map { sheetXml($1, selected: $0 == 0) }

        var sst = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        sst += "<sst xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" count=\"\(strings.count)\" uniqueCount=\"\(strings.count)\">"
        sst += strings.map { "<si><t xml:space=\"preserve\">\(escape($0))</t></si>" }.joined()
        sst += "</sst>"

        var workbook = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        workbook += "<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" "
        workbook += "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">"
        workbook += "<bookViews><workbookView activeTab=\"0\"/></bookViews>"
        workbook += "<sheets>"
        for (i, sheet) in sheets.enumerated() {
            workbook += "<sheet name=\"\(escape(sheet.name))\" sheetId=\"\(i + 1)\" r:id=\"rId\(i + 1)\"/>"
        }
        workbook += "</sheets>"
        var names = ""
        for (i, sheet) in sheets.enumerated() {
            if let area = sheet.printArea, let (r1, c1, r2, c2) = range(area) {
                let absolute = "$\(columnName(c1))$\(r1):$\(columnName(c2))$\(r2)"
                names += "<definedName name=\"_xlnm.Print_Area\" localSheetId=\"\(i)\">'\(escape(sheet.name))'!\(absolute)</definedName>"
            }
        }
        if !names.isEmpty { workbook += "<definedNames>\(names)</definedNames>" }
        workbook += "</workbook>"

        let n = sheets.count
        var types = contentTypes.replacingOccurrences(
            of: "<Override PartName=\"/xl/worksheets/sheet1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>",
            with: (1...n).map { "<Override PartName=\"/xl/worksheets/sheet\($0).xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>" }.joined())
        if n == 1 { types = contentTypes }
        var rels = workbookRels.replacingOccurrences(
            of: "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet1.xml\"/><Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/><Relationship Id=\"rId3\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings\" Target=\"sharedStrings.xml\"/>",
            with: (1...n).map { "<Relationship Id=\"rId\($0)\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet\($0).xml\"/>" }.joined()
                + "<Relationship Id=\"rId\(n + 1)\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/>"
                + "<Relationship Id=\"rId\(n + 2)\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings\" Target=\"sharedStrings.xml\"/>")
        if n == 1 { rels = workbookRels }

        var parts: [(String, String)] = [
            ("[Content_Types].xml", types),
            ("_rels/.rels", rootRels),
            ("docProps/app.xml", appXml),
            ("docProps/core.xml", coreXml()),
            ("xl/workbook.xml", workbook),
            ("xl/_rels/workbook.xml.rels", rels),
            ("xl/styles.xml", stylesXml(styles)),
            ("xl/sharedStrings.xml", sst),
        ]
        for (i, xml) in sheetXmls.enumerated() { parts.append(("xl/worksheets/sheet\(i + 1).xml", xml)) }
        return parts
    }

    static let contentTypes = """
        <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>
        """
    static let rootRels = """
        <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>
        """
    static let workbookRels = """
        <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>
        """
    /// what Excel itself writes there: nothing in the file names this program
    static let appXml = """
        <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>Microsoft Excel</Application></Properties>
        """

    static func coreXml() -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        let now = f.string(from: Date())
        return "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
            + "<cp:coreProperties xmlns:cp=\"http://schemas.openxmlformats.org/package/2006/metadata/core-properties\" "
            + "xmlns:dc=\"http://purl.org/dc/elements/1.1/\" xmlns:dcterms=\"http://purl.org/dc/terms/\" "
            + "xmlns:dcmitype=\"http://purl.org/dc/dcmitype/\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\">"
            + "<dc:creator></dc:creator><cp:lastModifiedBy></cp:lastModifiedBy>"
            + "<dcterms:created xsi:type=\"dcterms:W3CDTF\">\(now)</dcterms:created>"
            + "<dcterms:modified xsi:type=\"dcterms:W3CDTF\">\(now)</dcterms:modified></cp:coreProperties>"
    }

    static func stylesXml(_ styles: [XStyle]) -> String {
        var formats: [String] = []
        var fonts: [String] = []
        var borders: [String] = ["<border><left/><right/><top/><bottom/><diagonal/></border>"]
        var fills: [String] = []  // from id 2: ids 0 and 1 are the two the format requires
        var xfs = ""
        func index(_ list: inout [String], _ item: String) -> Int {
            if let i = list.firstIndex(of: item) { return i }
            list.append(item)
            return list.count - 1
        }
        for s in styles {
            var font = "<font>"
            if s.bold { font += "<b val=\"1\"/>" }
            if s.italic { font += "<i val=\"1\"/>" }
            font += "<sz val=\"\(number(s.fontSize))\"/>"
            if let c = s.fontColor { font += "<color rgb=\"FF\(c)\"/>" }
            font += "<name val=\"\(escape(s.fontName))\"/><family val=\"2\"/></font>"
            let fontId = index(&fonts, font)
            var borderId = 0
            if s.borderLeft || s.borderRight || s.borderTop || s.borderBottom {
                func side(_ name: String, _ on: Bool) -> String {
                    guard on else { return "<\(name)/>" }
                    let color = s.borderColor.map { "<color rgb=\"FF\($0)\"/>" } ?? ""
                    return "<\(name) style=\"thin\">\(color)</\(name)>"
                }
                let border = "<border>" + side("left", s.borderLeft) + side("right", s.borderRight)
                    + side("top", s.borderTop) + side("bottom", s.borderBottom) + "<diagonal/></border>"
                borderId = index(&borders, border)
            }
            var fillId = 0
            if let color = s.fill {
                fillId = 2 + index(&fills, "<fill><patternFill patternType=\"solid\"><fgColor rgb=\"FF\(color)\"/><bgColor indexed=\"64\"/></patternFill></fill>")
            }
            var numberId = 0
            if let format = s.numberFormat { numberId = 164 + index(&formats, format) }
            var alignment = ""
            if s.horizontal != nil || s.vertical != nil || s.wrap || s.shrink {
                alignment = "<alignment"
                if let h = s.horizontal { alignment += " horizontal=\"\(h)\"" }
                if let v = s.vertical { alignment += " vertical=\"\(v)\"" }
                if s.wrap { alignment += " wrapText=\"1\"" }
                if s.shrink { alignment += " shrinkToFit=\"1\"" }
                alignment += "/>"
            }
            xfs += "<xf numFmtId=\"\(numberId)\" fontId=\"\(fontId)\" fillId=\"\(fillId)\" borderId=\"\(borderId)\" xfId=\"0\""
            if numberId != 0 { xfs += " applyNumberFormat=\"1\"" }
            if fontId != 0 { xfs += " applyFont=\"1\"" }
            if fillId != 0 { xfs += " applyFill=\"1\"" }
            if borderId != 0 { xfs += " applyBorder=\"1\"" }
            xfs += alignment.isEmpty ? "/>" : " applyAlignment=\"1\">\(alignment)</xf>"
        }
        var out = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        out += "<styleSheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">"
        if !formats.isEmpty {
            out += "<numFmts count=\"\(formats.count)\">"
            for (i, f) in formats.enumerated() { out += "<numFmt numFmtId=\"\(164 + i)\" formatCode=\"\(escape(f))\"/>" }
            out += "</numFmts>"
        }
        out += "<fonts count=\"\(fonts.count)\">\(fonts.joined())</fonts>"
        out += "<fills count=\"\(2 + fills.count)\"><fill><patternFill patternType=\"none\"/></fill><fill><patternFill patternType=\"gray125\"/></fill>\(fills.joined())</fills>"
        out += "<borders count=\"\(borders.count)\">\(borders.joined())</borders>"
        out += "<cellStyleXfs count=\"1\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\"/></cellStyleXfs>"
        out += "<cellXfs count=\"\(styles.count)\">\(xfs)</cellXfs>"
        out += "<cellStyles count=\"1\"><cellStyle name=\"Normal\" xfId=\"0\" builtinId=\"0\"/></cellStyles>"
        out += "</styleSheet>"
        return out
    }

    // MARK: helpers

    /// openpyxl writes numbers with '%.16g'
    static func number(_ v: Double) -> String { String(format: "%.16g", v) }

    static func excelDay(_ y: Int, _ m: Int, _ d: Int) -> Int {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let day = calendar.date(from: DateComponents(year: y, month: m, day: d))!
        let origin = calendar.date(from: DateComponents(year: 1899, month: 12, day: 30))!
        return calendar.dateComponents([.day], from: origin, to: day).day!
    }

    public static func columnName(_ column: Int) -> String {
        var n = column, name = ""
        while n > 0 {
            let r = (n - 1) % 26
            name = String(UnicodeScalar(UInt8(65 + r))) + name
            n = (n - 1) / 26
        }
        return name
    }

    /// 'B5:C6' -> rows 5...6, columns 2...3
    static func range(_ ref: String) -> (Int, Int, Int, Int)? {
        let parts = ref.split(separator: ":").map(String.init)
        guard let first = parts.first, let last = parts.last, let a = cellRef(first), let z = cellRef(last) else { return nil }
        return (a.0, a.1, z.0, z.1)
    }

    static func cellRef(_ ref: String) -> (Int, Int)? {
        var column = 0, digits = ""
        for ch in ref where ch != "$" {
            if let a = ch.asciiValue, ch.isLetter { column = column * 26 + Int(a & 0x1F) } else { digits.append(ch) }
        }
        guard column > 0, let row = Int(digits) else { return nil }
        return (row, column)
    }

    /// Text for an XML part: the five markup characters escaped, characters XML 1.0 cannot hold dropped.
    static func escape(_ text: String) -> String {
        var out = ""
        for u in text.unicodeScalars {
            switch u {
            case "&": out += "&amp;"
            case "<": out += "&lt;"
            case ">": out += "&gt;"
            case "\"": out += "&quot;"
            case "\t", "\n", "\r": out.unicodeScalars.append(u)
            default:
                if u.value >= 0x20 && u.value != 0xFFFE && u.value != 0xFFFF && !(0xD800...0xDFFF).contains(u.value) {
                    out.unicodeScalars.append(u)
                }
            }
        }
        return out
    }
}
