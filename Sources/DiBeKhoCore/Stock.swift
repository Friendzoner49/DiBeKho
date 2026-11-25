import Foundation
import GRDB

/// One row of the Tồn kho screen (Python core/stock.stock_table).
public struct StockRow: Equatable {
    public let id: Int64
    public let code: String
    public let nameVi: String
    public let nameZh: String
    public let spec: String
    public let variant: String
    public let category: String
    public let unit: String
    public let stockNote: String
    public let stock: Double
    public let stockMain: Double
    public let stockOffice: Double
    public var stockBn: Double = 0  // Văn phòng Bắc Ninh
    public let lastOut: String?

    /// What the search box looks in (as the Python Tồn kho screen).
    public var haystack: String { "\(code) \(nameVi) \(nameZh) \(spec) \(variant)" }
}

public enum StockQueries {
    public static let main: Int64 = 1  // Kho tổng
    public static let office: Int64 = 2  // Văn phòng Hà Nội
    public static let bacNinh: Int64 = 3  // Văn phòng Bắc Ninh

    private static func text(_ row: Row, _ column: String) -> String {
        let value: String? = row[column]
        return value ?? ""
    }

    private static func number(_ row: Row, _ column: String) -> Double {
        let value: Double? = row[column]
        return value ?? 0
    }

    /// Active products with their stock in total and per place; stock is always the sum of stock_movements.
    public static func table(_ db: Database) throws -> [StockRow] {
        let rows = try Row.fetchAll(db, sql: """
            SELECT p.id, p.code, p.name_vi, p.name_zh, p.spec, p.variant, p.category, p.unit, p.stock_note,
                   COALESCE(SUM(m.qty), 0) AS stock,
                   COALESCE(SUM(CASE WHEN m.location_id = 1 THEN m.qty END), 0) AS stock_main,
                   COALESCE(SUM(CASE WHEN m.location_id = 2 THEN m.qty END), 0) AS stock_office,
                   COALESCE(SUM(CASE WHEN m.location_id = 3 THEN m.qty END), 0) AS stock_bn,
                   MAX(CASE WHEN m.kind = 'delivery_out' THEN m.occurred_on END) AS last_out
            FROM products p
            LEFT JOIN stock_movements m ON m.product_id = p.id
            WHERE p.active = 1
            GROUP BY p.id
            ORDER BY p.category, p.name_vi, p.spec
            """)
        return rows.map { row in
            let id: Int64 = row["id"]
            let lastOut: String? = row["last_out"]
            return StockRow(id: id, code: text(row, "code"), nameVi: text(row, "name_vi"), nameZh: text(row, "name_zh"),
                            spec: text(row, "spec"), variant: text(row, "variant"), category: text(row, "category"),
                            unit: text(row, "unit"), stockNote: text(row, "stock_note"), stock: number(row, "stock"),
                            stockMain: number(row, "stock_main"), stockOffice: number(row, "stock_office"),
                            stockBn: number(row, "stock_bn"), lastOut: lastOut)
        }
    }

    /// The shared alarm level (meta low_stock_default, 30 when not set; 0 = off).
    public static func lowStockDefault(_ db: Database) throws -> Double {
        let value = try String.fetchOne(db, sql: "SELECT value FROM meta WHERE key = 'low_stock_default'")
        return value.flatMap { Double($0) } ?? 30
    }

    public static func isLow(_ stock: Double, _ level: Double) -> Bool {
        level != 0 && stock < level
    }
}
