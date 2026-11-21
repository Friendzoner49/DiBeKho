"""Render packaging/dibekho-swift.svg into packaging/AppIcon.png (1024 px); scripts/make_app.sh turns that into the
.icns of the app with sips + iconutil on the Mac.

Run after changing the SVG (PySide6 of the Python app draws the SVG):
    uv --project K:/HeThongSonDiBe run python -X utf8 tools/make_icon.py
"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

PACKAGING = Path(__file__).resolve().parent.parent / "packaging"


def main() -> int:
    QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])
    image = QImage(1024, 1024, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(str(PACKAGING / "dibekho-swift.svg")).render(painter)
    painter.end()
    out = PACKAGING / "AppIcon.png"
    if not image.save(str(out)):
        print("could not write", out)
        return 1
    print("written:", out.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
