"""The shop's Cloud address, put into the build (user's request 15/11/2026: the app asks only for the account and
the password).

The project URL and the publishable key are public by design (the data is protected by passwords and RLS), but
they are not written in this public repository: scripts/make_cloud_builtin.py writes builtin.json next to this file
at build time, from the repository's Actions secrets (or, on the developer's machine, from webapp/config.js). A
build without it still works: the sign-in window then shows the two fields as before."""

import json
from importlib import resources

FILE = "builtin.json"


def builtin() -> tuple[str, str]:
    """(project URL, publishable key), or ("", "") in a build that carries none."""
    try:
        data = json.loads((resources.files("dibekho.core.cloud") / FILE).read_text(encoding="utf-8"))
        url, key = str(data.get("url") or "").strip(), str(data.get("key") or "").strip()
    except (OSError, ValueError, AttributeError, ModuleNotFoundError):
        return "", ""
    return (url, key) if url and key else ("", "")
