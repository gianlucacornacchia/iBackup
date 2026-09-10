"""Render every mock screen to PNG for review.

MOCK ONLY. Produces the reference images in ``screens/`` so the UI can be
reviewed without running the app. Usage:

    python docs/ui-sketch/mockup/capture_screens.py [--dark]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPalette, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from mock_data import MockArchive  # noqa: E402
from mock_dialogs import ConfirmDialog, ProgressDialog, SettingsDialog, ViewerDialog  # noqa: E402
from mock_tokens import tokens_color, tokens_font, tokens_stylesheet  # noqa: E402
from mock_views import ReclaimWindow  # noqa: E402
from run_mock import MockMainWindow  # noqa: E402

OUTPUT_DIRECTORY = Path(__file__).resolve().parent / "screens"


def capture_screens_apply_theme(application: QApplication, dark: bool) -> None:
    """Force the Qt palette to light or dark so both themes can be captured.

    application: the running QApplication.
    dark: whether to install the dark palette.
    """
    palette = QPalette()
    if dark:
        palette.setColor(QPalette.ColorRole.Window, QColor("#202020"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#FFFFFF"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#2C2C2C"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#FFFFFF"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#2D2D2D"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#FFFFFF"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#0078D4"))
    else:
        palette.setColor(QPalette.ColorRole.Window, QColor("#F3F3F3"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#000000"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#000000"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#FDFDFD"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#000000"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#0067C0"))
    application.setPalette(palette)


def capture_screens_save(widget: QWidget, name: str) -> None:
    """Render a widget over the window base color and write it to ``screens/``.

    widget: the widget to capture.
    name: output file stem.
    Compositing over a solid base stands in for the Mica backdrop, which cannot
    be rendered on a non-Windows capture host. The widget is rendered directly
    onto the filled canvas rather than grabbed and pasted, so antialiased text
    blends against the real background instead of against transparency.
    """
    widget.setStyleSheet(tokens_stylesheet())
    widget.show()
    QApplication.processEvents()
    canvas = QPixmap(widget.size())
    canvas.fill(tokens_color("SolidBackgroundFillColorBase"))
    painter = QPainter(canvas)
    widget.render(painter, QPoint(0, 0))
    painter.end()
    OUTPUT_DIRECTORY.mkdir(exist_ok=True)
    canvas.save(str(OUTPUT_DIRECTORY / f"{name}.png"))
    widget.hide()


def capture_screens_run(dark: bool) -> None:
    """Capture every screen in one theme.

    dark: whether to render the dark theme.
    """
    application = QApplication.instance() or QApplication(sys.argv)
    capture_screens_apply_theme(application, dark)
    application.setFont(tokens_font("body"))
    suffix = "dark" if dark else "light"
    archive = MockArchive()

    window = MockMainWindow(archive)
    window.resize(1180, 760)
    capture_screens_save(window, f"01-main-window-{suffix}")

    window.gallery_page.grid.setCurrentRow(2)
    window.gallery_page.grid.item(3).setSelected(True)
    window.gallery_page.grid.item(4).setSelected(True)
    QApplication.processEvents()
    capture_screens_save(window, f"02-selection-{suffix}")

    window.navigation.navigation_pane_toggle()
    capture_screens_save(window, f"03-nav-collapsed-{suffix}")
    window.navigation.navigation_pane_toggle()

    window.navigation.navigation_pane_select("deleted-phone")
    window.deleted_page.grid.item(0).setSelected(True)
    window.deleted_page.grid.item(1).setSelected(True)
    QApplication.processEvents()
    capture_screens_save(window, f"04-deleted-on-phone-{suffix}")

    window.navigation.navigation_pane_select("marked")
    capture_screens_save(window, f"05-marks-{suffix}")
    window.navigation.navigation_pane_select("all")

    progress = ProgressDialog("Importing from iPhone", "Copying", 4006, window)
    for _ in range(40):
        progress.progress_dialog_tick()
    capture_screens_save(progress, f"06-import-progress-{suffix}")
    progress.timer.stop()

    reclaim = ReclaimWindow(archive, window)
    reclaim.resize(720, 520)
    capture_screens_save(reclaim, f"07-reclaim-{suffix}")

    confirm = ConfirmDialog(
        "Delete 12 photos from the archive?",
        "This is permanent and cannot be undone.",
        46_200_000,
        tip='"Move to Deleted folder" is reversible.',
        parent=window,
    )
    capture_screens_save(confirm, f"08-confirm-{suffix}")

    assets = archive.mock_archive_assets_for("all")
    viewer = ViewerDialog(archive, assets, 4, window)
    viewer.resize(760, 640)
    capture_screens_save(viewer, f"09-viewer-{suffix}")

    settings = SettingsDialog(window)
    settings.resize(660, 430)
    capture_screens_save(settings, f"10-settings-{suffix}")


if __name__ == "__main__":
    application = QApplication(sys.argv)
    capture_screens_run(dark="--dark" in sys.argv)
    if "--both" in sys.argv:
        capture_screens_run(dark=True)
    print(f"Wrote screens to {OUTPUT_DIRECTORY}")
