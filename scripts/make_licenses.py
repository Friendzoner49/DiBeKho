"""Write src/dibekho/licenses/LICENSES.txt: DiBeKho's own MIT license plus every third-party component the
installed app contains (Python, Qt for Python, openpyxl, et-xmlfile, PyInstaller bootloader), with the full
license texts. The app shows it in Settings → General → Open-source licenses…, and it ships in the bundle.

Run from the repo root after changing a dependency version (tests/test_licenses.py checks the versions):
    uv run python scripts/make_licenses.py
"""

import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "dibekho" / "licenses" / "LICENSES.txt"
GNU = ROOT / "packaging" / "licenses"


def dist_file(dist: str, name: str) -> str:
    """A license file shipped in a package's .dist-info."""
    for f in metadata.files(dist) or []:
        if f.name == name and ".dist-info" in str(f):
            return f.read_text(encoding="utf-8")
    raise SystemExit(f"{name} not found in {dist}")


def section(title: str, text: str) -> str:
    return f"\n\n{'=' * 78}\n{title}\n{'=' * 78}\n\n{text.strip()}\n"


py = ".".join(map(str, sys.version_info[:3]))
qt = metadata.version("PySide6")
xl = metadata.version("openpyxl")
et = metadata.version("et-xmlfile")
pi = metadata.version("pyinstaller")

head = f"""DiBeKho — licenses
==================

DiBeKho is open-source software under the MIT License (first section below).
Source code: https://github.com/Friendzoner49/DiBeKho

The installed app also contains the following software, each under its own license:

- Python {py} — Python Software Foundation License. https://www.python.org/
  (includes SQLite, which is in the public domain)
- Qt for Python (PySide6 and Shiboken6) {qt} and the Qt {qt.rsplit('.', 1)[0]} libraries it ships with —
  GNU Lesser General Public License v3 (LGPLv3).
    Source code: https://code.qt.io/cgit/pyside/pyside-setup.git/ (tag v{qt})
                 https://download.qt.io/official_releases/QtForPython/
    Licenses of components inside Qt: https://doc.qt.io/qt-6/licenses-used-in-qt.html
    The Qt and PySide6 libraries are separate, unmodified files inside the app
    (Windows: DiBeKho\\_internal\\PySide6, macOS: DiBeKho.app/Contents/Frameworks/PySide6), so you can
    replace them with your own build of the same version.
- openpyxl {xl} — MIT License. https://foss.heptapod.net/openpyxl/openpyxl
- et-xmlfile {et} — MIT License (with parts under the Python license). https://foss.heptapod.net/openpyxl/et_xmlfile
- PyInstaller {pi} bootloader — GNU GPL v2 or later with the PyInstaller bootloader exception, which allows
  distributing programs built with it under any license. https://pyinstaller.org/
"""

text = head
text += section("DiBeKho — MIT License", (ROOT / "LICENSE").read_text(encoding="utf-8"))
text += section(f"Qt for Python (PySide6, Shiboken6) {qt} and Qt — GNU LGPL v3",
                (GNU / "LGPL-3.0.txt").read_text(encoding="utf-8"))
text += section("GNU GPL v3 (the LGPL v3 above is a set of additional permissions to it)",
                (GNU / "GPL-3.0.txt").read_text(encoding="utf-8"))
text += section(f"openpyxl {xl} — MIT License", dist_file("openpyxl", "LICENCE.rst"))
text += section(f"et-xmlfile {et} — MIT License", dist_file("et-xmlfile", "LICENCE.rst")
                + "\n\n" + dist_file("et-xmlfile", "LICENCE.python"))
text += section(f"Python {py} — license", (Path(sys.base_prefix) / "LICENSE.txt").read_text(encoding="utf-8"))
text += section(f"PyInstaller {pi} — license (see the bootloader exception)", dist_file("pyinstaller", "COPYING.txt"))

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(text, encoding="utf-8", newline="\n")
print(f"{OUT.relative_to(ROOT)}: {len(text.encode('utf-8')) // 1024} KB")
