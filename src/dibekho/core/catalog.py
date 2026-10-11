"""Products, aliases and customers."""

import difflib
import re
import sqlite3

from dibekho import db
from dibekho.core.stock import stock_count
from dibekho.core.text import clean, normalize_phone, unaccent


def guess_unit(spec: str) -> str:
    """'10KG/Thùng' -> 'thùng', '1m*20m/ cuộn' -> 'cuộn', 'Gói' -> 'gói'."""
    s = clean(spec)
    if "/" in s:
        s = s.rsplit("/", 1)[1]
    s = re.sub(r"[\d.,*]+\s*(kg|m|g|l)?", "", s, flags=re.IGNORECASE).strip()
    return s.lower()


def next_product_code(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(code, 3) AS INTEGER)) FROM products WHERE code GLOB 'SP[0-9]*'"
    ).fetchone()
    return f"SP{(row[0] or 0) + 1:03d}"


def create_product(conn, name_vi, name_zh="", spec="", unit="", category="", min_stock=0, variant="") -> int:
    cur = conn.execute(
        "INSERT INTO products(code, name_vi, name_zh, spec, unit, category, min_stock, variant) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (next_product_code(conn), clean(name_vi), clean(name_zh), clean(spec),
         clean(unit) or guess_unit(spec), clean(category), float(min_stock or 0), clean(variant)),
    )
    db.touch(conn)
    return cur.lastrowid


def update_product(conn, product_id, **fields) -> None:
    allowed = {"name_vi", "name_zh", "spec", "unit", "category", "min_stock", "active", "variant"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    conn.execute(
        f"UPDATE products SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
        (*sets.values(), product_id),
    )
    db.touch(conn)


def product_documents(conn, product_id) -> int:
    """How many documents (any status, cancelled ones too) have a line with this product."""
    return conn.execute(
        "SELECT COUNT(DISTINCT document_id) FROM ("
        " SELECT document_id FROM document_lines WHERE product_id = ?"
        " UNION ALL SELECT document_id FROM stock_movements WHERE product_id = ?)",
        (product_id, product_id),
    ).fetchone()[0]


def delete_product(conn, product_id) -> None:
    """Delete a product that no document uses, with the delivery-note names learned for it.
    A product that is in documents is kept (history and stock must stay right): set it inactive instead."""
    if product_documents(conn, product_id):
        raise ValueError("Mặt hàng đã có trong phiếu, không xoá được.")
    conn.execute("DELETE FROM product_aliases WHERE product_id = ?", (product_id,))
    conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    db.touch(conn)


def products(conn, include_inactive=False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM products"
    if not include_inactive:
        sql += " WHERE active = 1"
    return conn.execute(sql + " ORDER BY category, name_vi, spec, variant").fetchall()


def label(p) -> str:
    """'SP003 · Sơn FS-101 · 10KG · Xám nhạt' for pickers."""
    return " · ".join(x for x in (p["code"], p["name_vi"], p["spec"], p["variant"]) if x)


def long_label(p) -> str:
    """label() plus the Chinese name, so a picker can be searched in either language."""
    return label(p) + (f" · {p['name_zh']}" if p["name_zh"] and p["name_zh"] != p["name_vi"] else "")


def find_same(conn, name_vi, spec, variant):
    return conn.execute(
        "SELECT * FROM products WHERE unaccent(name_vi) = ? AND unaccent(spec) = ? AND unaccent(variant) = ?",
        (unaccent(clean(name_vi)), unaccent(clean(spec)), unaccent(clean(variant))),
    ).fetchone()


def import_catalog(conn, items, stock_date=None, note="") -> tuple[int, int, int]:
    """Create products that do not exist yet (same name + spec + variant). Returns (created, skipped, counted).

    stock_date given: the sheet's stock (item.stock) of every item, new or existing, is recorded as a stock
    count on that date, so the app's stock becomes exactly the sheet's number. One transaction."""
    created = skipped = 0
    counted: dict[int, float] = {}
    with db.transaction(conn):
        for it in items:
            same = find_same(conn, it.name_vi, it.spec, it.variant)
            if same:
                skipped += 1
                pid = same["id"]
            else:
                pid = create_product(conn, it.name_vi, it.name_zh, it.spec, it.unit, it.category,
                                     variant=it.variant)
                created += 1
            if stock_date is not None and getattr(it, "stock", None) is not None:
                counted[pid] = it.stock
        if counted:
            stock_count(conn, stock_date, counted, note)
        db.log(conn, "catalog_import", f"{created} created, {skipped} skipped, {len(counted)} stock")
    return created, skipped, len(counted)


def categories(conn) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM products WHERE category <> '' ORDER BY category")]


def alias_product(conn, key: str) -> int | None:
    row = conn.execute("SELECT product_id FROM product_aliases WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_alias(conn, key: str, product_id: int, label_: str = "") -> None:
    conn.execute(
        "INSERT INTO product_aliases(key, product_id, label) VALUES(?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET product_id = excluded.product_id, "
        "label = CASE WHEN excluded.label <> '' THEN excluded.label ELSE product_aliases.label END",
        (key, product_id, label_),
    )
    conn.execute("DELETE FROM ignored_lines WHERE key = ?", (key,))
    db.touch(conn)


# ---- lines that are not goods (phí vận chuyển, phí dịch vụ...) --------------

_FEE_WORDS = ("van chuyen", "ship", "dich vu", "cuoc", "运费", "服务费", "费用", "运输", "fee")


def looks_like_fee(name: str) -> bool:
    """Guess whether a delivery-note line is a fee rather than goods (only pre-selects 'skip' in the UI)."""
    text = unaccent(name).strip()
    return text.startswith("phi ") or any(w in text for w in _FEE_WORDS)


def is_ignored(conn, key: str) -> bool:
    return conn.execute("SELECT 1 FROM ignored_lines WHERE key = ?", (key,)).fetchone() is not None


def ignore_line(conn, key: str, label_: str) -> None:
    conn.execute("INSERT OR REPLACE INTO ignored_lines(key, label) VALUES(?, ?)", (key, label_))
    conn.execute("DELETE FROM product_aliases WHERE key = ?", (key,))
    db.touch(conn)


def unignore_line(conn, key: str) -> None:
    conn.execute("DELETE FROM ignored_lines WHERE key = ?", (key,))
    db.touch(conn)


def forget_alias(conn, key: str) -> None:
    conn.execute("DELETE FROM product_aliases WHERE key = ?", (key,))
    db.touch(conn)


def ignored_lines(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM ignored_lines ORDER BY label").fetchall()


_CJK_CHAR = re.compile("[㐀-䶿一-鿿]")  # CJK ideographs
_MODEL = re.compile(r"\b([A-Z]{2,4})\s*-?\s*(\d{2,4})\b")
_KG = re.compile(r"(\d+(?:[.,]\d+)?)\s*kg", re.IGNORECASE)
_DIM = re.compile(r"(\d+(?:[.,]\d+)?c?m)\s*\*\s*(\d+(?:[.,]\d+)?m)", re.IGNORECASE)


def _features(text: str) -> dict:
    up = text.upper()
    return {
        "cjk": set(_CJK_CHAR.findall(text)),
        "models": {f"{a}{b}" for a, b in _MODEL.findall(up)},
        "kg": {m.replace(",", ".").rstrip("0").rstrip(".") for m in _KG.findall(text)},
        "dims": {f"{a}*{b}".lower() for a, b in _DIM.findall(text)},
    }


def match_score(note_text: str, note_spec: str, p) -> float:
    """How likely a delivery-note line is product p. Chinese characters, model codes (FS-101) and the
    packing weight/size matter most, because Vietnamese descriptions differ a lot between documents."""
    a = _features(f"{note_text} {note_spec}")
    b = _features(f"{p['name_zh']} {p['name_vi']} {p['spec']}")
    score = 0.0
    if a["cjk"] and b["cjk"]:
        overlap = len(a["cjk"] & b["cjk"]) / len(a["cjk"])
        if overlap < 0.5:
            return 0.3 * overlap  # the Chinese name is the most reliable identifier
        score += 0.6 * overlap
    score += 0.2 * difflib.SequenceMatcher(None, unaccent(note_text), unaccent(f"{p['name_vi']} {p['name_zh']}")).ratio()
    if a["models"] and b["models"]:
        score += 0.3 if a["models"] & b["models"] else -0.6
    if a["kg"] and b["kg"]:
        score = score + 0.2 if a["kg"] & b["kg"] else score * 0.4  # same product, other packing = other item
    if a["dims"] and b["dims"]:
        score += 0.15 if a["dims"] & b["dims"] else -0.15
    return score


def suggest_product(conn, name: str, spec: str) -> int | None:
    """Best match among active products, or None when nothing is close enough.

    Only products whose Chinese name matches best are compared, so another product that merely
    shares the packing weight never wins over the same product in a different packing.
    """
    note = _features(f"{name} {spec}")["cjk"]
    candidates = products(conn)
    if note:
        overlap = {p["id"]: len(note & _features(p["name_zh"])["cjk"]) / len(note) for p in candidates}
        top = max(overlap.values(), default=0)
        candidates = [p for p in candidates if overlap[p["id"]] >= top - 1e-9]
    best, best_score = None, 0.0
    for p in candidates:
        score = match_score(name, spec, p)
        if score > best_score:
            best, best_score = p["id"], score
    return best if best_score >= 0.5 else None


def upsert_customer(conn, name, phone="", contact="", address="") -> int | None:
    name, phone_norm = clean(name), normalize_phone(phone)
    if not name and not phone_norm:
        return None
    row = None
    if phone_norm:
        row = conn.execute("SELECT * FROM customers WHERE phone_norm = ?", (phone_norm,)).fetchone()
    if row is None and name:
        row = conn.execute("SELECT * FROM customers WHERE unaccent(name) = ?", (unaccent(name),)).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO customers(name, contact, phone, phone_norm, address) VALUES(?,?,?,?,?)",
            (name or phone, clean(contact), clean(phone), phone_norm, clean(address)),
        )
        return cur.lastrowid
    # keep existing data, fill in what was missing
    conn.execute(
        "UPDATE customers SET contact = CASE WHEN contact = '' THEN ? ELSE contact END, "
        "phone = CASE WHEN phone = '' THEN ? ELSE phone END, "
        "phone_norm = CASE WHEN phone_norm = '' THEN ? ELSE phone_norm END, "
        "address = CASE WHEN address = '' THEN ? ELSE address END WHERE id = ?",
        (clean(contact), clean(phone), phone_norm, clean(address), row["id"]),
    )
    return row["id"]



# ---- master data (Excel 'Dữ liệu gốc') ----------------------------------------

def import_master(conn, products, customers) -> dict:
    """Load products (keeping their codes) and customers from the master-data workbook.

    A code that exists is updated to the file's values; a new code is created as is (no code: next free one).
    A product whose name/packing/variant already exists here under a code that is not in the file is skipped,
    so importing never duplicates a product.
    Customers are matched by phone number, then by name, and take the file's values.
    Returns counts and the rows that could not be imported.
    """
    result = {"products_new": 0, "products_updated": 0, "customers_new": 0, "customers_updated": 0,
              "skipped": []}
    file_codes = {p.code for p in products if p.code}
    with db.transaction(conn):
        for p in products:
            fields = dict(name_vi=p.name_vi, name_zh=p.name_zh, spec=p.spec, variant=p.variant,
                          unit=p.unit or guess_unit(p.spec), category=p.category, min_stock=float(p.min_stock or 0),
                          active=int(bool(p.active)))
            row = conn.execute("SELECT id FROM products WHERE code = ?", (p.code,)).fetchone() if p.code else None
            if row is not None:
                update_product(conn, row["id"], **fields)
                if p.created_at:
                    conn.execute("UPDATE products SET created_at = ? WHERE id = ?", (p.created_at, row["id"]))
                result["products_updated"] += 1
                continue
            same = find_same(conn, p.name_vi, p.spec, p.variant)
            if same is not None and same["code"] not in file_codes:  # already here under another code
                result["skipped"].append((p.row, p.code, same["code"]))
                continue
            code = p.code or next_product_code(conn)
            conn.execute(
                "INSERT INTO products(code, name_vi, name_zh, spec, unit, category, min_stock, active, variant, "
                "created_at) VALUES(?,?,?,?,?,?,?,?,?, COALESCE(NULLIF(?, ''), datetime('now','localtime')))",
                (code, fields["name_vi"], fields["name_zh"], fields["spec"], fields["unit"], fields["category"],
                 fields["min_stock"], fields["active"], fields["variant"], p.created_at),
            )
            result["products_new"] += 1
        for c in customers:
            phone_norm = normalize_phone(c.phone)
            row = None
            if phone_norm:
                row = conn.execute("SELECT id FROM customers WHERE phone_norm = ?", (phone_norm,)).fetchone()
            if row is None and c.name:
                row = conn.execute("SELECT id FROM customers WHERE unaccent(name) = ?", (unaccent(c.name),)).fetchone()
            values = (c.name or c.phone, clean(c.contact), clean(c.phone), phone_norm, clean(c.address))
            if row is None:
                conn.execute("INSERT INTO customers(name, contact, phone, phone_norm, address) VALUES(?,?,?,?,?)",
                             values)
                result["customers_new"] += 1
            else:
                conn.execute("UPDATE customers SET name = ?, contact = ?, phone = ?, phone_norm = ?, address = ? "
                             "WHERE id = ?", (*values, row["id"]))
                result["customers_updated"] += 1
        db.touch(conn)
        db.log(conn, "master_import", f"{result['products_new']}+{result['products_updated']} products, "
                                      f"{result['customers_new']}+{result['customers_updated']} customers")
    return result
