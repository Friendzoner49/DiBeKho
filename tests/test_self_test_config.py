"""`--self-test` runs in every build: it must never write the developer's or the customer's config.json (it once did,
through the window saving its geometry on close: workspace -> a temp folder, cloud login blanked)."""

import os
import subprocess
import sys


def test_self_test_writes_no_config(tmp_path):
    env = {**os.environ, "APPDATA": str(tmp_path), "HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path),
           "QT_QPA_PLATFORM": "offscreen"}
    done = subprocess.run([sys.executable, "-X", "utf8", "-m", "dibekho.app", "--self-test"], env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=150)
    assert "self-test OK" in done.stdout, done.stdout[-500:] + done.stderr[-1500:]
    assert not list(tmp_path.rglob("config.json"))
