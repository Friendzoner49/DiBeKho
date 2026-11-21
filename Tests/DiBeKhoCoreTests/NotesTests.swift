import Foundation
import XCTest

@testable import DiBeKhoCore

/// Phase 2: the Swift reader reads every made-up note exactly as the Python reader does (GoldenNotes), and, on the
/// developer's Mac, the customer's own notes (DIBEKHO_REAL_NOTES: a folder made by tools/gen_real_notes.py, never
/// committed).
final class NotesTests: XCTestCase {
    private var notes: URL { Bundle.module.resourceURL!.appendingPathComponent("Notes") }

    func testEveryMadeUpNoteReadsAsInPython() throws {
        XCTAssertFalse(GoldenNotes.notes.isEmpty)
        // every bundled note is compared: a note added later without regenerating the golden data fails here
        let bundled = try FileManager.default.contentsOfDirectory(atPath: notes.path).filter { $0.hasSuffix(".xlsx") }
        XCTAssertEqual(Set(bundled), Set(GoldenNotes.notes.keys))
        for (name, expected) in GoldenNotes.notes.sorted(by: { $0.key < $1.key }) {
            let url = notes.appendingPathComponent(name)
            XCTAssertTrue(FileManager.default.fileExists(atPath: url.path), name)
            XCTAssertEqual(NoteLines.lines(url), expected, name)
        }
    }

    func testTheCustomersOwnNotesWhenGiven() throws {
        guard let folder = ProcessInfo.processInfo.environment["DIBEKHO_REAL_NOTES"] else {
            throw XCTSkip("DIBEKHO_REAL_NOTES not set (the customer's notes are only on the developer's machines)")
        }
        let base = URL(fileURLWithPath: folder)
        let data = try Data(contentsOf: base.appendingPathComponent("expected.json"))
        let expected = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: [String]])
        var different: [String] = []
        for (name, lines) in expected.sorted(by: { $0.key < $1.key }) {
            let got = NoteLines.lines(base.appendingPathComponent(name))
            if got != lines {
                different.append(name)
                // which line differs, without printing the note itself into a shared log by mistake: line numbers only
                let first = zip(got, lines).enumerated().first { $0.element.0 != $0.element.1 }?.offset ?? min(got.count, lines.count)
                print("DIFFERENT \(name): first difference at line \(first) (Swift \(got.count) lines, Python \(lines.count))")
            }
        }
        print("customer's notes: \(expected.count) read, \(different.count) different")
        XCTAssertEqual(different, [], "notes read differently from the Python app")
    }

    func testCellsAsOpenpyxlSeesThem() {
        XCTAssertTrue(Xlsx.isDateFormat("dd/mm/yyyy"))
        XCTAssertTrue(Xlsx.isDateFormat("mm-dd-yy"))
        XCTAssertFalse(Xlsx.isDateFormat("General"))
        XCTAssertFalse(Xlsx.isDateFormat(#"_-* #,##0\ [$CNY]_-;\-* #,##0\ [$CNY]_-"#))
        XCTAssertFalse(Xlsx.isDateFormat("\"$\"#,##0_);(\"$\"#,##0)"))
        XCTAssertEqual(Xlsx.fromExcel(46_300, date1904: false), .date(2026, 10, 5, 0, 0, 0))
        XCTAssertEqual(Xlsx.fromExcel(46_299, date1904: false), .date(2026, 10, 4, 0, 0, 0))
        XCTAssertEqual(Xlsx.fromExcel(0.5, date1904: false), .time(12, 0, 0))
        XCTAssertEqual(Xlsx.coordinate("BC12")?.0, 12)
        XCTAssertEqual(Xlsx.coordinate("BC12")?.1, 55)
        XCTAssertEqual(CellValue.double(100000).pythonText, "100000.0")
        XCTAssertEqual(CellValue.double(2.5).pythonText, "2.5")
        XCTAssertEqual(CellValue.int(101).pythonText, "101")
        XCTAssertEqual(DeliveryNoteReader.repr(.text("abc")), "'abc'")
        XCTAssertEqual(DeliveryNoteReader.repr(.text("it's")), "\"it's\"")
        XCTAssertEqual(DeliveryNoteReader.toNumber(.text("1.500")), nil)
        XCTAssertEqual(DeliveryNoteReader.toNumber(.text("2,5")), 2.5)
        XCTAssertEqual(DeliveryNoteReader.toMoney(.text("1.188.000 đ")), 1_188_000)
    }
}
