import DiBeKhoCore
import SwiftUI

/// 'Tải file gốc từ Cloud' (user, 27/11/2026; Python ui/originals.py): the original files of the chosen orders come down
/// to this Mac, with a progress bar that says which order is on the way. Used by the order window ('Mở file gốc' too)
/// and the order list.
@MainActor
final class OriginalsDownloader: ObservableObject {
    typealias Order = (hash: String, code: String)

    @Published private(set) var running = false
    @Published private(set) var done = 0
    @Published private(set) var total = 1
    @Published private(set) var label = ""
    private var task: Task<Void, Never>?

    /// Only the owner's account reads the cloud's files, and only when signed in.
    static var allowed: Bool {
        guard let cfg = CloudConfig.load() else { return false }
        return cfg.hasSavedSession && !cfg.isStaff
    }

    /// then(result): nil when the cloud could not be reached; not called after Huỷ.
    func start(_ model: AppModel, _ orders: [Order], then: @escaping @MainActor (OriginalsDownload?) -> Void) {
        guard !running else { return }
        let codes = Dictionary(orders.map { ("\($0.hash).xlsx", $0.code) }, uniquingKeysWith: { first, _ in first })
        running = true
        done = 0
        total = max(codes.count, 1)
        label = t("originals.connecting")
        task = Task { @MainActor in
            let result = await model.cloud.downloadOriginals(codes.keys.sorted()) { [weak self] i, n, name in
                self?.done = i
                self?.total = max(n, 1)
                self?.label = t("originals.progress", ["n": String(i + 1), "total": String(n), "code": codes[name] ?? ""])
            }
            if Task.isCancelled { return }
            running = false
            UI.later { then(result) }
        }
    }

    func cancel() {
        task?.cancel()
        running = false
    }

    /// The plain words about what came down and what did not (originals.summary)
    static func summary(_ result: OriginalsDownload, _ orders: [Order]) -> String {
        let codes = Dictionary(orders.map { ("\($0.hash).xlsx", $0.code) }, uniquingKeysWith: { first, _ in first })
        func listed(_ names: [String]) -> String { names.map { codes[$0] ?? "" }.joined(separator: ", ") }
        var parts: [String] = []
        if !result.got.isEmpty { parts.append(t("originals.got", ["n": String(result.got.count)])) }
        if !result.absent.isEmpty { parts.append(t("originals.absent", ["codes": listed(result.absent)])) }
        if !result.failed.isEmpty { parts.append(t("originals.failed", ["codes": listed(result.failed)])) }
        return parts.joined(separator: "\n\n")
    }
}

/// The progress line, shown only while downloading.
struct OriginalsProgress: View {
    @ObservedObject var downloader: OriginalsDownloader

    var body: some View {
        if downloader.running {
            HStack(spacing: 10) {
                ProgressView(value: Double(downloader.done), total: Double(downloader.total))
                    .frame(width: 220 * UI.scale)
                Text(downloader.label)
                Button(t("btn.cancel")) { downloader.cancel() }
                Spacer()
            }
        }
    }
}
