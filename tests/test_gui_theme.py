"""Offscreen coverage of tokens, settings integration and live appearance changes."""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPalette  # noqa: E402

from iphone_archive.gui import application, theme  # noqa: E402
from iphone_archive.gui.main_window import MainWindow  # noqa: E402
from iphone_archive.gui.win32_effects import WindowEffects, WindowsAppearance  # noqa: E402
from iphone_archive.settings import Settings, SettingsError, settings_save  # noqa: E402


@pytest.fixture
def themed_window(qapp, qtbot, monkeypatch):
    """Create an isolated controller with injectable OS state and restore global Qt state."""
    palette = QPalette(qapp.palette())
    font = QFont(qapp.font())
    appearance = {"value": WindowsAppearance(dark=False, accent=0xFFCC6633)}
    monkeypatch.setattr(theme, "win32_effects_appearance", lambda: appearance["value"])
    monkeypatch.setattr(theme, "win32_effects_apply", lambda *args, **kwargs: WindowEffects())
    window = MainWindow()
    controller = theme.ThemeController(qapp, window)
    yield window, controller, appearance
    controller.timer.stop()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    setter = getattr(qapp.styleHints(), "setColorScheme", None)
    if setter is not None:
        setter(Qt.ColorScheme.Unknown)
    qapp.setPalette(palette)
    qapp.setFont(font)


@pytest.mark.parametrize("name,values", theme.TOKENS.items())
@pytest.mark.parametrize("dark", [False, True])
def test_exact_tokens_include_alpha(name, values, dark):
    value = values[int(dark)]
    expected = int(value[1:], 16)
    if len(value) == 7:
        expected |= 0xFF000000
    assert theme.theme_color(name, dark).rgba() == expected


@pytest.mark.parametrize("role,token", theme.TYPE_RAMP.items())
def test_type_ramp_uses_logical_pixels_and_semibold(role, token):
    font = theme.theme_font(role)
    assert font.pixelSize() == token.size
    assert font.weight() == token.weight
    assert font.weight() <= QFont.Weight.DemiBold
    assert token.line_height > token.size
    assert font.families()[:2] == ["Segoe UI Variable Text", "Segoe UI"]


def test_alpha_uses_qt_integer_rgba_syntax():
    assert theme.theme_css(theme.theme_color("LayerFillColorDefault", False)) == (
        "rgba(255, 255, 255, 128)"
    )


@pytest.mark.parametrize(
    "preference,system_dark,expected",
    [
        ("system", True, True),
        ("system", False, False),
        ("light", True, False),
        ("dark", False, True),
    ],
)
def test_theme_resolution(preference, system_dark, expected):
    assert theme.theme_resolve_dark(preference, system_dark) is expected


def test_unknown_theme_is_rejected(themed_window):
    _, controller, _ = themed_window
    with pytest.raises(SettingsError, match="theme"):
        controller.theme_set_preference("midnight")
    assert controller.preference == "system"


def test_scoped_styles_leave_native_controls_alone():
    stylesheet = theme.theme_stylesheet(True)
    for selector in ("QWidget {", "QPushButton", "QLineEdit", "QScrollBar", "QCheckBox"):
        assert selector not in stylesheet
    assert "QMainWindow#ArchiveWindow" in stylesheet
    assert "rgba(32, 32, 32, 255)" in stylesheet


def test_live_system_switch_and_explicit_override(themed_window, qapp):
    window, controller, appearance = themed_window
    assert not controller.dark
    appearance["value"] = replace(appearance["value"], dark=True)
    controller.theme_refresh()
    assert controller.dark
    assert qapp.palette().color(QPalette.ColorRole.Window).name() == "#202020"
    assert "rgba(32, 32, 32, 255)" in window.styleSheet()
    controller.theme_set_preference("light")
    assert not controller.dark
    assert qapp.palette().color(QPalette.ColorRole.Window).name() == "#f3f3f3"
    controller.theme_set_preference("system")
    assert controller.dark


def test_native_accent_changes_do_not_read_back_our_theme(themed_window, qapp):
    _, controller, appearance = themed_window
    assert qapp.palette().color(QPalette.ColorRole.Highlight).name() == "#3366cc"
    appearance["value"] = replace(appearance["value"], accent=0xFF00FFFF)
    controller.theme_refresh()
    assert qapp.palette().color(QPalette.ColorRole.Highlight).name() == "#ffff00"
    assert qapp.palette().color(QPalette.ColorRole.HighlightedText).name() == "#000000"
    appearance["value"] = replace(appearance["value"], accent=None)
    native = QPalette(controller.native_palette)
    native.setColor(QPalette.ColorRole.Accent, QColor("#663399"))
    qapp.setPalette(native)
    assert qapp.palette().color(QPalette.ColorRole.Highlight).name() == "#663399"
    assert qapp.palette().color(QPalette.ColorRole.HighlightedText).name() == "#ffffff"


def test_high_contrast_removes_custom_colors_and_recovers(themed_window, qapp):
    window, controller, appearance = themed_window
    native = QPalette(controller.native_palette)
    native.setColor(QPalette.ColorRole.Window, QColor("#000000"))
    native.setColor(QPalette.ColorRole.WindowText, QColor("#ffff00"))
    appearance["value"] = replace(appearance["value"], high_contrast=True)
    qapp.setPalette(native)
    assert controller.high_contrast
    assert window.styleSheet() == ""
    assert qapp.palette().color(QPalette.ColorRole.WindowText) == QColor("#ffff00")
    appearance["value"] = replace(appearance["value"], high_contrast=False)
    controller.theme_refresh()
    assert not controller.high_contrast
    assert window.styleSheet()


def test_high_contrast_releases_explicit_native_scheme(themed_window):
    _, controller, appearance = themed_window
    controller.theme_set_preference("dark")
    assert controller.native_scheme_preference == "dark"
    appearance["value"] = replace(appearance["value"], high_contrast=True)
    controller.theme_refresh()
    assert controller.native_scheme_preference == "system"
    assert controller.preference == "dark"
    appearance["value"] = replace(appearance["value"], high_contrast=False)
    controller.theme_refresh()
    assert controller.native_scheme_preference == "dark"


def test_qt_67_without_native_scheme_setter_still_applies_palette(themed_window, monkeypatch, qapp):
    _, controller, _ = themed_window
    monkeypatch.setattr(qapp.styleHints(), "setColorScheme", None, raising=False)
    controller.theme_set_preference("dark")
    assert qapp.palette().color(QPalette.ColorRole.Window).name() == "#202020"
    controller.theme_set_preference("light")
    assert qapp.palette().color(QPalette.ColorRole.Window).name() == "#f3f3f3"


def test_mica_probe_falls_back_to_opaque_painting(themed_window, monkeypatch, qtbot):
    window, controller, appearance = themed_window
    controller.mica_probe = True
    appearance["value"] = replace(appearance["value"], transparency=True)
    monkeypatch.setattr(
        theme, "win32_effects_apply", lambda *args, **kwargs: WindowEffects(True, True, True)
    )
    controller.theme_set_preference("light")
    assert not window.autoFillBackground()
    assert "QMainWindow#ArchiveWindow { background: transparent;" in window.styleSheet()
    appearance["value"] = replace(appearance["value"], transparency=False)
    monkeypatch.setattr(theme, "win32_effects_apply", lambda *args, **kwargs: WindowEffects())
    controller.theme_refresh()
    assert "rgba(243, 243, 243, 255)" in window.styleSheet()
    assert not window.testAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
    window.show()
    qtbot.waitExposed(window)
    image = window.grab().toImage()
    assert image.pixelColor(1, 1).alpha() == 255


def test_refresh_does_not_repeat_dwm_calls_without_changes(themed_window, monkeypatch):
    _, controller, _ = themed_window
    calls = []
    monkeypatch.setattr(
        theme,
        "win32_effects_apply",
        lambda *args, **kwargs: calls.append(args) or WindowEffects(),
    )
    controller.theme_refresh()
    controller.theme_refresh()
    assert not calls
    controller.theme_set_preference("dark")
    assert len(calls) == 1


def test_native_color_scheme_signal_updates_system_mode(themed_window, monkeypatch, qapp):
    _, controller, appearance = themed_window
    appearance["value"] = replace(appearance["value"], dark=None)
    monkeypatch.setattr(qapp.styleHints(), "colorScheme", lambda: Qt.ColorScheme.Dark)
    qapp.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
    assert controller.dark


def test_bootstrap_uses_persisted_theme(qapp, qtbot, monkeypatch):
    settings_save(Settings(theme="dark"))
    created = []
    monkeypatch.setattr(application, "application_create", lambda: qapp)
    monkeypatch.setattr(qapp, "exec", lambda: 0)
    original = theme.ThemeController

    def create_controller(app, window, preference, **kwargs):
        controller = original(app, window, preference, **kwargs)
        created.append(controller)
        return controller

    palette = QPalette(qapp.palette())
    font = QFont(qapp.font())
    monkeypatch.setattr(theme, "ThemeController", create_controller)
    assert application.application_main([]) == 0
    assert created[0].preference == "dark"
    assert created[0].dark
    created[0].window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    setter = getattr(qapp.styleHints(), "setColorScheme", None)
    if setter is not None:
        setter(Qt.ColorScheme.Unknown)
    qapp.setPalette(palette)
    qapp.setFont(font)


def test_mica_probe_is_explicit_and_windows_only(monkeypatch, capsys):
    monkeypatch.setattr(application, "sys", SimpleNamespace(platform="linux", stderr=sys.stderr))
    assert application.application_main(["--mica-probe"]) == 1
    assert "Windows 11 22H2+" in capsys.readouterr().err


def test_windows_style_fallback_is_observable(qapp, monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(
        application,
        "sys",
        SimpleNamespace(platform="win32", getwindowsversion=lambda: SimpleNamespace(build=22621)),
    )

    def set_style(name):
        calls.append(name)
        return qapp.style() if name == "Fusion" else None

    monkeypatch.setattr(qapp, "setStyle", set_style)
    application.application_configure(qapp, "win32")
    assert calls == ["windows11", "windowsvista", "Fusion"]
    assert "windows11 unavailable" in caplog.text
    assert "windowsvista unavailable" in caplog.text
