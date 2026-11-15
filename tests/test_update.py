"""Self-update (user, 15/11/2026): which release is offered, and a download that resumes and is only used when whole."""

import functools
import http.server
import threading
from pathlib import Path

import pytest

from dibekho.core import update

ROOT = Path(__file__).resolve().parent.parent


def test_versions_compare_as_numbers():
    assert update.is_newer("v0.5.10", "0.5.9")
    assert update.is_newer("0.6", "0.5.9")
    assert not update.is_newer("v0.5.6", "0.5.6")
    assert not update.is_newer("0.5.5", "0.5.6")
    assert not update.is_newer("nightly", "0.5.6")


def _release(tag="v0.5.7", assets=None, **kw):
    return {"tag_name": tag, "draft": False, "prerelease": False, "body": "ghi chú", **kw, "assets": assets if assets is not None else [
        {"name": update.WINDOWS_ASSET, "size": 10, "state": "uploaded", "browser_download_url": "http://x/win.exe",
         "digest": "sha256:ABC"},
        {"name": update.MAC_ASSET, "size": 20, "state": "uploaded", "browser_download_url": "http://x/mac.dmg"}]}


def test_the_file_of_this_computer_is_picked():
    win = update.pick(_release(), "win32", "0.5.6")
    assert (win.version, win.asset, win.size, win.sha256) == ("0.5.7", update.WINDOWS_ASSET, 10, "abc")
    assert update.pick(_release(), "darwin", "0.5.6").url == "http://x/mac.dmg"
    assert update.pick(_release(), "linux", "0.5.6") is None


def test_nothing_is_offered_until_the_file_is_there_or_when_not_newer():
    only_mac = _release(assets=[{"name": update.MAC_ASSET, "size": 20, "state": "uploaded", "browser_download_url": "u"}])
    assert update.pick(only_mac, "win32", "0.5.6") is None  # the Windows build is still uploading
    uploading = _release(assets=[{"name": update.WINDOWS_ASSET, "size": 10, "state": "starter", "browser_download_url": "u"}])
    assert update.pick(uploading, "win32", "0.5.6") is None
    assert update.pick(_release(), "win32", "0.5.7") is None
    assert update.pick(_release(prerelease=True), "win32", "0.5.6") is None


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture
def served(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "setup.exe").write_bytes(bytes(range(256)) * 2000)  # 512000 bytes
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", site
    server.shutdown()


def test_download_is_checked_and_resumes(served, tmp_path):
    base, site = served
    data = (site / "setup.exe").read_bytes()
    import hashlib

    rel = update.Release("0.5.7", update.WINDOWS_ASSET, f"{base}/setup.exe", len(data), hashlib.sha256(data).hexdigest())
    out = tmp_path / "dl"
    out.mkdir()
    # a part left by an earlier, broken try: only the rest is fetched (or all again when the server ignores Range)
    (out / f"0.5.7-{update.WINDOWS_ASSET}.part").write_bytes(data[:100000])
    seen = []
    path = update.download(rel, out, progress=lambda d, t: seen.append(d), wait=0)
    assert path.read_bytes() == data and seen[-1] == len(data)
    assert update.download(rel, out, wait=0) == path  # already there: not fetched again


def test_a_wrong_or_short_file_is_never_used(served, tmp_path):
    base, site = served
    size = (site / "setup.exe").stat().st_size
    bad = update.Release("0.5.7", update.WINDOWS_ASSET, f"{base}/setup.exe", size, "0" * 64)
    with pytest.raises(ValueError):
        update.download(bad, tmp_path / "a", wait=0)
    assert not (tmp_path / "a" / f"0.5.7-{update.WINDOWS_ASSET}").exists()
    short = update.Release("0.5.7", update.WINDOWS_ASSET, f"{base}/setup.exe", size + 5)
    with pytest.raises(OSError):
        update.download(short, tmp_path / "b", wait=0)
    assert not (tmp_path / "b" / f"0.5.7-{update.WINDOWS_ASSET}").exists()


def test_cancel_stops_the_download(served, tmp_path):
    base, site = served
    rel = update.Release("0.5.7", update.WINDOWS_ASSET, f"{base}/setup.exe", (site / "setup.exe").stat().st_size)
    with pytest.raises(InterruptedError):
        update.download(rel, tmp_path / "c", cancelled=lambda: True, wait=0)


def test_the_installer_opens_the_new_version_after_a_silent_install():
    iss = (ROOT / "packaging" / "windows.iss").read_text(encoding="utf-8")
    assert 'Filename: "{app}\\DiBeKho.exe"; Flags: nowait skipifnotsilent' in iss
    assert "/SILENT" in update.WINDOWS_ARGS and "/CLOSEAPPLICATIONS" in update.WINDOWS_ARGS


def test_the_installer_starts_without_the_packed_apps_loader_variables(monkeypatch):
    monkeypatch.setenv("_MEIPASS2", "x")
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "x")
    env = update.clean_env()
    assert "_MEIPASS2" not in env and "_PYI_APPLICATION_HOME_DIR" not in env
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_running_from_source_never_installs():
    assert not update.can_install()  # pytest runs from the source code
