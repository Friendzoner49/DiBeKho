import DiBeKhoCore
import SwiftUI

extension WebRequest: Identifiable {}

/// Python ui/web_requests.py: 'Yêu cầu từ nhân viên (web)' (goods-in slips, Excel delivery notes and stock counts staff
/// sent from the web page). Nothing reaches the books before the owner approves here. Shown in Cần xử lý on the
/// owner's machine. ⚠ Not run against a real Cloud.
struct WebRequestsBox: View {
    @ObservedObject var cloud: CloudRunner
    @State private var counting: WebRequest?

    var body: some View {
        GroupBox(t("web.title")) {
            VStack(alignment: .leading, spacing: 8) {
                Hint(t("web.hint"))
                // the table of web_requests.WebRequestsPanel: Loại, Người gửi, Nội dung, Gửi lúc, Thao tác
                VStack(spacing: 0) {
                    TableHeader(cells: [(t("web.col_kind"), 190), (t("web.col_sender"), 130), (t("web.col_detail"), nil),
                                        (t("web.col_sent"), 140), (t("pending.actions"), 240)])
                    ForEach(cloud.webRequests) { item in
                        HStack(spacing: 8) {
                            Text(CloudRunner.webKind(item.kind)).lineLimit(1).frame(width: 190, alignment: .leading)
                            Text(item.sender.isEmpty ? t("web.unknown_sender") : item.sender).lineLimit(1)
                                .frame(width: 130, alignment: .leading)
                            Text(CloudRunner.webDetail(item)).lineLimit(2).frame(maxWidth: .infinity, alignment: .leading)
                            Text(CloudClient.localTime(item.createdAt)).lineLimit(1).frame(width: 140, alignment: .leading)
                            HStack(spacing: 6) {
                                Button(t("web.apply")) { review(item) }
                                Button(t("pending.web_reject")) {
                                    if UI.ask(t("pending.web_reject_ask")) { Task { await cloud.rejectWeb(item) } }
                                }
                            }
                            .frame(width: 240, alignment: .leading)
                        }
                        .padding(.horizontal, 6).padding(.vertical, 4)
                        Divider().opacity(0.4)
                    }
                }
                .tableBox()
                HStack {
                    Spacer()
                    Button(t("web.apply_all")) {
                        let list = cloud.webRequests
                        let receipts = list.filter { $0.kind == WebInbox.receipt }.count
                        let files = list.filter { $0.kind == WebInbox.deliveryFile }.count
                        if UI.ask(t("web.apply_all_confirm", ["receipts": String(receipts), "files": String(files)])) {
                            Task { await cloud.approveAllWeb() }
                        }
                    }
                    .disabled(!cloud.webRequests.contains(where: { $0.kind != WebInbox.stockCount }))
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading).padding(6)
        }
        .sheet(item: $counting) { item in WebCountSheet(cloud: cloud, item: item) { counting = nil } }
    }

    private func review(_ item: WebRequest) {
        switch item.kind {
        case WebInbox.receipt:
            switch cloud.webReceiptText(item) {
            case .failure(let error): UI.error(error.message)
            case .success(let text): if UI.ask(text) { Task { await cloud.approveWeb(item) } }
            }
        case WebInbox.deliveryFile:
            let problems = WebInbox.checkDelivery(item)
            if !problems.isEmpty { UI.error(problems.joined(separator: " ")); return }
            let name = (item.payload["file_name"] as? String) ?? ""
            let who = item.sender.isEmpty ? t("web.unknown_sender") : item.sender
            if UI.ask(t("web.file_confirm", ["name": name, "sender": who])) { Task { await cloud.approveWeb(item) } }
        default:
            counting = item
        }
    }
}

/// The owner checks a count sent from the web: counted, what the app knew when it was sent, the difference.
struct WebCountSheet: View {
    @ObservedObject var cloud: CloudRunner
    let item: WebRequest
    let close: () -> Void

    var body: some View {
        let info = cloud.webCount(item)
        let rows = (info?.rows ?? []).sorted { (abs($0.diff), $1.code) > (abs($1.diff), $0.code) }
        let different = rows.filter { abs($0.diff) > 1e-9 }.count
        VStack(alignment: .leading, spacing: 10) {
            Text(t("web.count_title", ["sender": item.sender.isEmpty ? t("web.unknown_sender") : item.sender])).font(.title3).bold()
            if let info {
                Hint(t("web.count_head", ["place": UI.locationName(info.place), "date": Format.date(info.day),
                                          "sent": CloudClient.localTime(item.createdAt)]))
                if !info.problems.isEmpty { Text("⚠ " + info.problems.joined(separator: " ")).foregroundColor(.red) }
            }
            Text(t("web.count_summary", ["different": String(different), "total": String(rows.count)]))
            // the table of web_requests.WebCountDialog
            DataTable(
                columns: [Column(title: t("col.code"), width: 90), Column(title: t("col.product"), width: 300),
                          Column(title: t("web.col_counted"), width: 90, numeric: true),
                          Column(title: t("web.col_system"), width: 120, numeric: true),
                          Column(title: t("web.col_diff"), width: 90, numeric: true)],
                rows: rows.map { r in
                    [r.code, r.name, Format.quantity(r.counted), Format.quantity(r.system), String(format: "%+g", r.diff)]
                },
                sortable: false)
            HStack {
                Spacer()
                // Enter never approves a count by accident (no default button, as the Python dialog)
                Button(t("web.count_go")) {
                    close()
                    Task { await cloud.approveWeb(item) }
                }
                .disabled(info == nil || !(info?.problems.isEmpty ?? false))
                Button(t("btn.cancel")) { close() }
            }
        }
        .padding(16)
        .frame(minWidth: 820, minHeight: 520)
    }
}
