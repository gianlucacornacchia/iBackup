"""Tests for the desktop interface shell.

Run headless: ``QT_QPA_PLATFORM=offscreen`` is forced below so the suite never
needs a display and behaves the same in CI as on a developer machine.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from iphone_archive.gui import application  # noqa: E402
from iphone_archive.gui.main_window import (  # noqa: E402
    WINDOW_MINIMUM_SIZE,
    WINDOW_TITLE,
    MainWindow,
)


def test_gui_package_does_not_import_qt():
    """Importing the gui package must not pull in Qt, so the CLI survives a broken install."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import iphone_archive.gui; import iphone_archive.gui.application; "
            "assert not any(name.startswith('PySide6') for name in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_style_is_native_on_windows_and_neutral_elsewhere():
    """Windows gets the native style; other platforms get a usable fallback."""
    assert application.application_style_name("win32") == application.WINDOWS_STYLE
    assert application.application_style_name("linux") == application.FALLBACK_STYLE
    assert application.application_style_name("darwin") == application.FALLBACK_STYLE
    assert application.application_style_name("win32", 19045) == application.WINDOWS_LEGACY_STYLE
    assert application.application_style_name("win32", 22000) == application.WINDOWS_STYLE


def test_create_reuses_the_running_application(qapp):
    """A second call must not build a second QApplication, which Qt forbids."""
    assert application.application_create() is qapp
    assert application.application_create() is qapp


def test_configure_sets_application_identity(qapp):
    """The window manager and taskbar need a stable application name."""
    application.application_configure(qapp, platform_name="linux")

    assert qapp.applicationName() == application.APPLICATION_NAME
    assert qapp.organizationName() == application.ORGANIZATION_NAME


def test_main_window_opens_with_title_and_placeholder(qtbot):
    """The shell opens with a titled window and an explicit empty state."""
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.windowTitle() == WINDOW_TITLE
    assert window.pages.count() == 1
    assert window.minimumSize().width() == WINDOW_MINIMUM_SIZE[0]
    assert window.minimumSize().height() == WINDOW_MINIMUM_SIZE[1]


def test_main_window_shows_no_archive_until_one_is_opened(qtbot):
    """The status bar must not imply an archive is loaded when none is."""
    window = MainWindow()
    qtbot.addWidget(window)

    assert "no archive open" in window.statusBar().currentMessage()


def test_main_window_status_message_can_be_replaced(qtbot):
    """Later steps report progress through the status bar."""
    window = MainWindow()
    qtbot.addWidget(window)

    window.main_window_show_status("Imported 12 assets")

    assert window.statusBar().currentMessage() == "Imported 12 assets"


def test_main_window_is_shown_without_error(qtbot):
    """Showing the window must not raise under the offscreen platform."""
    window = MainWindow()
    qtbot.addWidget(window)

    window.show()
    qtbot.waitExposed(window)

    assert window.isVisible()


def test_help_exits_without_starting_qt(capsys):
    """``--help`` must answer without constructing a QApplication."""
    exit_code = application.application_main(["--help"])

    assert exit_code == 0
    assert "ibackup-gui" in capsys.readouterr().out
