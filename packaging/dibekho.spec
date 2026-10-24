# PyInstaller build for Windows and macOS (run on each OS; PyInstaller cannot cross-build).
#   uv run pyinstaller packaging/dibekho.spec --noconfirm
# Output: dist/DiBeKho/ (Windows, --onedir) or dist/DiBeKho.app (macOS).
# --onefile is NOT used: it unpacks to a temp folder on every start and can leave junk behind.

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src" / "dibekho"
sys.path.insert(0, str(ROOT / "src"))
from dibekho import __version__  # noqa: E402

datas = [
    (str(SRC / "db" / "migrations" / "*.sql"), "dibekho/db/migrations"),
    (str(SRC / "i18n" / "*.json"), "dibekho/i18n"),
    (str(SRC / "ui" / "icon.png"), "dibekho/ui"),
]

# Qt modules the app never uses; keeps the bundle small.
excludes = [
    "tkinter",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtNetwork", "PySide6.QtBluetooth",
    "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech",
]

icon_win = ROOT / "resources" / "dibekho.ico"
icon_mac = ROOT / "resources" / "dibekho.icns"

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    excludes=excludes,
    noarchive=False,
)
# Drop Qt libraries pulled in by plugins but never used (software OpenGL, QML/Quick, PDF).
_DROP = ("opengl32sw", "Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6VirtualKeyboard", "qtvirtualkeyboard", "qpdf",
         "QtQuick", "QtQml", "QtPdf")
a.binaries = [b for b in a.binaries if not any(x.lower() in b[0].lower() for x in _DROP)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DiBeKho",
    console=False,
    icon=str(icon_win) if sys.platform == "win32" and icon_win.exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="DiBeKho")

if sys.platform == "darwin":
    bundle_version = __version__.split(".dev")[0]  # macOS wants plain numbers: 0.1.0.dev0 -> 0.1.0
    app = BUNDLE(
        coll,
        name="DiBeKho.app",
        icon=str(icon_mac) if icon_mac.exists() else None,
        bundle_identifier="vn.dibekho.app",
        version=bundle_version,
        info_plist={
            "CFBundleDisplayName": "DiBeKho",
            "CFBundleShortVersionString": bundle_version,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "13.0",
            "NSDocumentsFolderUsageDescription": "DiBeKho lưu thư mục làm việc trong Documents.",
        },
    )
