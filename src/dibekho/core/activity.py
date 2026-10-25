"""Activity log (nhật ký thao tác): what the user did and what went wrong, in data/app.log.

One line per event: '2026-10-17 14:48:02 [click] Lưu phiếu hàng về · Nhập hàng về'. Errors carry their traceback.
The file never grows past MAX_BYTES: when it does, the oldest part is dropped (cut at a line, so Vietnamese and
Chinese text stay whole) and about KEEP_BYTES of the newest lines remain. Lines older than MAX_AGE_DAYS are
dropped once, when the app starts (see setup()) -- not on every write, since the file is small enough that this
is cheap once a day and need not run on every click.

Nothing is written until setup() is called (tests and --self-test never touch the user's folders), and a write
that fails is ignored: the log must never break the app. Typed text is never logged; message texts are, so the
file can hold customer names and file names. From 25/10/2026 this file travels with a data package (the other
machine's own copy is kept separately, see core.transfer): still local-only in the sense that it never leaves
the user's own machines.
"""

import os
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

MAX_BYTES = 1_000_000
KEEP_BYTES = 720_000
MAX_AGE_DAYS = 7
FILE_NAME = "app.log"

_path: Path | None = None


def setup(path: Path | None) -> None:
    global _path
    _path = Path(path) if path else None
    if _path is not None:
        trim_old(_path)


def path() -> Path | None:
    return _path


def log(kind: str, text: str = "") -> None:
    if _path is None:
        return
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} [{kind}] {text}".rstrip()
    line = line.replace("\r\n", "\n").replace("\n", "\n    ") + "\n"  # continuation lines indented
    try:
        with open(_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line)
        if _path.stat().st_size > MAX_BYTES:
            _trim(_path)
    except OSError:
        pass


def log_exception(kind: str = "error", text: str = "") -> None:
    """The exception being handled (call from an except block), with its traceback."""
    tb = traceback.format_exc().strip()
    log(kind, f"{text}\n{tb}" if text else tb)


def _trim(p: Path) -> None:
    data = p.read_bytes()
    tail = data[-KEEP_BYTES:]
    cut = tail.find(b"\n")
    tail = tail[cut + 1:] if cut >= 0 else b""
    while tail.startswith(b"    "):  # do not start in the middle of a traceback
        nl = tail.find(b"\n")
        tail = tail[nl + 1:] if nl >= 0 else b""
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_bytes(tail)
    os.replace(tmp, p)


def trim_old(p: Path, today: date | None = None) -> None:
    """Drop every line older than MAX_AGE_DAYS, including the indented traceback lines that follow it (they
    carry no date of their own, so they go with whatever top-level line comes before them). Used on this
    machine's own log at startup, and on another machine's log saved from a data package (core.transfer)."""
    try:
        if not p.exists():
            return
        data = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    cutoff = (today or date.today()) - timedelta(days=MAX_AGE_DAYS)
    lines = data.split("\n")
    keep_from = len(lines)  # nothing recent enough found yet: drop everything
    for i, line in enumerate(lines):
        if not line or line.startswith("    "):
            continue
        try:
            d = date.fromisoformat(line[:10])
        except ValueError:
            continue
        if d >= cutoff:
            keep_from = i
            break
    if keep_from == 0:
        return
    try:
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text("\n".join(lines[keep_from:]), encoding="utf-8", newline="\n")
        os.replace(tmp, p)
    except OSError:
        pass


def read() -> str:
    if _path is None or not _path.exists():
        return ""
    try:
        return _path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def clear() -> None:
    if _path is not None:
        try:
            _path.write_text("", encoding="utf-8")
        except OSError:
            pass
