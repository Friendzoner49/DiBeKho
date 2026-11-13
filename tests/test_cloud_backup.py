"""Full cloud backups: upload/prune/list/fetch/validate, a whole restore, and the Storage HTTP shapes."""

import hashlib
import io
import json
import sqlite3
import urllib.request
from datetime import date, datetime, timezone

import pytest

from dibekho import db
from dibekho.core import backup, catalog, stock
from dibekho.core.cloud import backup as cloud_backup
from dibekho.core.cloud import sync
from dibekho.core.cloud.client import CloudClient, CloudError


class FakeStorage:
    """In-memory stand-in for the four Storage calls."""

    def __init__(self):
        self.files = {}

    def storage_upload(self, name, data, token):
        assert name not in self.files, "uploads must never overwrite"
        self.files[name] = data

    def storage_list(self, token):
        return [{"name": n, "metadata": {"size": len(d)}} for n, d in self.files.items()] + [
            {"name": "notes.txt", "metadata": {"size": 3}}]  # a foreign file must be ignored

    def storage_download(self, name, token):
        return self.files[name]

    def storage_delete(self, names, token):
        for n in names:
            del self.files[n]


class Cfg:
    device_id, device_name = "dev-1", "May Chinh"


def _seed(conn):
    with db.transaction(conn):
        pid = catalog.create_product(conn, "Keo chống thấm", spec="15kg", unit="thùng")
        stock.stock_count(conn, date(2026, 11, 1), {(pid, stock.MAIN): 40})
    return pid


def test_name_roundtrip_and_foreign_names_ignored():
    when = datetime(2026, 11, 11, 9, 30, 0, tzinfo=timezone.utc)
    name = cloud_backup.make_name("May Chinh!", 9, when)
    assert name == "2026-11-11T09-30-00Z__MayChinh__s9.sqlite"
    item = cloud_backup.parse_name(name, 1234)
    assert item.device == "MayChinh" and item.schema == 9 and item.size == 1234
    assert item.at.astimezone(timezone.utc) == when
    assert cloud_backup.parse_name("notes.txt") is None


def test_prune_keeps_the_newest_and_list_is_newest_first():
    store = FakeStorage()
    for d in range(1, 6):
        store.files[f"2026-11-0{d}T08-00-00Z__May__s9.sqlite"] = b"x"
    assert cloud_backup.prune(store, "tok", keep=3) == 2
    assert sorted(store.files) == ["2026-11-03T08-00-00Z__May__s9.sqlite",
                                   "2026-11-04T08-00-00Z__May__s9.sqlite",
                                   "2026-11-05T08-00-00Z__May__s9.sqlite"]
    listed = cloud_backup.list_backups(store, "tok")
    assert [b.name[:10] for b in listed] == ["2026-11-05", "2026-11-04", "2026-11-03"]  # newest first


def test_upload_snapshot_is_a_restorable_database(conn, tmp_path):
    pid = _seed(conn)
    store = FakeStorage()
    name = cloud_backup.upload_snapshot(conn, Cfg, store, "tok")
    assert name in store.files
    path = cloud_backup.fetch(store, "tok", name, tmp_path / "dl")
    copy = sqlite3.connect(path)
    assert copy.execute("SELECT SUM(qty) FROM stock_movements WHERE product_id = ?", (pid,)).fetchone()[0] == 40
    assert copy.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    copy.close()


def test_validate_rejects_junk_empty_and_newer(tmp_path):
    junk = tmp_path / "junk.sqlite"
    junk.write_bytes(b"this is not a database")
    with pytest.raises(CloudError):
        cloud_backup.validate(junk)
    empty = tmp_path / "empty.sqlite"
    sqlite3.connect(empty).close()  # user_version 0, no tables
    with pytest.raises(CloudError):
        cloud_backup.validate(empty)
    newer = tmp_path / "newer.sqlite"
    c = db.connect(newer)
    c.execute(f"PRAGMA user_version = {db.schema_version() + 1}")
    c.close()
    with pytest.raises(CloudError, match="mới hơn"):
        cloud_backup.validate(newer)


def test_validate_upgrades_an_older_copy(tmp_path):
    old = tmp_path / "old.sqlite"
    c = db.connect(old)
    c.close()
    raw = sqlite3.connect(old)  # pretend it was made by the previous schema: roll the version back one step
    raw.execute(f"PRAGMA user_version = {db.schema_version() - 1}")
    raw.commit()
    raw.close()
    assert cloud_backup.validate(old) == db.schema_version() - 1  # reports what the file was
    again = sqlite3.connect(old)
    assert again.execute("PRAGMA user_version").fetchone()[0] == db.schema_version()  # upgraded on the copy
    again.close()


def test_whole_restore_brings_back_the_old_state(ws, tmp_path):
    conn = db.connect(ws.db_path)
    pid = _seed(conn)
    store = FakeStorage()
    name = cloud_backup.upload_snapshot(conn, Cfg, store, "tok")
    with db.transaction(conn):  # the day goes on: more stock moves after the backup
        stock.stock_count(conn, date(2026, 11, 2), {(pid, stock.MAIN): 5})
    assert conn.execute("SELECT SUM(qty) FROM stock_movements").fetchone()[0] == 5

    path = cloud_backup.fetch(store, "tok", name, tmp_path / "dl")
    backup.named_backup(conn, ws, "truoc-khoi-phuc-cloud")
    conn.close()
    backup.restore(ws, path)

    restored = db.connect(ws.db_path)
    assert restored.execute("SELECT SUM(qty) FROM stock_movements").fetchone()[0] == 40
    assert any("truoc-khoi-phuc-cloud" in f.name for f in backup.list_backups(ws))  # a way back exists
    restored.close()


# ---- Storage HTTP shapes ------------------------------------------------------------------------------------

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capture(monkeypatch, reply=b"[]"):
    seen = []

    def opener(req, timeout=None):
        seen.append(req)
        return _Resp(reply)

    monkeypatch.setattr(urllib.request, "urlopen", opener)
    return seen


def test_storage_upload_and_download_requests(monkeypatch):
    seen = _capture(monkeypatch, reply=b"\x00binary\xff")
    c = CloudClient("https://xxx.supabase.co", "key1")
    c.storage_upload("a b.sqlite", b"DATA", "tok")
    req = seen[-1]
    assert req.get_method() == "POST" and req.full_url == "https://xxx.supabase.co/storage/v1/object/backups/a%20b.sqlite"
    assert req.data == b"DATA" and req.get_header("Content-type") == "application/octet-stream"
    assert req.get_header("Authorization") == "Bearer tok"
    assert c.storage_download("a b.sqlite", "tok") == b"\x00binary\xff"
    assert seen[-1].get_method() == "GET" and "/object/authenticated/backups/" in seen[-1].full_url


def test_storage_list_and_delete_requests(monkeypatch):
    seen = _capture(monkeypatch, reply=json.dumps([{"name": "n"}]).encode())
    c = CloudClient("https://xxx.supabase.co", "key1")
    assert c.storage_list("tok") == [{"name": "n"}]
    assert seen[-1].full_url.endswith("/storage/v1/object/list/backups") and seen[-1].get_method() == "POST"
    seen2 = _capture(monkeypatch, reply=b"[]")
    c.storage_delete(["x", "y"], "tok")
    assert seen2[-1].get_method() == "DELETE"
    assert json.loads(seen2[-1].data) == {"prefixes": ["x", "y"]}


# ---- after the database file is replaced ----------------------------------------------------------------------

def test_replacing_the_database_file_marks_data_unpushed(ws, tmp_path):
    """Undo / restore / package import all swap kho.sqlite. last_change_at and cloud_last_push_at come back from
    the older copy together, so without AppContext.reopen() touching the data the app would think the cloud is
    current and never push: the web would keep showing what was just undone."""
    from dibekho.core.workspace import Config
    from dibekho.ui.common import AppContext

    ctx = AppContext(Config(workspace=str(ws.root)), ws)
    before = backup.snapshot(ctx.conn, tmp_path / "before.sqlite")  # the state Undo would put back
    with db.transaction(ctx.conn):
        catalog.create_product(ctx.conn, "Keo", spec="15kg", unit="thùng")  # a change ...
    class Client(FakeStorage):
        def get(self, *a):
            return []
    sync.finish_push(ctx.conn, Cfg, Client(), "tok")  # ... that is backed up
    assert not sync.has_unpushed(ctx.conn)

    ctx.close()
    backup.restore(ws, before)  # Undo
    ctx.reopen()
    assert sync.has_unpushed(ctx.conn)  # the cloud still holds the undone change: it must be pushed again
    ctx.close()


def test_after_restore_hides_other_machines_file_notes(conn):
    with db.transaction(conn):
        conn.execute("INSERT INTO scanned_files(hash, rel_path, status) VALUES('h1', 'a.xlsx', 'imported')")
        conn.execute("INSERT INTO scanned_files(hash, rel_path, status) VALUES('h2', 'b.xlsx', 'needs_mapping')")
    other = cloud_backup.parse_name("2026-11-11T09-30-00Z__MayKhac__s9.sqlite")
    cloud_backup.after_restore(conn, Cfg, other)
    status = {r[0]: r[1] for r in conn.execute("SELECT hash, status FROM scanned_files")}
    assert status == {"h1": "missing_ignored", "h2": "needs_mapping"}  # only the 'lost file' notes are hidden


def test_after_restore_keeps_file_notes_for_the_same_machine(conn):
    with db.transaction(conn):
        conn.execute("INSERT INTO scanned_files(hash, rel_path, status) VALUES('h1', 'a.xlsx', 'imported')")
    mine = cloud_backup.parse_name("2026-11-11T09-30-00Z__MayChinh__s9.sqlite")
    cloud_backup.after_restore(conn, Cfg, mine)  # Cfg.device_name = "May Chinh" -> "MayChinh"
    assert conn.execute("SELECT status FROM scanned_files").fetchone()[0] == "imported"


def test_finish_push_can_skip_the_full_backup(conn):
    """On a slow line the close-time push must not also upload the backup (the window would look frozen)."""
    class Client:
        def get(self, *a):
            return []  # reconcile_applied: nothing recorded on the web

        def storage_upload(self, *a):
            raise AssertionError("no upload expected")

        def patch(self, *a):
            raise AssertionError("nothing to confirm")

    assert sync.finish_push(conn, Cfg, Client(), "tok", with_backup=False) is None


def test_finish_push_reports_backup_failure_but_does_not_raise(conn):
    class Client(FakeStorage):
        def get(self, *a):
            return []

        def storage_upload(self, name, data, token):
            raise CloudError("Cloud báo lỗi 404: Bucket not found")

    reason = sync.finish_push(conn, Cfg, Client(), "tok")
    assert "Bucket not found" in reason  # shown to the user after "Đồng bộ ngay"; the push itself stands


def test_finish_push_on_shared_data_confirms_requests_only_once_nothing_is_left_to_send(conn):
    """Đồng bộ ngay starts a round in the background and goes straight on: the web must not show a request as
    recorded while its document is still waiting here."""
    from dibekho.core.cloud import inbox, replica

    replica.set_enabled(conn, True)
    with db.transaction(conn):
        pid = catalog.create_product(conn, "Keo")
        doc = stock.insert_document(conn, "receipt", date(2026, 11, 12), [stock.Line(pid, 5)], code="HV001")
        db.set_meta(conn, inbox.META_KEY, '{"req-1": %d}' % doc)  # approved here, still queued for the cloud

    class Client:
        def get(self, *a):
            return []

        def patch(self, *a):
            raise AssertionError("confirmed before the document reached the cloud")

    assert sync.finish_push(conn, Cfg, Client(), "tok", with_backup=False) is None


def test_a_package_for_shared_data_is_written_aside_and_the_live_file_stays(ws, tmp_path):
    from dibekho.core import transfer
    from dibekho.core.workspace import Config

    live = db.connect(ws.db_path)
    with db.transaction(live):
        catalog.create_product(live, "Keo")
    package = transfer.export_package(live, ws, Config(workspace=str(ws.root), device_name="May kia"))
    live.close()
    before = ws.db_path.read_bytes()
    dest = tmp_path / "new.sqlite"
    manifest = transfer.import_package(ws, package, dest=dest)
    assert ws.db_path.read_bytes() == before  # untouched until the cloud has it
    copy = db.connect(dest)
    assert copy.execute("SELECT name_vi FROM products").fetchone()[0] == "Keo" and manifest.device_name == "May kia"
    copy.close()


# ---- the kept delivery notes (data/phieu-goc) -------------------------------------------------------------------

class FolderStorage(FakeStorage):
    """Storage with folders, as Supabase lists them: the root shows a folder entry, a prefix shows its files."""

    def storage_list(self, token, prefix="", limit=200, offset=0):
        if prefix:
            names = sorted(n[len(prefix) + 1:] for n in self.files if n.startswith(prefix + "/"))
            return [{"name": n, "metadata": {"size": 1}} for n in names][offset:offset + limit]
        rows = [{"name": n, "metadata": {"size": len(d)}} for n, d in self.files.items() if "/" not in n]
        if any("/" in n for n in self.files):
            rows.append({"name": "phieu-goc", "id": None, "metadata": None})
        return rows

    def get(self, *a):
        return []


def _note(ws, text: str) -> str:
    data = text.encode()
    name = hashlib.sha256(data).hexdigest() + ".xlsx"
    ws.originals.mkdir(parents=True, exist_ok=True)
    (ws.originals / name).write_bytes(data)
    return name


def test_kept_notes_go_up_once_and_lock_files_stay_home(ws):
    store = FolderStorage()
    a, b = _note(ws, "phieu 1"), _note(ws, "phieu 2")
    (ws.originals / ("~$" + a)).write_bytes(b"lock")
    assert cloud_backup.upload_originals(ws, store, "tok") == (2, 0)
    assert set(store.files) == {f"phieu-goc/{a}", f"phieu-goc/{b}"}
    assert cloud_backup.upload_originals(ws, store, "tok") == (0, 0)  # FakeStorage refuses an overwrite
    c = _note(ws, "phieu 3")
    assert cloud_backup.upload_originals(ws, store, "tok") == (1, 0) and f"phieu-goc/{c}" in store.files


def test_kept_notes_stop_at_the_time_limit_and_finish_next_time(ws):
    store = FolderStorage()
    for i in range(3):
        _note(ws, f"phieu {i}")
    assert cloud_backup.upload_originals(ws, store, "tok", max_seconds=-1) == (0, 3)
    assert cloud_backup.upload_originals(ws, store, "tok") == (3, 0)


def test_many_kept_notes_are_listed_page_by_page(ws, monkeypatch):
    store = FolderStorage()
    for i in range(5):
        store.files[f"phieu-goc/{i:064x}.xlsx"] = b"x"
    real = store.storage_list
    monkeypatch.setattr(store, "storage_list", lambda token, prefix="", limit=200, offset=0: real(token, prefix, 2, offset))
    assert len(cloud_backup.cloud_originals(store, "tok")) == 5


def test_finish_push_also_sends_the_kept_notes_and_the_backup_list_ignores_their_folder(ws, conn):
    store = FolderStorage()
    a = _note(ws, "phieu 1")
    assert sync.finish_push(conn, Cfg, store, "tok", ws=ws, originals_seconds=10) is None
    assert f"phieu-goc/{a}" in store.files
    backups = cloud_backup.list_backups(store, "tok")
    assert len(backups) == 1 and backups[0].name.endswith(".sqlite")
    assert cloud_backup.prune(store, "tok", keep=0) == 1 and f"phieu-goc/{a}" in store.files  # notes never pruned


def test_a_restore_brings_back_the_kept_notes_it_lacks_and_skips_a_damaged_one(ws, tmp_path):
    from dibekho.core.workspace import Workspace

    store = FolderStorage()
    a, b = _note(ws, "phieu 1"), _note(ws, "phieu 2")
    cloud_backup.upload_originals(ws, store, "tok")
    bad = hashlib.sha256(b"real").hexdigest() + ".xlsx"
    store.files[f"phieu-goc/{bad}"] = b"tampered"
    other = Workspace(tmp_path / "may-moi")
    other.ensure()
    (other.originals / a).write_bytes(b"phieu 1")  # already here: not downloaded again
    downloads = []
    real = store.storage_download
    store.storage_download = lambda name, token: downloads.append(name) or real(name, token)
    assert cloud_backup.fetch_originals(other, store, "tok") == (1, 1)
    assert (other.originals / b).read_bytes() == b"phieu 2"
    assert not (other.originals / bad).exists() and not list(other.originals.glob("*.tai-ve"))
    assert f"phieu-goc/{a}" not in downloads


def test_a_restore_offline_does_not_fail_on_the_notes(ws):
    class Offline(FolderStorage):
        def storage_list(self, *a, **k):
            raise CloudError("Không kết nối được Cloud.")

    assert cloud_backup.fetch_originals(ws, Offline(), "tok") == (0, 0)


def test_storage_list_of_a_folder_request(monkeypatch):
    seen = _capture(monkeypatch, reply=b"[]")
    CloudClient("https://xxx.supabase.co", "key1").storage_list("tok", prefix="phieu-goc", limit=1000, offset=1000)
    assert json.loads(seen[-1].data)["prefix"] == "phieu-goc"
    assert json.loads(seen[-1].data)["offset"] == 1000 and json.loads(seen[-1].data)["limit"] == 1000
