"""Reader for the customer's monthly stock sheet (Bảng thống kê nhập - xuất kho tháng ...), used to load the product catalog.

Layout (by label, not position): a header row with 'Tên sản phẩm' and 'Phân loại'; one product per row
below it. Column A = Vietnamese name + Chinese name on two lines, column B = category for single rows.
When column A is merged over several rows, each row is a variant of the same product and column B
holds the variant (纯原料 / 再生料 / 瑞德牌 / 纯白色) instead of a category.
Pure function: workbook in, list of items out. Quantities in the sheet are ignored.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import openpyxl

from dibekho.core.text import clean, has_cjk, nfc, unaccent

CATEGORY_NAMES = {
    "涂料类": "Sơn, vữa, keo (涂料类)",
    "自粘膜": "Màng tự dính (自粘膜)",
    "SBS": "Màng SBS",
    "聚酯布": "Vải polyester (聚酯布)",
}
VARIANT_NAMES = {
    "纯原料": "Nguyên sinh (纯原料)",
    "再生料": "Tái chế (再生料)",
    "瑞德牌": "Hiệu Thụy Đức (瑞德牌)",
    "纯白色": "Trắng tinh (纯白色)",
}
COLOURS = {
    "纯白色": "Trắng tinh",
    "浅灰色": "Xám nhạt",
    "白色": "Trắng",
    "灰色": "Xám",
    "蓝色": "Xanh dương",
}
ROLL_CATEGORY = "Màng PPE/PPP (卷材)"

_WEIGHT = re.compile(r"[（(]?\s*(\d+(?:[.,]\d+)?)\s*kg\s*[)）]?", re.IGNORECASE)
_THICK = re.compile(r"(\d+(?:[.,]\d+)?)\s*mm", re.IGNORECASE)
_DIMS = re.compile(r"(\d+(?:[.,]\d+)?\s*c?m\s*\*\s*\d+(?:[.,]\d+)?\s*m)", re.IGNORECASE)
_GSM = re.compile(r"(\d+)\s*g(?:/m²)?(?![a-z])", re.IGNORECASE)
_TRAILING_PAREN = re.compile(r"[（(]\s*([^（）()]+?)\s*[)）]\s*$")


@dataclass
class CatalogItem:
    row: int
    name_vi: str
    name_zh: str
    spec: str
    unit: str
    category: str
    variant: str


class NotCatalogSheet(Exception):
    pass


def read_catalog(path: Path | str) -> list[CatalogItem]:
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as exc:
        raise NotCatalogSheet(f"Không mở được file Excel: {exc}") from exc
    try:
        for ws in wb.worksheets:
            items = _read_sheet(ws)
            if items is not None:
                return items
    finally:
        wb.close()
    raise NotCatalogSheet("Không thấy cột 'Tên sản phẩm' / 'Phân loại'.")


def _read_sheet(ws) -> list[CatalogItem] | None:
    header_row = name_col = type_col = None
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 20)):
        for cell in row:
            plain = unaccent(str(cell.value or ""))
            if "ten san pham" in plain:
                header_row, name_col = cell.row, cell.column
            elif "phan loai" in plain:
                type_col = cell.column
        if header_row:
            break
    if header_row is None:
        return None

    # rows covered by a merged block in the name column -> first row of the block
    block_start: dict[int, int] = {}
    block_size: dict[int, int] = {}
    for rng in ws.merged_cells.ranges:
        if rng.min_col <= name_col <= rng.max_col and rng.min_row > header_row:
            for r in range(rng.min_row, rng.max_row + 1):
                block_start[r] = rng.min_row
            block_size[rng.min_row] = rng.max_row - rng.min_row + 1

    items: list[CatalogItem] = []
    last_name_row = None
    for r in range(header_row + 1, ws.max_row + 1):
        raw = ws.cell(r, name_col).value
        kind = clean(ws.cell(r, type_col).value) if type_col else ""
        if raw is not None and len(clean(raw)) <= 1:
            continue  # the 'A | B | C' column-letter row
        start = block_start.get(r)
        if start is None and raw is None and kind and last_name_row is not None:
            start = last_name_row  # variant row without merged cells
        if raw is None and start is None:
            continue
        source_row = start or r
        if raw is not None:
            last_name_row = r
        text = ws.cell(source_row, name_col).value
        if not clean(text):
            continue
        grouped = start is not None and (block_size.get(start, 1) > 1 or start != r)
        items.append(_item(r, str(text), kind, grouped))
    return items


def _item(row: int, text: str, kind: str, grouped: bool) -> CatalogItem:
    # Line 1 = Vietnamese name, following lines = Chinese name. A single line is used for both if it is Chinese.
    lines = [clean(x) for x in nfc(text).splitlines() if clean(x)]
    if len(lines) == 1:
        name_vi = lines[0]
        name_zh = lines[0] if has_cjk(lines[0]) and not _latin_heavy(lines[0]) else ""
    else:
        name_vi, name_zh = lines[0], " ".join(lines[1:])

    variants = []
    m = _TRAILING_PAREN.search(name_zh)
    if m and m.group(1) in COLOURS:
        variants.append(COLOURS[m.group(1)])
        name_zh = name_zh[: m.start()].strip()

    spec = _spec(f"{name_vi} {name_zh}")
    name_vi = _strip_weight(name_vi)
    name_zh = _strip_weight(name_zh)

    if grouped:
        category = ROLL_CATEGORY if re.search(r"PP[EP]", text) else ""
        if kind:
            variants.append(VARIANT_NAMES.get(kind, kind))
    else:
        category = CATEGORY_NAMES.get(kind, kind)

    return CatalogItem(
        row=row,
        name_vi=name_vi or name_zh,
        name_zh=name_zh,
        spec=spec,
        unit=_unit(spec, category, name_zh),
        category=category,
        variant=", ".join(variants),
    )


def _latin_heavy(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(1 for c in letters if has_cjk(c)) / len(letters) < 0.3


def _spec(text: str) -> str:
    parts = []
    if m := _THICK.search(text):
        parts.append(f"{m.group(1).replace(',', '.')}mm")
    else:
        # 'SBS 1.5' / 'SBS 2mm' in Vietnamese names
        if m := re.search(r"SBS\s+(\d+(?:[.,]\d+)?)\b", text):
            parts.append(f"{m.group(1).replace(',', '.')}mm")
    if m := _GSM.search(re.sub(r"\d+(?:[.,]\d+)?\s*kg", "", text, flags=re.IGNORECASE)):
        parts.append(f"{m.group(1)}g")
    if m := _DIMS.search(text):
        parts.append(re.sub(r"\s+", "", m.group(1)))
    if m := _WEIGHT.search(text):
        parts.append(f"{m.group(1).replace(',', '.')}KG")
    return " ".join(parts)


def _strip_weight(name: str) -> str:
    """Remove '(20KG)' / '（16.5 kg）' from a name; the weight lives in the spec column."""
    name = _WEIGHT.sub(" ", name)
    name = re.sub(r"[（(]\s*[)）]", " ", name)  # brackets left empty
    return clean(name)


def _unit(spec: str, category: str, name_zh: str) -> str:
    if "袋" in name_zh:
        return "gói"
    if any(k in category for k in ("Màng", "Vải")) or "*" in spec or "mm" in spec:
        return "cuộn"
    if "KG" in spec:
        return "thùng"
    return ""
