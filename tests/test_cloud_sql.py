"""cloud/supabase/*.sql: the fresh-install schema and the migrations must not drift apart, and every table the
web may send must be one the app understands. (Nothing here runs Postgres; it reads the files.)"""

import re
from pathlib import Path

SQL = Path(__file__).resolve().parent.parent / "cloud" / "supabase"


def _text(name):
    return (SQL / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def test_request_kinds_in_sql_match_the_ones_the_app_understands():
    """web_inbox.kind is restricted in SQL; a kind the app does not know would sit pending forever, and a kind the SQL
    refuses could never be sent. Also: editors may send only the staff requests (the old owner commands of 006 are no
    longer sent; their rows would be ignored)."""
    from dibekho.core.cloud import inbox
    expected = set(inbox.KINDS)
    for name in ("001_init.sql", "006_owner_commands.sql"):
        text = _text(name)
        block = text[text.index("kind in ("):]
        listed = set(re.findall(r"'(\w+)'", block[:block.index(")") + 400].split("create policy")[0]))
        assert expected <= listed, (name, expected - listed)
        policy = text[text.index("create policy inbox_insert"):]
        policy = policy[:policy.index(";")]
        assert "my_role() = 'desktop'" in policy and "my_role() = 'editor' and kind in" in policy, name
        editors = policy[policy.index("my_role() = 'editor' and kind in"):]
        assert not re.search(r"'cmd_\w+'", editors), f"{name}: editors must not be allowed to send owner commands"
