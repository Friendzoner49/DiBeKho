import sys
from pathlib import Path

from dibekho.core import uninstall


def test_mac_bundle_found_from_the_executable(monkeypatch, tmp_path):
    exe = tmp_path / "Applications" / "DiBeKho.app" / "Contents" / "MacOS" / "DiBeKho"
    exe.parent.mkdir(parents=True)
    exe.touch()
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert uninstall.mac_bundle() == (tmp_path / "Applications" / "DiBeKho.app").resolve()


def test_no_bundle_when_running_from_source(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert uninstall.mac_bundle() is None


def test_never_removes_from_the_mounted_dmg(tmp_path):
    assert not uninstall.can_remove(Path("/Volumes/DiBeKho/DiBeKho.app"))
    (tmp_path / "DiBeKho.app").mkdir()
    assert uninstall.can_remove(tmp_path / "DiBeKho.app")
