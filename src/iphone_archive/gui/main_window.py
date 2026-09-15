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

        self.shell = ArchiveShell(self.worker, self.models, self)
        self.shell.shell_status_changed.connect(self.main_window_show_state)
        self.shell.shell_command.connect(self.main_window_command)
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
        if self.worker.service_thread.isRunning():
            event.ignore()
            self.close_pending = True
            self.main_window_show_status("Stopping archive work safely...")
            self.worker.worker_shutdown()
        else:
            self.worker.worker_shutdown()
            self.previews.previews_shutdown()
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
        Returns None. A failed mutation makes the shell re-read its counters,
        and those reads succeed; treating them as success would wipe the very
        error that caused them.
        """
        request_id = getattr(reply, "request_id", None)
        if isinstance(request_id, int) and self.shell.shell_is_housekeeping(request_id):
            return
        self.status_override = None

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
