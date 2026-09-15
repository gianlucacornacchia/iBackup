"""Main window shell.

Holds the window chrome and the page stack. This step establishes the frame
only: navigation, the gallery and the command bar arrive in later steps, so the
window deliberately shows a neutral placeholder rather than pretending to have
content it cannot yet load.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QStatusBar, QWidget

from .. import __version__
from ..browse.thumbnails import DEFAULT_THUMBNAIL_SIZE
from ..settings import settings_load
from .models import ArchiveModels
from .previews import MAX_PREVIEW_SIZE, MIN_PREVIEW_SIZE, PreviewLoader
from .shell import ArchiveShell
from .viewer import VIEWER_PREVIEW_SIZE, ViewerDialog
from .worker import WorkerController, WorkerFailure

LOGGER = logging.getLogger(__name__)

WINDOW_TITLE = "iPhone Archive"
WINDOW_DEFAULT_SIZE = (1180, 760)
WINDOW_MINIMUM_SIZE = (900, 560)


class MainWindow(QMainWindow):
    """The application's only top-level window."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the window shell and its empty page stack.

        parent: optional parent widget, normally None.
        """
        super().__init__(parent)
        self.setObjectName("ArchiveWindow")
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*WINDOW_DEFAULT_SIZE)
        self.setMinimumSize(*WINDOW_MINIMUM_SIZE)
        self.worker = WorkerController(self)
        self.close_pending = False
        # An error must not be wiped by the next idle status line the shell emits.
        self.status_override: str | None = None
        self.worker.stopped.connect(self.main_window_worker_stopped)
        self.worker.failed.connect(self.main_window_worker_failed)
        self.models = ArchiveModels(self.worker, self)
        self.previews = PreviewLoader(self, size=main_window_preview_size())
        self.worker.result_ready.connect(self.main_window_sync_previews)
        self.worker.failed.connect(self.main_window_sync_previews)
        self.worker.cancelled.connect(self.main_window_sync_previews)
        self.worker.stopped.connect(self.main_window_sync_previews)

        # The viewer renders at a much larger bounding box than a tile. Sharing
        # the grid's loader would either evict every tile on each open or force
        # the viewer to enlarge a 256px thumbnail, so it gets its own bounded
        # cache instead.
        self.viewer_previews = PreviewLoader(self, size=VIEWER_PREVIEW_SIZE, cache_entries=8)
        self.viewer: ViewerDialog | None = None

        self.shell = ArchiveShell(self.worker, self.models, self.previews, self)
        self.shell.shell_status_changed.connect(self.main_window_show_state)
        self.shell.shell_command.connect(self.main_window_command)
        self.shell.shell_selection_action.connect(self.main_window_selection_action)
        self.shell.shell_open_asset.connect(self.main_window_open_viewer)
        # Connected after the shell so its housekeeping reads can be recognised.
        self.worker.result_ready.connect(self.main_window_clear_error)
        self.setCentralWidget(self.shell)

        status_bar = QStatusBar()
        status_bar.setObjectName("ArchiveStatusBar")
        status_bar.showMessage(f"iPhone Archive {__version__} - no archive open")
        self.setStatusBar(status_bar)
        self.shell.shell_apply_state()

    def main_window_show_status(self, message: str) -> None:
        """Show a message in the status bar, replacing any error currently held.

        message: the text to display.
        Returns None.
        """
        self.status_override = None
        status_bar = self.statusBar()
        if status_bar is not None:
            status_bar.showMessage(message)

    @Slot(str)
    def main_window_show_state(self, message: str) -> None:
        """Show the shell's idle status unless an error is still being reported.

        message: the shell's current state line.
        Returns None. Errors persist until the next successful reply or command,
        so a routine state refresh cannot silently hide a failure.
        """
        status_bar = self.statusBar()
        if status_bar is not None and self.status_override is None:
            status_bar.showMessage(message)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Keep the window/event loop alive until worker-owned resources have been released."""
        self.previews.previews_cancel_all()
        self.viewer_previews.previews_cancel_all()
        if self.viewer is not None:
            self.viewer.close()
            self.viewer = None
        if self.worker.service_thread.isRunning():
            event.ignore()
            self.close_pending = True
            self.main_window_show_status("Stopping archive work safely...")
            self.worker.worker_shutdown()
        else:
            self.worker.worker_shutdown()
            self.previews.previews_shutdown()
            self.viewer_previews.previews_shutdown()
            event.accept()

    @Slot()
    def main_window_worker_stopped(self) -> None:
        """Complete a deferred window close after the worker has been joined."""
        if self.close_pending:
            self.close_pending = False
            self.close()

    def main_window_sync_previews(self, reply: object = None) -> None:
        """Rebind previews when the open archive changes; identical hashes differ per archive."""
        self.previews.previews_set_archive(self.worker.archive_root)
        self.viewer_previews.previews_set_archive(self.worker.archive_root)

    @Slot(int)
    def main_window_open_viewer(self, row: int) -> None:
        """Open the single-asset viewer on a grid row.

        row: the asset model row that was activated.
        Returns None. Only one viewer exists at a time, so activating another
        tile re-targets the open dialog instead of stacking windows.
        """
        if not self.models.assets.index(row).isValid():
            self.main_window_show_status("That asset is no longer in this view.")
            return
        if self.viewer is not None and self.viewer.isVisible():
            self.viewer.viewer_show_row(row)
            self.viewer.raise_()
            return
        viewer = ViewerDialog(self.models.assets, self.viewer_previews, row, self)
        viewer.viewer_set_actions(self.main_window_viewer_actions())
        viewer.viewer_action.connect(self.main_window_viewer_action)
        viewer.finished.connect(self.main_window_viewer_closed)
        self.viewer = viewer
        viewer.show()

    def main_window_viewer_actions(self) -> tuple[str, ...]:
        """Return the per-asset actions the current view supports.

        Returns the action keys, without the gallery's own "open" verb.
        """
        actions = self.shell.shell_view_actions(self.shell.navigation.current_key) or ()
        return tuple(key for key in actions if key != "open")

    @Slot(int)
    def main_window_viewer_closed(self, result: int = 0) -> None:
        """Forget the viewer and stop rendering large previews for it.

        result: the dialog's result code, unused.
        Returns None. The dialog deletes itself on close, so the reference is
        dropped here to avoid touching a destroyed object.
        """
        self.viewer = None
        self.viewer_previews.previews_cancel_all()

    @Slot(str, int)
    def main_window_viewer_action(self, key: str, row: int) -> None:
        """Apply a viewer action to the asset on screen.

        key: the action key requested.
        row: the model row the viewer is showing.
        Returns None. The row is selected in the grid first so the action runs
        through exactly the same exact-copy selection path as a batch action.
        """
        grid = self.shell.gallery.grid
        index = self.models.assets.index(row)
        if not index.isValid():
            self.main_window_show_status("That asset is no longer in this view.")
            return
        grid.grid_clear_selection()
        grid.setCurrentIndex(index)
        self.shell.shell_gallery_action(key)

    @Slot(str, object)
    def main_window_selection_action(self, key: str, selection: object) -> None:
        """Acknowledge a selection action until its dialog exists.

        key: the action key requested.
        selection: the captured AssetSelection.
        Returns None. Steps 8-9 replace this with the real operations; the
        selection is already exact-copy scoped, so nothing is lost here.
        """
        count = len(getattr(selection, "asset_ids", ()))
        self.main_window_show_status(
            f"{key}: {count} selected - available once its dialog is implemented (step 8+)."
        )

    @Slot(object)
    def main_window_worker_failed(self, failure: WorkerFailure) -> None:
        """Surface worker errors in the shell; operation-specific views arrive in later steps."""
        message = f"{failure.operation} failed: {failure.message}"
        self.main_window_show_status(message)
        self.status_override = message

    @Slot(object)
    def main_window_clear_error(self, reply: object = None) -> None:
        """Stop holding an error once a user-initiated operation has succeeded.

        reply: the worker result being delivered.
        Returns None. A failed mutation makes the shell re-read its counters and
        the gallery fetch pages; those reads succeed, so treating them as
        success would wipe the very error that caused them. Only a read the user
        actually asked for clears the message.
        """
        request_id = getattr(reply, "request_id", None)
        if isinstance(request_id, int) and self.main_window_is_automatic(request_id):
            return
        self.status_override = None

    def main_window_is_automatic(self, request_id: int) -> bool:
        """Report whether a request was issued by the GUI itself rather than the user.

        request_id: the worker request being answered.
        Returns True for shell counter refreshes and model page reads.
        """
        return self.shell.shell_is_housekeeping(request_id) or self.models.models_is_page_request(
            request_id
        )

    @Slot(str)
    def main_window_command(self, key: str) -> None:
        """Acknowledge a command until its dialog exists, so no verb silently does nothing.

        key: the command-bar key that was activated.
        Returns None. Steps 8-10 replace this with the real operation dialogs.
        """
        self.main_window_show_status(f"{key}: available once its dialog is implemented (step 8+).")


def main_window_preview_size() -> int:
    """Read the persisted thumbnail size, falling back to the default.

    Returns a usable bounding-box size. A hand-edited settings file must never
    stop the window from opening, and ``settings_load`` validates as it reads,
    so the read itself is guarded rather than only its result.
    """
    try:
        size = settings_load().thumbnail_size
    except Exception as error:
        LOGGER.warning("using the default thumbnail size: %s", error)
        return DEFAULT_THUMBNAIL_SIZE
    if not isinstance(size, int) or isinstance(size, bool):
        return DEFAULT_THUMBNAIL_SIZE
    return size if MIN_PREVIEW_SIZE <= size <= MAX_PREVIEW_SIZE else DEFAULT_THUMBNAIL_SIZE
