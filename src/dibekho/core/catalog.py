"""Products, aliases and customers."""

import difflib
from dataclasses import dataclass
from datetime import date, datetime
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

from dibekho import db
from dibekho.core import backup, undo
from dibekho.core.stock import stock_count
from dibekho.core.text import clean, normalize_phone, unaccent
from dibekho.core.workspace import Workspace


def guess_unit(spec: str) -> str:
    """'10KG/Thùng' -> 'thùng', '1m*20m/ cuộn' -> 'cuộn', 'Gói' -> 'gói'."""
    s = clean(spec)
    if "/" in s:
        s = s.rsplit("/", 1)[1]
    s = re.sub(r"[\d.,*]+\s*(kg|m|g|l)?", "", s, flags=re.IGNORECASE).strip()
    return s.lower()


# highest SPxxx number ever given out: a deleted product's code is never given to another product
CODE_MAX_KEY = "product_code_max"
# codes freed by merge_products() (comma-separated, smallest first): given out again before a new one.
# Kept in meta, not a table, so it travels with data packages and rolls back with Hoàn tác like CODE_MAX_KEY.
FREED_CODES_KEY = "freed_codes"


def _freed_codes(conn) -> list[str]:
    raw = db.get_meta(conn, FREED_CODES_KEY, "")
    return [c for c in raw.split(",") if c]


def _free_a_code(conn, code: str) -> None:
    codes = _freed_codes(conn)
    if code not in codes:
        db.set_meta(conn, FREED_CODES_KEY, ",".join(codes + [code]))


def _consume_freed_code(conn, code: str) -> None:
    codes = [c for c in _freed_codes(conn) if c != code]
    db.set_meta(conn, FREED_CODES_KEY, ",".join(codes))


def next_product_code(conn: sqlite3.Connection) -> str:
    """A code freed by merge_products() is given out first (smallest one); otherwise the next SPxxx."""
    freed = _freed_codes(conn)
    if freed:
        return min(freed, key=lambda c: int(c[2:]))
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(code, 3) AS INTEGER)) FROM products WHERE code GLOB 'SP[0-9]*'"
    ).fetchone()
    used = int(db.get_meta(conn, CODE_MAX_KEY, "0") or 0)
    return f"SP{max(row[0] or 0, used) + 1:03d}"


def create_product(conn, name_vi, name_zh="", spec="", unit="", category="", min_stock=0, variant="") -> int:
    code = next_product_code(conn)
    cur = conn.execute(
        "INSERT INTO products(code, name_vi, name_zh, spec, unit, category, min_stock, variant) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (code, clean(name_vi), clean(name_zh), clean(spec),
         clean(unit) or guess_unit(spec), clean(category), float(min_stock or 0), clean(variant)),
    )
    _consume_freed_code(conn, code)
    db.touch(conn)
    return cur.lastrowid


def update_product(conn, product_id, **fields) -> None:
    allowed = {"name_vi", "name_zh", "spec", "unit", "category", "min_stock", "active", "variant", "stock_note"}
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
    code = conn.execute("SELECT code FROM products WHERE id = ?", (product_id,)).fetchone()
    if code and re.fullmatch(r"SP\d+", code[0]):
        used = int(db.get_meta(conn, CODE_MAX_KEY, "0") or 0)
        db.set_meta(conn, CODE_MAX_KEY, str(max(used, int(code[0][2:]))))
    conn.execute("DELETE FROM product_aliases WHERE product_id = ?", (product_id,))
    conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    db.touch(conn)


def _code_num(code: str) -> int:
    m = re.fullmatch(r"SP(\d+)", code or "")
    return int(m.group(1)) if m else -1  # a code outside the SPxxx scheme never loses a merge


def merge_products(conn, product_id_a: int, product_id_b: int) -> int:
    """Two products that turned out to be the same item (typically: one restored from a backup after being
    deleted by mistake, next to a duplicate created in the meantime). Every document line, stock movement
    and alias of the one with the larger code is moved onto the one with the smaller code; any field left
    empty on the surviving product (name_zh, category, min_stock, stock_note) is filled from the other one,
    so a note typed on either side is not lost. The larger one is then deleted and its code freed for the
    next new product. Returns the id that survived."""
    a = conn.execute("SELECT * FROM products WHERE id = ?", (product_id_a,)).fetchone()
    b = conn.execute("SELECT * FROM products WHERE id = ?", (product_id_b,)).fetchone()
    keep, drop = (a, b) if _code_num(a["code"]) <= _code_num(b["code"]) else (b, a)
    conn.execute("UPDATE document_lines SET product_id = ? WHERE product_id = ?", (keep["id"], drop["id"]))
    conn.execute("UPDATE stock_movements SET product_id = ? WHERE product_id = ?", (keep["id"], drop["id"]))
    conn.execute("UPDATE product_aliases SET product_id = ? WHERE product_id = ?", (keep["id"], drop["id"]))
    fill = {}
    for field in ("name_zh", "category", "stock_note"):
        if not (keep[field] or "").strip() and (drop[field] or "").strip():
            fill[field] = drop[field]
    if not (keep["min_stock"] or 0) and (drop["min_stock"] or 0):
        fill["min_stock"] = drop["min_stock"]
    if fill:
        update_product(conn, keep["id"], **fill)
    conn.execute("DELETE FROM products WHERE id = ?", (drop["id"],))
    if re.fullmatch(r"SP\d+", drop["code"] or ""):
        _free_a_code(conn, drop["code"])
    db.touch(conn)
    return keep["id"]


# ---- restoring a deleted product from a backup -----------------------------

_PRODUCT_COLUMNS = ("code", "name_vi", "name_zh", "spec", "unit", "category", "min_stock", "variant", "stock_note")


@dataclass
class DeletedProduct:
    code: str
    name_vi: str
    name_zh: str
    spec: str
    unit: str
    category: str
    min_stock: float
    variant: str
    stock_note: str
    backup_at: datetime  # of the newest backup that still has it
    alias_keys: tuple = ()  # delivery-note names it used to be recognised by, read from that same backup


def _open_readonly(path: Path) -> sqlite3.Connection:
    p = quote(str(path.resolve()).replace("\\", "/"), safe="/:")
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def _backup_files(ws: Workspace) -> list[Path]:
    """Every backup that might still have a deleted product's row, oldest first (so the newest one read
    for a given code wins): daily/named backups and Hoàn tác snapshots (the one just before a delete)."""
    files = backup.list_backups(ws) + [p.path for p in undo.points(ws)]
    return sorted(set(files), key=lambda p: p.stat().st_mtime)


def deleted_products(conn, ws: Workspace) -> list[DeletedProduct]:
    """Products found in some backup but missing from the catalog now (deleted, by mistake or not).
    A code already waiting in the freed pool (merged away on purpose) is not offered again.
    Never writes to a backup file. Old backups (schema before 'variant'/'stock_note' existed) are read too."""
    current = {r[0] for r in conn.execute("SELECT code FROM products")} | set(_freed_codes(conn))
    found: dict[str, DeletedProduct] = {}
    for path in _backup_files(ws):
        try:
            b = _open_readonly(path)
        except sqlite3.Error:
            continue
        try:
            cols = {r[1] for r in b.execute("PRAGMA table_info(products)")}
            present = [c for c in _PRODUCT_COLUMNS if c in cols]
            if "code" not in present or "name_vi" not in present:
                continue
            has_aliases = bool(b.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'product_aliases'").fetchone())
            at = datetime.fromtimestamp(path.stat().st_mtime)
            for row in b.execute(f"SELECT id, {', '.join(present)} FROM products").fetchall():
                data = dict(zip(("id", *present), row))
                if data["code"] in current:
                    continue
                keys = tuple(r[0] for r in b.execute(
                    "SELECT key FROM product_aliases WHERE product_id = ?", (data["id"],))) if has_aliases else ()
                found[data["code"]] = DeletedProduct(
                    code=data["code"], name_vi=data["name_vi"], name_zh=data.get("name_zh", ""),
                    spec=data.get("spec", ""), unit=data.get("unit", ""), category=data.get("category", ""),
                    min_stock=data.get("min_stock", 0) or 0, variant=data.get("variant", ""),
                    stock_note=data.get("stock_note", ""), backup_at=at, alias_keys=keys,
                )
        except sqlite3.Error:
            continue
        finally:
            b.close()
    return sorted(found.values(), key=lambda p: p.code)


def restore_product(conn, code: str, data: DeletedProduct) -> int:
    """Re-create a deleted product with its original code (freed by delete_product so nothing else could
    have taken it). It has no stock movements: a product can only be deleted when no document uses it."""
    cur = conn.execute(
        "INSERT INTO products(code, name_vi, name_zh, spec, unit, category, min_stock, variant, stock_note) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (code, data.name_vi, data.name_zh, data.spec, data.unit, data.category, data.min_stock, data.variant,
         data.stock_note),
    )
    _consume_freed_code(conn, code)
    db.touch(conn)
    return cur.lastrowid


def find_merge_candidates(conn, new_id: int, data: DeletedProduct) -> list[sqlite3.Row]:
    """Products that might be the same item as the one just restored, best evidence first -- never the
    restored product itself:
    1. a product that now owns one of the delivery-note names this one used to be recognised by (read from
       the same backup): the near-certain sign of a duplicate created by re-reading a note after the mistake;
    2. an exact name + packing + type match;
    3. the fuzzy matcher 'Cần xử lý' uses for a line it does not recognise.
    The caller shows these next to the restored product and merges with merge_products() if the user picks
    one; it decides which code survives."""
    seen = {new_id}
    result = []
    for key in data.alias_keys:
        pid = alias_product(conn, key)
        if pid is not None and pid not in seen:
            seen.add(pid)
            row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
            if row is not None:
                result.append(row)
    same = find_same(conn, data.name_vi, data.spec, data.variant)
    if same is not None and same["id"] not in seen:
        seen.add(same["id"])
        result.append(same)
    for p in suggest_products(conn, data.name_zh or data.name_vi, data.spec):
        if p["id"] not in seen:
            seen.add(p["id"])
            result.append(p)
    return result


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


def find_same(conn, name_vi, spec, variant, category=None):
    """Same name + packing + variant (and category, when given), ignoring accents."""
    sql = "SELECT * FROM products WHERE unaccent(name_vi) = ? AND unaccent(spec) = ? AND unaccent(variant) = ?"
    args = [unaccent(clean(name_vi)), unaccent(clean(spec)), unaccent(clean(variant))]
    if category is not None:
        sql += " AND unaccent(category) = ?"
        args.append(unaccent(clean(category)))
    return conn.execute(sql, args).fetchone()


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


def match_score(note_text: str, note_spec: str, p, labels: bool = False) -> float:
    """How likely a delivery-note line is product p. Chinese characters, model codes (FS-101) and the
    packing weight/size matter most, because Vietnamese descriptions differ a lot between documents.
    labels=True also counts the category and type/colour (纯白色, 瑞德牌…), which notes often name."""
    a = _features(f"{note_text} {note_spec}")
    extra = f" {p['category'] or ''} {p['variant'] or ''}" if labels else ""
    b = _features(f"{p['name_zh']} {p['name_vi']} {p['spec']}{extra}")
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
    ranked = _ranked(conn, name, spec)
    return ranked[0][1]["id"] if ranked and ranked[0][0] >= 0.5 else None


def suggest_products(conn, name: str, spec: str, n: int = 3) -> list:
    """The few products that could be this line of a note, best first (e.g. the three sizes of 管根套).
    Shown first in 'Cần xử lý'; the full list stays one click away. Compared with every product, the
    category and type/colour included, since notes name them in their own words (涤纶PPE 瑞德包装 18,5kg)."""
    scored = [(match_score(name, spec, p, labels=True), p) for p in products(conn)]
    return [p for score, p in sorted(scored, key=lambda x: -x[0]) if score > 0.15][:n]


def _ranked(conn, name: str, spec: str) -> list:
    """(score, product) of the products whose Chinese name matches best, best first.

    Only those are compared, so another product that merely shares the packing weight never wins over
    the same product in a different packing.
    """
    note = _features(f"{name} {spec}")["cjk"]
    candidates = products(conn)
    if note:
        overlap = {p["id"]: len(note & _features(p["name_zh"])["cjk"]) / len(note) for p in candidates}
        top = max(overlap.values(), default=0)
        if top == 0:
            return []
        candidates = [p for p in candidates if overlap[p["id"]] >= top - 1e-9]
    scored = [(match_score(name, spec, p), p) for p in candidates]
    return sorted((x for x in scored if x[0] > 0), key=lambda x: -x[0])


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
    # keep existing data, fill in what was missing; a name that is only the phone number (the note had
    # no readable name) is a placeholder and gives way to the real name
    if name and normalize_phone(row["name"]) == row["phone_norm"] and row["phone_norm"]:
        conn.execute("UPDATE customers SET name = ? WHERE id = ?", (name, row["id"]))
    conn.execute(
        "UPDATE customers SET contact = CASE WHEN contact = '' THEN ? ELSE contact END, "
        "phone = CASE WHEN phone = '' THEN ? ELSE phone END, "
        "phone_norm = CASE WHEN phone_norm = '' THEN ? ELSE phone_norm END, "
        "address = CASE WHEN address = '' THEN ? ELSE address END WHERE id = ?",
        (clean(contact), clean(phone), phone_norm, clean(address), row["id"]),
    )
    return row["id"]



# ---- master data (Excel 'Dữ liệu gốc') ----------------------------------------

def _free_code(conn, reserved: set[str]) -> str:
    """Next SPxxx that is neither in the database nor used further down in the file."""
    code = next_product_code(conn)
    while code in reserved:
        code = f"SP{int(code[2:]) + 1:03d}"
    return code


def import_master(conn, products, customers, stock=(), stock_date=None, note="") -> dict:
    """Load products (keeping their codes) and customers from the master-data workbook.

    A code that exists is updated to the file's values; a new code is created as is (no code: next free one).
    A product whose name/packing/variant already exists here under a code that is not in the file is skipped,
    so importing never duplicates a product.
    Customers are matched by phone number, then by name, and take the file's values.
    A code used on several rows (the user copied a row for another variant) belongs to the first of them;
    the other rows become new products with the next free codes (listed in 'renumbered').
    stock (rows of the 'Tồn kho' sheet, each tied to a row of the products sheet): recorded as one stock count
    on stock_date (default today), so the app's stock equals the file's numbers. The stock sheet is the one the
    customer edits, so its category and type/colour replace the product's ('labels_updated').
    Returns counts and the rows that could not be imported.
    """
    result = {"products_new": 0, "products_updated": 0, "customers_new": 0, "customers_updated": 0,
              "skipped": [], "stock_counted": 0, "stock_skipped": [], "renumbered": [], "labels_updated": []}
    row_ids: dict[int, int] = {}  # row of the products sheet -> product id
    seen_codes: set[str] = set()
    file_codes = {p.code for p in products if p.code}
    with db.transaction(conn):
        for p in products:
            fields = dict(name_vi=p.name_vi, name_zh=p.name_zh, spec=p.spec, variant=p.variant,
                          unit=p.unit or guess_unit(p.spec), category=p.category, min_stock=float(p.min_stock or 0),
                          active=int(bool(p.active)))
            duplicate = bool(p.code) and p.code in seen_codes
            seen_codes.add(p.code)
            row = None
            if p.code and not duplicate:
                row = conn.execute("SELECT id FROM products WHERE code = ?", (p.code,)).fetchone()
            if row is not None:
                update_product(conn, row["id"], **fields)
                if p.created_at:
                    conn.execute("UPDATE products SET created_at = ? WHERE id = ?", (p.created_at, row["id"]))
                result["products_updated"] += 1
                row_ids[p.row] = row["id"]
                continue
            # the category counts too: users tell variants apart in either column
            same = find_same(conn, p.name_vi, p.spec, p.variant, p.category)
            if same is not None and same["code"] not in file_codes:  # already here under another code
                result["skipped"].append((p.row, p.code, same["code"]))
                row_ids[p.row] = same["id"]
                continue
            code = p.code if p.code and not duplicate else _free_code(conn, file_codes)
            if duplicate:
                result["renumbered"].append((p.row, p.code, code))
            cur = conn.execute(
                "INSERT INTO products(code, name_vi, name_zh, spec, unit, category, min_stock, active, variant, "
                "created_at) VALUES(?,?,?,?,?,?,?,?,?, COALESCE(NULLIF(?, ''), datetime('now','localtime')))",
                (code, fields["name_vi"], fields["name_zh"], fields["spec"], fields["unit"], fields["category"],
                 fields["min_stock"], fields["active"], fields["variant"], p.created_at),
            )
            _consume_freed_code(conn, code)
            row_ids[p.row] = cur.lastrowid
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
        counted: dict[int, float] = {}
        for st in stock:
            pid = row_ids.get(st.product_row) if st.product_row else None
            if pid is None:
                result["stock_skipped"].append((st.row, st.code or st.name))
            else:
                counted[pid] = st.stock
                p = conn.execute("SELECT code, category, variant FROM products WHERE id = ?", (pid,)).fetchone()
                if (p["category"], p["variant"]) != (st.category, st.variant):
                    update_product(conn, pid, category=st.category, variant=st.variant)
                    result["labels_updated"].append(p["code"])
                if st.note is not None:
                    update_product(conn, pid, stock_note=st.note)
        if counted:
            stock_count(conn, stock_date or date.today(), counted, note)
            result["stock_counted"] = len(counted)
    return result
