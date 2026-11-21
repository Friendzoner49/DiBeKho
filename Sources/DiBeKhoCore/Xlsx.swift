import Foundation
import ZIPFoundation

/// A cell's value as openpyxl gives it with data_only=True (the cached result of a formula; none when there is none).
public enum CellValue: Equatable {
    case text(String)
    case int(Int64)
    case double(Double)
    case bool(Bool)
    /// a number in a date format: year, month, day, hour, minute, second
    case date(Int, Int, Int, Int, Int, Int)
    /// a number below 1 in a date format (openpyxl: a time of day)
    case time(Int, Int, Int)

    /// Python's str() of the value.
    public var pythonText: String {
        switch self {
        case let .text(s): return s
        case let .int(i): return String(i)
        case let .double(d): return Xlsx.pythonFloat(d)
        case let .bool(b): return b ? "True" : "False"
        case let .date(y, m, d, h, mi, s): return String(format: "%04d-%02d-%02d %02d:%02d:%02d", y, m, d, h, mi, s)
        case let .time(h, mi, s): return String(format: "%02d:%02d:%02d", h, mi, s)
        }
    }

    public var isNumber: Bool {
        switch self {
        case .int, .double: return true
        default: return false
        }
    }
}

/// One worksheet as a grid from A1 (openpyxl ws.iter_rows(values_only=True)), with each cell's number format.
public struct Worksheet {
    public let name: String
    public let rows: [[CellValue?]]
    public let formats: [[String]]
    /// merged ranges (1-based rows and columns); only the top-left cell of one has a value
    public var merges: [MergeRange] = []
}

public struct MergeRange: Equatable {
    public let minRow: Int, minCol: Int, maxRow: Int, maxCol: Int
}

public struct XlsxError: Error, LocalizedError {
    public let reason: String
    public var errorDescription: String? { reason }
}

/// A small reader of .xlsx files (a zip of XML parts), enough for the shop's delivery notes: shared and inline
/// strings, numbers, booleans, dates by number format (as openpyxl decides), merged cells read as their top-left.
public enum Xlsx {
    // openpyxl.styles.numbers.BUILTIN_FORMATS
    static let builtinFormats: [Int: String] = [
        0: "General", 1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00", 5: "\"$\"#,##0_);(\"$\"#,##0)",
        6: "\"$\"#,##0_);[Red](\"$\"#,##0)", 7: "\"$\"#,##0.00_);(\"$\"#,##0.00)",
        8: "\"$\"#,##0.00_);[Red](\"$\"#,##0.00)", 9: "0%", 10: "0.00%", 11: "0.00E+00", 12: "# ?/?", 13: "# ??/??",
        14: "mm-dd-yy", 15: "d-mmm-yy", 16: "d-mmm", 17: "mmm-yy", 18: "h:mm AM/PM", 19: "h:mm:ss AM/PM",
        20: "h:mm", 21: "h:mm:ss", 22: "m/d/yy h:mm", 37: "#,##0_);(#,##0)", 38: "#,##0_);[Red](#,##0)",
        39: "#,##0.00_);(#,##0.00)", 40: "#,##0.00_);[Red](#,##0.00)",
        41: "_(* #,##0_);_(* \\(#,##0\\);_(* \"-\"_);_(@_)", 42: "_(\"$\"* #,##0_);_(\"$\"* \\(#,##0\\);_(\"$\"* \"-\"_);_(@_)",
        43: "_(* #,##0.00_);_(* \\(#,##0.00\\);_(* \"-\"??_);_(@_)",
        44: "_(\"$\"* #,##0.00_)_(\"$\"* \\(#,##0.00\\)_(\"$\"* \"-\"??_)_(@_)", 45: "mm:ss", 46: "[h]:mm:ss",
        47: "mmss.0", 48: "##0.0E+0", 49: "@",
    ]

    /// openpyxl is_date_format: the first section, without quoted text and [locale] parts (but [h] [m] [s] kept),
    /// holds d, m, h, y or s not escaped by _ or \.
    static func isDateFormat(_ format: String) -> Bool {
        var fmt = String(format.split(separator: ";", omittingEmptySubsequences: false).first ?? "")
        fmt = fmt.replacingOccurrences(of: #"".*?"|\[(?!hh?\]|mm?\]|ss?\])[^\]]*\]"#, with: "", options: .regularExpression)
        return fmt.range(of: #"(?<![_\\])[dmhysDMHYS]"#, options: .regularExpression) != nil
    }

    /// openpyxl is_timedelta_format ([h]:mm and the like): such numbers are durations, not dates.
    static func isTimedeltaFormat(_ format: String) -> Bool {
        let fmt = String(format.split(separator: ";", omittingEmptySubsequences: false).first ?? "")
        return fmt.range(of: #"\[hh?\](:mm(:ss(\.0*)?)?)?|\[mm?\](:ss(\.0*)?)?|\[ss?\](\.0*)?"#,
                         options: [.regularExpression, .caseInsensitive]) != nil
    }

    /// Python's str(float): the shortest form, '.0' on whole numbers, an exponent from 1e16 and below 1e-4.
    static func pythonFloat(_ d: Double) -> String {
        if d.isNaN { return "nan" }
        if d.isInfinite { return d < 0 ? "-inf" : "inf" }
        let magnitude = abs(d)
        if magnitude != 0 && (magnitude >= 1e16 || magnitude < 1e-4) {
            // Swift writes 1e-05 and 1e+16 as Python does
            return "\(d)"
        }
        let text = "\(d)"
        return text.contains("e") ? String(format: "%.1f", d) : text
    }

    /// openpyxl from_excel: a serial day number to a date (1900 or 1904 system); below 1, a time of day.
    static func fromExcel(_ value: Double, date1904: Bool) -> CellValue? {
        guard value.isFinite, abs(value) < 3_000_000 else { return nil }
        let day = (value).rounded(.down)
        let fraction = value - day
        var millis = (fraction * 86_400_000).rounded(.toNearestOrEven)
        var wholeDays = day
        if millis >= 86_400_000 {
            millis -= 86_400_000
            wholeDays += 1
        }
        let seconds = Int(millis / 1000)
        if value >= 0 && value < 1 && wholeDays == 0 {
            return .time(seconds / 3600, (seconds % 3600) / 60, seconds % 60)
        }
        if !date1904 && value > 0 && value < 60 { wholeDays += 1 }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let epoch = date1904 ? DateComponents(year: 1904, month: 1, day: 1) : DateComponents(year: 1899, month: 12, day: 30)
        guard let start = calendar.date(from: epoch),
              let when = calendar.date(byAdding: .second, value: Int(wholeDays) * 86_400 + seconds, to: start) else { return nil }
        let c = calendar.dateComponents([.year, .month, .day, .hour, .minute, .second], from: when)
        return .date(c.year ?? 0, c.month ?? 0, c.day ?? 0, c.hour ?? 0, c.minute ?? 0, c.second ?? 0)
    }

    public static func read(_ url: URL) throws -> [Worksheet] {
        let archive: Archive
        do {
            archive = try Archive(url: url, accessMode: .read)
        } catch {
            throw XlsxError(reason: "File is not a zip file")
        }
        func part(_ path: String) throws -> Data? {
            let clean = path.hasPrefix("/") ? String(path.dropFirst()) : path
            guard let entry = archive[clean] else { return nil }
            var data = Data()
            _ = try archive.extract(entry, consumer: { data.append($0) })
            return data
        }
        guard let workbookData = try part("xl/workbook.xml") else {
            throw XlsxError(reason: "There is no item named 'xl/workbook.xml' in the archive")
        }
        let workbook = WorkbookParser()
        workbook.parse(workbookData)
        let rels = RelsParser()
        if let data = try part("xl/_rels/workbook.xml.rels") { rels.parse(data) }
        var strings: [String] = []
        let stringsTarget = rels.targets.values.first { $0.type.hasSuffix("/sharedStrings") }?.target ?? "sharedStrings.xml"
        if let data = try part(resolve(stringsTarget)) {
            let parser = SharedStringsParser()
            parser.parse(data)
            strings = parser.strings
        }
        var formats: [String] = []
        var dates = Set<Int>()
        var durations = Set<Int>()
        let stylesTarget = rels.targets.values.first { $0.type.hasSuffix("/styles") }?.target ?? "styles.xml"
        if let data = try part(resolve(stylesTarget)) {
            let parser = StylesParser()
            parser.parse(data)
            for (i, id) in parser.xfFormatIds.enumerated() {
                let format = parser.customFormats[id] ?? builtinFormats[id] ?? "General"
                formats.append(format)
                if isTimedeltaFormat(format) {
                    durations.insert(i)
                } else if (parser.customFormats[id] != nil || builtinFormats[id] != nil) && isDateFormat(format) {
                    dates.insert(i)
                }
            }
        }
        var sheets: [Worksheet] = []
        for sheet in workbook.sheets {
            guard let rel = rels.targets[sheet.relId], rel.type.hasSuffix("/worksheet"),
                  let data = try part(resolve(rel.target)) else { continue }
            let parser = SheetParser(strings: strings, formats: formats, dates: dates, durations: durations,
                                     date1904: workbook.date1904)
            parser.parse(data)
            sheets.append(parser.worksheet(name: sheet.name))
        }
        return sheets
    }

    static func resolve(_ target: String) -> String {
        target.hasPrefix("/") ? String(target.dropFirst()) : "xl/" + target
    }

    /// "BC12" -> (row 12, column 55), 1-based
    static func coordinate(_ ref: String) -> (Int, Int)? {
        var column = 0
        var digits = ""
        for ch in ref.uppercased() {
            if let ascii = ch.asciiValue, ascii >= 65 && ascii <= 90 && digits.isEmpty {
                column = column * 26 + Int(ascii - 64)
            } else if ch.isNumber {
                digits.append(ch)
            } else {
                return nil
            }
        }
        guard column > 0, let row = Int(digits), row > 0 else { return nil }
        return (row, column)
    }
}

// ---- the XML parts

private func localName(_ name: String) -> String {
    if let i = name.lastIndex(of: ":") { return String(name[name.index(after: i)...]) }
    return name
}

/// Each part's parser is its own XMLParserDelegate (NSObject subclass declaring the protocol itself, so the
/// Objective-C runtime finds its methods).
private protocol PartParser: XMLParserDelegate {}

extension PartParser {
    func parse(_ data: Data) {
        let parser = XMLParser(data: data)
        parser.delegate = self
        parser.shouldProcessNamespaces = false
        parser.parse()
    }
}

private final class WorkbookParser: NSObject, PartParser {
    struct Sheet { let name: String; let relId: String }
    var sheets: [Sheet] = []
    var date1904 = false

    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?, qualifiedName: String?,
                attributes: [String: String] = [:]) {
        switch localName(elementName) {
        case "workbookPr":
            let value = attributes["date1904"] ?? ""
            date1904 = value == "1" || value.lowercased() == "true"
        case "sheet":
            let relId = attributes.first { localName($0.key) == "id" && $0.key.contains(":") }?.value ?? ""
            sheets.append(Sheet(name: attributes["name"] ?? "", relId: relId))
        default:
            break
        }
    }
}

private final class RelsParser: NSObject, PartParser {
    var targets: [String: (target: String, type: String)] = [:]

    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?, qualifiedName: String?,
                attributes: [String: String] = [:]) {
        if localName(elementName) == "Relationship", let id = attributes["Id"], let target = attributes["Target"] {
            targets[id] = (target, attributes["Type"] ?? "")
        }
    }
}

/// openpyxl read_string_table: the text of each <si> (its <t> and its runs' <t>, not the phonetic <rPh>), 'x005F_'
/// removed.
private final class SharedStringsParser: NSObject, PartParser {
    var strings: [String] = []
    private var current = ""
    private var inText = false
    private var phonetic = 0

    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?, qualifiedName: String?,
                attributes: [String: String] = [:]) {
        switch localName(elementName) {
        case "si": current = ""
        case "rPh": phonetic += 1
        case "t": inText = phonetic == 0
        default: break
        }
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        if inText { current += string }
    }

    func parser(_ parser: XMLParser, didEndElement elementName: String, namespaceURI: String?, qualifiedName: String?) {
        switch localName(elementName) {
        case "si": strings.append(current.replacingOccurrences(of: "x005F_", with: ""))
        case "rPh": phonetic -= 1
        case "t": inText = false
        default: break
        }
    }
}

private final class StylesParser: NSObject, PartParser {
    var customFormats: [Int: String] = [:]
    var xfFormatIds: [Int] = []
    private var inCellXfs = false

    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?, qualifiedName: String?,
                attributes: [String: String] = [:]) {
        switch localName(elementName) {
        case "numFmt":
            if let id = Int(attributes["numFmtId"] ?? ""), let code = attributes["formatCode"] { customFormats[id] = code }
        case "cellXfs":
            inCellXfs = true
        case "xf" where inCellXfs:
            xfFormatIds.append(Int(attributes["numFmtId"] ?? "0") ?? 0)
        default:
            break
        }
    }

    func parser(_ parser: XMLParser, didEndElement elementName: String, namespaceURI: String?, qualifiedName: String?) {
        if localName(elementName) == "cellXfs" { inCellXfs = false }
    }
}

/// openpyxl WorkSheetParser.parse_cell with data_only=True.
private final class SheetParser: NSObject, PartParser {
    private let strings: [String]
    private let formats: [String]
    private let dates: Set<Int>
    private let durations: Set<Int>
    private let date1904: Bool

    private var cells: [Int: [Int: (CellValue?, String)]] = [:]
    private var maxRow = 0
    private var maxColumn = 0
    private var row = 0
    private var column = 0
    private var type = "n"
    private var style = 0
    private var value: String?
    private var inline = ""
    private var hasInline = false
    private var inValue = false
    private var inInlineText = false
    private var phonetic = 0
    private var merges: [MergeRange] = []

    init(strings: [String], formats: [String], dates: Set<Int>, durations: Set<Int>, date1904: Bool) {
        self.strings = strings
        self.formats = formats
        self.dates = dates
        self.durations = durations
        self.date1904 = date1904
    }

    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?, qualifiedName: String?,
                attributes: [String: String] = [:]) {
        switch localName(elementName) {
        case "row":
            row = Int(attributes["r"] ?? "") ?? (row + 1)
            column = 0
        case "c":
            if let ref = attributes["r"], let place = Xlsx.coordinate(ref) {
                row = place.0
                column = place.1
            } else {
                column += 1
            }
            type = attributes["t"] ?? "n"
            style = Int(attributes["s"] ?? "0") ?? 0
            value = nil
            inline = ""
            hasInline = false
        case "v":
            inValue = true
            value = (value ?? "")
        case "is":
            hasInline = true
        case "rPh":
            phonetic += 1
        case "mergeCell":
            let ends = (attributes["ref"] ?? "").split(separator: ":").map(String.init)
            if let first = ends.first.flatMap({ Xlsx.coordinate($0) }), let last = (ends.count > 1 ? Xlsx.coordinate(ends[1]) : first) {
                merges.append(MergeRange(minRow: first.0, minCol: first.1, maxRow: last.0, maxCol: last.1))
            }
        case "t":
            inInlineText = hasInline && phonetic == 0
        default:
            break
        }
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        if inValue { value = (value ?? "") + string }
        if inInlineText { inline += string }
    }

    func parser(_ parser: XMLParser, didEndElement elementName: String, namespaceURI: String?, qualifiedName: String?) {
        switch localName(elementName) {
        case "v": inValue = false
        case "t": inInlineText = false
        case "rPh": phonetic -= 1
        case "c": finishCell()
        default: break
        }
    }

    private func finishCell() {
        let format = style < formats.count ? formats[style] : "General"
        var result: CellValue?
        let raw = (value?.isEmpty ?? true) ? nil : value
        if type == "inlineStr" {
            result = hasInline ? .text(inline) : nil
        } else if let raw {
            switch type {
            case "s":
                if let i = Int(raw), i >= 0, i < strings.count { result = .text(strings[i]) }
            case "b":
                result = .bool((Int(raw) ?? 0) != 0)
            case "str", "e":
                result = .text(raw)
            case "d":
                result = .text(raw)
            default:
                let number: CellValue
                if raw.contains(".") || raw.contains("E") || raw.contains("e") {
                    number = .double(Double(raw) ?? 0)
                } else if let i = Int64(raw) {
                    number = .int(i)
                } else {
                    number = .double(Double(raw) ?? 0)
                }
                if dates.contains(style) && !durations.contains(style) {
                    let serial: Double
                    switch number {
                    case let .int(i): serial = Double(i)
                    case let .double(d): serial = d
                    default: serial = 0
                    }
                    result = Xlsx.fromExcel(serial, date1904: date1904) ?? .text("#VALUE!")
                } else {
                    result = number
                }
            }
        }
        guard row > 0, column > 0 else { return }
        cells[row, default: [:]][column] = (result, format)
        maxRow = max(maxRow, row)
        maxColumn = max(maxColumn, column)
    }

    func worksheet(name: String) -> Worksheet {
        var rows: [[CellValue?]] = []
        var formatRows: [[String]] = []
        guard maxRow > 0 else { return Worksheet(name: name, rows: [], formats: []) }
        for r in 1...maxRow {
            var values = [CellValue?](repeating: nil, count: maxColumn)
            var fmts = [String](repeating: "General", count: maxColumn)
            for (c, cell) in cells[r] ?? [:] {
                values[c - 1] = cell.0
                fmts[c - 1] = cell.1
            }
            rows.append(values)
            formatRows.append(fmts)
        }
        return Worksheet(name: name, rows: rows, formats: formatRows, merges: merges)
    }
}
