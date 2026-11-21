import AppKit
import DiBeKhoCore
import SwiftUI

/// Python ui/staff_pushes.py: what the staff's machines sent for the owner to approve, as a table (Người gửi, Máy, Nội
/// dung, Gửi lúc, Thao tác; the whole list of a request as the tooltip of its Nội dung). Shown in Cần xử lý on the
/// owner's machine. ⚠ Not run against a real Cloud.
struct StaffRequestsBox: View {
    @ObservedObject var cloud: CloudRunner

    /// staff_pushes.SHOWN: lines of one request in the question before approving; the rest is counted
    static let shown = 30

    var body: some View {
        GroupBox(t("staff.title")) {
            VStack(alignment: .leading, spacing: 8) {
                Hint(t("staff.hint"))
                VStack(spacing: 0) {
                    TableHeader(cells: [(t("web.col_sender"), 130), (t("cloud.col_device"), 150), (t("web.col_detail"), nil),
                                        (t("web.col_sent"), 140), (t("pending.actions"), 200)])
                    ForEach(Array(cloud.staffRequests.enumerated()), id: \.offset) { _, item in
                        row(item)
                        Divider().opacity(0.4)
                    }
                }
                .tableBox()
            }
            .frame(maxWidth: .infinity, alignment: .leading).padding(6)
        }
    }

    private func row(_ item: [String: Any]) -> some View {
        let sender = Self.sender(item)
        let device = item["device"] as? String ?? ""
        let lines = Self.describe(item["summary"])
        return HStack(spacing: 8) {
            Text(sender).lineLimit(1).frame(width: 130, alignment: .leading)
            Text(device).lineLimit(1).frame(width: 150, alignment: .leading)
            Text(Self.short(item["summary"])).lineLimit(1).frame(maxWidth: .infinity, alignment: .leading)
                .help(lines.prefix(Self.shown).joined(separator: "\n"))
            Text(CloudClient.localTime(item["created_at"] as? String)).lineLimit(1)
                .frame(width: 140, alignment: .leading)
            HStack(spacing: 6) {
                Button(t("staff.approve")) { approve(item, sender: sender, device: device, lines: lines) }
                Button(t("pending.web_reject")) {
                    if let reason = Self.askReason(t("staff.reject_reason", ["sender": sender])) {
                        ActivityLog.write("click", "staff_push reject")
                        let trimmed = reason.trimmingCharacters(in: .whitespaces)
                        Task { await cloud.decide(item, approve: false, reason: trimmed) }
                    }
                }
            }
            .frame(width: 200, alignment: .leading)
        }
        .padding(.horizontal, 6).padding(.vertical, 4)
    }

    private func approve(_ item: [String: Any], sender: String, device: String, lines: [String]) {
        var text = lines.prefix(Self.shown).map { "• " + $0 }.joined(separator: "\n")
        if lines.count > Self.shown { text += "\n" + t("staff.more", ["n": String(lines.count - Self.shown)]) }
        guard UI.ask(t("staff.confirm_approve", ["sender": sender, "device": device, "lines": text])) else { return }
        ActivityLog.write("click", "staff_push approve")
        Task { await cloud.decide(item, approve: true) }
    }

    static func sender(_ item: [String: Any]) -> String {
        let s = item["sender"] as? String ?? ""
        return s.isEmpty ? t("web.unknown_sender") : s
    }

    private static func items(_ any: Any?) -> [[String: Any]] {
        ((any as? [Any]) ?? []).compactMap { $0 as? [String: Any] }
    }

    private static func value(_ s: [String: Any], _ k: String) -> String {
        guard let x = s[k], !(x is NSNull) else { return "" }
        return "\(x)"
    }

    private static func number(_ s: [String: Any], _ k: String) -> String {
        String((s[k] as? NSNumber)?.intValue ?? Int(value(s, k)) ?? 0)
    }

    /// staff_pushes.describe: one line per item of the request, in the interface language
    static func describe(_ any: Any?) -> [String] {
        items(any).compactMap { s -> String? in
            switch value(s, "t") {
            case "doc":
                let kindKey = value(s, "kind")
                let kind = kindKey.isEmpty ? t("sync.table.documents") : t("kind.\(kindKey)")
                let text = t(value(s, "status") == "active" ? "staff.item_doc" : "staff.item_doc_closed",
                             ["kind": kind, "code": value(s, "code"), "date": Format.date(value(s, "date")),
                              "n": number(s, "lines")])
                let customer = value(s, "customer")
                return text + (customer.isEmpty ? "" : " · \(customer)")
            case "doc_deleted": return t("staff.item_doc_deleted")
            case "product": return t("staff.item_product", ["code": value(s, "code"), "name": value(s, "name")])
            case "product_deleted": return t("staff.item_product_deleted")
            case "customer": return t("staff.item_customer", ["name": value(s, "name")])
            case "other": return t("staff.item_other", ["n": number(s, "n")])
            default: return nil
            }
        }
    }

    /// staff_pushes.short: "{docs} phiếu · {rest} mục khác"
    static func short(_ any: Any?) -> String {
        let list = items(any)
        let docs = list.filter { ["doc", "doc_deleted"].contains($0["t"] as? String ?? "") }.count
        return t("staff.short", ["docs": String(docs), "rest": String(list.count - docs)])
    }

    @MainActor private static func askReason(_ prompt: String) -> String? {
        let alert = NSAlert()
        alert.messageText = t("pending.web_reject")
        alert.informativeText = prompt
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
        alert.accessoryView = field
        alert.addButton(withTitle: t("btn.ok"))
        alert.addButton(withTitle: t("btn.cancel"))
        return alert.runModal() == .alertFirstButtonReturn ? field.stringValue : nil
    }
}
