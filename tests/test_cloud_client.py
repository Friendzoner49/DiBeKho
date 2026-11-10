"""Cloud client (stdlib HTTP) and push_mirror, with the network faked."""

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


def test_push_mirror_success_remembers_push_id(conn):
    client = FakeClient([{"conflict": False, "push_id": 12}])
    result = sync.push_mirror(conn, Cfg, client, "tok")
    assert result["push_id"] == 12
    assert sync.last_push(conn)[0] == 12
    name, args, token = client.calls[0]
    assert name == "replace_mirror" and token == "tok"
    assert args["payload"]["based_on_push"] is None and args["force"] is False


def test_push_mirror_conflict_changes_nothing_until_forced(conn):
    client = FakeClient([
        {"conflict": True, "last_push": {"device_name": "May kia", "last_push_at": "2026-11-10T09:00:00Z"}},
        {"conflict": False, "push_id": 13},
    ])
    result = sync.push_mirror(conn, Cfg, client, "tok")
    assert result["conflict"] and sync.last_push(conn)[0] is None  # nothing recorded
    result = sync.push_mirror(conn, Cfg, client, "tok", force=True)
    assert result["push_id"] == 13 and sync.last_push(conn)[0] == 13
    assert client.calls[1][1]["force"] is True


def test_has_unpushed_follows_touch_and_push(conn):
    assert not sync.has_unpushed(conn)  # nothing changed yet
    with db.transaction(conn):
        db.touch(conn)
    assert sync.has_unpushed(conn)
    client = FakeClient([{"conflict": False, "push_id": 1}])
    sync.push_mirror(conn, Cfg, client, "tok")
    assert not sync.has_unpushed(conn)  # the push covered the change


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


def test_get_and_fetch_state(monkeypatch):
    calls = fake_urlopen(monkeypatch, lambda req: [{"device_id": "d2", "device_name": "May kia",
                                                    "last_push_id": 9, "last_push_at": "2026-11-10T10:00:00Z"}])
    client = CloudClient("https://xxx.supabase.co", "k")
    state = sync.fetch_state(client, "tok")
    assert state["device_id"] == "d2" and state["last_push_id"] == 9
    (req,) = calls
    assert req.get_method() == "GET" and req.full_url.endswith("/rest/v1/sync_state?select=*")


def test_push_mirror_sends_last_seen_push_as_based_on(conn):
    with db.transaction(conn):
        db.set_meta(conn, "cloud_last_push_id", "7")
    client = FakeClient([{"conflict": False, "push_id": 8}])
    sync.push_mirror(conn, Cfg, client, "tok")
    assert client.calls[0][1]["payload"]["based_on_push"] == 7
