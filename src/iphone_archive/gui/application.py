"""Application bootstrap for the desktop interface.

Owns process-level Qt setup: the ``QApplication``, high-DPI behaviour, the
platform style and logging. Kept separate from the window so tests can build a
window against pytest-qt's own application without this module's side effects.

Qt is imported lazily inside the entry point so that ``ibackup-gui --help`` and
a missing or broken PySide6 install produce a readable message rather than an
import traceback.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import TYPE_CHECKING

from ..logging_setup import logging_setup_configure
from ..settings import settings_load
from .win32_effects import WINDOWS_11_BUILD

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

LOGGER = logging.getLogger(__name__)

APPLICATION_NAME = "iPhone Archive"
ORGANIZATION_NAME = "ibackup"
# The Windows 11 style only exists on Windows; Fusion is the closest neutral
# match elsewhere and keeps the development machine usable.
WINDOWS_STYLE = "windows11"
WINDOWS_LEGACY_STYLE = "windowsvista"
FALLBACK_STYLE = "Fusion"


def application_style_name(platform_name: str, windows_build: int | None = None) -> str:
    """Choose the Qt widget style for a platform.

    platform_name: the value of ``sys.platform``.
    windows_build: native Windows build when known; Windows 10 uses Vista style.
    Returns the style name to request from Qt.
    """
    if platform_name != "win32":
        return FALLBACK_STYLE
    return (
        WINDOWS_LEGACY_STYLE
        if windows_build is not None and windows_build < WINDOWS_11_BUILD
        else WINDOWS_STYLE
    )


def application_configure(application: QApplication, platform_name: str = sys.platform) -> None:
    """Apply process-wide identity and style to a Qt application.

    application: the QApplication to configure.
    platform_name: the platform deciding which widget style is requested.
    Returns None.
    """
    application.setApplicationName(APPLICATION_NAME)
    application.setOrganizationName(ORGANIZATION_NAME)
    application.setApplicationDisplayName(APPLICATION_NAME)
    windows_build: int | None = None
    if sys.platform == "win32":
        if platform_name == "win32":
            windows_build = sys.getwindowsversion().build
    style_name = application_style_name(platform_name, windows_build)
    if application.setStyle(style_name) is None:
        fallback = WINDOWS_LEGACY_STYLE if style_name == WINDOWS_STYLE else FALLBACK_STYLE
        LOGGER.warning("Qt style %s unavailable; trying %s", style_name, fallback)
        if application.setStyle(fallback) is None:
            LOGGER.warning("Qt style %s unavailable; using %s", fallback, FALLBACK_STYLE)
            application.setStyle(FALLBACK_STYLE)


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
    parser = argparse.ArgumentParser(prog="ibackup-gui", description="Open the desktop interface.")
    parser.add_argument(
        "--mica-probe",
        action="store_true",
        help="experiment with Mica client painting on Windows 11 22H2+ (unverified)",
    )
    try:
        options = parser.parse_args(arguments)
    except SystemExit as result:
        return int(result.code or 0)
    if options.mica_probe and sys.platform != "win32":
        print("The Mica probe requires Windows 11 22H2+.", file=sys.stderr)
        return 1

    settings = settings_load()
    logging_setup_configure(level=settings.log_level)

    try:
        application = application_create()
        from .main_window import MainWindow
        from .theme import ThemeController
    except ImportError as error:
        # A broken Qt install must not look like an application crash.
        print(f"Could not start the desktop interface: {error}", file=sys.stderr)
        print("Install the GUI dependencies with: pip install PySide6", file=sys.stderr)
        return 1

    window = MainWindow()
    if options.mica_probe:
        LOGGER.warning("Experimental Mica probe; native title bar/painting are unverified")
        from PySide6.QtCore import Qt

        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    theme_controller = ThemeController(
        application, window, settings.theme, mica_probe=options.mica_probe
    )
    window.show()
    theme_controller.theme_refresh()
    LOGGER.debug("desktop interface started")
    return int(application.exec())


if __name__ == "__main__":
    raise SystemExit(application_main())
