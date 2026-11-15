"""Checking for a newer version and fetching it (user's request 15/11/2026: update without uninstalling and downloading
again by hand). No Qt here: the window asks, this module talks to GitHub and to the disk.

- latest(): the newest release of the public repository (GitHub's API, no account, a generic User-Agent). A release is
  offered only when its tag is newer than this build AND the file for this computer is already attached: GitHub shows
  the release while the build jobs are still uploading, a missing file just means "ask again next time".
- download(): resumes with HTTP Range and retries (the line drops), and the file is used only when its size is the one
  GitHub announced (and its sha256, when GitHub gives one): a half-downloaded installer is never run.
- Windows: the installer runs with /SILENT (a progress window, no questions), closes the app's files, and starts the
  new version itself (packaging/windows.iss, the [Run] line with skipifnotsilent). Data and config.json stay.
- macOS (this Python build): the .dmg is opened; the user quits the app and drags DiBeKho onto Applications. A file
  fetched by the app carries no quarantine flag, so macOS should not ask "Vẫn mở" again (⚠ to be checked on a Mac).

DIBEKHO_UPDATE_URL replaces the releases address (tests, and a full trial run against a local server).
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from dibekho import __version__
from dibekho.core.net import ssl_context

RELEASES_URL = "https://api.github.com/repos/Friendzoner49/DiBeKho/releases/latest"
USER_AGENT = "DiBeKho-app"
WINDOWS_ASSET = "DiBeKho-windows-setup.exe"
MAC_ASSET = "DiBeKho-mac-arm64.dmg"
CHUNK = 256 * 1024
TRIES = 6
WINDOWS_ARGS = ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]


@dataclass
class Release:
    version: str
    asset: str
    url: str
    size: int
    sha256: str = ""
    notes: str = ""


def parse_version(text: str) -> tuple[int, ...] | None:
    """'v0.5.7' / '0.5.7' -> (0, 5, 7); anything else -> None."""
    m = re.fullmatch(r"\s*v?(\d+(?:\.\d+){0,3})\s*", str(text or ""))
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def is_newer(remote: str, local: str = __version__) -> bool:
    r, here = parse_version(remote), parse_version(local)
    if r is None or here is None:
        return False
    width = max(len(r), len(here))
    return r + (0,) * (width - len(r)) > here + (0,) * (width - len(here))


def asset_name(platform: str = sys.platform) -> str | None:
    if platform.startswith("win"):
        return WINDOWS_ASSET
    if platform == "darwin":
        return MAC_ASSET
    return None


def releases_url() -> str:
    return os.environ.get("DIBEKHO_UPDATE_URL") or RELEASES_URL


def _open(url: str, timeout: float, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    ctx = ssl_context() if url.lower().startswith("https:") else None
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)


def pick(release_json: dict, platform: str = sys.platform, local: str = __version__) -> Release | None:
    """The release to offer from GitHub's answer, or None (not newer, a draft or pre-release, no file for this
    computer yet)."""
    if not isinstance(release_json, dict) or release_json.get("draft") or release_json.get("prerelease"):
        return None
    tag = str(release_json.get("tag_name") or "")
    if not is_newer(tag, local):
        return None
    name = asset_name(platform)
    for a in release_json.get("assets") or []:
        if a.get("name") == name and a.get("state", "uploaded") == "uploaded" and int(a.get("size") or 0) > 0:
            digest = str(a.get("digest") or "")
            return Release(tag.lstrip("vV"), name, str(a.get("browser_download_url") or ""), int(a["size"]),
                           digest[7:].lower() if digest.lower().startswith("sha256:") else "",
                           str(release_json.get("body") or ""))
    return None


def latest(timeout: float = 8.0, platform: str = sys.platform) -> Release | None:
    """The newer release for this computer, or None. Raises OSError/ValueError when GitHub cannot be read."""
    with _open(releases_url(), timeout, {"Accept": "application/vnd.github+json"}) as resp:
        return pick(json.loads(resp.read().decode("utf-8")), platform)


def download_dir() -> Path:
    return Path(os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp") / "DiBeKho-update"


def download(rel: Release, dest_dir: Path | None = None, progress=None, cancelled=None,
             timeout: float = 30.0, wait: float = 2.0) -> Path:
    """Fetch the release's file into dest_dir (resuming a part left by an earlier try). progress(done, total) is
    called as it goes; cancelled() -> True stops it (raises InterruptedError). Returns the finished file; raises OSError
    when it cannot be fetched whole, ValueError when what arrived is not the announced file."""
    dest_dir = dest_dir or download_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / f"{rel.version}-{rel.asset}"
    part = final.with_name(final.name + ".part")
    if final.exists() and final.stat().st_size == rel.size and _digest_ok(final, rel):
        return final
    last: Exception | None = None
    for attempt in range(TRIES):
        done = part.stat().st_size if part.exists() else 0
        if done > rel.size:
            part.unlink()
            done = 0
        try:
            if done < rel.size:
                headers = {"Range": f"bytes={done}-"} if done else {}
                with _open(rel.url, timeout, headers) as resp:
                    if done and getattr(resp, "status", 200) != 206:
                        done = 0  # the server ignored Range: start over
                    with open(part, "ab" if done else "wb") as out:
                        while True:
                            if cancelled and cancelled():
                                raise InterruptedError("cancelled")
                            chunk = resp.read(CHUNK)
                            if not chunk:
                                break
                            out.write(chunk)
                            done += len(chunk)
                            if progress:
                                progress(done, rel.size)
            if part.stat().st_size != rel.size:
                raise OSError(f"incomplete: {part.stat().st_size} of {rel.size} bytes")
            if not _digest_ok(part, rel):
                part.unlink()
                raise ValueError("the downloaded file is not the announced one (sha256)")
            part.replace(final)
            return final
        except InterruptedError:
            raise
        except ValueError:
            raise
        except (OSError, urllib.error.URLError) as exc:
            last = exc
            if attempt + 1 < TRIES:
                time.sleep(wait * (attempt + 1))
    raise OSError(f"download failed: {last}")


def _digest_ok(path: Path, rel: Release) -> bool:
    if not rel.sha256:
        return True
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest() == rel.sha256


def clean_env() -> dict:
    """The environment for the installer: without the variables the packed app's own loader set, so the new app the
    installer starts sets up from scratch (PyInstaller documents PYINSTALLER_RESET_ENVIRONMENT for this)."""
    env = {k: v for k, v in os.environ.items() if not (k.startswith("_PYI") or k.startswith("_MEI"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def start_windows_installer(path: Path, tries: int = 3) -> None:
    """Start the installer on its own (it outlives the app, which must quit right after). Antivirus may still hold a
    file just downloaded: try again a few times."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    for attempt in range(tries):
        try:
            subprocess.Popen([str(path), *WINDOWS_ARGS], env=clean_env(), creationflags=flags, close_fds=True)
            return
        except OSError:
            if attempt + 1 == tries:
                raise
            time.sleep(1.5)


def open_mac_image(path: Path) -> None:
    subprocess.Popen(["open", str(path)], env=clean_env())


def running_from_disk_image() -> bool:
    """A Mac app started straight from the opened .dmg (/Volumes/...): it cannot replace itself there."""
    return sys.platform == "darwin" and str(Path(sys.executable).resolve()).startswith("/Volumes/")


def can_install() -> bool:
    """Only a packed build installs updates (running from the source code, `uv run dibekho`, never does)."""
    return bool(getattr(sys, "frozen", False)) and asset_name() is not None
