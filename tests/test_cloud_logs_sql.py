"""Every account's activity log on the cloud (cloud/supabase/017_app_logs.sql) on PGlite: any role sends, only maychinh
reads (the other owners neither list nor open), one row per account + machine + day, 30 days kept."""

import pytest

from tests.pgdb import WEB_FILES, PgError, Session, needs_pg

pytestmark = needs_pg
ADMIN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNER2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
STAFF = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
NOROLE = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


@pytest.fixture(scope="module")
def session():
    s = Session(WEB_FILES)
    yield s
    s.close()


@pytest.fixture
def pg(session):
    for table in ("public.app_logs", "public.profiles", "auth.users"):
        session.query(f"delete from {table}")
    for uid, mail, role in ((ADMIN, "maychinh@dibekho.local", "desktop"), (OWNER2, "quanly@dibekho.local", "desktop"),
                            (STAFF, "nhanvien1@dibekho.local", "editor")):
        session.query("insert into auth.users(id, email) values ($1, $2)", [uid, mail])
        session.query("insert into public.profiles(user_id, display_name, role) values ($1, $2, $3)",
                      [uid, mail.split("@")[0], role])
    session.query("insert into auth.users(id, email) values ($1, $2)", [NOROLE, "moi@dibekho.local"])
    return session


def _send(pg, sub, day="today", content="2026-11-15 08:00:00 [start] DiBeKho\n", device="May-abc"):
    day_sql = "current_date" if day == "today" else f"current_date - {int(day)}"
    pg.query(f"select public.log_send($1, '0.5.3', {day_sql}, $2)", [device, content], sub=sub)


def test_any_role_sends_and_only_maychinh_reads(pg):
    _send(pg, STAFF, content="2026-11-15 08:00:00 [error] boom\n")
    _send(pg, OWNER2)
    rows = pg.query("select public.log_list() as r", sub=ADMIN)[0]["r"]
    assert sorted(r["sender"] for r in rows) == ["nhanvien1", "quanly"]
    staff = next(r for r in rows if r["sender"] == "nhanvien1")
    assert staff["errors"] == 1 and staff["version"] == "0.5.3"
    text = pg.query("select public.log_get($1, $2, $3::date) as r", [STAFF, "May-abc", staff["day"]], sub=ADMIN)[0]["r"]
    assert "[error] boom" in text
    for other in (OWNER2, STAFF):  # another owner sees nothing, not even the list
        with pytest.raises(PgError):
            pg.query("select public.log_list() as r", sub=other)
        with pytest.raises(PgError):
            pg.query("select public.log_get($1, $2, current_date) as r", [STAFF, "May-abc"], sub=other)


def test_an_account_without_a_role_cannot_send(pg):
    with pytest.raises(PgError):
        _send(pg, NOROLE)


def test_a_day_is_replaced_and_old_days_go(pg):
    _send(pg, STAFF, content="a\n")
    _send(pg, STAFF, content="b\n")
    pg.query("insert into public.app_logs(user_id, device, day, content) values ($1, 'x', current_date - 40, 'old')",
             [STAFF])
    _send(pg, STAFF, day="1", content="y\n")
    rows = pg.query("select day::text as d, content from public.app_logs order by day")
    assert [r["content"] for r in rows] == ["y\n", "b\n"]


def test_nobody_reads_the_table_directly(pg):
    _send(pg, STAFF)
    with pytest.raises(PgError):
        pg.query("select * from public.app_logs", sub=ADMIN)
