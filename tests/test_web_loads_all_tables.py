"""The web page must download every shared table its screens use (a missing one once made product history and
statistics fail silently on the real page while the fixture-based tests stayed green), each with a stable order (PostgREST
pages at 1000 rows) and without soft-deleted rows."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_web_loads_every_table_it_uses():
    app = (ROOT / "webapp" / "app.js").read_text(encoding="utf-8")
    listed = set(re.findall(r'"(\w+)"', re.search(r"WEB_TABLES = \[([^\]]*)\]", app).group(1)))
    fetched = set(re.findall(r'fetchAll\("(\w+)"', app))
    needed = {"products", "customers", "suppliers", "documents", "document_lines", "stock_movements", "meta"}
    assert needed <= fetched and listed == fetched
    sql = (ROOT / "cloud" / "supabase" / "007_core.sql").read_text(encoding="utf-8")
    assert needed <= set(re.findall(r"create table public\.(\w+)", sql))
    start = app.index("async function fetchAll")
    fetch = app[start:app.index("\n}\n", start)]
    assert '.eq("deleted", false)' in fetch and ".order(key)" in fetch
