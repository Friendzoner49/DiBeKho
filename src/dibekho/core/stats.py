"""Period statistics: opening, in, out, count adjustments, closing per product.

Dates are business dates (date on the delivery note / receipt), not import time.
"""

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

IN_KINDS = ("receipt_in", "receipt_reverse")
OUT_KINDS = ("delivery_out", "delivery_reverse")
ADJ_KINDS = ("count_adjust", "count_reverse")


@dataclass
class Filters:
    product_ids: list[int] | None = None   # None = all
    categories: list[str] | None = None
    customer_ids: list[int] | None = None  # affects outgoing quantities only

    def product_sql(self, alias="p") -> tuple[str, list]:
        parts, args = [], []
        if self.product_ids:
            parts.append(f"{alias}.id IN ({','.join('?' * len(self.product_ids))})")
            args += list(self.product_ids)
        if self.categories:
            parts.append(f"{alias}.category IN ({','.join('?' * len(self.categories))})")
            args += list(self.categories)
        return (" AND ".join(parts) or "1=1"), args

    def customer_sql(self, alias="d") -> tuple[str, list]:
        if not self.customer_ids:
            return "1=1", []
        return f"{alias}.customer_id IN ({','.join('?' * len(self.customer_ids))})", list(self.customer_ids)


@dataclass
class Bucket:
    label: str
    start: date
    end: date


@dataclass
class SummaryRow:
    product_id: int
    code: str
    name_vi: str
    name_zh: str
    spec: str
    variant: str
    unit: str
    category: str
    opening: float | None
    qty_in: float
    qty_out: float
    adjust: float
    closing: float | None
    per_bucket: dict = field(default_factory=dict)  # label -> (in, out)


# ---- periods ---------------------------------------------------------------

def day_range(d: date) -> tuple[date, date]:
    return d, d


def month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def quarter_range(year: int, quarter: int) -> tuple[date, date]:
    first_month = 3 * (quarter - 1) + 1
    return date(year, first_month, 1), month_range(year, first_month + 2)[1]


def year_range(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year, 12, 31)


def buckets(start: date, end: date, by: str) -> list[Bucket]:
    """by: 'day' | 'month' | 'none'."""
    if by == "day":
        out, d = [], start
        while d <= end:
            out.append(Bucket(d.strftime("%d/%m"), d, d))
            d += timedelta(days=1)
        return out
    if by == "month":
        out, y, m = [], start.year, start.month
        while date(y, m, 1) <= end:
            s, e = month_range(y, m)
            out.append(Bucket(f"{m:02d}/{y}", max(s, start), min(e, end)))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out
    return []


# ---- queries ---------------------------------------------------------------

def summary(conn, start: date, end: date, filters: Filters | None = None, by: str = "none") -> list[SummaryRow]:
    f = filters or Filters()
    psql, pargs = f.product_sql()
    csql, cargs = f.customer_sql()
    s, e = start.isoformat(), end.isoformat()
    in_marks, out_marks, adj_marks = (",".join("?" * len(k)) for k in (IN_KINDS, OUT_KINDS, ADJ_KINDS))
    rows = conn.execute(
        f"""
        SELECT p.id, p.code, p.name_vi, p.name_zh, p.spec, p.variant, p.unit, p.category,
          COALESCE(SUM(CASE WHEN m.occurred_on < ? THEN m.qty END), 0) AS opening,
          COALESCE(SUM(CASE WHEN m.occurred_on BETWEEN ? AND ? AND m.kind IN ({in_marks}) THEN m.qty END), 0) AS qty_in,
          COALESCE(-SUM(CASE WHEN m.occurred_on BETWEEN ? AND ? AND m.kind IN ({out_marks}) AND ({csql})
                             THEN m.qty END), 0) AS qty_out,
          COALESCE(SUM(CASE WHEN m.occurred_on BETWEEN ? AND ? AND m.kind IN ({adj_marks}) THEN m.qty END), 0) AS adjust
        FROM products p
        LEFT JOIN stock_movements m ON m.product_id = p.id
        LEFT JOIN documents d ON d.id = m.document_id
        WHERE {psql} AND (p.active = 1 OR m.id IS NOT NULL)
        GROUP BY p.id
        ORDER BY p.category, p.name_vi, p.spec, p.variant
        """,
        [s, s, e, *IN_KINDS, s, e, *OUT_KINDS, *cargs, s, e, *ADJ_KINDS, *pargs],
    ).fetchall()

    customer_filtered = bool(f.customer_ids)
    result = []
    for r in rows:
        closing = r["opening"] + r["qty_in"] - r["qty_out"] + r["adjust"]
        result.append(SummaryRow(
            r["id"], r["code"], r["name_vi"], r["name_zh"], r["spec"], r["variant"], r["unit"], r["category"],
            None if customer_filtered else r["opening"], r["qty_in"], r["qty_out"], r["adjust"],
            None if customer_filtered else closing,
        ))
    if customer_filtered:
        result = [x for x in result if x.qty_out]
    if by != "none" and result:
        _fill_buckets(conn, result, buckets(start, end, by), f)
    return result


def _fill_buckets(conn, rows: list[SummaryRow], bks: list[Bucket], f: Filters) -> None:
    csql, cargs = f.customer_sql()
    ids = [r.product_id for r in rows]
    by_id = {r.product_id: r for r in rows}
    for r in rows:
        r.per_bucket = {b.label: (0.0, 0.0) for b in bks}
    for b in bks:
        data = conn.execute(
            f"""
            SELECT m.product_id,
              COALESCE(SUM(CASE WHEN m.kind IN ({','.join('?' * len(IN_KINDS))}) THEN m.qty END), 0),
              COALESCE(-SUM(CASE WHEN m.kind IN ({','.join('?' * len(OUT_KINDS))}) AND ({csql}) THEN m.qty END), 0)
            FROM stock_movements m JOIN documents d ON d.id = m.document_id
            WHERE m.occurred_on BETWEEN ? AND ? AND m.product_id IN ({','.join('?' * len(ids))})
            GROUP BY m.product_id
            """,
            [*IN_KINDS, *OUT_KINDS, *cargs, b.start.isoformat(), b.end.isoformat(), *ids],
        )
        for pid, qin, qout in data:
            by_id[pid].per_bucket[b.label] = (qin, qout)


def top_out(conn, start: date, end: date, filters: Filters | None = None, limit=10):
    rows = [r for r in summary(conn, start, end, filters) if r.qty_out > 0]
    return sorted(rows, key=lambda r: r.qty_out, reverse=True)[:limit]


def daily_out(conn, start: date, end: date, filters: Filters | None = None) -> list[tuple[date, float]]:
    """Total outgoing quantity per day (for the chart)."""
    f = filters or Filters()
    psql, pargs = f.product_sql()
    csql, cargs = f.customer_sql()
    rows = dict(conn.execute(
        f"""
        SELECT m.occurred_on, -SUM(m.qty)
        FROM stock_movements m JOIN products p ON p.id = m.product_id JOIN documents d ON d.id = m.document_id
        WHERE m.kind IN ({','.join('?' * len(OUT_KINDS))}) AND m.occurred_on BETWEEN ? AND ? AND {psql} AND {csql}
        GROUP BY m.occurred_on
        """,
        [*OUT_KINDS, start.isoformat(), end.isoformat(), *pargs, *cargs],
    ).fetchall())
    out, d = [], start
    while d <= end:
        out.append((d, rows.get(d.isoformat(), 0.0)))
        d += timedelta(days=1)
    return out


def customer_product(conn, start: date, end: date, filters: Filters | None = None):
    f = filters or Filters()
    psql, pargs = f.product_sql()
    csql, cargs = f.customer_sql()
    return conn.execute(
        f"""
        SELECT c.name AS customer_name, p.code, p.name_vi, p.spec, p.variant, p.unit,
               SUM(l.qty) AS total_qty, COUNT(DISTINCT d.id) AS times, MAX(d.doc_date) AS last_date
        FROM document_lines l
        JOIN documents d ON d.id = l.document_id
        JOIN products p ON p.id = l.product_id
        LEFT JOIN customers c ON c.id = d.customer_id
        WHERE d.kind = 'delivery' AND d.status = 'active' AND d.doc_date BETWEEN ? AND ? AND {psql} AND {csql}
        GROUP BY d.customer_id, p.id
        ORDER BY c.name, total_qty DESC
        """,
        [start.isoformat(), end.isoformat(), *pargs, *cargs],
    ).fetchall()


def detail_lines(conn, start: date, end: date, filters: Filters | None = None):
    """Every movement in the period with its document — sheet 'Chi tiết phiếu'."""
    f = filters or Filters()
    psql, pargs = f.product_sql()
    csql, cargs = f.customer_sql()
    customer_clause = f"AND (m.kind NOT IN ({','.join('?' * len(OUT_KINDS))}) OR {csql})" if f.customer_ids else ""
    customer_args = [*OUT_KINDS, *cargs] if f.customer_ids else []
    return conn.execute(
        f"""
        SELECT m.occurred_on, m.kind, m.qty, d.code, d.kind AS doc_kind, d.receipt_source, c.name AS customer_name,
               p.code AS product_code, p.name_vi, p.spec, p.variant, p.unit,
               (SELECT note FROM document_lines l WHERE l.document_id = d.id AND l.product_id = p.id LIMIT 1) AS note
        FROM stock_movements m
        JOIN documents d ON d.id = m.document_id
        JOIN products p ON p.id = m.product_id
        LEFT JOIN customers c ON c.id = d.customer_id
        WHERE m.occurred_on BETWEEN ? AND ? AND {psql} {customer_clause}
        ORDER BY m.occurred_on, d.id, p.name_vi
        """,
        [start.isoformat(), end.isoformat(), *pargs, *customer_args],
    ).fetchall()
