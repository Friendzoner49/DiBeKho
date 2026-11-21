import DiBeKhoCore
import Foundation
import GRDB

/// What a detail window shows (ui/details.py): a title, label/value pairs, then its tables and the lines under them.
struct DetailData: Identifiable {
    /// what a double click on a row of a table opens (the row's id in `ids`)
    enum Opens { case none, product, document, customer }
    /// a value shown red and bold (a document not in force), bigger and bold (the stock), or in the warning colour
    enum Emphasis { case alert, big, warn }

    struct Table {
        let title: String
        let columns: [Column]
        let rows: [[String]]
        var tones: [RowTone] = []
        var ids: [Int64?] = []
        var opens: Opens = .none
        var stretch: Int? = 1
        var sortable = true
        /// in a framed box with its title (QGroupBox), else under a bold title (none when empty)
        var boxed = false
    }

    /// the value of the 'Lấy hàng từ' row of a delivery note: the place picker is drawn there
    static let placeMarker = "\u{1}place"

    let id = UUID()
    let title: String
    let info: [(String, String)]
    let tables: [Table]
    /// a document's window: its id, kind and status (for Huỷ phiếu / Sửa phiếu…)
    var docId: Int64?
    var docKind = ""
    var docStatus = ""
    var docCode = ""
    /// a delivery note's window: the file it came from, where its goods were taken from (and whether the user chose it),
    /// or both places at once (a stock issue note)
    var sourceHash = ""
    var sourceFile = ""
    var docLocation: Int64?
    var docLocationSet = true
    var docMixed = false
    /// a customer's window: for 'Sửa thông tin khách hàng…'
    var customerId: Int64?
    /// rows of `info` shown in another style, by index
    var emphasis: [Int: Emphasis] = [:]
    /// a row of `info` whose value is a link to that customer's window
    var customerLink: (row: Int, id: Int64)?
    /// grey lines under the label/value pairs (a customer's unpriced orders)
    var infoHints: [String] = []
    /// lines under the tables: text (may hold <b>…</b>) and whether it is a grey hint
    var footer: [(String, Bool)] = []
}

/// The detail windows of the Python app (Chi tiết đơn, Chi tiết khách, Chi tiết mặt hàng), read only.
enum Details {
    static func text(_ row: Row, _ column: String) -> String {
        let value: String? = row[column]
        return value ?? ""
    }

    static func number(_ row: Row, _ column: String) -> Double? {
        let value: Double? = row[column]
        return value
    }

    static func moveName(_ kind: String) -> String {
        switch kind {
        case "delivery_out": return t("move.delivery_out")
        case "delivery_reverse": return t("move.delivery_reverse")
        case "receipt_in": return t("move.receipt_in")
        case "receipt_reverse": return t("move.receipt_reverse")
        case "count_adjust": return t("move.count_adjust")
        case "count_reverse": return t("move.count_reverse")
        case "transfer_in": return t("move.transfer_in")
        case "transfer_out": return t("move.transfer_out")
        case "transfer_reverse": return t("move.transfer_reverse")
        case "trial_out": return t("move.trial_out")
        case "trial_reverse": return t("move.trial_reverse")
        default: return kind
        }
    }

    static func kindName(_ kind: String) -> String {
        switch kind {
        case "delivery": return t("kind.delivery")
        case "receipt": return t("kind.receipt")
        case "stock_count": return t("kind.stock_count")
        case "transfer": return t("kind.transfer")
        case "trial": return t("kind.trial")
        default: return kind
        }
    }

    static func productName(_ row: Row) -> String {
        [text(row, "name_vi"), text(row, "variant")].filter { !$0.isEmpty }.joined(separator: " ")
    }

    // ---- Chi tiết đơn (details.DocumentDialog)

    static func order(_ db: Database, id: Int64) throws -> DetailData? {
        guard let head = try Lookup.documentHead(db, id: id) else { return nil }
        let lines = try Lookup.documentLines(db, id: id)
        let kind = text(head, "kind"), code = text(head, "code"), status = text(head, "status")
        let currency = text(head, "currency")
        let rate = number(head, "fx_rate")
        func money(_ v: Double?, approx: Bool = true) -> String {
            Format.money(v, currency: currency, rate: rate, approx: approx)
        }
        let location: Int64? = head["location_id"]
        let customerId: Int64? = head["customer_id"]
        let title: String
        if kind == "delivery" {
            title = t("doc.title_delivery", ["code": code])
        } else if kind == "receipt" && !code.isEmpty {
            title = t("doc.title_receipt", ["code": code])
        } else {
            title = kindName(kind)
        }

        var info: [(String, String)] = [(t("col.date"), Format.date(text(head, "doc_date"))),
                                        (t("col.status"), t("status.\(status)"))]
        var emphasis: [Int: DetailData.Emphasis] = [:]
        if status != "active" { emphasis[1] = .alert }
        var link: (row: Int, id: Int64)?
        if kind == "delivery" {
            if let customerId {
                link = (info.count, customerId)
                info.append((t("col.customer"), text(head, "customer_name")))
            }
            info += [(t("col.contact"), text(head, "contact")), (t("col.phone"), text(head, "phone")),
                     (t("col.address"), text(head, "address"))]
        }
        let mixed = try kind == "delivery" && Ledger.isMixed(db, id)
        if mixed {
            info.append((t("loc.taken_from"), t("loc.both")))
        } else if kind == "delivery" {
            info.append((t("loc.taken_from"), DetailData.placeMarker))
        } else if kind == "receipt" {
            info.append((t("loc.put_in"), UI.locationName(location)))
        } else if kind == "transfer" {
            let to: Int64? = head["to_location_id"]
            info += [(t("transfer.from"), UI.locationName(location)), (t("transfer.to"), UI.locationName(to))]
        } else if kind == "trial" {
            info.append((t("trial.location"), UI.locationName(location)))
        }
        let source = text(head, "receipt_source")
        if kind == "receipt" && !source.isEmpty {
            info.append((t("receipt_form.source"), t("receipt_form.source_short_\(source)")))
            if source == "return" {
                if let customerId {
                    link = (info.count, customerId)
                    info.append((t("col.customer"), text(head, "customer_name")))
                }
                if !text(head, "ref_code").isEmpty { info.append((t("receipt_form.order"), text(head, "ref_code"))) }
            } else {
                info.append((t("receipt_form.supplier"), text(head, "supplier_name")))
            }
        }
        if !text(head, "note").isEmpty { info.append((t("col.note"), text(head, "note"))) }
        if !text(head, "source_file").isEmpty { info.append((t("col.file"), text(head, "source_file"))) }
        let created = text(head, "created_at")
        let clock = created.count >= 16 ? String(Array(created)[10..<16]) : ""
        info.append((t("doc.read_at"), Format.date(created) + clock))

        let table = try linesTable(db, id: id, kind: kind, lines: lines, mixed: mixed, money: money)

        var footer: [(String, Bool)] = []
        if ["delivery", "receipt", "transfer", "trial"].contains(kind) {
            let total = lines.reduce(0.0) { $0 + (number($1, "qty") ?? 0) }
            footer.append((t("doc.total", ["lines": String(lines.count), "qty": Format.quantity(total)]), true))
        }
        if kind == "delivery", let orderTotal = number(head, "order_total") {
            footer.append((t("doc.money", ["goods": money(number(head, "goods_amount") ?? 0, approx: false),
                                           "fees": money(number(head, "fee_amount") ?? 0, approx: false),
                                           "total": money(orderTotal)]), false))
            if currency == "CNY" {
                footer.append((rate.map { t("doc.in_cny_rate", ["rate": Format.quantity($0.rounded())]) } ?? t("doc.in_cny"), true))
            }
            if let printed = number(head, "note_total"), abs(printed - orderTotal) >= 1 {
                footer.append((t("doc.money_printed", ["total": money(printed, approx: false)]), true))
            }
        }
        let unpriced: Int = (head["unpriced_lines"] as Int?) ?? 0
        if kind == "delivery" && unpriced > 0 { footer.append((t("doc.unpriced", ["count": String(unpriced)]), true)) }
        footer.append((t("doc.hint_open_product"), true))

        var data = DetailData(title: title, info: info, tables: [table], docId: id, docKind: kind, docStatus: status)
        data.docCode = code
        data.sourceHash = text(head, "source_hash")
        data.sourceFile = text(head, "source_file")
        data.docLocation = location
        data.docLocationSet = ((head["location_set"] as Int?) ?? 1) != 0
        data.docMixed = mixed
        data.emphasis = emphasis
        data.customerLink = link
        data.footer = footer
        return data
    }

    /// The lines of a document as details.DocumentDialog shows them for its kind; a double click opens the product.
    private static func linesTable(_ db: Database, id: Int64, kind: String, lines: [Row], mixed: Bool,
                                   money: (Double?, Bool) -> String) throws -> DetailData.Table {
        let ids: [Int64?] = lines.map { $0["product_id"] }
        let head = [Column(title: t("col.code"), width: 70), Column(title: t("col.product"), width: 240),
                    Column(title: t("col.name_zh"), width: 130), Column(title: t("col.spec"), width: 100),
                    Column(title: t("col.variant"), width: 90)]
        func first(_ l: Row) -> [String] {
            [text(l, "code"), text(l, "name_vi"), text(l, "name_zh"), text(l, "spec"), text(l, "variant")]
        }
        if kind == "stock_count" {
            let diffs = try Lookup.countDifferences(db, docId: id)
            let rows = lines.map { l -> [String] in
                let place: Int64? = l["location_id"]
                let product: Int64 = l["product_id"]
                let diff = diffs[Lookup.PlaceKey(productId: product, locationId: place ?? Ledger.main)] ?? 0
                return first(l) + [place.map { UI.locationName($0) } ?? t("loc.total"),
                                   Format.quantity(number(l, "qty")), Format.quantity(diff)]
            }
            return DetailData.Table(
                title: "", columns: head + [Column(title: t("col.place"), width: 100),
                                            Column(title: t("col.counted"), width: 90, numeric: true),
                                            Column(title: t("col.difference"), width: 90, numeric: true)],
                rows: rows, ids: ids, opens: .product)
        }
        if kind == "delivery" {
            var columns = head + [Column(title: t("col.qty"), width: 80, numeric: true), Column(title: t("col.unit"), width: 60),
                                  Column(title: t("col.unit_price"), width: 110, numeric: true),
                                  Column(title: t("col.amount"), width: 120, numeric: true),
                                  Column(title: t("col.note"), width: 160)]
            var rows = lines.map { l -> [String] in
                first(l) + [Format.quantity(number(l, "qty")), text(l, "unit"), money(number(l, "unit_price"), false),
                            money(number(l, "amount"), false), text(l, "note")]
            }
            if mixed {
                // a stock issue note taking from both places: the place of each line (or both, with how much)
                columns.insert(Column(title: t("col.place"), width: 160), at: 5)
                var taken: [Int64: [(Int64, Double)]] = [:]
                for m in try Row.fetchAll(db, sql: """
                    SELECT product_id, location_id, -SUM(qty) AS qty FROM stock_movements WHERE document_id = ?
                    AND kind = 'delivery_out' GROUP BY product_id, location_id ORDER BY location_id
                    """, arguments: [id]) {
                    taken[m["product_id"], default: []].append((m["location_id"], m["qty"]))
                }
                for (i, l) in lines.enumerated() {
                    let place: Int64? = l["location_id"]
                    let product: Int64 = l["product_id"]
                    let both = (taken[product] ?? []).map { "\(UI.locationName($0.0)) \(Format.quantity($0.1))" }
                    rows[i].insert(place.map { UI.locationName($0) } ?? both.joined(separator: " · "), at: 5)
                }
            }
            return DetailData.Table(title: "", columns: columns, rows: rows, ids: ids, opens: .product)
        }
        let rows = lines.map { l -> [String] in
            first(l) + [Format.quantity(number(l, "qty")), text(l, "unit"), text(l, "note")]
        }
        return DetailData.Table(
            title: "", columns: head + [Column(title: t("col.qty"), width: 80, numeric: true),
                                        Column(title: t("col.unit"), width: 60), Column(title: t("col.note"), width: 160)],
            rows: rows, ids: ids, opens: .product)
    }

    // ---- Chi tiết khách (details.CustomerDialog)

    /// '1.200.000', or '1.100.000 – 1.200.000' when the price changed over the period (details._price_range)
    static func priceRange(_ low: Double?, _ high: Double?, _ currency: String = "") -> String {
        guard let low else { return Format.showMoney(nil) }
        let high = high ?? low
        let one = Format.money(low, currency: currency, rate: nil, approx: false)
        if abs(high - low) < 0.005 * max(abs(high), 1) || abs(high - low) < 0.005 { return one }
        return "\(one) – \(Format.money(high, currency: currency, rate: nil, approx: false))"
    }

    /// The prices in dong and those in yuan apart (details._price_ranges)
    static func priceRanges(_ p: Row) -> String {
        guard number(p, "min_price_cny") != nil else { return priceRange(number(p, "min_price"), number(p, "max_price")) }
        let yuan = priceRange(number(p, "min_price_cny"), number(p, "max_price_cny"), "CNY")
        guard number(p, "min_price") != nil else { return yuan }
        return "\(priceRange(number(p, "min_price"), number(p, "max_price"))) · \(yuan)"
    }

    static func customer(_ db: Database, id: Int64, start: String? = nil, end: String? = nil) throws -> DetailData? {
        guard let c = try Lookup.customer(db, id: id) else { return nil }
        let m = try Lookup.customerMoney(db, customerId: id, start: start, end: end)
        let products = try Lookup.customerProducts(db, customerId: id, start: start, end: end)
        let docs = try OrderQueries.documents(db, kind: "delivery", from: start, to: end, customerId: id)
        let lines = try Lookup.customerLines(db, customerId: id, start: start, end: end)

        var moneyText = t("cust.money_value", [
            "total": Format.both(m.total ?? 0, m.totalCny, approx: m.approx), "orders": String(m.orders),
            "goods": Format.both(m.goods ?? 0, m.goodsCny, approx: nil, brackets: false),
            "fees": Format.both(m.fees ?? 0, m.feesCny, approx: nil, brackets: false)])
        if m.returned != 0 || m.returnedCny != 0 {
            moneyText += t("money.returned", ["returned": Format.both(m.returned, m.returnedCny, approx: nil, brackets: false)])
        }
        let orderCount: Int = (c["order_count"] as Int?) ?? 0
        let info: [(String, String)] = [
            (t("col.contact"), text(c, "contact")), (t("col.phone"), text(c, "phone")),
            (t("col.address"), text(c, "address")), (t("col.tax_code"), text(c, "tax_code")),
            (t("col.email"), text(c, "email")),
            (t("cust.summary"), t("cust.summary_value", ["count": String(orderCount),
                                                         "first": Format.date(text(c, "first_order")),
                                                         "last": Format.date(text(c, "last_order"))])),
            (t("cust.money"), moneyText),
        ]

        let bought = DetailData.Table(
            title: t("cust.products_title"),
            columns: [Column(title: t("col.product"), width: 240), Column(title: t("col.name_zh"), width: 130),
                      Column(title: t("col.spec"), width: 100), Column(title: t("col.variant"), width: 90),
                      Column(title: t("col.total_qty"), width: 90, numeric: true), Column(title: t("col.unit"), width: 60),
                      Column(title: t("col.revenue"), width: 160, numeric: true),
                      Column(title: t("col.price_range"), width: 200),
                      Column(title: t("col.times"), width: 70, numeric: true), Column(title: t("col.last_date"), width: 100)],
            rows: products.map { p -> [String] in
                [text(p, "name_vi"), text(p, "name_zh"), text(p, "spec"), text(p, "variant"),
                 Format.quantity(number(p, "total_qty")), text(p, "unit"),
                 Format.both(number(p, "revenue"), number(p, "revenue_cny"), approx: number(p, "revenue_approx")),
                 priceRanges(p), String((p["times"] as Int?) ?? 0), Format.date(text(p, "last_date"))]
            },
            ids: products.map { $0["id"] }, opens: .product, stretch: 0, boxed: true)

        // each order (newest first) in bold, its lines and prices under it, then its other fees (_fill_orders);
        // a flat list with the order rows in bold stands for the Python tree
        var byDoc: [Int64: [Row]] = [:]
        for l in lines { byDoc[l["document_id"], default: []].append(l) }
        var rows: [[String]] = [], tones: [RowTone] = [], ids: [Int64?] = []
        for d in docs {
            let docId: Int64 = d["id"]
            let cur = text(d, "currency"), rate = number(d, "fx_rate")
            rows.append([t("cust.order_head", ["date": Format.date(text(d, "doc_date")), "code": text(d, "code")]), "", "",
                         t("cust.order_lines", ["count": String((d["line_count"] as Int?) ?? 0)]), "", "",
                         Format.money(number(d, "goods_amount"), currency: cur, rate: rate), ""])
            tones.append(.header)
            ids.append(docId)
            for l in byDoc[docId] ?? [] {
                let name = [text(l, "name_vi"), text(l, "variant")].filter { !$0.isEmpty }.joined(separator: " · ")
                let lcur = text(l, "currency"), lrate = number(l, "fx_rate")
                rows.append(["      " + name, text(l, "name_zh"), text(l, "spec"), Format.quantity(number(l, "qty")),
                             text(l, "unit"), Format.money(number(l, "unit_price"), currency: lcur, rate: lrate, approx: false),
                             Format.money(number(l, "amount"), currency: lcur, rate: lrate, approx: false), text(l, "note")])
                tones.append(.normal)
                ids.append(docId)
            }
            if let fee = number(d, "fee_amount"), fee != 0 {
                rows.append(["      " + t("cust.fees"), "", "", "", "", "",
                             Format.money(fee, currency: cur, rate: rate, approx: false), ""])
                tones.append(.normal)
                ids.append(docId)
            }
        }
        let orders = DetailData.Table(
            title: t("cust.orders_title"),
            columns: [Column(title: t("col.order_or_product"), width: 300), Column(title: t("col.name_zh"), width: 120),
                      Column(title: t("col.spec"), width: 100), Column(title: t("col.qty"), width: 80, numeric: true),
                      Column(title: t("col.unit"), width: 60), Column(title: t("col.unit_price"), width: 110, numeric: true),
                      Column(title: t("col.amount"), width: 120, numeric: true), Column(title: t("col.note"), width: 160)],
            rows: rows, tones: tones, ids: ids, opens: .document, stretch: nil, sortable: false, boxed: true)

        var data = DetailData(title: text(c, "name"), info: info, tables: [bought, orders])
        data.customerId = id
        if (m.unpriced ?? 0) > 0 { data.infoHints = [t("cust.unpriced", ["count": String(m.unpriced ?? 0)])] }
        return data
    }

    // ---- Đọc phiếu: one note as the Swift reader read it

    static func note(_ note: DeliveryNote?, error: String?, file: URL) -> DetailData {
        guard let note else {
            return DetailData(title: file.lastPathComponent, info: [(tr("Không đọc được", "Cannot be read", "无法读取"), error ?? "")], tables: [])
        }
        func money(_ v: Double?) -> String { Format.money(v, currency: note.currency, rate: nil) }
        var info: [(String, String)] = [
            (tr("Mã đơn hàng", "Order code", "订单编号"), note.code), (tr("Ngày giao hàng", "Delivery date", "送货日期"), Format.date(note.docDate)), (t("col.customer"), note.customerName),
            (t("col.phone"), note.phone), (t("col.contact"), note.contact), (t("col.address"), note.address),
            (t("col.currency"), note.currency == "CNY" ? tr("Nhân dân tệ (¥)", "Chinese yuan (¥)", "人民币（¥）") : tr("Đồng (₫)", "Dong (₫)", "越南盾（₫）")),
        ]
        if let total = note.total { info.append((tr("Tổng cộng trên phiếu", "Total on the note", "单据合计"), money(total))) }
        for (name, fee) in note.fees { info.append((tr("Phí: \(name)", "Fee: \(name)", "费用：\(name)"), money(fee))) }
        for warning in note.warnings { info.append((tr("Cảnh báo", "Warning", "警告"), warning)) }
        if !note.title.isEmpty { info.append((tr("Tiêu đề", "Title", "标题"), note.title)) }
        let lines = DetailData.Table(
            title: tr("Các dòng hàng đọc được", "Lines that could be read", "读取到的商品行"),
            columns: [Column(title: tr("Dòng Excel", "Excel row", "Excel 行"), width: 70, numeric: true), Column(title: tr("Tên trên phiếu", "Name on the note", "单据上的名称"), width: 260),
                      Column(title: tr("Tên Việt", "Vietnamese name", "越南语名称"), width: 200), Column(title: t("col.name_zh"), width: 120),
                      Column(title: t("col.spec"), width: 100), Column(title: t("col.qty"), width: 80, numeric: true),
                      Column(title: t("col.unit_price"), width: 110, numeric: true), Column(title: t("col.amount"), width: 120, numeric: true),
                      Column(title: t("col.note"), width: 150), Column(title: tr("Mã hàng", "Product code", "商品编码"), width: 70), Column(title: tr("Lấy từ", "Taken from", "来源"), width: 160)],
            rows: note.lines.map { l -> [String] in
                let places = l.places.map { "\(OrderQueries.placeName(Int64($0.0))): \(Format.quantity($0.1))" }
                return [String(l.row), l.rawName, l.nameVi, l.nameZh, l.spec, Format.quantity(l.qty), money(l.unitPrice),
                        money(l.amount), l.note, l.productCode, places.joined(separator: "; ")]
            })
        var tables = [lines]
        if !note.skippedRows.isEmpty {
            tables.append(DetailData.Table(title: tr("Dòng không phải hàng (bỏ qua)", "Lines that are not goods (skipped)", "非商品行（已跳过）"), columns: [Column(title: tr("Nội dung", "Content", "内容"), width: 500)],
                                           rows: note.skippedRows.map { [$0] }))
        }
        return DetailData(title: "\(file.lastPathComponent) · \(tr("đơn", "order", "订单")) \(note.code)", info: info, tables: tables)
    }

    // ---- Chi tiết mặt hàng (details.ProductDialog)

    static func product(_ db: Database, id: Int64) throws -> DetailData? {
        guard let p = try Lookup.product(db, id: id) else { return nil }
        let history = Array(try Lookup.productHistory(db, id: id).reversed())  // newest first
        let top = try Lookup.productTopCustomers(db, id: id)
        let unit = text(p, "unit")
        var info: [(String, String)] = [
            (t("col.code"), text(p, "code")), (t("col.name_zh"), text(p, "name_zh")),
            (t("col.category"), text(p, "category")),
            (t("col.stock"), "\(Format.quantity(number(p, "stock"))) \(unit)"),
            (t("prod.places"), t("prod.places_value", ["main": Format.quantity(number(p, "stock_main")),
                                                       "office": Format.quantity(number(p, "stock_office")), "unit": unit])),
        ]
        var emphasis: [Int: DetailData.Emphasis] = [3: .big]
        if !text(p, "stock_note").isEmpty {
            emphasis[info.count] = .warn
            info.append((t("col.stock_note"), text(p, "stock_note")))
        }
        let moves = DetailData.Table(
            title: t("prod.history_title"),
            columns: [Column(title: t("col.date"), width: 90), Column(title: t("col.kind"), width: 140),
                      Column(title: t("col.doc_code"), width: 80), Column(title: t("col.customer"), width: 200),
                      Column(title: t("col.place"), width: 90), Column(title: t("col.qty_change"), width: 90, numeric: true),
                      Column(title: t("col.balance"), width: 80, numeric: true)],
            rows: history.map { m -> [String] in
                let location: Int64? = m["location_id"]
                return [Format.date(text(m, "occurred_on")), moveName(text(m, "kind")), text(m, "code"),
                        text(m, "customer_name"), UI.locationName(location), Format.quantity(number(m, "qty")),
                        Format.quantity(number(m, "balance"))]
            },
            tones: history.map { m -> RowTone in (number(m, "balance") ?? 0) < 0 ? .negative : .normal },
            ids: history.map { $0["document_id"] }, opens: .document, stretch: 3, boxed: true)
        let customers = DetailData.Table(
            title: t("prod.customers_title"),
            columns: [Column(title: t("col.customer"), width: 240), Column(title: t("col.total_qty"), width: 90, numeric: true),
                      Column(title: t("col.revenue"), width: 200, numeric: true),
                      Column(title: t("col.times"), width: 70, numeric: true), Column(title: t("col.last_date"), width: 100)],
            rows: top.map { c -> [String] in
                [text(c, "name"), Format.quantity(number(c, "total_qty")),
                 Format.both(number(c, "revenue"), number(c, "revenue_cny"), approx: number(c, "revenue_approx")),
                 String((c["times"] as Int?) ?? 0), Format.date(text(c, "last_date"))]
            },
            ids: top.map { $0["id"] }, opens: .customer, stretch: 0, boxed: true)
        let title = [text(p, "name_vi"), text(p, "spec"), text(p, "variant")].filter { !$0.isEmpty }.joined(separator: " — ")
        var data = DetailData(title: title, info: info, tables: [moves, customers])
        data.emphasis = emphasis
        return data
    }
}
