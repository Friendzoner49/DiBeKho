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
