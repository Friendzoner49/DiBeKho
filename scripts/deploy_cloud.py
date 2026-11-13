"""One command to put the cloud side on the internet after a change (instead of three manual steps in three dashboards):

    python -X utf8 scripts/deploy_cloud.py              # SQL 009-011 + Edge Function `accounts` + web page
    python -X utf8 scripts/deploy_cloud.py --only sql   # or: function | web  (several allowed: --only sql web)

Needs two access tokens, kept OUTSIDE the repo (never commit them), in the environment or in the file
`~/.dibekho-deploy.env` (one `NAME=value` per line):
    SUPABASE_ACCESS_TOKEN   supabase.com -> Account -> Access Tokens -> Generate new token (this is NOT the project key)
    CLOUDFLARE_API_TOKEN    Cloudflare -> My Profile -> API Tokens -> Create Token -> template "Edit Cloudflare Workers"
                            (or a custom token with Account > Cloudflare Pages > Edit)
    CLOUDFLARE_ACCOUNT_ID   Cloudflare -> Workers & Pages -> right side "Account ID"
Optional: CLOUDFLARE_PAGES_PROJECT (default `dibekho`).
The Supabase project is read from webapp/config.js. Needs Node (npx). Safe to run again: the SQL files can be re-run."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQL_FILES = ["009_web_rpc.sql", "010_web_receipt_new_products.sql", "011_accounts.sql", "012_web_settings.sql"]  # each re-runs; 010 after 009
ENV_FILE = Path.home() / ".dibekho-deploy.env"


def load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def need(name, how):
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"Thiếu {name}. {how}\nĐặt trong biến môi trường hoặc trong file {ENV_FILE} (mỗi dòng NAME=giá trị).")
    return value


def project_ref():
    config = (ROOT / "webapp" / "config.js").read_text(encoding="utf-8")
    found = re.search(r"https://([a-z0-9]+)\.supabase\.co", config)
    if not found:
        sys.exit("Không đọc được địa chỉ Supabase trong webapp/config.js.")
    return found.group(1)


def run_sql(ref):
    token = need("SUPABASE_ACCESS_TOKEN", "Lấy ở supabase.com → Account → Access Tokens.")
    for name in SQL_FILES:
        sql = (ROOT / "cloud" / "supabase" / name).read_text(encoding="utf-8")
        request = urllib.request.Request(
            f"https://api.supabase.com/v1/projects/{ref}/database/query",
            data=json.dumps({"query": sql}).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "dibekho-deploy"})
        try:
            urllib.request.urlopen(request, timeout=120).read()
        except urllib.error.HTTPError as e:
            sys.exit(f"SQL {name} bị Supabase từ chối ({e.code}): {e.read().decode('utf-8', 'replace')[:600]}")
        print(f"  SQL {name}: xong")


def npx():
    found = shutil.which("npx")
    if not found:
        sys.exit("Cần cài Node.js (npx) để triển khai hàm và trang web.")
    return found


def run_function(ref):
    env = dict(os.environ, SUPABASE_ACCESS_TOKEN=need("SUPABASE_ACCESS_TOKEN", "Lấy ở supabase.com → Account → Access Tokens."))
    with tempfile.TemporaryDirectory() as work:  # the CLI wants supabase/functions/<name>/ under a work directory
        target = Path(work) / "supabase" / "functions" / "accounts"
        target.mkdir(parents=True)
        shutil.copy(ROOT / "cloud" / "supabase" / "functions" / "accounts" / "index.ts", target / "index.ts")
        # --no-verify-jwt: the function checks the caller itself, and this avoids the "Invalid JWT" 401
        done = subprocess.run([npx(), "--yes", "supabase", "functions", "deploy", "accounts", f"--remote={ref}", "--yes",
                               "--use-api", "--no-verify-jwt", "--workdir", work], env=env, cwd=work)
    if done.returncode:
        sys.exit("Triển khai hàm accounts lỗi (xem chữ báo ở trên).")
    print("  Edge Function accounts: xong")


def run_web():
    subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "make_web_deploy.py")], check=True, cwd=ROOT)
    env = dict(os.environ,
               CLOUDFLARE_API_TOKEN=need("CLOUDFLARE_API_TOKEN", "Lấy ở Cloudflare → My Profile → API Tokens."),
               CLOUDFLARE_ACCOUNT_ID=need("CLOUDFLARE_ACCOUNT_ID", "Xem ở Cloudflare → Workers & Pages (cột bên phải)."))
    project = os.environ.get("CLOUDFLARE_PAGES_PROJECT", "dibekho")
    done = subprocess.run([npx(), "--yes", "wrangler", "pages", "deploy", str(ROOT / "dist" / "web"), "--project-name", project,
                           "--branch", "main", "--commit-dirty=true"], env=env, cwd=ROOT)
    if done.returncode:
        sys.exit("Đưa trang web lên Cloudflare lỗi (xem chữ báo ở trên).")
    print("  Trang web: xong")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="+", choices=["sql", "function", "web"], help="chỉ làm một số bước")
    steps = parser.parse_args().only or ["sql", "function", "web"]
    load_env()
    ref = project_ref()
    if "sql" in steps:
        print("1. SQL…"); run_sql(ref)
    if "function" in steps:
        print("2. Edge Function accounts…"); run_function(ref)
    if "web" in steps:
        print("3. Trang web…"); run_web()
    print("Xong.")


if __name__ == "__main__":
    main()
