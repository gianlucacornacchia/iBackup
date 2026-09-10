"""Clickable UI mock for iPhone Archive — run this to review the interface.

MOCK ONLY. This is a throwaway review artifact, not application code:

* it imports nothing from ``iphone_archive`` and touches no archive or iPhone;
* every number and image is fake;
* buttons navigate and demonstrate behaviour, they do not perform operations.

Run it with:  python docs/ui-sketch/mockup/run_mock.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QAction, QGuiApplication  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from mock_data import MockArchive, mock_data_format_size  # noqa: E402
from mock_dialogs import (  # noqa: E402
    ConfirmDialog,
    ProgressDialog,
    SettingsDialog,
    ViewerDialog,
    dialogs_caption,
    dialogs_heading,
)
from mock_tokens import (  # noqa: E402
    GROUP_GAP,
    PAGE_MARGIN,
    tokens_color,
    tokens_font,
    tokens_is_dark,
    tokens_stylesheet,
)
from mock_views import DeletedOnPhoneView, MarksView, ReclaimWindow  # noqa: E402
from mock_widgets import CommandBar, NavigationPane, PhotoGrid, SelectionBar  # noqa: E402

VIEW_TITLES = {
    "all": "All photos",
    "unsorted": "Unsorted",
    "deleted-phone": "Deleted from phone",
    "recycled": "Recycle bin",
    "marked": "Marked",
}


def run_mock_apply_window_effects(window: QMainWindow) -> str:
    """Apply Mica, rounded corners and the dark caption on Windows 11.

    window: the top-level window to decorate.
    Returns a short description of what was applied, for the status bar. On
    non-Windows hosts nothing is applied and a solid background is used, which
    is exactly the documented fallback path.
    """
    if sys.platform != "win32":
        return "solid background (DWM effects are Windows-only)"

    import ctypes

    try:
        handle = int(window.winId())
        dwm = ctypes.windll.dwmapi
        applied = []
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        dark = ctypes.c_int(1 if tokens_is_dark() else 0)
        if dwm.DwmSetWindowAttribute(handle, 20, ctypes.byref(dark), ctypes.sizeof(dark)) == 0:
            applied.append("dark caption")
        # DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2
        corner = ctypes.c_int(2)
        if dwm.DwmSetWindowAttribute(handle, 33, ctypes.byref(corner), ctypes.sizeof(corner)) == 0:
            applied.append("rounded corners")
        # DWMWA_SYSTEMBACKDROP_TYPE = 38, DWMSBT_MAINWINDOW = 2 (Mica)
        backdrop = ctypes.c_int(2)
        if (
            dwm.DwmSetWindowAttribute(handle, 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop))
            == 0
        ):
            window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
            applied.append("Mica")
        return ", ".join(applied) if applied else "solid background (DWM calls refused)"
    except Exception as error:
        return f"solid background (DWM unavailable: {type(error).__name__})"


class GalleryPage(QWidget):
    """The default page: title header, thumbnail grid and selection bar."""

    def __init__(self, archive: MockArchive, window: MockMainWindow) -> None:
        """Build the gallery page.

        archive: the fake archive.
        window: the owning main window, used for dialogs and status updates.
        """
        super().__init__()
        self.archive = archive
        self.window_ref = window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GROUP_GAP)

        self.title_label = dialogs_heading("All photos", "title")
        layout.addWidget(self.title_label)
        self.subtitle_label = dialogs_caption("")
        layout.addWidget(self.subtitle_label)

        self.grid = PhotoGrid(archive)
        self.grid.selection_changed.connect(self.gallery_page_selection_changed)
        self.grid.asset_activated.connect(self.gallery_page_open_viewer)
        layout.addWidget(self.grid, 1)

        self.selection_bar = SelectionBar()
        self.selection_bar.selection_bar_add("Move to album...", self.gallery_page_move)
        self.selection_bar.selection_bar_add("Mark", self.gallery_page_mark)
        self.selection_bar.selection_bar_add("Delete...", self.gallery_page_delete, "Destructive")
        layout.addWidget(self.selection_bar)

    def gallery_page_show(self, view_key: str) -> None:
        """Display one navigation target.

        view_key: the key selected in the navigation pane.
        """
        assets = self.archive.mock_archive_assets_for(view_key)
        title = VIEW_TITLES.get(view_key, view_key.split(":", 1)[-1])
        self.title_label.setText(title)
        total = sum(asset.size for asset in assets)
        photos = sum(1 for asset in assets if asset.media_type == "image")
        videos = len(assets) - photos
        self.subtitle_label.setText(
            f"{photos} photos, {videos} videos - {mock_data_format_size(total)}"
        )
        self.grid.photo_grid_show(assets)
        self.selection_bar.selection_bar_update([])

    def gallery_page_selection_changed(self, assets: list) -> None:
        """Update the selection bar and status text.

        assets: the currently selected assets.
        """
        self.selection_bar.selection_bar_update(assets)

    def gallery_page_open_viewer(self, asset) -> None:
        """Open the single-photo viewer on a double-clicked tile.

        asset: the activated asset.
        """
        assets = [
            self.grid.item(index).data(Qt.ItemDataRole.UserRole + 1)
            for index in range(self.grid.count())
        ]
        ViewerDialog(self.archive, assets, assets.index(asset), self.window_ref).exec()

    def gallery_page_move(self) -> None:
        """Report a move of the selected assets to another album."""
        count = len(self.grid.photo_grid_selected_assets())
        self.window_ref.main_window_status(f"Moved {count} item(s) to another album")

    def gallery_page_mark(self) -> None:
        """Mark the selection for later deletion without deleting anything."""
        count = len(self.grid.photo_grid_selected_assets())
        self.window_ref.main_window_status(
            f"Marked {count} item(s) - nothing deleted; review them under Marked"
        )

    def gallery_page_delete(self) -> None:
        """Delete the selection permanently, behind the confirmation dialog."""
        assets = self.grid.photo_grid_selected_assets()
        dialog = ConfirmDialog(
            f"Delete {len(assets)} photos from the archive?",
            "This is permanent and cannot be undone.",
            sum(asset.size for asset in assets),
            tip='"Move to Deleted folder" is reversible.',
            parent=self.window_ref,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.window_ref.main_window_status(f"Permanently deleted {len(assets)} item(s)")


class MockMainWindow(QMainWindow):
    """Main window: navigation pane, command bar, page stack and status bar."""

    def __init__(self, archive: MockArchive) -> None:
        """Assemble the whole mock interface."""
        super().__init__()
        self.archive = archive
        self.phone_connected = True
        self.setWindowTitle("iPhone Archive")
        self.resize(1180, 760)

        root = QWidget()
        root.setObjectName("MockRoot")
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.navigation = NavigationPane(archive)
        self.navigation.view_selected.connect(self.main_window_navigate)
        self.navigation.settings_requested.connect(self.main_window_open_settings)
        root_layout.addWidget(self.navigation)

        content = QWidget()
        content.setObjectName("ContentLayer")
        root_layout.addWidget(content, 1)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, GROUP_GAP)
        content_layout.setSpacing(GROUP_GAP)

        self.command_bar = CommandBar()
        self.import_button = self.command_bar.command_bar_add(
            "Import", "import", self.main_window_import
        )
        self.verify_button = self.command_bar.command_bar_add(
            "Verify", "verify", self.main_window_verify
        )
        self.scan_button = self.command_bar.command_bar_add(
            "Scan phone", "scan", self.main_window_scan
        )
        self.reclaim_button = self.command_bar.command_bar_add(
            "Free up space", "broom", self.main_window_reclaim
        )
        self.overflow_button = self.command_bar.command_bar_add(
            "", "more", self.main_window_overflow, "More commands"
        )
        content_layout.addWidget(self.command_bar)

        self.pages = QStackedWidget()
        self.gallery_page = GalleryPage(archive, self)
        self.deleted_page = DeletedOnPhoneView(archive)
        self.deleted_page.action_taken.connect(self.main_window_status)
        self.marks_page = MarksView(archive)
        self.marks_page.action_taken.connect(self.main_window_status)
        for page in (self.gallery_page, self.deleted_page, self.marks_page):
            self.pages.addWidget(page)
        content_layout.addWidget(self.pages, 1)

        self.status_frame = QFrame()
        self.status_frame.setObjectName("StatusBar")
        status_layout = QHBoxLayout(self.status_frame)
        status_layout.setContentsMargins(PAGE_MARGIN, 6, PAGE_MARGIN, 6)
        self.status_label = QLabel()
        self.status_label.setFont(tokens_font("caption"))
        status_layout.addWidget(self.status_label)
        status_layout.addStretch(1)
        self.effects_label = QLabel()
        self.effects_label.setFont(tokens_font("caption"))
        self.effects_label.setProperty("role", "secondary")
        status_layout.addWidget(self.effects_label)
        self.setStatusBar(None)

        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        content_layout.addWidget(self.status_frame)

        self.main_window_navigate("all")
        self.main_window_refresh_status()

    def main_window_navigate(self, view_key: str) -> None:
        """Switch the content area to the selected navigation target.

        view_key: the key emitted by the navigation pane.
        """
        if view_key == "deleted-phone":
            self.pages.setCurrentWidget(self.deleted_page)
        elif view_key == "marked":
            self.pages.setCurrentWidget(self.marks_page)
        else:
            self.pages.setCurrentWidget(self.gallery_page)
            self.gallery_page.gallery_page_show(view_key)

    def main_window_status(self, message: str) -> None:
        """Show a transient message in the status bar.

        message: the text to display alongside the archive counters.
        """
        self.status_label.setText(message)

    def main_window_refresh_status(self) -> None:
        """Show the standing archive and phone counters."""
        total = sum(asset.size for asset in self.archive.assets.values())
        phone = (
            "iPhone connected" if self.phone_connected else "No iPhone connected"
        )
        self.status_label.setText(
            f"{phone} - {len(self.archive.assets)} assets - {len(self.archive.albums)} albums - "
            f"{len(self.archive.deleted_on_phone_ids)} gone from phone - "
            f"{mock_data_format_size(total)}"
        )

    def main_window_set_phone(self, connected: bool) -> None:
        """Toggle the simulated phone connection.

        connected: whether a phone should appear connected.
        """
        self.phone_connected = connected
        for button in (self.import_button, self.scan_button, self.reclaim_button):
            button.setEnabled(connected)
            button.setToolTip(
                "" if connected else "Connect an iPhone via USB, unlock it, and tap Trust"
            )
        self.main_window_refresh_status()

    def main_window_import(self) -> None:
        """Run the simulated import with progress."""
        dialog = ProgressDialog("Importing from iPhone", "Copying", 4006, self)
        dialog.hidden_to_status.connect(self.main_window_status)
        if dialog.exec() == QDialog.DialogCode.Rejected and dialog.cancelled:
            self.main_window_status("Import cancelled - the archive is consistent and resumable")

    def main_window_verify(self) -> None:
        """Run the simulated integrity verification with progress."""
        dialog = ProgressDialog("Verifying archive", "Hashing", 1284, self)
        dialog.hidden_to_status.connect(self.main_window_status)
        dialog.exec()

    def main_window_scan(self) -> None:
        """Simulate scanning the phone for deletions."""
        self.main_window_status(
            f"Scanned phone - {len(self.archive.deleted_on_phone_ids)} archived items "
            "are no longer on it"
        )

    def main_window_reclaim(self) -> None:
        """Open the reclaim window in dry-run state."""
        ReclaimWindow(self.archive, self).exec()

    def main_window_open_settings(self) -> None:
        """Open the settings dialog."""
        if SettingsDialog(self).exec() == QDialog.DialogCode.Accepted:
            self.main_window_status("Settings saved")

    def main_window_overflow(self) -> None:
        """Show the overflow menu that replaces the old menu bar."""
        menu = QMenu(self)
        menu.addAction(QAction("New archive...", menu))
        menu.addAction(QAction("Open archive...", menu))
        menu.addSeparator()
        menu.addAction(QAction("Storage report", menu))
        menu.addAction(QAction("Clear preview cache", menu))
        menu.addSeparator()
        phone_action = QAction(
            "Simulate: no iPhone connected" if self.phone_connected else "Simulate: iPhone connected",
            menu,
        )
        phone_action.triggered.connect(lambda: self.main_window_set_phone(not self.phone_connected))
        menu.addAction(phone_action)
        about_action = QAction("About this mock", menu)
        about_action.triggered.connect(self.main_window_about)
        menu.addAction(about_action)
        menu.exec(self.overflow_button.mapToGlobal(self.overflow_button.rect().bottomLeft()))

    def main_window_about(self) -> None:
        """Explain that this is a non-functional review mock."""
        QMessageBox.information(
            self,
            "About this mock",
            "This is a clickable UI mock for review only.\n\n"
            "No archive, catalog or iPhone is touched. All photos, counts and "
            "progress are fake. Buttons navigate and demonstrate behaviour; they "
            "do not perform real operations.",
        )


def run_mock_main() -> int:
    """Start the mock application.

    Returns the Qt exit code.
    """
    application = QApplication(sys.argv)
    # Qt 6.7+ selects the native windows11 style automatically on Windows 11;
    # naming it explicitly makes the intent visible and is a no-op elsewhere.
    if sys.platform == "win32":
        application.setStyle("windows11")
    application.setFont(tokens_font("body"))

    archive = MockArchive()
    window = MockMainWindow(archive)

    palette = window.palette()
    palette.setColor(
        window.backgroundRole(), tokens_color("SolidBackgroundFillColorBase")
    )
    window.setPalette(palette)
    window.setStyleSheet(tokens_stylesheet())
    window.show()

    effects = run_mock_apply_window_effects(window)
    window.effects_label.setText(
        f"MOCK - no real data - {'dark' if tokens_is_dark() else 'light'} theme - {effects}"
    )
    return application.exec()


if __name__ == "__main__":
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    sys.exit(run_mock_main())
