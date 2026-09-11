"""Main window shell.

Holds the window chrome and the page stack. This step establishes the frame
only: navigation, the gallery and the command bar arrive in later steps, so the
window deliberately shows a neutral placeholder rather than pretending to have
content it cannot yet load.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from .theme import GROUP_GAP, PAGE_MARGIN
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
        self.worker.stopped.connect(self.main_window_worker_stopped)
        self.worker.failed.connect(self.main_window_worker_failed)

        self.pages = QStackedWidget()
        self.pages.setObjectName("ContentLayer")
        self.pages.addWidget(main_window_placeholder_page())
        self.setCentralWidget(self.pages)

        status_bar = QStatusBar()
        status_bar.setObjectName("ArchiveStatusBar")
        status_bar.showMessage(f"iPhone Archive {__version__} - no archive open")
        self.setStatusBar(status_bar)

    def main_window_show_status(self, message: str) -> None:
        """Show a message in the status bar.

        message: the text to display.
        Returns None.
        """
        status_bar = self.statusBar()
        if status_bar is not None:
            status_bar.showMessage(message)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Keep the window/event loop alive until worker-owned resources have been released."""
        if self.worker.service_thread.isRunning():
            event.ignore()
            self.close_pending = True
            self.main_window_show_status("Stopping archive work safely...")
            self.worker.worker_shutdown()
        else:
            self.worker.worker_shutdown()
            event.accept()

    @Slot()
    def main_window_worker_stopped(self) -> None:
        """Complete a deferred window close after the worker has been joined."""
        if self.close_pending:
            self.close_pending = False
            self.close()

    @Slot(object)
    def main_window_worker_failed(self, failure: WorkerFailure) -> None:
        """Surface worker errors in the shell; operation-specific views arrive in later steps."""
        self.main_window_show_status(f"{failure.operation} failed: {failure.message}")


def main_window_placeholder_page() -> QWidget:
    """Build the neutral page shown until real views exist.

    Returns a widget stating that no archive is open.
    """
    page = QWidget()
    page.setObjectName("PlaceholderPage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
    layout.setSpacing(GROUP_GAP)
    label = QLabel("No archive open.")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setObjectName("PlaceholderLabel")
    label.setProperty("role", "secondary")
    layout.addWidget(label)
    return page
