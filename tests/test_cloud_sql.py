"""cloud/supabase/*.sql: the fresh-install schema and the migrations must not drift apart, and every table the
desktop pushes must be emptied, refilled and readable. (Nothing here runs Postgres; it reads the files.)"""

import re
from pathlib import Path

from dibekho.core.cloud import mirror

SQL = Path(__file__).resolve().parent.parent / "cloud" / "supabase"


def _text(name):
    return (SQL / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def _function(text):
    start = text.index("create or replace function public.replace_mirror")
    return text[start:text.index("$$;", text.index("returns jsonb language plpgsql", start)) + 3]


def test_fresh_install_and_latest_migration_use_the_same_replace_mirror():
    latest = max(p.name for p in SQL.glob("0*.sql") if "create or replace function public.replace_mirror" in
                 p.read_text(encoding="utf-8"))
    assert _function(_text("001_init.sql")) == _function(_text(latest)), latest


def test_every_mirror_table_is_replaced_and_readable():
    init = _text("001_init.sql")
    tables = re.findall(r"create table public\.(mirror_\w+)", init)
    assert {"mirror_movements", "mirror_products", "mirror_documents"} <= set(tables)
    function = _function(init)
    for table in tables:
        if table == "mirror_snapshot":
            continue  # history of pushes, not a mirror of the data
        assert re.search(rf"truncate table[^;]*\b{table}\b", function, re.S), f"{table} is not emptied"
        assert f"insert into {table}" in function, f"{table} is not refilled"
        assert f"'{table}'" in init, f"{table} has no read policy"  # the policy loop lists table names
        assert f"public.{table} " in init and "enable row level security" in init


def test_the_payload_keys_are_the_ones_the_function_reads():
    function = _function(_text("001_init.sql"))
    used = set(re.findall(r"payload->'(\w+)'", function))
    from dibekho import db
    conn = db.connect(":memory:")
    pushed = set(mirror.build_payload(conn, "d", "m"))
    conn.close()
    assert used <= pushed, f"the function reads {used - pushed} but the app does not send it"
    assert {"products", "customers", "documents", "document_lines", "movements", "stock"} == used


def test_staff_cannot_send_owner_commands_once_that_migration_exists():
    """Placeholder guard for the commands migration: when 006 exists, an editor may insert only the three request
    kinds and only the desktop role may insert anything else."""
    path = SQL / "006_owner_commands.sql"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    assert "'editor'" in text and "'receipt'" in text and "'delivery_file'" in text and "'stock_count'" in text
