"""The web page must download every table the desktop mirrors (a missing one made product history and statistics
fail silently on the real page while the fixture-based tests stayed green)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_web_loads_every_mirror_table():
    app = (ROOT / "webapp" / "app.js").read_text(encoding="utf-8")
    loaded = set(re.findall(r'fetchAll\("(mirror_\w+)"', app))
    sql = (ROOT / "cloud" / "supabase" / "001_init.sql").read_text(encoding="utf-8")
    tables = set(re.findall(r"create table public\.(mirror_\w+)", sql))
    assert tables - {"mirror_snapshot"} <= loaded, tables - loaded
