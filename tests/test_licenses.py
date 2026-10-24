"""The licenses shipped with the app: DiBeKho's MIT license and every bundled component, at the versions in
use (after changing a dependency: uv run python scripts/make_licenses.py)."""

import sys
from importlib import metadata
from pathlib import Path

from dibekho.ui.license_dialog import license_text

ROOT = Path(__file__).resolve().parent.parent


def test_licenses_list_the_bundled_versions():
    text = license_text()
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").strip() in text
    for dist in ("PySide6", "openpyxl", "et-xmlfile", "pyinstaller"):
        assert f" {metadata.version(dist)}" in text, f"{dist}: run scripts/make_licenses.py"
    assert f"Python {sys.version_info[0]}.{sys.version_info[1]}." in text
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in text and "Version 3, 29 June 2007" in text


def test_the_build_ships_the_licenses():
    spec = (ROOT / "packaging" / "dibekho.spec").read_text(encoding="utf-8")
    assert '"licenses" / "LICENSES.txt"' in spec
