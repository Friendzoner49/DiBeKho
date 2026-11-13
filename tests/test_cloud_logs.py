"""Each machine's activity log on the cloud (core/cloud/logs.py): replaced, not piled up; at most every 10 minutes;
a failure never stops a sync; the developer can read them back."""

from dibekho.core import activity
from dibekho.core.cloud import logs
from dibekho.core.cloud.client import CloudError
from dibekho.core.workspace import Config


class FakeStorage:
    def __init__(self, fail=False):
        self.files, self.fail, self.calls = {}, fail, []

    def storage_upload(self, name, data, token):
        self.calls.append(("up", name))
        if self.fail:
            raise CloudError("offline")
        if name in self.files:
            raise CloudError("409 Duplicate")  # the bucket has no update policy, like the real one
        self.files[name] = data

    def storage_delete(self, names, token):
        self.calls.append(("del", tuple(names)))
        for n in names:
            self.files.pop(n, None)

    def storage_list(self, token, prefix="", limit=100, offset=0):
        return [{"name": n.split("/", 1)[1]} for n in self.files if n.startswith(prefix + "/")]

    def storage_download(self, name, token):
        return self.files[name]


def _cfg():
    return Config(workspace="x", language="vi", device_id="abc123", device_name="Máy chính!")


def test_the_log_is_replaced_and_read_back(ws, tmp_path):
    (ws.data / activity.FILE_NAME).write_text("2026-11-13 08:00:00 [start] DiBeKho\n", encoding="utf-8")
    store = FakeStorage()
    assert logs.upload_log(ws, _cfg(), store, "t")
    (ws.data / activity.FILE_NAME).write_text("2026-11-13 09:00:00 [slow] refresh StockPage 1500 ms\n", encoding="utf-8")
    assert logs.upload_log(ws, _cfg(), store, "t")  # a second upload replaces the first
    assert list(store.files) == ["nhat-ky/Máychính-abc123.log.gz"]
    got = logs.fetch_logs(store, "t", tmp_path / "out")
    assert [p.name for p in got] == ["Máychính-abc123.log"]
    assert "[slow] refresh StockPage" in got[0].read_text(encoding="utf-8")


def test_no_log_yet_uploads_nothing(ws):
    store = FakeStorage()
    assert logs.upload_log(ws, _cfg(), store, "t") is False and store.calls == []


def test_at_most_every_ten_minutes_and_a_failure_is_only_logged(ws):
    (ws.data / activity.FILE_NAME).write_text("x\n", encoding="utf-8")
    store = FakeStorage(fail=True)
    up = logs.LogUploader()
    up.maybe_upload(ws, _cfg(), store, "t")  # offline: no exception reaches the sync
    up.maybe_upload(ws, _cfg(), store, "t")  # too soon: not tried again
    assert [c for c in store.calls if c[0] == "up"] == [("up", "nhat-ky/Máychính-abc123.log.gz")]
    up.last -= logs.EVERY + 1
    up.maybe_upload(ws, _cfg(), store, "t")
    assert len([c for c in store.calls if c[0] == "up"]) == 2
