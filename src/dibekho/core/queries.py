"""Read-only queries for the lookup screens: orders, customers, products, search."""

from datetime import date

from dibekho.core.text import normalize_code, unaccent


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


# Money of one delivery note (alias d), as correlated subqueries so joins with its lines never multiply it.
# order total = goods (sum of line amounts) + fees; NULL when the note has no price at all.
_GOODS = "(SELECT SUM(x.amount) FROM document_lines x WHERE x.document_id = d.id)"
_UNPRICED = "(SELECT COUNT(*) FROM document_lines x WHERE x.document_id = d.id AND x.amount IS NULL)"
_TOTAL = f"(CASE WHEN {_GOODS} IS NULL AND d.fee_amount IS NULL THEN NULL " \
         f"ELSE COALESCE({_GOODS}, 0) + COALESCE(d.fee_amount, 0) END)"


def _period(where: list, args: list, date_from: date | None, date_to: date | None, column="d.doc_date") -> None:
    if date_from:
        where.append(f"{column} >= ?")
        args.append(_iso(date_from))
    if date_to:
        where.append(f"{column} <= ?")
        args.append(_iso(date_to))


# ---- documents -------------------------------------------------------------

def documents(conn, kind="delivery", date_from: date | None = None, date_to: date | None = None,
              customer_id=None, product_id=None, include_closed=False, text=""):
    where, args = ["d.kind = ?"], [kind]
    if not include_closed:
        where.append("d.status = 'active'")
    if date_from:
        where.append("d.doc_date >= ?")
        args.append(_iso(date_from))
    if date_to:
        where.append("d.doc_date <= ?")
        args.append(_iso(date_to))
    if customer_id:
        where.append("d.customer_id = ?")
        args.append(customer_id)
    if product_id:
        where.append("EXISTS (SELECT 1 FROM document_lines x WHERE x.document_id = d.id AND x.product_id = ?)")
        args.append(product_id)
    if text:
        where.append("(unaccent(d.code) LIKE ? OR unaccent(COALESCE(c.name, '')) LIKE ? OR d.code_norm = ?)")
        like = f"%{unaccent(text)}%"
        args += [like, like, normalize_code(text)]
    return conn.execute(
        f"""
        SELECT d.*, c.name AS customer_name, s.name AS supplier_name,
               COUNT(l.id) AS line_count, COALESCE(SUM(l.qty), 0) AS total_qty,
               {_GOODS} AS goods_amount, {_TOTAL} AS order_total, {_UNPRICED} AS unpriced_lines
        FROM documents d
        LEFT JOIN customers c ON c.id = d.customer_id
        LEFT JOIN suppliers s ON s.id = d.supplier_id
        LEFT JOIN document_lines l ON l.document_id = d.id
        WHERE {' AND '.join(where)}
        GROUP BY d.id
        ORDER BY d.doc_date DESC, d.id DESC
        """,
        args,
    ).fetchall()


def document(conn, doc_id: int):
    head = conn.execute(
        f"""
        SELECT d.*, c.name AS customer_name, c.contact, c.phone, c.address, s.name AS supplier_name,
               {_GOODS} AS goods_amount, {_TOTAL} AS order_total, {_UNPRICED} AS unpriced_lines
        FROM documents d LEFT JOIN customers c ON c.id = d.customer_id
        LEFT JOIN suppliers s ON s.id = d.supplier_id
        WHERE d.id = ?
        """,
        (doc_id,),
    ).fetchone()
    lines = conn.execute(
        """
        SELECT l.*, p.code, p.name_vi, p.name_zh, p.spec, p.variant, p.unit
        FROM document_lines l JOIN products p ON p.id = l.product_id
        WHERE l.document_id = ? ORDER BY l.line_no
        """,
        (doc_id,),
    ).fetchall()
    return head, lines


def count_differences(conn, doc_id: int) -> dict[tuple[int, int], float]:
    """For a stock_count document: (product_id, location_id) -> adjustment applied (a count of the total is
    adjusted at Kho tổng)."""
    rows = conn.execute(
        "SELECT product_id, location_id, SUM(qty) FROM stock_movements WHERE document_id = ? "
        "AND kind = 'count_adjust' GROUP BY product_id, location_id",
        (doc_id,),
    )
    return {(r[0], r[1]): r[2] for r in rows}


# ---- customers -------------------------------------------------------------

def customers(conn, text=""):
    where, args = "", []
    if text:
        like = f"%{unaccent(text)}%"
        where = "WHERE unaccent(c.name) LIKE ? OR unaccent(c.contact) LIKE ? OR c.phone_norm LIKE ? " \
                "OR unaccent(c.address) LIKE ?"
        args = [like, like, f"%{''.join(ch for ch in text if ch.isdigit()) or '#'}%", like]
    return conn.execute(
        f"""
        SELECT c.*, COUNT(d.id) AS order_count, MIN(d.doc_date) AS first_order, MAX(d.doc_date) AS last_order,
               SUM({_TOTAL}) AS revenue
        FROM customers c
        LEFT JOIN documents d ON d.customer_id = c.id AND d.kind = 'delivery' AND d.status = 'active'
        {where}
        GROUP BY c.id
        ORDER BY last_order DESC NULLS LAST, c.name
        """,
        args,
    ).fetchall()


def customer(conn, customer_id: int):
    return conn.execute(
        """
        SELECT c.*, COUNT(d.id) AS order_count, MIN(d.doc_date) AS first_order, MAX(d.doc_date) AS last_order
        FROM customers c
        LEFT JOIN documents d ON d.customer_id = c.id AND d.kind = 'delivery' AND d.status = 'active'
        WHERE c.id = ? GROUP BY c.id
        """,
        (customer_id,),
    ).fetchone()


def customer_money(conn, customer_id: int, date_from: date | None = None, date_to: date | None = None):
    """Orders, goods, fees and total (revenue) of a customer in a period; unpriced = orders with a line
    whose price is unknown (their known lines still count)."""
    where, args = ["d.customer_id = ?", "d.kind = 'delivery'", "d.status = 'active'"], [customer_id]
    _period(where, args, date_from, date_to)
    return conn.execute(
        f"""
        SELECT COUNT(*) AS orders, SUM({_GOODS}) AS goods, SUM(d.fee_amount) AS fees, SUM({_TOTAL}) AS total,
               SUM(CASE WHEN {_UNPRICED} > 0 THEN 1 ELSE 0 END) AS unpriced
        FROM documents d WHERE {' AND '.join(where)}
        """,
        args,
    ).fetchone()


def customer_lines(conn, customer_id: int, date_from: date | None = None, date_to: date | None = None):
    """Every line this customer bought in a period, newest order first, with its price."""
    where, args = ["d.customer_id = ?", "d.kind = 'delivery'", "d.status = 'active'"], [customer_id]
    _period(where, args, date_from, date_to)
    return conn.execute(
        f"""
        SELECT d.id AS document_id, d.doc_date, d.code, d.fee_amount, l.product_id, l.qty, l.unit_price, l.amount,
               l.note, p.code AS product_code, p.name_vi, p.name_zh, p.spec, p.variant, p.unit
        FROM document_lines l
        JOIN documents d ON d.id = l.document_id
        JOIN products p ON p.id = l.product_id
        WHERE {' AND '.join(where)}
        ORDER BY d.doc_date DESC, d.id DESC, l.line_no
        """,
        args,
    ).fetchall()


def customer_products(conn, customer_id: int, date_from: date | None = None, date_to: date | None = None):
    """What this customer buys: total quantity, money, number of orders, price range, last purchase."""
    where, args = ["d.customer_id = ?", "d.kind = 'delivery'", "d.status = 'active'"], [customer_id]
    _period(where, args, date_from, date_to)
    return conn.execute(
        f"""
        SELECT p.id, p.code, p.name_vi, p.name_zh, p.spec, p.variant, p.unit,
               SUM(l.qty) AS total_qty, COUNT(DISTINCT d.id) AS times, MAX(d.doc_date) AS last_date,
               SUM(l.amount) AS revenue, MIN(l.unit_price) AS min_price, MAX(l.unit_price) AS max_price
        FROM document_lines l
        JOIN documents d ON d.id = l.document_id
        JOIN products p ON p.id = l.product_id
        WHERE {' AND '.join(where)}
        GROUP BY p.id
        ORDER BY total_qty DESC
        """,
        args,
    ).fetchall()


# ---- products --------------------------------------------------------------

def product(conn, product_id: int):
    return conn.execute(
        "SELECT p.*, COALESCE((SELECT SUM(qty) FROM stock_movements WHERE product_id = p.id), 0) AS stock, "
        "COALESCE((SELECT SUM(qty) FROM stock_movements WHERE product_id = p.id AND location_id = 1), 0) AS stock_main, "
        "COALESCE((SELECT SUM(qty) FROM stock_movements WHERE product_id = p.id AND location_id = 2), 0) "
        "AS stock_office FROM products p WHERE p.id = ?",
        (product_id,),
    ).fetchone()


def product_history(conn, product_id: int, date_from: date | None = None, date_to: date | None = None):
    """Every movement with its document, oldest first, plus running balance."""
    where, args = ["m.product_id = ?"], [product_id]
    if date_from:
        where.append("m.occurred_on >= ?")
        args.append(_iso(date_from))
    if date_to:
        where.append("m.occurred_on <= ?")
        args.append(_iso(date_to))
    rows = conn.execute(
        f"""
        SELECT m.*, d.code, d.kind AS doc_kind, d.status AS doc_status, c.name AS customer_name,
               (SELECT COALESCE(SUM(qty), 0) FROM stock_movements m2
                WHERE m2.product_id = m.product_id
                  AND (m2.occurred_on < m.occurred_on OR (m2.occurred_on = m.occurred_on AND m2.id <= m.id))
               ) AS balance
        FROM stock_movements m
        JOIN documents d ON d.id = m.document_id
        LEFT JOIN customers c ON c.id = d.customer_id
        WHERE {' AND '.join(where)}
        ORDER BY m.occurred_on, m.id
        """,
        args,
    ).fetchall()
    return rows


def product_top_customers(conn, product_id: int, limit=10):
    return conn.execute(
        """
        SELECT c.id, c.name, SUM(l.qty) AS total_qty, COUNT(DISTINCT d.id) AS times, MAX(d.doc_date) AS last_date,
               SUM(l.amount) AS revenue
        FROM document_lines l
        JOIN documents d ON d.id = l.document_id
        JOIN customers c ON c.id = d.customer_id
        WHERE l.product_id = ? AND d.kind = 'delivery' AND d.status = 'active'
        GROUP BY c.id ORDER BY total_qty DESC LIMIT ?
        """,
        (product_id, limit),
    ).fetchall()


# ---- global search ---------------------------------------------------------

def search(conn, text: str, limit=50) -> dict:
    """Accent-insensitive search over products, customers and documents."""
    q = unaccent(text.strip())
    if not q:
        return {"products": [], "customers": [], "documents": []}
    like = f"%{q}%"
    digits = "".join(ch for ch in text if ch.isdigit())
    products = conn.execute(
        """
        SELECT p.*, COALESCE((SELECT SUM(qty) FROM stock_movements WHERE product_id = p.id), 0) AS stock
        FROM products p
        WHERE unaccent(p.name_vi) LIKE ?1 OR unaccent(p.name_zh) LIKE ?1 OR unaccent(p.code) LIKE ?1
           OR unaccent(p.spec) LIKE ?1 OR unaccent(p.category) LIKE ?1 OR unaccent(p.variant) LIKE ?1
           OR EXISTS (SELECT 1 FROM product_aliases a WHERE a.product_id = p.id AND unaccent(a.key) LIKE ?3)
        ORDER BY p.active DESC, p.name_vi LIMIT ?4
        """,
        (like, f"%{text.strip()}%", f"%{q.replace(' ', '')}%", limit),
    ).fetchall()
    customers_ = conn.execute(
        """
        SELECT * FROM customers
        WHERE unaccent(name) LIKE ?1 OR unaccent(contact) LIKE ?1 OR unaccent(address) LIKE ?1
           OR (?2 <> '' AND phone_norm LIKE '%' || ?2 || '%')
        ORDER BY name LIMIT ?3
        """,
        (like, digits if len(digits) >= 3 else "", limit),
    ).fetchall()
    documents_ = conn.execute(
        """
        SELECT DISTINCT d.*, c.name AS customer_name
        FROM documents d
        LEFT JOIN customers c ON c.id = d.customer_id
        LEFT JOIN document_lines l ON l.document_id = d.id
        WHERE d.code_norm = ?1 OR unaccent(d.code) LIKE ?2 OR unaccent(d.note) LIKE ?2 OR unaccent(c.name) LIKE ?2
           OR unaccent(d.source_file) LIKE ?2 OR unaccent(l.note) LIKE ?2 OR unaccent(l.raw_name) LIKE ?2
        ORDER BY d.doc_date DESC LIMIT ?3
        """,
        (normalize_code(text), like, limit),
    ).fetchall()
    return {"products": products, "customers": customers_, "documents": documents_}
