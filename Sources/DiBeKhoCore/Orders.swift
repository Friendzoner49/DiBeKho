import Foundation
import GRDB

/// One row of the Đơn hàng screen (Python core/queries.documents, kind 'delivery').
public struct OrderRow: Equatable {
    public let id: Int64
    public let date: String
    public let code: String
    public let customer: String
    public let customerId: Int64?
    public let place: String
    public let lineCount: Int
    public let totalQty: Double
    public let goods: Double?
    public let fees: Double?
    public let currency: String
    public let fxRate: Double?
    public let status: String
    public let sourceFile: String

    public var isYuan: Bool { currency == "CNY" }
    public var haystack: String { "\(code) \(customer) \(sourceFile)" }
}

public enum OrderQueries {
    public static func placeName(_ id: Int64?) -> String {
        id == StockQueries.office ? "Văn phòng Hà Nội" : id == StockQueries.bacNinh ? "Văn phòng Bắc Ninh" : "Kho tổng"
    }

    public static func statusName(_ status: String) -> String {
        switch status {
        case "cancelled": return "Đã huỷ"
        case "replaced": return "Đã thay bằng bản sửa"
        default: return "Hiệu lực"
        }
    }

    /// Delivery notes, newest first; only those in force unless includeClosed.
    public static func deliveries(_ db: Database, includeClosed: Bool = false) throws -> [OrderRow] {
        let rows = try Row.fetchAll(db, sql: """
            SELECT d.id, d.doc_date, d.code, d.status, d.source_file, d.fee_amount, d.currency, d.fx_rate,
                   d.location_id, d.location_set, d.customer_id, c.name AS customer_name,
                   COUNT(l.id) AS line_count, COALESCE(SUM(l.qty), 0) AS total_qty,
                   (SELECT SUM(x.amount) FROM document_lines x WHERE x.document_id = d.id) AS goods_amount,
                   (SELECT COUNT(DISTINCT m.location_id) FROM stock_movements m WHERE m.document_id = d.id) AS places
            FROM documents d
            LEFT JOIN customers c ON c.id = d.customer_id
            LEFT JOIN document_lines l ON l.document_id = d.id
            WHERE d.kind = 'delivery' \(includeClosed ? "" : "AND d.status = 'active'")
            GROUP BY d.id
            ORDER BY d.doc_date DESC, d.id DESC
            """)
        return rows.map { row in
            let id: Int64 = row["id"]
            let places: Int? = row["places"]
            let locationSet: Int? = row["location_set"]
            let location: Int64? = row["location_id"]
            let date: String? = row["doc_date"]
            let code: String? = row["code"]
            let customer: String? = row["customer_name"]
            let customerId: Int64? = row["customer_id"]
            let lines: Int? = row["line_count"]
            let qty: Double? = row["total_qty"]
            let goods: Double? = row["goods_amount"]
            let fees: Double? = row["fee_amount"]
            let currency: String? = row["currency"]
            let rate: Double? = row["fx_rate"]
            let status: String? = row["status"]
            let file: String? = row["source_file"]
            let place = (places ?? 0) > 1
                ? "Nhiều nơi"
                : placeName(location) + ((locationSet ?? 1) != 0 ? "" : " (?)")
            return OrderRow(id: id, date: date ?? "", code: code ?? "", customer: customer ?? "", customerId: customerId, place: place,
                            lineCount: lines ?? 0, totalQty: qty ?? 0, goods: goods, fees: fees,
                            currency: currency ?? "VND", fxRate: rate, status: status ?? "active",
                            sourceFile: file ?? "")
        }
    }
}
