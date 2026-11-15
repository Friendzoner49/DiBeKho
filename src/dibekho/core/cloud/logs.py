"""Every account's activity log (data/app.log) on the cloud, for the maychinh login only (cloud/supabase/017): a
problem on a customer's machine ('the app is slow', an error) can be read without asking for a data package, and the
way the app is used can be studied later.

One row per account + machine + day, replaced while the day lasts, kept 30 days. Before anything leaves the machine
the text goes through anonymize(): file names, quoted texts, phone numbers, e-mails and paths become placeholders,
the lines that list what was read or saved (scan/apply/receipt/forget) keep only their numbers, window titles keep
only their first part. What stays: time, kind of event, screen, button, error and traceback (paths cut to the app's
own files). The user can switch the sending off (Cài đặt → Cloud: Config.send_logs). Sent at most every EVERY
seconds, only the days whose text changed, from the sync worker thread (network only, never the database)."""

import hashlib
import re
import time
from datetime import date, timedelta
from pathlib import Path

from dibekho import __version__
from dibekho.core import activity
from dibekho.core.cloud.backup import _safe_device
from dibekho.core.cloud.client import CloudClient
from dibekho.core.workspace import Workspace

EVERY = 10 * 60  # s
DAYS = 2  # today and yesterday (a machine left on over midnight)
OLD_FOLDER = "nhat-ky"  # before 017: one gzip per machine in the 'backups' bucket, deleted once by each app

_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) \[(\w+)\] ?(.*)$")
_COUNTS_ONLY = {"scan", "apply", "receipt", "forget", "data"}
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|/(?:Users|home|Volumes|private|var|tmp)/)[^\s\"'<>|]*")
_FILE = re.compile(r"[^\s\"'«»“”/\\:]+\.(?:xlsx|xlsm|xls|dibekho|sqlite|csv|pdf|zip|log|json|txt)\b", re.I)
_QUOTED = re.compile(r"«[^»\n]*»|“[^”\n]*”|\"[^\"\n]*\"|'[^'\n]{2,}'")
_DIGITS = re.compile(r"\+?\d[\d .-]{5,}\d")
_TITLE_CUT = re.compile(r"\s*(?:[:：—–·|(]|\s-\s).*$")


def _path(m: re.Match) -> str:
    text = m.group(0).replace("\\", "/")
    for anchor in ("/dibekho/", "/site-packages/", "/_internal/"):
        if anchor in text:
            return anchor.strip("/") + "/" + text.split(anchor, 1)[1]
    return "<path>"


def _scrub(text: str) -> str:
    text = _EMAIL.sub("<email>", text)
    text = _PATH.sub(_path, text)
    text = _FILE.sub("<file>", text)
    text = _QUOTED.sub("«…»", text)
    return _DIGITS.sub("<số>", text)


_AFTER_LABEL = re.compile(r"([:：]\s*)[^·→\n]*?(?=\s*[·→]|$)", re.M)  # 'Khách: <name> · ...' -> 'Khách: «…» · ...'
_titles: set[str] | None = None


def _app_titles() -> set[str]:
    """Every text of the app's own interface (i18n/*.json), cut like a window title: a title that is not one of them
    (a dialog named after a customer or a file) is hidden."""
    global _titles
    if _titles is None:
        import json

        import dibekho.i18n  # plain json files next to this package (no Qt), also inside the built app
        _titles = set()
        for path in Path(dibekho.i18n.__file__).resolve().parent.glob("*.json"):
            try:
                values = json.loads(path.read_text(encoding="utf-8")).values()
            except (OSError, ValueError):
                continue
            _titles |= {_TITLE_CUT.sub("", str(v)).strip() for v in values}
        _titles.discard("")
    return _titles


def _title(text: str) -> str:
    cut = _TITLE_CUT.sub("", text).strip()
    return cut if cut in _app_titles() else "«…»"


def _message(text: str) -> str:
    return _AFTER_LABEL.sub(lambda m: m.group(1) + "«…»" if m.group(0).strip(":： ") else m.group(0), _scrub(text))


_FRAME = re.compile(r'^(\s*File )"([^"]+)"(.*)$')


def _trace_line(line: str) -> str:
    """'  File "C:\\Users\\X\\...\\dibekho\\core\\stock.py", line 5, in f' keeps the app's own path and the line."""
    m = _FRAME.match(line)
    if m:
        return f'{m.group(1)}"{_PATH.sub(_path, m.group(2))}"{_scrub(m.group(3))}'
    return _scrub(line)


def _anonymize_event(kind: str, text: str) -> str:
    first, _, rest = text.partition("\n")
    if kind == "scan":  # 'read 2: <file names> · waiting 1'
        m = re.match(r"read (\d+).*?waiting (\d+)", first)
        return f"read {m.group(1)} · waiting {m.group(2)}" if m else ""
    if kind in _COUNTS_ONLY:
        numbers = re.findall(r"(?<![\w.])\d+(?![\w.])", _DIGITS.sub("", _FILE.sub("", first)))
        lines = text.count("\n")
        return " ".join(numbers[:6]) + (f" (+{lines} dòng)" if lines else "")
    if kind == "window":
        return _title(first)
    if kind in ("error", "crash"):  # the message may name a customer; the traceback is code
        trace = "\n".join(_trace_line(line) for line in rest.split("\n")) if rest else ""
        return _scrub(first) + ("\n" + trace if trace else "")  # keep the cause readable: names are quoted or files
    if kind in ("ask", "info"):
        return _message(text)
    return _scrub(text)


def anonymize(text: str) -> dict[str, str]:
    """app.log text -> {'2026-11-15': anonymized lines of that day}. Continuation lines (indented) follow their event."""
    days: dict[str, list[str]] = {}
    event: tuple[str, str, str, list[str]] | None = None

    def flush():
        if event:
            day, clock, kind, parts = event
            body = _anonymize_event(kind, "\n".join(parts)).replace("\n", "\n    ")
            days.setdefault(day, []).append(f"{day} {clock} [{kind}] {body}".rstrip())

    for line in text.splitlines():
        m = _LINE.match(line)
        if m:
            flush()
            event = (m.group(1), m.group(2), m.group(3), [m.group(4)])
        elif event and line.startswith("    "):
            event[3].append(line[4:])
    flush()
    return {d: "\n".join(lines) + "\n" for d, lines in days.items()}


class LogUploader:
    """Called from the sync worker thread. A failure is written to the log and never stops a sync."""

    def __init__(self, every: float = EVERY):
        self.every, self.last = every, None
        self.sent: dict[str, str] = {}  # day -> hash of what the cloud has
        self.old_deleted = False

    def maybe_upload(self, ws: Workspace, cfg, client: CloudClient, token: str) -> None:
        if not getattr(cfg, "send_logs", True):
            return
        now = time.monotonic()
        if self.last is not None and now - self.last < self.every:
            return
        self.last = now
        try:
            self.upload(ws, cfg, client, token)
        except Exception as exc:  # noqa: BLE001 -- the log must never stop a sync (no SQL 017 yet, odd answer...)
            activity.log("error", f"uploading the activity log: {type(exc).__name__}: {exc}")

    def upload(self, ws: Workspace, cfg, client: CloudClient, token: str) -> int:
        """Send the days that changed; -> how many were sent."""
        if not self.old_deleted:
            self.old_deleted = True
            try:
                client.storage_delete([f"{OLD_FOLDER}/{_safe_device(cfg.device_name)}-{cfg.device_id}.log.gz"], token)
            except Exception:  # noqa: BLE001 -- not there, or the account may not delete: 017 removes them too
                pass
        path = Path(ws.data) / activity.FILE_NAME
        if not path.exists():
            return 0
        days = anonymize(path.read_text(encoding="utf-8", errors="replace"))
        wanted = {(date.today() - timedelta(days=n)).isoformat() for n in range(DAYS)}
        device = f"{_safe_device(cfg.device_name)}-{cfg.device_id}"
        sent = 0
        for day in sorted(wanted & set(days)):
            digest = hashlib.sha1(days[day].encode("utf-8")).hexdigest()
            if self.sent.get(day) == digest:
                continue
            client.rpc("log_send", {"p_device": device, "p_version": __version__, "p_day": day,
                                    "p_content": days[day]}, token)
            self.sent[day] = digest
            sent += 1
        return sent


def fetch_logs(client: CloudClient, token: str, folder: Path) -> list[Path]:
    """Download every log the cloud keeps into folder (maychinh only: scripts/fetch_cloud_logs.py)."""
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for row in client.rpc("log_list", {}, token) or []:
        text = client.rpc("log_get", {"p_user": row["user_id"], "p_device": row["device"], "p_day": row["day"]}, token)
        name = f"{row['day']}_{_safe_device(row.get('sender') or 'x')}_{row['device']}.log"
        target = folder / name
        target.write_text(text or "", encoding="utf-8")
        out.append(target)
    return out
