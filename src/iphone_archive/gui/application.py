"""Application bootstrap for the desktop interface.

Owns process-level Qt setup: the ``QApplication``, high-DPI behaviour, the
platform style and logging. Kept separate from the window so tests can build a
window against pytest-qt's own application without this module's side effects.

Qt is imported lazily inside the entry point so that ``ibackup-gui --help`` and
a missing or broken PySide6 install produce a readable message rather than an
import traceback.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from ..logging_setup import logging_setup_configure
from ..settings import settings_load

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

LOGGER = logging.getLogger(__name__)

APPLICATION_NAME = "iPhone Archive"
ORGANIZATION_NAME = "ibackup"
# The Windows 11 style only exists on Windows; Fusion is the closest neutral
# match elsewhere and keeps the development machine usable.
WINDOWS_STYLE = "windows11"
FALLBACK_STYLE = "Fusion"


def application_style_name(platform_name: str) -> str:
    """Choose the Qt widget style for a platform.

    platform_name: the value of ``sys.platform``.
    Returns the style name to request from Qt.
    """
    return WINDOWS_STYLE if platform_name == "win32" else FALLBACK_STYLE


def application_configure(
    application: QApplication, platform_name: str = sys.platform
) -> None:
    """Apply process-wide identity and style to a Qt application.

    application: the QApplication to configure.
    platform_name: the platform deciding which widget style is requested.
    Returns None.
    """
    application.setApplicationName(APPLICATION_NAME)
    application.setOrganizationName(ORGANIZATION_NAME)
    application.setApplicationDisplayName(APPLICATION_NAME)
    style_name = application_style_name(platform_name)
    # setStyle silently ignores an unknown style, so a Qt build without the
    # requested style degrades to the default rather than failing to start.
    application.setStyle(style_name)


def application_create() -> QApplication:
    """Return the running QApplication, creating it when absent.

    Returns the ``QApplication`` instance. Reusing an existing instance lets
    tests drive windows under pytest-qt's application.
    """
    from PySide6.QtWidgets import QApplication

    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    application = QApplication(sys.argv)
    application_configure(application)
    return application


def application_main(argv: list[str] | None = None) -> int:
    """Start the desktop interface.

    argv: command-line arguments, defaulting to ``sys.argv``.
    Returns the process exit code.
    """
    arguments = sys.argv[1:] if argv is None else argv
    if "--help" in arguments or "-h" in arguments:
        print("Usage: ibackup-gui\n\nOpens the iPhone Archive desktop interface.")
        return 0

    settings = settings_load()
    logging_setup_configure(level=settings.log_level)

    try:
        application = application_create()
        from .main_window import MainWindow
    except ImportError as error:
        # A broken Qt install must not look like an application crash.
        print(f"Could not start the desktop interface: {error}", file=sys.stderr)
        print("Install the GUI dependencies with: pip install PySide6", file=sys.stderr)
        return 1

    window = MainWindow()
    window.show()
    LOGGER.debug("desktop interface started")
    return int(application.exec())


if __name__ == "__main__":
    raise SystemExit(application_main())
