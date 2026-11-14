"""Write src/dibekho/core/cloud/builtin.json: the shop's Cloud address carried by the build, so the app's sign-in
window asks only for the account and the password (core/cloud/builtin.py).

Taken from the environment variables DIBEKHO_CLOUD_URL and DIBEKHO_CLOUD_KEY (GitHub Actions: the repository's
secrets of the same names), else from webapp/config.js (the developer's machine, gitignored). The file is
gitignored too: the address never enters this public repository. Neither found: no file, the build still works and
the sign-in window shows the address fields. Prints only whether an address was found, never the values.

    uv run python scripts/make_cloud_builtin.py
"""

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "dibekho" / "core" / "cloud" / "builtin.json"


def from_config_js() -> tuple[str, str]:
    try:
        text = (ROOT / "webapp" / "config.js").read_text(encoding="utf-8")
    except OSError:
        return "", ""
    url = re.search(r'url\s*:\s*"([^"]+)"', text)
    key = re.search(r'key\s*:\s*"([^"]+)"', text)
    return (url.group(1) if url else ""), (key.group(1) if key else "")


def main() -> int:
    url, key = os.environ.get("DIBEKHO_CLOUD_URL", "").strip(), os.environ.get("DIBEKHO_CLOUD_KEY", "").strip()
    source = "environment"
    if not (url and key):
        url, key = from_config_js()
        source = "webapp/config.js"
    if not (url.startswith("https://") and key) or "YOUR-PROJECT" in url:
        OUT.unlink(missing_ok=True)
        print("No Cloud address found: the build asks for it in the sign-in window.")
        return 0
    OUT.write_text(json.dumps({"url": url, "key": key}), encoding="utf-8")
    print(f"Cloud address written into the build (from {source}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
