"""CNY ⇄ VND, for the ₫ | ¥ switch at the bottom left (user's request, 14/11/2026: the market rate).

The rate comes from FXRatesAPI (no key, the market rate of the minute; user 15/11/2026: the once-a-day rate "does
not work in real time"); when it does not answer, from the free ExchangeRate-API endpoint (once a day). Both ask to
be named next to the rate. It is kept in fx.json next to config.json, so the switch still works offline with the
last rate, which then shows its time. Nothing about the user or the data is sent: one plain GET.
"""

import json
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dibekho.core import workspace

URL = "https://api.fxratesapi.com/latest?base=CNY&currencies=VND"
SOURCE = "FXRatesAPI"
DAILY_URL = "https://open.er-api.com/v6/latest/CNY"  # the fallback: one rate a day
DAILY_SOURCE = "ExchangeRate-API"
TIMEOUT = 8  # seconds; the window shows the cached rate meanwhile
FILE = "fx.json"
FRESH_SECONDS = 600  # the rate on screen is asked again when older than this (the switch, every 10 minutes)


@dataclass
class Rate:
    vnd_per_cny: float
    updated: datetime  # when the provider computed it (local time)
    fetched: datetime  # when this computer got it
    source: str = SOURCE

    def to_vnd(self, cny: float) -> float:
        return cny * self.vnd_per_cny

    def to_cny(self, vnd: float) -> float:
        return vnd / self.vnd_per_cny


def _path() -> Path:
    return workspace.config_dir() / FILE  # through the module: tests point it at a temporary folder


def parse(data: dict, fetched: datetime | None = None) -> Rate:
    """A provider's JSON -> Rate: FXRatesAPI ({"success": true, "base": "CNY", "timestamp": ...}) or ExchangeRate-API
    ({"result": "success", "base_code": "CNY", "time_last_update_unix": ...}). Raises ValueError when it is not a
    usable answer."""
    if not isinstance(data, dict):
        raise ValueError("Trang tỷ giá trả lời không đúng.")
    if data.get("success") is True and data.get("base") == "CNY":
        stamp, source = data.get("timestamp"), SOURCE
    elif data.get("result") == "success" and data.get("base_code") == "CNY":
        stamp, source = data.get("time_last_update_unix"), DAILY_SOURCE
    else:
        raise ValueError("Trang tỷ giá trả lời không đúng.")
    rates = data.get("rates")
    vnd = rates.get("VND") if isinstance(rates, dict) else None
    if isinstance(vnd, bool) or not isinstance(vnd, (int, float)) or not vnd > 0:
        raise ValueError("Trang tỷ giá không có tỷ giá VND.")
    try:
        updated = datetime.fromtimestamp(int(stamp or 0), timezone.utc).astimezone()
    except (TypeError, ValueError, OverflowError, OSError) as exc:
        raise ValueError("Trang tỷ giá trả lời không đúng.") from exc
    return Rate(float(vnd), updated.replace(tzinfo=None), fetched or datetime.now(), source)


def _get(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "DiBeKho", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch(timeout: float = TIMEOUT, get=_get) -> Rate:
    """Ask the provider of the minute's rate, then the once-a-day one (network); the rate got is cached.
    Raises OSError/ValueError when neither answers."""
    try:
        rate = parse(get(URL, timeout))
    except (OSError, ValueError):
        rate = parse(get(DAILY_URL, timeout))
    save(rate)
    return rate


def save(rate: Rate) -> None:
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"vnd_per_cny": rate.vnd_per_cny, "updated": rate.updated.isoformat(),
                                    "fetched": rate.fetched.isoformat(), "source": rate.source}), encoding="utf-8")
    except OSError:
        pass  # only a cache


def cached() -> Rate | None:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return Rate(float(data["vnd_per_cny"]), datetime.fromisoformat(data["updated"]),
                    datetime.fromisoformat(data["fetched"]), str(data.get("source") or DAILY_SOURCE))
    except (OSError, ValueError, KeyError, TypeError):
        return None


class Display:
    """What the screens show money in (the ₫ / ¥ switch at the bottom left, user's request 14/11/2026: every amount
    of the app in yuan at today's rate). The data and every file stay in VND; only the text on screen changes."""

    currency = "vnd"  # "vnd" | "cny"
    rate: Rate | None = None

    @classmethod
    def in_cny(cls) -> bool:
        return cls.currency == "cny" and cls.rate is not None


def show_money(value, lang: str = "vi") -> str:
    """An amount (VND in the data) as the screens show it: '1.188.000' in dong, '¥308,88' in yuan at the chosen
    rate (two decimals at most; Vietnamese writes 1.234,5, Chinese and English 1,234.5). Unknown -> '—'."""
    if value is None:
        return "—"
    if not Display.in_cny():
        return f"{round(float(value)):,}".replace(",", ".")
    return cny_text(float(value) / Display.rate.vnd_per_cny, lang)


def cny_text(cny: float, lang: str = "vi") -> str:
    """'¥308,88': two decimals at most; Vietnamese writes 1.234,5, Chinese and English 1,234.5."""
    text = f"{round(cny, 2):,.2f}".rstrip("0").rstrip(".")
    if lang == "vi":
        text = text.replace(",", " ").replace(".", ",").replace(" ", ".")
    return "¥" + text


def is_fresh(rate: Rate | None, now: datetime | None = None) -> bool:
    """Fetched within the last FRESH_SECONDS: no need to ask again."""
    return rate is not None and ((now or datetime.now()) - rate.fetched).total_seconds() < FRESH_SECONDS
