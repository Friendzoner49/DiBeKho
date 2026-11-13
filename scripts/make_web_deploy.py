"""Build the web page for hosting (Cloudflare Pages "Direct Upload", or any static host).

    uv run python scripts/make_web_deploy.py

-> dist/web/ (the folder to upload) and dist/DiBeKho-web.zip. webapp/config.js (the Supabase address and the
publishable key, not in git) must exist: the page cannot sign in without it. That key is meant to be public;
what protects the data is the row level security of cloud/supabase/*.sql. Nothing else is added or changed.
"""

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webapp"
OUT = ROOT / "dist" / "web"
ZIP = ROOT / "dist" / "DiBeKho-web.zip"
LEAVE_OUT = {"config.example.js"}

# Cloudflare Pages reads this file: headers a <meta> tag cannot set, and no stale page after an update
HEADERS = """/*
  X-Frame-Options: DENY
  Content-Security-Policy: frame-ancestors 'none'
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  Cache-Control: no-cache
"""


def main() -> int:
    config = SRC / "config.js"
    if not config.exists() or "supabase.co" not in config.read_text(encoding="utf-8"):
        print("Thiếu webapp/config.js (chép config.example.js thành config.js rồi điền địa chỉ + mã kết nối).")
        return 1
    shutil.rmtree(OUT, ignore_errors=True)
    shutil.copytree(SRC, OUT, ignore=lambda folder, names: [n for n in names if n in LEAVE_OUT])
    (OUT / "_headers").write_text(HEADERS, encoding="utf-8")
    ZIP.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(OUT.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(OUT).as_posix())
    files = sum(1 for f in OUT.rglob("*") if f.is_file())
    print(f"OK: {OUT} ({files} file) và {ZIP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
