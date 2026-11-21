import Foundation

/// How the Python app shows numbers, money and dates (core/text.fmt_qty, core/fx.native_text, ui/common.fmt_date),
/// checked against it by Golden.swift. Python's round() goes to the even number on a tie (2.5 -> 2): so does this.
public enum Format {
    /// 1234567 -> "1.234.567" (Vietnamese thousands dots).
    static func grouped(_ digits: String) -> String {
        var sign = ""
        var body = Substring(digits)
        if body.hasPrefix("-") {
            sign = "-"
            body = body.dropFirst()
        }
        var out: [Character] = []
        for (i, ch) in body.reversed().enumerated() {
            if i > 0 && i % 3 == 0 { out.append(".") }
            out.append(ch)
        }
        return sign + String(out.reversed())
    }

    /// Two decimals at most, trailing zeros dropped, Vietnamese separators: 1234.5 -> "1.234,5".
    static func twoDecimals(_ value: Double) -> String {
        var text = String(format: "%.2f", value)  // correctly rounded, as Python's format
        if text.hasPrefix("-0.00") { text = "0.00" }
        while text.hasSuffix("0") { text.removeLast() }
        if text.hasSuffix(".") { text.removeLast() }
        let parts = text.split(separator: ".", omittingEmptySubsequences: false)
        let whole = grouped(String(parts[0]))
        return parts.count > 1 ? "\(whole),\(parts[1])" : whole
    }

    /// Whole dong: 1188000 -> "1.188.000".
    public static func dong(_ value: Double) -> String {
        let rounded = value.rounded(.toNearestOrEven)
        return grouped(String(format: "%.0f", rounded == 0 ? 0 : rounded))
    }

    /// A quantity: 5 -> "5", 2.5 -> "2,5", nothing -> "".
    public static func quantity(_ value: Double?) -> String {
        guard let value else { return "" }
        if value == value.rounded() && abs(value) < 1e15 {
            return grouped(String(format: "%.0f", value == 0 ? 0 : value))
        }
        return twoDecimals(value)
    }

    /// "¥308,88"; Vietnamese writes 1.234,5, English and Chinese 1,234.5.
    public static func yuan(_ value: Double) -> String {
        let text = twoDecimals(value)
        guard L10n.language != "vi" else { return "¥" + text }
        let swapped = text.map { $0 == "." ? "," : ($0 == "," ? "." : $0) }
        return "¥" + String(swapped)
    }

    /// An amount (dong in the data) as the screens show it: dong, or yuan at the chosen rate while the switch is on ¥.
    public static func showMoney(_ value: Double?) -> String {
        guard let value else { return "—" }
        guard FX.inCny, let r = FX.rate else { return dong(value) }
        return yuan(value / r.vndPerCny)
    }

    /// The amount of one note in its own currency, with the screens on dong: dong as is; yuan as printed, then
    /// "(≈ … ₫)" at the rate kept with the note when approx. Unknown -> "—".
    public static func money(_ value: Double?, currency: String, rate: Double?, approx: Bool = true) -> String {
        guard let value else { return "—" }
        guard currency == "CNY" else { return showMoney(value) }
        let text = yuan(value)
        let rate = (rate ?? 0) != 0 ? rate : FX.rate?.vndPerCny  // the note's own rate, else today's
        guard !FX.inCny, approx, let rate, rate != 0 else { return text }
        return "\(text) (≈ \(dong(value * rate)) ₫)"
    }

    /// A sum over notes of both currencies, never one number: "120.000.000 ₫ + ¥4.800 (≈ 137.280.000 ₫)".
    /// vnd = notes in dong, cny = notes in yuan, approx = the yuan as dong at the notes' own rates.
    public static func both(_ vnd: Double?, _ cny: Double?, approx: Double?, brackets: Bool = true) -> String {
        guard let cny, cny != 0 else { return showMoney(vnd) }
        if FX.inCny, let r = FX.rate { return yuan((vnd ?? 0) / r.vndPerCny + cny) }
        var approx = approx
        if (approx ?? 0) == 0, let r = FX.rate { approx = cny * r.vndPerCny }
        let yuanText = yuan(cny)
        let hasApprox = (approx ?? 0) != 0 && brackets
        guard let vnd, vnd != 0 else {
            return yuanText + (hasApprox ? " (≈ \(dong(approx ?? 0)) ₫)" : "")
        }
        return "\(dong(vnd)) ₫ + \(yuanText)" + (hasApprox ? " (≈ \(dong(vnd + (approx ?? 0))) ₫)" : "")
    }

    /// "2026-11-05" -> "05/11/2026".
    public static func date(_ iso: String?) -> String {
        guard let iso, iso.count >= 10 else { return "" }
        let parts = iso.prefix(10).split(separator: "-")
        guard parts.count == 3 else { return "" }
        return "\(parts[2])/\(parts[1])/\(parts[0])"
    }
}
