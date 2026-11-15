"""Every account's activity log on the cloud (core/cloud/logs.py): names hidden before anything leaves the machine, one
upload per changed day, at most every 10 minutes, nothing when switched off, a failure never stops a sync."""

from datetime import date, timedelta

from dibekho.core import activity
from dibekho.core.cloud import logs
from dibekho.core.cloud.client import CloudError
from dibekho.core.workspace import Config

TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


class FakeCloud:
    def __init__(self, fail=False):
        self.fail, self.rows, self.calls = fail, {}, []

    def rpc(self, name, args, token):
        self.calls.append(name)
        if self.fail:
            raise CloudError("offline")
        if name == "log_send":
            self.rows[(args["p_device"], args["p_day"])] = args["p_content"]
            return None
        if name == "log_list":
            return [{"user_id": "u", "device": d, "day": day, "sender": "maychinh"} for d, day in self.rows]
        if name == "log_get":
            return self.rows[(args["p_device"], args["p_day"])]
        raise AssertionError(name)

    def storage_delete(self, names, token):
        self.calls.append("del")


def _cfg(**kw):
    return Config(workspace="x", language="vi", device_id="abc123", device_name="Máy chính!", **kw)


def test_names_are_hidden():
    text = (
        f"{TODAY} 08:00:00 [scan] read 2: 113 Công ty A.xlsx, 114.xlsx · waiting 1\n"
        f"{TODAY} 08:01:00 [ask] Thay phiếu «Công ty A» bằng bản mới? → yes\n"
        f"{TODAY} 08:02:00 [window] Khách hàng: Công ty A\n"
        f"{TODAY} 08:03:00 [info] Gọi 0900 000 123 hoặc khach@mau.vn\n"
        f"{TODAY} 08:04:00 [error] Không mở được C:\\Users\\Ten\\Documents\\DiBeKho\\phieu.xlsx\n"
        f"    Traceback (most recent call last):\n"
        f"      File \"C:\\Users\\Ten\\AppData\\dibekho\\core\\stock.py\", line 5, in f\n"
        f"    KeyError: 'Khách Mẫu'\n"
        f"{TODAY} 08:05:00 [apply] Công ty A · Keo A 5\n    Sơn B 3\n"
        f"{TODAY} 08:06:00 [click] Lưu phiếu hàng về · Nhập hàng về\n"
        f"{TODAY} 08:07:00 [window] Công ty A\n"
        f"{TODAY} 08:08:00 [ask] Ngày 14/11/2026 · Khách: Công ty A → yes\n"
    )
    out = logs.anonymize(text)[TODAY]
    for secret in ("Công ty A", "113 Công", "0900", "khach@", "Ten", "Khách Mẫu", "phieu.xlsx", "Keo A", "Sơn B"):
        assert secret not in out, secret
    assert "[scan] read 2 · waiting 1" in out  # counts only
    assert "dibekho/core/stock.py" in out and "line 5" in out  # the traceback still points at the code
    assert "[window] Khách hàng\n" in out and "[window] «…»\n" in out  # only the app's own titles stay
    assert "Khách: «…» → yes" in out
    assert "[click] Lưu phiếu hàng về · Nhập hàng về" in out
    assert "[apply] 5 (+1 dòng)" in out


def test_one_row_per_day_sent_again_only_when_it_changed(ws, tmp_path):
    log = ws.data / activity.FILE_NAME
    log.write_text(f"{YESTERDAY} 23:59:00 [start] DiBeKho\n{TODAY} 08:00:00 [page] stock\n", encoding="utf-8")
    cloud, up = FakeCloud(), logs.LogUploader()
    assert up.upload(ws, _cfg(), cloud, "t") == 2
    assert up.upload(ws, _cfg(), cloud, "t") == 0  # nothing new
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"{TODAY} 09:00:00 [slow] refresh StockPage 1500 ms\n")
    assert up.upload(ws, _cfg(), cloud, "t") == 1
    got = logs.fetch_logs(cloud, "t", tmp_path / "out")
    assert len(got) == 2 and any("[slow] refresh StockPage" in p.read_text(encoding="utf-8") for p in got)
    assert cloud.calls.count("del") == 1  # the old nhat-ky/ file, once


def test_switched_off_sends_nothing(ws):
    (ws.data / activity.FILE_NAME).write_text(f"{TODAY} 08:00:00 [start] x\n", encoding="utf-8")
    cloud = FakeCloud()
    logs.LogUploader().maybe_upload(ws, _cfg(send_logs=False), cloud, "t")
    assert cloud.calls == []


def test_at_most_every_ten_minutes_and_a_failure_is_only_logged(ws):
    (ws.data / activity.FILE_NAME).write_text(f"{TODAY} 08:00:00 [start] x\n", encoding="utf-8")
    cloud = FakeCloud(fail=True)
    up = logs.LogUploader()
    up.maybe_upload(ws, _cfg(), cloud, "t")  # offline: no exception reaches the sync
    up.maybe_upload(ws, _cfg(), cloud, "t")  # too soon: not tried again
    assert cloud.calls.count("log_send") == 1
    up.last -= logs.EVERY + 1
    up.maybe_upload(ws, _cfg(), cloud, "t")
    assert cloud.calls.count("log_send") == 2
