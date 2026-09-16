"""Generate the Windows application icon from the GUI's own line-art glyphs.

The app draws every in-window icon in code (see ``iphone_archive.gui.icons``)
specifically to avoid bundling a third-party icon set and its redistribution
obligations (ADR-0011 item 4). The taskbar/`.exe` icon follows the same rule:
this script renders the existing "photos" glyph at several sizes and packs
them into ``packaging/icon.ico`` so the file's own icon matches what the app
shows internally, with no new asset or license to track.

Run once (or whenever the glyph changes) from the project venv:

    .venv\\Scripts\\python packaging\\make_icon.py

The output is committed, so building the executable does not itself need a Qt
platform plugin.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# icons_pixmap() needs a QApplication but never shows a window; offscreen
# keeps this runnable in CI/headless shells with no display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
GLYPH = "photos"
# Matches the accent used for the primary command in the WinUI light theme
# token set (see iphone_archive.gui.theme); kept literal here so this script
# has no import-order dependency on the running theme.
GLYPH_COLOR = "#0F6CBD"
OUTPUT_PATH = Path(__file__).resolve().parent / "icon.ico"


def make_icon(output_path: Path = OUTPUT_PATH, size: int = max(ICON_SIZES)) -> Path:
    """Render the app glyph and save it as a multi-resolution .ico.

    output_path: where to write the icon file.
    size: the source resolution rendered before downscaling into the .ico.
    Returns the output path. Raises whatever PySide6/Pillow raise on failure.
    """
    from PIL import Image
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    from iphone_archive.gui.icons import icons_pixmap

    application = QApplication.instance() or QApplication([sys.argv[0]])
    pixmap = icons_pixmap(GLYPH, QColor(GLYPH_COLOR), size)
    temp_png = output_path.with_suffix(".tmp.png")
    pixmap.save(str(temp_png), "PNG")
    try:
        image = Image.open(temp_png).convert("RGBA")
        image.save(output_path, format="ICO", sizes=[(s, s) for s in ICON_SIZES])
    finally:
        temp_png.unlink(missing_ok=True)
    del application
    return output_path


if __name__ == "__main__":
    path = make_icon()
    print(f"Wrote {path}")
