"""Render resources/dibekho.svg into the app icons: dibekho.png, src/dibekho/ui/icon.png (window icon),
.ico (Windows) and .icns (macOS).

Run from the repo root after changing the SVG:  uv run python scripts/make_icons.py
"""

import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QImageWriter, QPainter
from PySide6.QtSvg import QSvgRenderer

RES = Path(__file__).resolve().parent.parent / "resources"


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(str(RES / "dibekho.svg")).render(painter)
    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    return bytes(buf.data())


def write_ico(path: Path, sizes=(16, 24, 32, 48, 64, 128, 256)) -> None:
    """Multi-size .ico with PNG entries (Qt's writer only stores one size)."""
    images = [png_bytes(render(s)) for s in sizes]
    header = b"\0\0\1\0" + len(sizes).to_bytes(2, "little")
    entries, offset = b"", 6 + 16 * len(sizes)
    for s, data in zip(sizes, images):
        dim = 0 if s >= 256 else s
        entries += bytes([dim, dim, 0, 0]) + (1).to_bytes(2, "little") + (32).to_bytes(2, "little")
        entries += len(data).to_bytes(4, "little") + offset.to_bytes(4, "little")
        offset += len(data)
    path.write_bytes(header + entries + b"".join(images))


def main() -> int:
    QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])
    render(256).save(str(RES / "dibekho.png"))
    render(256).save(str(RES.parent / "src" / "dibekho" / "ui" / "icon.png"))  # window icon, shipped with the app
    write_ico(RES / "dibekho.ico")
    writer = QImageWriter(str(RES / "dibekho.icns"), b"icns")
    if not writer.write(render(1024)):
        print("icns:", writer.errorString())
        return 1
    print("written:", ", ".join(p.name for p in sorted(RES.iterdir())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
