"""The rounded stylesheet must keep drop-down / spin-box arrows visible (they vanished once inputs got a border)."""

import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dibekho.ui.common import _rounded_qss  # noqa: E402


def test_arrow_images_exist_and_are_not_blank():
    QApplication.instance() or QApplication([])
    qss = _rounded_qss()
    paths = re.findall(r"image: url\(([^)]+\.png)\)", qss)
    names = sorted(Path(p).name.split("-")[0] for p in paths)
    assert names == ["down", "up"]  # one shared image per direction (combo, date and spin box arrows)
    for p in paths:
        img = QImage(str(Path(p)))
        assert not img.isNull() and (img.width(), img.height()) == (10, 6)
        assert any(img.pixelColor(x, y).alpha() > 0 for x in range(10) for y in range(6))
