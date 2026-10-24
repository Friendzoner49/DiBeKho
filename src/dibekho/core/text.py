"""Text normalization helpers shared by the Excel readers, matching and search."""

import re
import unicodedata

_CJK = re.compile(r"[　-〿㐀-䶿一-鿿＀-￯]")
_SPACES = re.compile(r"\s+")


def nfc(text: str) -> str:
    # macOS stores file names in NFD; compare everything in NFC.
    return unicodedata.normalize("NFC", text)


def clean(text) -> str:
    """Collapse whitespace and trim. None -> ''."""
    if text is None:
        return ""
    return _SPACES.sub(" ", nfc(str(text))).strip()


def unaccent(text) -> str:
    """Lowercase, strip Vietnamese diacritics, map đ -> d. Used for accent-insensitive search."""
    if text is None:
        return ""
    s = unicodedata.normalize("NFKD", str(text).casefold())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.replace("đ", "d")


def match_key(name: str, spec: str) -> str:
    """Key used to recognise the same product line across delivery notes.

    NFKC turns full-width brackets/colons into ASCII; whitespace is removed entirely
    so '20KG/thùng' and '20kg/ thùng' give the same key.
    """
    def norm(s: str) -> str:
        s = unicodedata.normalize("NFKC", s or "").casefold()
        return _SPACES.sub("", s).rstrip(".,;")

    return f"{norm(name)}|{norm(spec)}"


def has_cjk(text: str) -> bool:
    return bool(_CJK.search(text or ""))


def split_bilingual_name(raw: str) -> tuple[str, str]:
    """Split a cell like '背水涂\\nvữa chống thấm ...' into (name_vi, name_zh)."""
    lines = [clean(x) for x in nfc(raw or "").splitlines()]
    lines = [x for x in lines if x]
    zh = [x for x in lines if has_cjk(x) and not _mostly_latin(x)]
    vi = [x for x in lines if x not in zh]
    return " ".join(vi), " ".join(zh)


def _mostly_latin(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    cjk = sum(1 for c in letters if _CJK.match(c))
    return cjk / len(letters) < 0.3


def normalize_phone(phone) -> str:
    digits = re.sub(r"\D", "", str(phone or ""))
    if digits.startswith("84") and len(digits) >= 11:
        digits = "0" + digits[2:]
    return digits


def normalize_code(code) -> str:
    """Order codes '076' and '76' are the same order."""
    s = clean(code)
    return s.lstrip("0") or s


def parse_number(text) -> float:
    """'12', '12,5', '１２' or '１２，５' (typed with a Chinese input method) -> float. Raises ValueError."""
    s = unicodedata.normalize("NFKC", str(text)).strip().replace(" ", "").replace(",", ".")
    s = s.replace("。", ".")
    return float(s)


def fmt_qty(value) -> str:
    """Show 5.0 as '5' and 2.5 as '2.5'."""
    if value is None:
        return ""
    v = float(value)
    if v.is_integer():
        return f"{int(v):,}".replace(",", ".")
    return f"{v:,.2f}".rstrip("0").rstrip(".").replace(",", "X").replace(".", ",").replace("X", ".")
