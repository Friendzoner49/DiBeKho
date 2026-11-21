import DiBeKhoCore
import SwiftUI

/// The '₫ | ¥' switch at the bottom left (ui/currency_switch.py): ¥ shows every amount of the app in yuan at today's
/// market rate; ₫ goes back to dong. The data and every file stay in VND; only the text on screen changes. The rate is
/// kept in fx.json for offline use and asked again in the background when older than ten minutes (while yuan is shown),
/// and whenever the user presses ⟳ or Quét lại. The choice is remembered in the app's own preferences (config.json of
/// the Python app is never written here).
@MainActor
final class CurrencyModel: ObservableObject {
    @Published private(set) var cny = false
    @Published private(set) var busy = false
    @Published private(set) var problem = false
    @Published private(set) var info = ""
    /// the screens must draw their amounts again
    var changed: () -> Void = {}
    private var switchAfter = false
    private var timer: Timer?

    init() {
        FX.rate = FX.cached()
        let wanted = UserDefaults.standard.string(forKey: "currency") == "cny"
        FX.currency = wanted && FX.rate != nil ? "cny" : "vnd"
        cny = FX.currency == "cny"
        showInfo()
        if cny && !FX.isFresh(FX.rate) {
            refresh()
        } else if wanted && FX.rate == nil {
            switchAfter = true  // yuan chosen but no rate kept on this computer: dong until it arrives
            refresh()
        }
        timer = Timer.scheduledTimer(withTimeInterval: FX.freshSeconds, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refreshIfShown() }
        }
    }

    func choose(cny wantYuan: Bool, explicit: Bool = true) {
        if wantYuan && FX.rate == nil {
            switchAfter = true  // no rate yet: stay in dong while it is fetched, then switch
            refresh(explicit: true)
            return
        }
        set(wantYuan ? "cny" : "vnd")
        if wantYuan && !FX.isFresh(FX.rate) { refresh() }
    }

    private func set(_ currency: String) {
        FX.currency = currency
        cny = currency == "cny"
        UserDefaults.standard.set(currency, forKey: "currency")
        showInfo()
        changed()
    }

    private func showInfo() {
        guard let rate = FX.rate else {
            info = busy ? t("fx.no_rate") : (problem ? t("fx.no_rate_error") : "")
            return
        }
        let f = DateFormatter()
        f.dateFormat = "HH:mm dd/MM"
        var text = t("fx.rate_short", ["rate": Format.dong(rate.vndPerCny.rounded()), "when": f.string(from: rate.updated)])
        if problem {
            f.dateFormat = "dd/MM HH:mm"
            text += "\n" + t("fx.offline", ["when": f.string(from: rate.fetched)])
        }
        info = text
    }

    /// Quét lại / F5 and the ten-minute timer: a new rate when the amounts are in yuan (no message on failure).
    func refreshIfShown() {
        if FX.currency == "cny" { refresh() }
    }

    func refresh(explicit: Bool = false) {
        guard !busy else { return }
        busy = true
        showInfo()
        Task {
            var got: FX.Rate?
            var failed = false
            do { got = try await FX.fetch() } catch { failed = true }  // offline, VPN, provider down: the cached rate stays
            busy = false
            problem = failed
            if let got { FX.rate = got }
            showInfo()
            if switchAfter {
                switchAfter = false
                if FX.rate != nil {
                    set("cny")
                    return
                }
            }
            if FX.rate == nil && explicit { UI.error(t("fx.no_rate_error")) }
            if got != nil && FX.currency == "cny" { changed() }  // new rate: the amounts change
        }
    }
}

struct CurrencySwitch: View {
    @ObservedObject var currency: CurrencyModel

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 0) {
                pick("₫", on: !currency.cny, help: t("fx.show_vnd")) { currency.choose(cny: false) }
                pick("¥", on: currency.cny, help: t("fx.show_cny")) { currency.choose(cny: true) }
                Button { currency.refresh(explicit: true) } label: { Text("⟳") }
                    .buttonStyle(.plain).padding(.leading, 8).help(t("fx.refresh")).disabled(currency.busy)
                Spacer()
            }
            if !currency.info.isEmpty {
                Text(currency.info).font(.caption).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
                    .help(FX.rate.map { t("fx.source", ["source": $0.source]) } ?? "")
            }
        }
        .padding(.horizontal, 6)
    }

    private func pick(_ label: String, on: Bool, help: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(label).bold(on).frame(width: 44, height: 24 * UI.scale)
                .background(RoundedRectangle(cornerRadius: 5).fill(on ? Color.primary.opacity(0.18) : Color.clear))
                .overlay(RoundedRectangle(cornerRadius: 5).stroke(Color.primary.opacity(0.25)))
        }
        .buttonStyle(.plain).help(help)
    }
}
