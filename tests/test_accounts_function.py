"""The Edge Function `accounts` (cloud/supabase/functions/accounts/index.ts) run under Node against a fake Supabase:
only the owner, validated input, no half-made accounts, and a password that is never printed or sent back."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


@pytest.fixture(scope="module")
def r():
    done = subprocess.run([NODE, str(ROOT / "tests" / "accounts_function_probe.mjs"),
                           str(ROOT / "cloud" / "supabase" / "functions" / "accounts" / "index.ts")],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


def _touched(case, name):
    return [c for c in case["calls"] if c[0] == name]


def test_the_browser_may_call_it(r):
    assert r["options"]["status"] == 204 and r["options"]["cors"] == "*"
    assert "authorization" in r["options"]["allowHeaders"] and "apikey" in r["options"]["allowHeaders"]
    assert r["created"]["cors"] == "*"  # answers carry the header too, or the page cannot read them


def test_nothing_happens_without_a_valid_owner(r):
    assert r["get"]["status"] == 405
    for key in ("noAuth", "badToken", "tokenCheckThrows"):
        assert r[key]["status"] == 401, key
        assert not _touched(r[key], "createUser") and not _touched(r[key], "roleOf"), key
    assert r["roleCheckThrows"]["json"]["ok"] is False and not _touched(r["roleCheckThrows"], "createUser")
    for key in ("staffCreates", "staffResets"):
        assert r[key]["json"]["ok"] is False and "Chỉ tài khoản của chủ" in r[key]["json"]["error"], key
        assert not _touched(r[key], "createUser") and not _touched(r[key], "setPassword"), key
    assert r["badJson"]["status"] == 400 and r["unknownAction"]["status"] == 400


def test_the_role_is_read_from_the_profile_of_the_checked_token_not_from_the_request(r):
    case = r["created"]
    assert [c[0] for c in case["calls"]][:2] == ["getUserId", "roleOf"]
    assert _touched(case, "roleOf")[0][1] == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def test_creating_an_account_makes_the_login_and_the_role(r):
    case = r["created"]
    assert case["json"]["ok"] is True and case["json"]["username"] == "nhanvien1"
    assert _touched(case, "createUser")[0][1] == "nhanvien1@dibekho.local"
    prof = _touched(case, "insertProfile")[0]
    assert prof[1:] == ["11111111-1111-4111-8111-111111111111", "Lan kho", "editor"]
    assert _touched(r["createdNoName"], "insertProfile")[0][2] == "nhanvien1"  # the name defaults to the login name
    assert r["createdOwnerRole"]["json"]["role"] == "desktop"


def test_bad_input_is_refused_before_anything_is_made(r):
    for key in [k for k in r if k.startswith("badUser_")] + ["badPwShort", "badPwLong", "badPwMissing", "badRole", "noRole"]:
        assert r[key]["json"]["ok"] is False, key
        assert not _touched(r[key], "createUser"), key
    assert "@dibekho.local" in r["badUser_email"]["json"]["error"]
    assert "ít nhất 8" in r["badPwShort"]["json"]["error"]


def test_supabases_refusals_are_explained_in_vietnamese(r):
    assert "đã có người dùng" in r["duplicate"]["json"]["error"]
    assert "Supabase không chấp nhận mật khẩu" in r["weak"]["json"]["error"] and "letters and digits" in r["weak"]["json"]["error"]
    assert "Không tạo được tài khoản" in r["authDown"]["json"]["error"]
    assert not _touched(r["duplicate"], "insertProfile") and not _touched(r["weak"], "insertProfile")


def test_no_half_made_account_when_the_role_cannot_be_saved(r):
    case = r["profileFails"]
    assert case["json"]["ok"] is False and "chưa tạo gì cả" in case["json"]["error"]
    assert _touched(case, "deleteUser")[0][1] == "11111111-1111-4111-8111-111111111111"
    both = r["profileAndDeleteFail"]["json"]["error"]
    assert "chưa xoá được" in both and "Authentication" in both  # says what to clean up by hand


def test_reset_password(r):
    assert r["reset"]["json"]["ok"] is True
    assert _touched(r["reset"], "setPassword")[0][1:] == ["eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee", r["SECRET"]]
    for key in ("resetBadId", "resetUnknown", "resetShort"):
        assert r[key]["json"]["ok"] is False and not _touched(r[key], "setPassword"), key
    assert "Supabase không chấp nhận mật khẩu" in r["resetFails"]["json"]["error"]


def test_a_password_is_never_printed_or_sent_back(r):
    assert r["passwordPrinted"] is False
    secret = r["SECRET"]
    for key, case in r.items():
        if isinstance(case, dict) and "text" in case:
            assert secret not in case["text"], key
