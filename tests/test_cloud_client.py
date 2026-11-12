"""Cloud client (stdlib HTTP), signing in and the cloud backup bookkeeping, with the network faked."""

import io
import json
import urllib.error
import urllib.request

import pytest

from dibekho import db
from dibekho.core.cloud import sync
from dibekho.core.cloud.client import CloudClient, CloudError, full_email


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(monkeypatch, handler):
    calls = []

    def opener(req, timeout=None):
        calls.append(req)
        return FakeResponse(json.dumps(handler(req)).encode())

    monkeypatch.setattr(urllib.request, "urlopen", opener)
    return calls


def test_full_email_appends_technical_domain():
    assert full_email("maychinh") == "maychinh@dibekho.local"
    assert full_email("ai-do@gmail.com") == "ai-do@gmail.com"


def test_base_url_normalized_from_pasted_rest_endpoint():
    c = CloudClient("https://xxx.supabase.co/rest/v1/", "k")
    assert c.base == "https://xxx.supabase.co"


def test_sign_in_posts_email_and_returns_tokens(monkeypatch):
    calls = fake_urlopen(monkeypatch, lambda req: {"access_token": "A", "refresh_token": "R"})
    tokens = CloudClient("https://xxx.supabase.co", "key1").sign_in("maychinh", "mk")
    assert tokens == {"access_token": "A", "refresh_token": "R"}
    (req,) = calls
    assert req.full_url.endswith("/auth/v1/token?grant_type=password")
    body = json.loads(req.data.decode())
    assert body == {"email": "maychinh@dibekho.local", "password": "mk"}
    assert req.get_header("Apikey") == "key1"


def test_wrong_password_is_a_friendly_error(monkeypatch):
    def opener(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {},
                                     io.BytesIO(b'{"error_description":"Invalid login credentials"}'))

    monkeypatch.setattr(urllib.request, "urlopen", opener)
    with pytest.raises(CloudError, match="Sai tên đăng nhập"):
        CloudClient("https://xxx.supabase.co", "k").sign_in("maychinh", "sai")


def test_network_down_is_a_friendly_error(monkeypatch):
    def opener(req, timeout=None):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(urllib.request, "urlopen", opener)
    with pytest.raises(CloudError, match="Không kết nối được"):
        CloudClient("https://xxx.supabase.co", "k").rpc("replace_mirror", {}, "tok")


class FakeClient:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def rpc(self, name, args, token):
        self.calls.append((name, args, token))
        return self.results.pop(0)


class Cfg:
    device_id, device_name = "dev-1", "May"


def test_has_unpushed_follows_touch_and_the_cloud_backup(conn):
    assert not sync.has_unpushed(conn)  # nothing changed yet
    with db.transaction(conn):
        db.touch(conn)
    assert sync.has_unpushed(conn)
    class Uploads:
        def get(self, *a):
            return []  # nothing recorded on the web to reconcile

        def storage_upload(self, name, data, token):
            pass

        def storage_list(self, token, prefix=""):
            return []
    assert sync.finish_push(conn, Cfg, Uploads(), "tok") is None
    assert not sync.has_unpushed(conn) and sync.last_backup(conn)  # the backup covered the change


def test_session_none_until_cloud_configured(tmp_path, monkeypatch):
    from dibekho.core.workspace import Config

    monkeypatch.setattr(Config, "path", staticmethod(lambda: tmp_path / "config.json"))
    cfg = Config(workspace=str(tmp_path))
    assert sync.session(cfg) is None  # not set up: silently skip cloud work

    class FakeCloudClient:
        def __init__(self, url, key, timeout=None):
            pass

        def refresh(self, token):
            assert token == "old"
            return {"access_token": "A", "refresh_token": "new"}

    monkeypatch.setattr(sync, "CloudClient", FakeCloudClient)
    cfg.cloud_url, cfg.cloud_key, cfg.cloud_user, cfg.cloud_refresh_token = "u", "k", "may", "old"
    client, token = sync.session(cfg)
    assert token == "A"
    assert cfg.cloud_refresh_token == "new"  # rotation saved
    assert Config.load().cloud_refresh_token == "new"


def test_config_keeps_unknown_keys_on_save(tmp_path, monkeypatch):
    """An older app version must not erase settings a newer one saved (the cloud fields were lost
    this way once: the installed 0.4.5 rewrote config.json without them)."""
    from dibekho.core.workspace import Config

    monkeypatch.setattr(Config, "path", staticmethod(lambda: tmp_path / "config.json"))
    (tmp_path / "config.json").write_text(
        json.dumps({"workspace": "x", "language": "vi", "future_setting": "keep me"}), encoding="utf-8")
    cfg = Config.load()
    cfg.language = "en"
    cfg.save()
    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert saved["future_setting"] == "keep me"
    assert saved["language"] == "en"
    assert not any(k.startswith("_") for k in saved)


def test_local_time_converts_utc_to_this_machine():
    from datetime import datetime, timezone

    from dibekho.core.cloud.client import local_time

    expected = datetime(2026, 11, 11, 9, 36, tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    assert local_time("2026-11-11T09:36:52.92042+00:00") == expected
    assert local_time("2026-11-11T09:36:52Z") == expected
    assert local_time("") == "" and local_time(None) == ""
    assert local_time("not a date") == "not a date"  # never raises into the UI
