"""The account the app works with (user's request 15/11/2026): the app asks for it when it opens, and the machine
then works on the shared data at once.

- role 'desktop' (the owner): writes the shared data;
- role 'editor' (staff): works on this machine, what it does waits for the owner's approval (core/cloud/approval.py);
- role 'viewer' or none: the web page only, the app does not open.

The password is used once and never stored; later starts reuse the rotating refresh token in config.json, and the
role is remembered there so the app also opens without a network (it syncs when the line is back).
No Qt here."""

from dataclasses import dataclass

from dibekho.core import backup
from dibekho.core.cloud import builtin as builtin_mod
from dibekho.core.cloud import replica, twoway
from dibekho.core.cloud import sync as cloud_sync
from dibekho.core.cloud.approval import OWNER, STAFF
from dibekho.core.cloud.client import CloudClient, CloudError, SessionExpired

SIGN_IN_TIMEOUT = 20  # s per request while the sign-in window waits


class NotForApp(CloudError):
    """A valid account that may not use the app (view-only, or no role yet)."""


@dataclass
class Session:
    client: CloudClient
    token: str
    role: str


def apply_builtin(cfg) -> bool:
    """The address the build carries wins over what an older version saved. True when an address is known."""
    url, key = builtin_mod.builtin()
    if url and key:
        cfg.cloud_url, cfg.cloud_key = url, key
    return bool(cfg.cloud_url and cfg.cloud_key)


def has_builtin() -> bool:
    return all(builtin_mod.builtin())


def role_of(client, token: str) -> str:
    role = client.rpc("my_role", {}, token)
    return role if isinstance(role, str) else ""


def _allowed(role: str) -> str:
    if role not in (OWNER, STAFF):
        raise NotForApp("Tài khoản này chỉ dùng để xem trên trang web, chưa được dùng app. "
                        "Nhờ chủ cấp vai trò Máy chính hoặc Nhân viên (trang web → Cài đặt → Tài khoản).")
    return role


def sign_in(cfg, username: str, password: str, url: str = "", key: str = "") -> Session:
    """Check the account with the cloud and remember the session. Raises CloudError (shown as it is)."""
    username = username.strip()
    url, key = (url or cfg.cloud_url).strip(), (key or cfg.cloud_key).strip()
    if not url or not key:
        raise CloudError("Chưa có địa chỉ Cloud và mã kết nối.")
    if not username or not password:
        raise CloudError("Hãy gõ tên đăng nhập và mật khẩu.")
    client = CloudClient(url, key, timeout=SIGN_IN_TIMEOUT)
    tokens = client.sign_in(username, password)
    role = _allowed(role_of(client, tokens["access_token"]))
    cfg.cloud_url, cfg.cloud_key, cfg.cloud_user = url, key, username
    cfg.cloud_refresh_token, cfg.cloud_role = tokens["refresh_token"], role
    cfg.save()
    return Session(client, tokens["access_token"], role)


def has_saved_session(cfg) -> bool:
    return bool(cfg.cloud_url and cfg.cloud_key and cfg.cloud_user and cfg.cloud_refresh_token
                and getattr(cfg, "cloud_role", "") in (OWNER, STAFF))


def resume(cfg, timeout: float = 10) -> Session:
    """The saved session, checked with the cloud. Raises SessionExpired (the password is needed again), NotForApp
    (the owner took the role away) or CloudError (no network)."""
    pair = cloud_sync.session(cfg, timeout=timeout)
    if pair is None:
        raise SessionExpired("Chưa đăng nhập trên máy này.")
    client, token = pair
    role = _allowed(role_of(client, token))
    remember_role(cfg, role)
    return Session(client, token, role)


def remember_role(cfg, role: str) -> bool:
    """True when the role changed (the owner changed it on the web)."""
    if role == getattr(cfg, "cloud_role", ""):
        return False
    cfg.cloud_role = role
    cfg.save()
    return True


def sign_out(cfg) -> None:
    """Forget the session on this machine; the next start asks for the account again."""
    cfg.cloud_refresh_token, cfg.cloud_role = "", ""
    cfg.save()


def has_local_data(conn) -> bool:
    return any(conn.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone() for t in ("products", "documents", "customers"))


UPLOADED, ADOPTED, ALREADY, EMPTY_CLOUD, REFUSED = "uploaded", "adopted", "already", "empty_cloud", "refused"


def link(conn, ws, session: Session, confirm_adopt) -> str:
    """Join the shared data, once per machine (afterwards the background sync keeps it current).

    - the cloud is empty: the owner's machine becomes the shared data; a staff machine waits for the owner;
    - the cloud holds data: this machine takes it. When the machine has data of its own, confirm_adopt() is asked
      first and the file is backed up (sao-luu/, 'truoc-dung-du-lieu-cloud'): the web's data is the reference.
    Returns UPLOADED / ADOPTED / ALREADY / EMPTY_CLOUD / REFUSED. Raises CloudError."""
    if replica.enabled(conn):
        return ALREADY
    pulled = twoway.fetch(session.client, session.token, 0)
    if twoway.cloud_empty(pulled):
        if session.role != OWNER:
            return EMPTY_CLOUD
        twoway.start_from_this_machine(conn)
        return UPLOADED
    if has_local_data(conn):
        if not confirm_adopt():
            return REFUSED
        backup.named_backup(conn, ws, "truoc-dung-du-lieu-cloud")
    twoway.start_from_cloud(conn)
    return ADOPTED
