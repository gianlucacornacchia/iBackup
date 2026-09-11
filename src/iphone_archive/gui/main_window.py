"""Main window shell.

Holds the window chrome and the page stack. This step establishes the frame
only: navigation, the gallery and the command bar arrive in later steps, so the
window deliberately shows a neutral placeholder rather than pretending to have
content it cannot yet load.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .. import __version__

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
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*WINDOW_DEFAULT_SIZE)
        self.setMinimumSize(*WINDOW_MINIMUM_SIZE)

        self.pages = QStackedWidget()
        self.pages.addWidget(main_window_placeholder_page())
        self.setCentralWidget(self.pages)

        status_bar = QStatusBar()
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


def main_window_placeholder_page() -> QWidget:
    """Build the neutral page shown until real views exist.

    Returns a widget stating that no archive is open.
    """
    page = QWidget()
    layout = QVBoxLayout(page)
    label = QLabel("No archive open.")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setObjectName("PlaceholderLabel")
    layout.addWidget(label)
    return page
