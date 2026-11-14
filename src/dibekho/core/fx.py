"""CNY ⇄ VND, for the small converter at the bottom left (user's request, 14/11/2026: the market rate).

The rate comes from the free ExchangeRate-API endpoint (no key, updated once a day; its terms ask to name it next
to the rate). It is kept in fx.json next to config.json, so the converter still works offline with the last rate,
which then shows its date. Nothing about the user or the data is sent: one plain GET.
"""

import json
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dibekho.core import workspace

URL = "https://open.er-api.com/v6/latest/CNY"
SOURCE = "ExchangeRate-API"
SOURCE_URL = "https://www.exchangerate-api.com"
TIMEOUT = 8  # seconds; the window shows the cached rate meanwhile
FILE = "fx.json"


@dataclass
class Rate:
    vnd_per_cny: float
    updated: datetime  # when the provider computed it (local time)
    fetched: datetime  # when this computer got it

    def to_vnd(self, cny: float) -> float:
        return cny * self.vnd_per_cny

    def to_cny(self, vnd: float) -> float:
        return vnd / self.vnd_per_cny


def _path() -> Path:
    return workspace.config_dir() / FILE  # through the module: tests point it at a temporary folder


def parse(data: dict, fetched: datetime | None = None) -> Rate:
    """The provider's JSON -> Rate. Raises ValueError when it is not a usable answer."""
    if data.get("result") != "success" or data.get("base_code") != "CNY":
        raise ValueError("Trang tỷ giá trả lời không đúng.")
    vnd = data.get("rates", {}).get("VND")
    if not isinstance(vnd, (int, float)) or not vnd > 0:
        raise ValueError("Trang tỷ giá không có tỷ giá VND.")
    updated = datetime.fromtimestamp(int(data.get("time_last_update_unix") or 0), timezone.utc).astimezone()
    return Rate(float(vnd), updated.replace(tzinfo=None), fetched or datetime.now())


def fetch(timeout: float = TIMEOUT) -> Rate:
    """Ask the provider (network); on success the rate is cached. Raises OSError/ValueError."""
    req = urllib.request.Request(URL, headers={"User-Agent": "DiBeKho", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    rate = parse(data)
    save(rate)
    return rate


def save(rate: Rate) -> None:
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"vnd_per_cny": rate.vnd_per_cny, "updated": rate.updated.isoformat(),
                                    "fetched": rate.fetched.isoformat()}), encoding="utf-8")
    except OSError:
        pass  # only a cache


def cached() -> Rate | None:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return Rate(float(data["vnd_per_cny"]), datetime.fromisoformat(data["updated"]),
                    datetime.fromisoformat(data["fetched"]))
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
    v = round(float(value) / Display.rate.vnd_per_cny, 2)
    text = f"{v:,.2f}".rstrip("0").rstrip(".")
    if lang == "vi":
        text = text.replace(",", " ").replace(".", ",").replace(" ", ".")
    return "¥" + text


def is_fresh(rate: Rate | None, now: datetime | None = None) -> bool:
    """Fetched within the last 6 hours: no need to ask again when the window opens."""
    return rate is not None and ((now or datetime.now()) - rate.fetched).total_seconds() < 6 * 3600
