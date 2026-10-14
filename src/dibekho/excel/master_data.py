"""'Dữ liệu gốc': the product catalog and the customer list as one Excel workbook.

Written from Settings ('Xuất dữ liệu gốc'), readable by people, and read back on another computer
('Nhập dữ liệu gốc') to get exactly the same products (same codes) and customers.

Layout (fixed, so the file reads back whatever the interface language was):
  sheet 1 = products, sheet 2 = customers; A1 starts with MARKER; header in row 4; data from row 5.
  products : STT | code | name_vi | name_zh | spec | variant | unit | category | created | min_stock | active
  customers: STT | name | phone | contact | address | orders (read-only, recomputed by the app)
  sheet 3 = stock, like the customer's monthly stock sheet: code | name | category | variant | stock.
            The customer may correct the stock there; importing the file sets the app's stock to it (a stock
            count). The stock sheet is the reference (the user's rule, 14/10/2026): sheet 1 is only used to find
            the product each stock row describes. Each stock row is tied to a row of sheet 1 (product_row):
            1. by code, when the code is unique in sheet 1;
            2. otherwise by what the row says: same name (+ packing + Chinese name), or else same Chinese name
               and packing (the Vietnamese name was edited in one sheet); then the most labels in common
               (category, type/colour, in whichever column the user typed them); row order only breaks ties;
            3. otherwise by position, if that product is still free.
            Files exported before the code column existed (name | category | variant | stock) work the same way.
            Rows not tied by code are shown to the user before the import (ui: StockMatchDialog).
"""

from dataclasses import dataclass
from datetime import date, datetime
from itertools import permutations
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from dibekho.core.stock import stock_levels
from dibekho.core.text import clean, match_key, parse_number
from dibekho.i18n import t

MARKER = "DIBEKHO"
HEADER_ROW = 4

_HEAD = Font(bold=True, color="FFFFFF")
_FILL = PatternFill("solid", fgColor="1F4E78")
_THIN = Side(style="thin", color="BFBFBF")
_BOX = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


class NotMasterData(ValueError):
    pass


@dataclass
class MasterProduct:
    row: int
    code: str
    name_vi: str
    name_zh: str = ""
    spec: str = ""
    variant: str = ""
    unit: str = ""
    category: str = ""
    created_at: str = ""  # 'YYYY-MM-DD HH:MM:SS' or ''
    min_stock: float = 0
    active: bool = True


@dataclass
class MasterStock:
    row: int
    code: str
    name: str
    stock: float
    product_row: int | None = None  # the row of sheet 1 it belongs to; None = not found
    category: str = ""
    variant: str = ""
    matched_by: str = ""  # 'code' | 'name' | 'position' | '' (not found)


def needs_check(stock: list[MasterStock]) -> bool:
    """True when some stock row is not tied to its product by a unique code."""
    return any(st.matched_by != "code" for st in stock)


def stock_differs(st: MasterStock, p: MasterProduct) -> bool:
    """The stock row does not describe this product: another name (neither the whole name nor the Chinese
    name + packing), or a category/type label of the stock row that the product does not have."""
    text = _stock_key(st.name)
    same_name = _fits_whole(text, _product_key(p)) or (
        _chinese_key(p) is not None and _fits_chinese(text, _chinese_key(p)))
    return not same_name or not _labels(st.category, st.variant) <= _labels(p.category, p.variant)


def _norm(text) -> str:
    """Compared without case, spaces or full-width forms ('（HY98）' = '(hy98)')."""
    return match_key(clean(text), "")[:-1]  # match_key ends with '|' + spec


def _stock_key(name: str) -> str:
    return _norm(name)


def _product_key(p: MasterProduct) -> str:
    return _norm(_name_text(p.name_vi, p.spec, p.name_zh))


def _fits_whole(text: str, key: str) -> bool:
    return text == key


def _chinese_key(p: MasterProduct):
    """Chinese name + packing, for a product whose Vietnamese name was edited in one sheet only."""
    return (_norm(p.name_zh), _norm(p.spec)) if p.name_zh else None


def _fits_chinese(text: str, key) -> bool:
    return text.endswith(key[0]) and key[1] in text  # the stock row ends with the Chinese name


def _labels(*values) -> frozenset:
    """Category and type/colour as a set: users put the same label in either column."""
    return frozenset(_norm(x) for v in values for x in clean(v).split() if x)


@dataclass
class MasterCustomer:
    row: int
    name: str
    phone: str = ""
    contact: str = ""
    address: str = ""


# ---- write -------------------------------------------------------------------

def export(path: Path, conn) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = t("master.sheet_products")
    products = conn.execute("SELECT * FROM products ORDER BY code").fetchall()
    rows = [[i, p["code"], p["name_vi"], p["name_zh"], p["spec"], p["variant"], p["unit"], p["category"],
             _to_datetime(p["created_at"]), p["min_stock"], t("btn.yes") if p["active"] else t("btn.no")]
            for i, p in enumerate(products, 1)]
    _sheet(ws, t("master.title_products"),
           [t("master.col_no"), t("col.code"), t("master.col_name_vi"), t("col.name_zh"), t("col.spec"),
            t("col.variant"), t("col.unit"), t("col.category"), t("master.col_created"), t("col.min_stock"),
            t("settings.active")],
           rows, [5, 10, 42, 30, 14, 20, 8, 24, 12, 12, 9], date_col=9)

    ws2 = wb.create_sheet(t("master.sheet_customers"))
    customers = conn.execute(
        "SELECT c.*, (SELECT COUNT(*) FROM documents d WHERE d.customer_id = c.id AND d.kind = 'delivery' "
        "AND d.status = 'active') AS orders FROM customers c ORDER BY c.name"
    ).fetchall()
    rows = [[i, c["name"], c["phone"], c["contact"], c["address"], c["orders"]] for i, c in enumerate(customers, 1)]
    _sheet(ws2, t("master.title_customers"),
           [t("master.col_no"), t("col.customer"), t("col.phone"), t("col.contact"), t("col.address"),
            t("master.col_orders")],
           rows, [5, 36, 15, 18, 48, 9])

    ws3 = wb.create_sheet(t("master.sheet_stock"))
    levels = stock_levels(conn)
    # by code = the row order of the monthly sheet the catalog was loaded from
    active = conn.execute("SELECT * FROM products WHERE active = 1 ORDER BY code")
    rows = [[p["code"], _stock_name(p), p["category"], p["variant"], levels.get(p["id"], 0)] for p in active]
    _sheet(ws3, t("master.title_stock"),
           [t("col.code"), t("col.product"), t("col.category"), t("col.variant"), t("col.stock")],
           rows, [10, 52, 26, 22, 12])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def _stock_name(p) -> str:
    """Like column A of the monthly sheet: Vietnamese name (with packing) on line 1, Chinese name on line 2."""
    return _name_text(p["name_vi"], p["spec"], p["name_zh"])


def _name_text(name_vi, spec, name_zh) -> str:
    first = name_vi
    if spec and spec.casefold() not in first.casefold():
        first += f" ({spec})"
    return f"{first}\n{name_zh}" if name_zh and name_zh != name_vi else first


def _sheet(ws, title, headers, rows, widths, date_col=None, freeze="C5"):
    ws.append([f"{MARKER} – {title}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([t("master.note", at=datetime.now().strftime("%d/%m/%Y %H:%M"))])
    ws["A2"].font = Font(italic=True, color="595959")
    ws.append([])
    ws.append(headers)
    for c in ws[HEADER_ROW]:
        c.font, c.fill, c.border = _HEAD, _FILL, _BOX
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in rows:
        ws.append(row)
        for c in ws[ws.max_row]:
            c.border = _BOX
            c.alignment = Alignment(vertical="top", wrap_text=True)
        if date_col:
            ws.cell(ws.max_row, date_col).number_format = "dd/mm/yyyy"
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = freeze
    ws.auto_filter.ref = f"A{HEADER_ROW}:{get_column_letter(len(headers))}{max(ws.max_row, HEADER_ROW)}"


def _to_datetime(text: str):
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return text


# ---- read --------------------------------------------------------------------

def read(path: Path | str) -> tuple[list[MasterProduct], list[MasterCustomer], list[MasterStock]]:
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as exc:  # not an Excel file, damaged, locked
        raise NotMasterData(str(exc)) from exc
    try:
        return _read(wb)
    finally:
        wb.close()


def _read(wb):
    sheets = wb.worksheets
    if len(sheets) < 2 or not all(str(s["A1"].value or "").startswith(MARKER) for s in sheets[:2]):
        raise NotMasterData(t("master.not_master"))
    products, customers = [], []
    for r, row in enumerate(sheets[0].iter_rows(min_row=HEADER_ROW + 1, values_only=True), HEADER_ROW + 1):
        row = list(row) + [None] * 11
        name_vi = clean(row[2])
        if not name_vi:
            continue
        products.append(MasterProduct(
            r, clean(row[1]), name_vi, clean(row[3]), clean(row[4]), clean(row[5]), clean(row[6]), clean(row[7]),
            _created(row[8]), _number(row[9]), _active(row[10]),
        ))
    for r, row in enumerate(sheets[1].iter_rows(min_row=HEADER_ROW + 1, values_only=True), HEADER_ROW + 1):
        row = list(row) + [None] * 6
        name, phone = clean(row[1]), clean(row[2])
        if name or phone:
            customers.append(MasterCustomer(r, name, phone, clean(row[3]), clean(row[4])))
    stock = []
    if len(sheets) > 2 and str(sheets[2]["A1"].value or "").startswith(MARKER):
        stock = _read_stock(sheets[2], products)
    return products, customers, stock


def _read_stock(ws, products: list[MasterProduct]) -> list[MasterStock]:
    """Rows of the stock sheet, each tied to a row of sheet 1 (see the module docstring)."""
    header = [clean(c.value) for c in ws[HEADER_ROW]]
    with_code = len([h for h in header if h]) >= 5
    lines = []  # (row, code, name, category, variant, stock)
    for r, row in enumerate(ws.iter_rows(min_row=HEADER_ROW + 1, values_only=True), HEADER_ROW + 1):
        row = list(row) + [None] * 5
        if not with_code:
            row = [None] + row
        code, name = clean(row[0]), clean(row[1])
        if code or name:
            lines.append((r, code, name, clean(row[2]), clean(row[3]), _stock_value(row[4])))

    active = [p for p in products if p.active]
    code_count: dict[str, int] = {}
    for p in products:
        code_count[p.code] = code_count.get(p.code, 0) + 1
    by_code = {p.code: p for p in products if p.code and code_count[p.code] == 1}
    rows = [MasterStock(r, code, name, value, None, category, variant)
            for r, code, name, category, variant, value in lines]
    taken: set[int] = set()

    for st in rows:  # 1. code
        p = by_code.get(st.code) if st.code else None
        if p is not None and p.row not in taken:
            st.product_row, st.matched_by = p.row, "code"
            taken.add(p.row)

    # 2. what the row says: the whole name, then the Chinese name + packing
    position = {p.row: i for i, p in enumerate(active)}
    for product_key, fits in ((_product_key, _fits_whole), (_chinese_key, _fits_chinese)):
        groups: dict = {}  # key -> (stock rows with their index, products)
        for p in active:
            if p.row not in taken and product_key(p) is not None:
                groups.setdefault(product_key(p), ([], []))[1].append(p)
        for i, st in enumerate(rows):
            if st.product_row is None:
                keys = [k for k in groups if fits(_stock_key(st.name), k)]
                if len(keys) == 1:
                    groups[keys[0]][0].append((i, st))
        for stocks, prods in groups.values():
            for st, p in _best_pairs(stocks, prods, position):
                st.product_row, st.matched_by = p.row, "name"
                taken.add(p.row)

    # 3. position, for rows whose name was changed in one sheet only
    if len(rows) == len(active):
        for i, st in enumerate(rows):
            if st.product_row is None and active[i].row not in taken:
                st.product_row, st.matched_by = active[i].row, "position"
                taken.add(active[i].row)
    return [st for st in rows if st.stock is not None]


def _best_pairs(stocks: list[tuple[int, MasterStock]], prods: list[MasterProduct], position: dict[int, int]):
    """Stock rows (with their index in the sheet) and products sharing one name: pair them for the most
    labels in common, then the most rows at the same position. A handful of rows per name, so trying every
    pairing is cheap."""
    if not stocks or not prods:
        return []
    if len(stocks) > 7 or len(prods) > 7:  # never seen; keep the order
        return [(st, p) for (_, st), p in zip(stocks, prods)]

    def score(pairs):
        common = sum(len(_labels(st.category, st.variant) & _labels(p.category, p.variant)) for (_, st), p in pairs)
        same_place = sum(i == position[p.row] for (i, _), p in pairs)
        return common, same_place

    if len(stocks) <= len(prods):
        options = (list(zip(stocks, chosen)) for chosen in permutations(prods, len(stocks)))
    else:
        options = (list(zip(chosen, prods)) for chosen in permutations(stocks, len(prods)))
    return [(st, p) for (_, st), p in max(options, key=score)]


def _stock_value(value) -> float | None:
    if value is None or clean(value) == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return parse_number(clean(value))
    except ValueError:
        return None


def _created(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d 00:00:00")
    text = clean(value)
    try:  # '2026-10-14 09:36:32' typed or kept as text
        return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10], fmt).strftime("%Y-%m-%d 00:00:00")
        except ValueError:
            pass
    return ""


def _number(value) -> float:
    try:
        return float(str(value).replace(",", ".")) if value not in (None, "") else 0
    except ValueError:
        return 0


def _active(value) -> bool:
    text = clean(value).casefold()
    return text not in ("không", "khong", "no", "0", "false", "否")  # "No" in any app language
