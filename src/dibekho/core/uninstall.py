"""Removing the app itself on macOS ('Gỡ app' in Settings).

A running app cannot delete its own bundle safely, so a tiny detached shell process waits until
this process has exited and then removes DiBeKho.app. On Windows the normal uninstaller in
Settings -> Apps does this job.
"""

import os
import subprocess
import sys
from pathlib import Path


def mac_bundle() -> Path | None:
    """The DiBeKho.app this process runs from, or None (not macOS, or running from source)."""
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    for parent in Path(sys.executable).resolve().parents:
        if parent.suffix == ".app":
            return parent
    return None


def can_remove(bundle: Path) -> bool:
    # Not from the mounted .dmg (read-only), and the folder holding the app must be writable.
    return not str(bundle).startswith("/Volumes/") and os.access(bundle.parent, os.W_OK)


def schedule_bundle_removal(bundle: Path) -> None:
    """Delete `bundle` once this process has exited."""
    script = 'while kill -0 "$0" 2>/dev/null; do sleep 0.3; done; rm -rf "$1"'
    subprocess.Popen(
        ["/bin/sh", "-c", script, str(os.getpid()), str(bundle)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
