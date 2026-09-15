"""WinUI tokens and scoped Qt styling, without replacing native control rendering."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, QTimer, Slot
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from ..settings import THEME_CHOICES, SettingsError
from .win32_effects import (
    WindowEffects,
    WindowsAppearance,
    win32_effects_appearance,
    win32_effects_apply,
)

TOKENS = {
    "SolidBackgroundFillColorBase": ("#F3F3F3", "#202020"),
    "LayerFillColorDefault": ("#80FFFFFF", "#4C3A3A3A"),
    "CardBackgroundFillColorDefault": ("#B3FFFFFF", "#0DFFFFFF"),
    "TextFillColorPrimary": ("#E4000000", "#FFFFFFFF"),
    "TextFillColorSecondary": ("#9E000000", "#C5FFFFFF"),
    "TextFillColorDisabled": ("#5C000000", "#5DFFFFFF"),
    "ControlStrokeColorDefault": ("#0F000000", "#12FFFFFF"),
    "DividerStrokeColorDefault": ("#0F000000", "#15FFFFFF"),
}


@dataclass(frozen=True)
class TypeRole:
    """Logical-pixel font size, recommended line height and native font weight."""

    size: int
    line_height: int
    weight: QFont.Weight = QFont.Weight.Normal


TYPE_RAMP = {
    "caption": TypeRole(12, 16),
    "body": TypeRole(14, 20),
    "body_strong": TypeRole(14, 20, QFont.Weight.DemiBold),
    "body_large": TypeRole(18, 24),
    "subtitle": TypeRole(20, 28, QFont.Weight.DemiBold),
    "title": TypeRole(28, 36, QFont.Weight.DemiBold),
}
CONTROL_HEIGHT = 32
ROW_HEIGHT = 40
PAGE_MARGIN = 16
GROUP_GAP = 8
CONTROL_GAP = 4
CONTROL_RADIUS = 4
OVERLAY_RADIUS = 8


def theme_color(name: str, dark: bool) -> QColor:
    """Return an exact WinUI token, preserving the #AARRGGBB alpha channel."""
    value = TOKENS[name][int(dark)]
    return QColor.fromRgba(int(value[1:], 16)) if len(value) == 9 else QColor(value)


def theme_css(color: QColor) -> str:
    """Serialize a QColor into Qt's integer-channel rgba() syntax."""
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"


def theme_font(role: str) -> QFont:
    """Return a type-ramp font using installed Segoe families, never bundled font files."""
    token = TYPE_RAMP[role]
    font = QFont()
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Sans Serif"])
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setPixelSize(token.size)
    font.setWeight(token.weight)
    return font


def theme_resolve_dark(preference: str, system_dark: bool) -> bool:
    """Resolve a validated light/dark/system preference against the native appearance."""
    if preference not in THEME_CHOICES:
        raise SettingsError(f"theme must be one of {THEME_CHOICES}")
    return system_dark if preference == "system" else preference == "dark"


def theme_accent(palette: QPalette, appearance: WindowsAppearance) -> QColor:
    """Read Windows' ABGR accent or Qt's native accent, without a hard-coded blue."""
    if appearance.accent is not None:
        value = appearance.accent
        return QColor(value & 255, (value >> 8) & 255, (value >> 16) & 255)
    return palette.color(QPalette.ColorRole.Accent)


def theme_palette(native: QPalette, dark: bool, accent: QColor) -> QPalette:
    """Build an explicit-theme palette with a contrasting selection foreground."""
    palette = QPalette(native)
    background = theme_color("SolidBackgroundFillColorBase", dark)
    foreground = theme_color("TextFillColorPrimary", dark)
    for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Button):
        palette.setColor(role, background)
    palette.setColor(QPalette.ColorRole.Base, QColor("#1C1C1C" if dark else "#FFFFFF"))
    palette.setColor(QPalette.ColorRole.AlternateBase, background)
    palette.setColor(QPalette.ColorRole.ToolTipBase, background)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.ToolTipText,
    ):
        palette.setColor(role, foreground)
        palette.setColor(
            QPalette.ColorGroup.Disabled, role, theme_color("TextFillColorDisabled", dark)
        )
    palette.setColor(
        QPalette.ColorRole.PlaceholderText, theme_color("TextFillColorSecondary", dark)
    )
    palette.setColor(QPalette.ColorRole.Highlight, accent)
    palette.setColor(QPalette.ColorRole.Accent, accent)
    channels = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in (accent.redF(), accent.greenF(), accent.blueF())
    ]
    luminance = sum(
        channel * weight for channel, weight in zip(channels, (0.2126, 0.7152, 0.0722), strict=True)
    )
    palette.setColor(
        QPalette.ColorRole.HighlightedText, QColor("#000000" if luminance > 0.179 else "#FFFFFF")
    )
    return palette


def theme_stylesheet(dark: bool, *, mica: bool = False) -> str:
    """Style only named application surfaces and opt-in labels, not native controls."""
    base = "transparent" if mica else theme_css(theme_color("SolidBackgroundFillColorBase", dark))
    layer = theme_css(theme_color("LayerFillColorDefault", dark))
    card = theme_css(theme_color("CardBackgroundFillColorDefault", dark))
    stroke = theme_css(theme_color("ControlStrokeColorDefault", dark))
    divider = theme_css(theme_color("DividerStrokeColorDefault", dark))
    secondary = theme_css(theme_color("TextFillColorSecondary", dark))
    disabled = theme_css(theme_color("TextFillColorDisabled", dark))
    return f"""
    QMainWindow#ArchiveWindow {{ background: {base}; }}
    QStackedWidget#ContentLayer {{ background: transparent; }}
    QWidget#ShellPage {{ background: transparent; }}
    QFrame#NavPane {{ background: transparent; border-right: 1px solid {divider}; }}
    QListWidget#NavList {{ background: transparent; outline: none; }}
    QPushButton#Command {{
        background: transparent; border: 1px solid transparent;
        border-radius: {CONTROL_RADIUS}px; padding: 4px 10px; text-align: left;
    }}
    QPushButton#Command:hover {{ background: {layer}; border-color: {stroke}; }}
    QPushButton#Command:disabled {{ color: {disabled}; }}
    QPushButton#Command::menu-indicator {{ width: 0px; }}
    QWidget#Card {{
        background: {card}; border: 1px solid {stroke}; border-radius: {CONTROL_RADIUS}px;
    }}
    QFrame#Overlay {{
        background: {card}; border: 1px solid {stroke}; border-radius: {OVERLAY_RADIUS}px;
    }}
    QListView#AssetGrid {{ background: transparent; border: none; outline: none; }}
    QDialog#ViewerDialog {{ background: {base}; }}
    QLabel#ViewerImage {{ background: {layer}; border-radius: {CONTROL_RADIUS}px; }}
    QStatusBar#ArchiveStatusBar {{
        background: transparent; border-top: 1px solid {divider}; color: {secondary};
    }}
    QLabel[role="secondary"] {{ color: {secondary}; background: transparent; }}
    QLabel[role="secondary"]:disabled {{ color: {disabled}; }}
    """


class ThemeController(QObject):
    """Own live theme updates on the GUI thread, tied to one window's lifetime."""

    def __init__(
        self,
        application: QApplication,
        window: QWidget,
        preference: str = "system",
        *,
        mica_probe: bool = False,
    ) -> None:
        """Bind application/window, settings preference and optional Windows probe mode."""
        super().__init__(window)
        self.application = application
        self.window = window
        self.preference = preference
        self.mica_probe = mica_probe
        self.native_palette = QPalette(application.palette())
        self.native_font = QFont(application.font())
        self.applying = False
        self.setting_native_scheme = False
        self.native_scheme_preference: str | None = None
        self.dark = False
        self.high_contrast = False
        self.effects = WindowEffects()
        self.previous_state: tuple[object, ...] | None = None
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.theme_refresh)
        application.styleHints().colorSchemeChanged.connect(self.theme_refresh)
        application.paletteChanged.connect(self.theme_native_palette_changed)
        self.theme_set_preference(preference)
        if sys.platform == "win32":
            # Qt 6.7 has no contrast/transparency notification API.
            self.timer.start()

    def theme_set_preference(self, preference: str) -> None:
        """Apply a validated preference immediately; persistence remains in settings."""
        theme_resolve_dark(preference, False)
        self.preference = preference
        self.previous_state = None
        self.theme_refresh()

    def theme_configure_native_scheme(self, preference: str) -> None:
        """Notify Qt 6.8+ controls, releasing any override for high-contrast themes."""
        if preference == self.native_scheme_preference:
            return
        self.setting_native_scheme = True
        try:
            setter = getattr(self.application.styleHints(), "setColorScheme", None)
            if setter is not None:
                setter(
                    {
                        "system": Qt.ColorScheme.Unknown,
                        "light": Qt.ColorScheme.Light,
                        "dark": Qt.ColorScheme.Dark,
                    }[preference]
                )
            self.native_scheme_preference = preference
        finally:
            self.setting_native_scheme = False

    @Slot(QPalette)
    def theme_native_palette_changed(self, palette: QPalette) -> None:
        """Capture external palette updates without mistaking our own palette for the OS."""
        if self.setting_native_scheme:
            self.native_palette = QPalette(palette)
        elif not self.applying:
            self.native_palette = QPalette(palette)
            self.previous_state = None
            self.theme_refresh()

    @Slot()
    def theme_refresh(self) -> None:
        """Reapply only when native preferences change; preserve high-contrast rendering."""
        if self.applying:
            return
        self.applying = True
        try:
            appearance = win32_effects_appearance()
            self.theme_configure_native_scheme(
                "system" if appearance.high_contrast else self.preference
            )
            scheme = self.application.styleHints().colorScheme()
            system_dark = appearance.dark
            if system_dark is None:
                system_dark = (
                    self.native_palette.color(QPalette.ColorRole.Window).lightness() < 128
                    if scheme == Qt.ColorScheme.Unknown
                    else scheme == Qt.ColorScheme.Dark
                )
            dark = theme_resolve_dark(self.preference, system_dark)
            state = (appearance, dark, self.preference, int(self.window.winId()))
            if state == self.previous_state:
                return
            self.dark = dark
            self.high_contrast = appearance.high_contrast
            self.effects = win32_effects_apply(
                int(self.window.winId()), dark, appearance, mica_probe=self.mica_probe
            )
            self.window.setAttribute(
                Qt.WidgetAttribute.WA_NoSystemBackground, self.effects.mica_requested
            )
            self.window.setAutoFillBackground(not self.effects.mica_requested)
            if self.high_contrast:
                self.window.setStyleSheet("")
                self.application.setPalette(self.native_palette)
                self.application.setFont(self.native_font)
            else:
                accent = theme_accent(self.native_palette, appearance)
                self.application.setPalette(theme_palette(self.native_palette, dark, accent))
                self.application.setFont(theme_font("body"))
                self.window.setStyleSheet(theme_stylesheet(dark, mica=self.effects.mica_requested))
            label = self.window.findChild(QLabel, "PlaceholderLabel")
            if label is not None:
                label.setFont(self.native_font if self.high_contrast else theme_font("body_large"))
            self.previous_state = state
        finally:
            self.applying = False
