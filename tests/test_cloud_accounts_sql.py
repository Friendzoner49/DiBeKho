"""The owner's account management from the web (cloud/supabase/011_accounts.sql) on PGlite: only the owner, no way to
lock oneself out, a revoked account keeps existing but reads nothing."""

import pytest

from tests.pgdb import WEB_FILES, PgError, Session, needs_pg

pytestmark = needs_pg
OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNER2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
STAFF = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
VIEWER = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
NEW = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


@pytest.fixture(scope="module")
def session():
    s = Session(WEB_FILES)
    yield s
    s.close()


@pytest.fixture
def pg(session):
    for table in ("public.products", "public.profiles", "auth.users"):
        session.query(f"delete from {table}")
    for uid, mail, role in ((OWNER, "maychinh@dibekho.local", "desktop"), (OWNER2, "quanly@dibekho.local", "desktop"),
                            (STAFF, "nhanvien1@dibekho.local", "editor"), (VIEWER, "xem@dibekho.local", "viewer")):
        session.query("insert into auth.users(id, email) values ($1, $2)", [uid, mail])
        session.query("insert into public.profiles(user_id, display_name, role) values ($1, $2, $3)",
                      [uid, mail.split("@")[0], role])
    session.query("insert into auth.users(id, email) values ($1, $2)", [NEW, "moi@dibekho.local"])  # no role yet
    return session


def _call(pg, fn, sub, *args):
    marks = ", ".join(f"${i}" for i in range(1, len(args) + 1))
    return pg.query(f"select public.{fn}({marks}) as r", list(args), sub=sub)[0]["r"]


def _role(pg, uid):
    rows = pg.query("select role from public.profiles where user_id = $1", [uid])
    return rows[0]["role"] if rows else ""


def test_the_owner_lists_everyone_with_roles_and_accounts_without_a_role(pg):
    rows = _call(pg, "web_accounts_list", OWNER)
    assert {r["email"]: r["role"] for r in rows} == {
        "maychinh@dibekho.local": "desktop", "quanly@dibekho.local": "desktop", "nhanvien1@dibekho.local": "editor",
        "xem@dibekho.local": "viewer", "moi@dibekho.local": ""}


def test_deleting_an_account_keeps_the_requests_it_sent(pg):
    pg.query("insert into public.web_inbox(kind, payload, created_by) values ('receipt', '{}'::jsonb, $1)", [STAFF])
    pg.query("delete from auth.users where id = $1", [STAFF])  # what the Edge Function's deleteUser does
    rows = pg.query("select created_by from public.web_inbox")
    assert len(rows) == 1 and rows[0]["created_by"] is None
    assert pg.query("select count(*) as n from public.profiles where user_id = $1", [STAFF])[0]["n"] == 0


def test_only_the_owner_manages_accounts(pg):
    for who in (STAFF, VIEWER, NEW, None, OWNER2):  # OWNER2 is an owner too, but not the main machine's login
        with pytest.raises(PgError, match="Chỉ tài khoản của chủ"):
            _call(pg, "web_accounts_list", who)
        with pytest.raises(PgError, match="Chỉ tài khoản của chủ"):
            _call(pg, "web_account_set_role", who, STAFF, "desktop", None)
        with pytest.raises(PgError, match="Chỉ tài khoản của chủ"):
            _call(pg, "web_account_revoke", who, VIEWER)
    assert _role(pg, STAFF) == "editor" and _role(pg, VIEWER) == "viewer"  # nothing changed


def test_no_products_or_shared_data_needed(pg):
    assert pg.query("select count(*) as n from public.products")[0]["n"] == 0
    assert _call(pg, "web_account_set_role", OWNER, NEW, "editor", "Lan - kho")["role"] == "editor"


def test_give_change_and_bring_back_a_role(pg):
    _call(pg, "web_account_set_role", OWNER, NEW, "editor", "Lan - kho")
    assert _role(pg, NEW) == "editor"
    assert pg.query("select display_name from public.profiles where user_id = $1", [NEW])[0]["display_name"] == "Lan - kho"
    _call(pg, "web_account_set_role", OWNER, NEW, "viewer", None)  # the name stays when none is given
    assert _role(pg, NEW) == "viewer"
    assert pg.query("select display_name from public.profiles where user_id = $1", [NEW])[0]["display_name"] == "Lan - kho"
    _call(pg, "web_account_revoke", OWNER, NEW)
    assert _role(pg, NEW) == ""
    _call(pg, "web_account_set_role", OWNER, NEW, "editor", "  Lan   B ")  # re-granting after a revoke works
    assert _role(pg, NEW) == "editor"
    assert pg.query("select display_name from public.profiles where user_id = $1", [NEW])[0]["display_name"] == "Lan B"


def test_the_name_defaults_to_the_short_login_name(pg):
    _call(pg, "web_account_set_role", OWNER, NEW, "viewer", None)
    assert pg.query("select display_name from public.profiles where user_id = $1", [NEW])[0]["display_name"] == "moi"


def test_bad_role_and_unknown_account_are_refused(pg):
    for role in ("admin", "", None):
        with pytest.raises(PgError, match="Vai trò không hợp lệ"):
            _call(pg, "web_account_set_role", OWNER, NEW, role, None)
    ghost = "99999999-9999-4999-8999-999999999999"
    with pytest.raises(PgError, match="Không tìm thấy"):
        _call(pg, "web_account_set_role", OWNER, ghost, "viewer", None)
    with pytest.raises(PgError, match="Không tìm thấy"):
        _call(pg, "web_account_revoke", OWNER, ghost)


def test_an_owner_cannot_lock_themselves_out(pg):
    with pytest.raises(PgError, match="Không tự hạ quyền"):
        _call(pg, "web_account_set_role", OWNER, OWNER, "editor", None)
    with pytest.raises(PgError, match="Không tự thu hồi"):
        _call(pg, "web_account_revoke", OWNER, OWNER)
    assert _role(pg, OWNER) == "desktop"
    # keeping the owner role (just a new display name) is fine
    _call(pg, "web_account_set_role", OWNER, OWNER, "desktop", "Chu cua hang")
    assert pg.query("select display_name from public.profiles where user_id = $1", [OWNER])[0]["display_name"] == "Chu cua hang"


def test_one_owner_may_demote_another_but_one_always_stays(pg):
    _call(pg, "web_account_set_role", OWNER, OWNER2, "editor", None)
    assert _role(pg, OWNER2) == "editor"
    assert pg.query("select count(*) as n from public.profiles where role = 'desktop'")[0]["n"] == 1


def test_a_revoked_account_reads_and_writes_nothing_but_is_not_deleted(pg):
    pg.query("insert into public.products(id, code, name_vi, created_at) values (gen_random_uuid(), 'SP001', 'Keo A', now())")
    assert pg.query("select count(*) as n from public.products", sub=STAFF)[0]["n"] == 1
    _call(pg, "web_account_revoke", OWNER, STAFF)
    assert pg.query("select count(*) as n from public.products", sub=STAFF)[0]["n"] == 0
    assert pg.query("select count(*) as n from auth.users where id = $1", [STAFF])[0]["n"] == 1
    with pytest.raises(PgError):
        _call(pg, "web_account_revoke", STAFF, VIEWER)


def test_the_page_size_is_set_by_the_account_manager_and_read_by_everyone_with_a_role(pg):
    _call(pg, "web_setting_set", OWNER, "ui_scale", "140")
    _call(pg, "web_setting_set", OWNER, "ui_scale", "120")  # changing it again replaces the value
    for who in (OWNER, OWNER2, STAFF, VIEWER):
        rows = pg.query("select value from public.web_settings where key = 'ui_scale'", sub=who)
        assert [r["value"] for r in rows] == ["120"], who
    assert pg.query("select value from public.web_settings", sub=NEW) == []  # no role: reads nothing
    for who in (OWNER2, STAFF, VIEWER, NEW, None):  # another owner, staff, anyone: refused
        with pytest.raises(PgError, match="Chỉ tài khoản của chủ"):
            _call(pg, "web_setting_set", who, "ui_scale", "100")
    for key, value in (("ui_scale", "500"), ("other", "120"), ("ui_scale", "")):
        with pytest.raises(PgError, match="không hợp lệ"):
            _call(pg, "web_setting_set", OWNER, key, value)
    with pytest.raises(PgError):  # no direct writes either
        pg.query("insert into public.web_settings values ('ui_scale', '140')", sub=STAFF)
