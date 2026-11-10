"""Talk to Supabase over plain HTTPS: GoTrue sign-in and PostgREST RPC. stdlib only, no new dependency.

The project URL and the publishable (anon) key are public by design -- the data is protected by RLS and
account passwords (cloud/supabase/001_init.sql). The service role key must NEVER appear anywhere in the app.
Accounts use technical emails: the user types just a name ('maychinh'), the client appends @dibekho.local.
"""

import json
import urllib.error
import urllib.request

EMAIL_DOMAIN = "dibekho.local"
TIMEOUT = 40  # seconds; the whole mirror is a few MB at most


class CloudError(Exception):
    """Shown to the user as-is (Vietnamese, like other core errors)."""


def full_email(username: str) -> str:
    username = username.strip()
    return username if "@" in username else f"{username}@{EMAIL_DOMAIN}"


class CloudClient:
    def __init__(self, url: str, key: str, timeout: float = TIMEOUT):
        base = (url or "").strip().rstrip("/")
        for suffix in ("/rest/v1", "/auth/v1"):  # the user may paste the REST endpoint instead of the project URL
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        self.base = base
        self.key = (key or "").strip()
        self.timeout = timeout

    def sign_in(self, username: str, password: str) -> dict:
        """-> {"access_token", "refresh_token"}."""
        return self._tokens(self._post(
            f"{self.base}/auth/v1/token?grant_type=password",
            {"email": full_email(username), "password": password},
        ))

    def refresh(self, refresh_token: str) -> dict:
        """Refresh tokens rotate: the caller must store the new refresh_token."""
        return self._tokens(self._post(
            f"{self.base}/auth/v1/token?grant_type=refresh_token",
            {"refresh_token": refresh_token},
        ))

    def rpc(self, name: str, args: dict, access_token: str):
        return self._post(f"{self.base}/rest/v1/rpc/{name}", args, access_token)

    def get(self, path: str, access_token: str):
        """GET a PostgREST path, e.g. '/rest/v1/sync_state?select=*'."""
        return self._request(f"{self.base}{path}", None, access_token, "GET")

    def _tokens(self, data) -> dict:
        if not isinstance(data, dict) or not data.get("access_token") or not data.get("refresh_token"):
            raise CloudError("Cloud trả về dữ liệu đăng nhập không hiểu được.")
        return {"access_token": data["access_token"], "refresh_token": data["refresh_token"]}

    def _post(self, url: str, body: dict, access_token: str | None = None):
        return self._request(url, body, access_token, "POST")

    def _request(self, url: str, body: dict | None, access_token: str | None, method: str):
        if not self.base or not self.key:
            raise CloudError("Chưa điền địa chỉ Cloud hoặc mã kết nối.")
        req = urllib.request.Request(
            url,
            data=None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {access_token or self.key}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise CloudError(_http_message(exc)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CloudError("Không kết nối được Cloud. Kiểm tra mạng rồi thử lại.") from exc
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise CloudError("Cloud trả về dữ liệu không hiểu được.") from exc


def _http_message(exc: "urllib.error.HTTPError") -> str:
    """A short Vietnamese line; the server's own words are appended for troubleshooting (never a token)."""
    detail = ""
    try:
        data = json.loads(exc.read().decode("utf-8", errors="replace"))
        detail = str(data.get("error_description") or data.get("message") or data.get("msg") or data.get("error") or "")
    except (ValueError, OSError):
        pass
    if "invalid login credentials" in detail.lower() or exc.code in (400, 401) and "grant" in detail.lower():
        return "Sai tên đăng nhập hoặc mật khẩu."
    if exc.code in (401, 403):
        return f"Cloud từ chối truy cập ({detail or exc.code}). Kiểm tra tài khoản và vai trò."
    return f"Cloud báo lỗi {exc.code}: {detail or 'không rõ'}"
