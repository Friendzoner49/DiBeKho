"""Run the project's Supabase SQL on a real Postgres (PGlite via node, tests/pg) from a test.

Dev-only and optional: tests that use it are skipped when node or the PGlite package is missing
(`cd tests/pg && npm install` once). Nothing here ships with the app."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PG_DIR = ROOT / "tests" / "pg"
NODE = shutil.which("node")
AVAILABLE = NODE is not None and (PG_DIR / "node_modules" / "@electric-sql" / "pglite").exists()
needs_pg = pytest.mark.skipif(not AVAILABLE, reason="PGlite not installed (cd tests/pg && npm install)")

SUPABASE_FILES = ["cloud/supabase/001_init.sql", "cloud/supabase/007_core.sql"]


def run(steps: list[dict], files: list[str] = SUPABASE_FILES) -> list[list[dict]]:
    """Each step: {"sql", "params"?, "sub"?}. Returns the rows of every step; raises AssertionError on SQL errors."""
    payload = {"files": [str(ROOT / f) for f in files], "steps": steps}
    done = subprocess.run([NODE, str(PG_DIR / "run.mjs")], input=json.dumps(payload), capture_output=True,
                          text=True, encoding="utf-8", cwd=PG_DIR, timeout=300)
    assert done.stdout, done.stderr[-2000:]
    out = json.loads(done.stdout)
    if "error" in out:
        raise AssertionError(f"Postgres error at step {out['step']}: {out['error']}")
    return out["results"]


ALL_FILES = [*SUPABASE_FILES, "cloud/supabase/008_sync_rpc.sql"]


class Session:
    """A Postgres that stays up for a whole test (tests/pg/serve.mjs): Python steps and SQL interleave."""

    def __init__(self, files: list[str] = ALL_FILES):
        self.proc = subprocess.Popen([NODE, str(PG_DIR / "serve.mjs"), *[str(ROOT / f) for f in files]],
                                     cwd=PG_DIR, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, encoding="utf-8")
        ready = self.proc.stdout.readline()
        assert ready.strip(), self.proc.stderr.read()[-2000:]

    def query(self, sql: str, params: list | None = None, sub: str | None = None) -> list[dict]:
        self.proc.stdin.write(json.dumps({"sql": sql, "params": params or [], "sub": sub}) + "\n")
        self.proc.stdin.flush()
        answer = json.loads(self.proc.stdout.readline())
        if "error" in answer:
            raise PgError(answer["error"])
        return answer["rows"]

    def add_account(self, uid: str, role: str = "desktop") -> None:
        self.query("insert into auth.users(id) values ($1)", [uid])
        self.query("insert into public.profiles(user_id, role) values ($1, $2)", [uid, role])

    def close(self) -> None:
        self.proc.stdin.close()
        self.proc.wait(timeout=30)


class PgError(Exception):
    pass


class FakeCloud:
    """CloudClient.rpc() against the test Postgres; the access token is the account's uuid."""

    def __init__(self, session: Session):
        self.session = session
        self.lose_next_reply = False  # the call reaches the database, the answer never comes back

    def rpc(self, name: str, args: dict, access_token: str):
        params, parts = [], []
        for i, (key, value) in enumerate(args.items(), start=1):
            cast = "jsonb" if isinstance(value, (dict, list)) else "bigint" if isinstance(value, int) else "text"
            params.append(json.dumps(value) if cast == "jsonb" else value)
            parts.append(f"{key} => ${i}::{cast}")
        rows = self.session.query(f"select public.{name}({', '.join(parts)}) as r", params, sub=access_token)
        if self.lose_next_reply:
            self.lose_next_reply = False
            from dibekho.core.cloud.client import CloudError

            raise CloudError("timed out")
        return rows[0]["r"]
# the owner's writes from the web, in the order the user runs them on Supabase
WEB_FILES = [*ALL_FILES, "cloud/supabase/009_web_rpc.sql", "cloud/supabase/010_web_receipt_new_products.sql",
             "cloud/supabase/011_accounts.sql", "cloud/supabase/012_web_settings.sql",
             "cloud/supabase/013_return_prices.sql"]
