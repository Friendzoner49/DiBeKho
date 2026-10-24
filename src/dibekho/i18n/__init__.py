"""Tiny translation helper: t("key", name="x") looks up i18n/<lang>.json.

Vietnamese is the default and the reference: every key must exist in vi.json.
Missing English/Chinese keys fall back to Vietnamese; missing keys everywhere show the key itself.
"""

import json
from importlib import resources

LANGUAGES = {"vi": "Tiếng Việt", "en": "English", "zh": "中文（简体）"}
_tables: dict[str, dict] = {}
_current = "vi"


def _load(lang: str) -> dict:
    if lang not in _tables:
        text = (resources.files("dibekho.i18n") / f"{lang}.json").read_text(encoding="utf-8")
        _tables[lang] = json.loads(text)
    return _tables[lang]


def set_language(lang: str) -> None:
    global _current
    _current = lang if lang in LANGUAGES else "vi"


def language() -> str:
    return _current


def t(key: str, **kwargs) -> str:
    text = _load(_current).get(key) or _load("vi").get(key) or key
    return text.format(**kwargs) if kwargs else text
