import Foundation

/// The search rules of the Python app (core/text.py), checked against it by Golden.swift.
public enum TextRules {
    /// Lowercase, no Vietnamese accents, đ -> d, full-width digits and letters made plain (NFKD).
    public static func unaccent(_ text: String?) -> String {
        guard let text else { return "" }
        let decomposed = text.lowercased().decomposedStringWithCompatibilityMapping
        var out = String.UnicodeScalarView()
        for scalar in decomposed.unicodeScalars where scalar.properties.canonicalCombiningClass == .notReordered {
            out.append(scalar)
        }
        return String(out).replacingOccurrences(of: "đ", with: "d")
    }

    /// Letters and digits only (Python's [\W_]+ removed): 'FS-101' -> 'fs101'.
    static func alnum(_ text: String) -> String {
        var out = String.UnicodeScalarView()
        for scalar in text.unicodeScalars where isWordChar(scalar) {
            out.append(scalar)
        }
        return String(out)
    }

    private static func isWordChar(_ scalar: Unicode.Scalar) -> Bool {
        switch scalar.properties.generalCategory {
        case .uppercaseLetter, .lowercaseLetter, .titlecaseLetter, .modifierLetter, .otherLetter:
            return true
        default:
            return scalar.properties.numericType != nil
        }
    }

    /// Python core/text.clean: NFC, every run of whitespace one space, trimmed. nil -> "".
    public static func clean(_ text: String?) -> String {
        (text ?? "").precomposedStringWithCanonicalMapping
            .split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
    }

    /// Python core/text.match_key: the key that recognises the same product line across notes (NFKC, lowercase,
    /// no whitespace at all, no trailing . , ;).
    public static func matchKey(_ name: String, _ spec: String) -> String {
        func norm(_ s: String) -> String {
            var text = String(s.precomposedStringWithCompatibilityMapping.lowercased().filter { !$0.isWhitespace })
            while let last = text.last, ".,;".contains(last) { text.removeLast() }
            return text
        }
        return "\(norm(name))|\(norm(spec))"
    }

    /// Python _CJK: CJK symbols and punctuation, CJK ideographs, full-width forms.
    static func isCJK(_ scalar: Unicode.Scalar) -> Bool {
        switch scalar.value {
        case 0x3000...0x303F, 0x3400...0x4DBF, 0x4E00...0x9FFF, 0xFF00...0xFFEF: return true
        default: return false
        }
    }

    public static func hasCJK(_ text: String) -> Bool {
        text.unicodeScalars.contains(where: isCJK)
    }

    static func isLetter(_ scalar: Unicode.Scalar) -> Bool {
        switch scalar.properties.generalCategory {
        case .uppercaseLetter, .lowercaseLetter, .titlecaseLetter, .modifierLetter, .otherLetter: return true
        default: return false
        }
    }

    static func mostlyLatin(_ text: String) -> Bool {
        let letters = text.unicodeScalars.filter(isLetter)
        guard !letters.isEmpty else { return false }
        let cjk = letters.filter(isCJK).count
        return Double(cjk) / Double(letters.count) < 0.3
    }

    /// Python split_bilingual_name: '背水涂\nvữa chống thấm ...' -> (Vietnamese lines, Chinese lines).
    public static func splitBilingual(_ raw: String) -> (vi: String, zh: String) {
        let lines = raw.precomposedStringWithCanonicalMapping.split(whereSeparator: { $0.isNewline })
            .map { clean(String($0)) }.filter { !$0.isEmpty }
        let zh = lines.filter { hasCJK($0) && !mostlyLatin($0) }
        let vi = lines.filter { !zh.contains($0) }
        return (vi.joined(separator: " "), zh.joined(separator: " "))
    }

    /// Search boxes: every word typed must appear somewhere, in any order, without accents, ignoring spaces and
    /// punctuation ('fs101' finds 'FS-101').
    public static func matchesWords(_ needle: String, _ haystack: String) -> Bool {
        let hay = alnum(unaccent(haystack))
        let words = unaccent(needle).split(whereSeparator: { $0.isWhitespace }).map { alnum(String($0)) }
        return words.allSatisfy { $0.isEmpty || hay.contains($0) }
    }
}
