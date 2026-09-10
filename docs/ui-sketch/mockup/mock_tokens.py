"""Windows 11 Fluent design tokens for the clickable mock.

MOCK ONLY. This is a throwaway artifact used to review the UI before any
application code is written; it is not imported by ``iphone_archive`` and is
not shipped. The token values mirror ui-sketch/README.md section 0.3 so the
mock shows the real intended colors, type ramp and metrics.
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette

# Exact WinUI tokens from the sketch, as (light, dark) pairs in #AARRGGBB or
# #RRGGBB form. Qt understands both once parsed through tokens_color.
TOKENS = {
    "SolidBackgroundFillColorBase": ("#F3F3F3", "#202020"),
    "SolidBackgroundFillColorSecondary": ("#EEEEEE", "#1C1C1C"),
    "LayerFillColorDefault": ("#80FFFFFF", "#4C3A3A3A"),
    "CardBackgroundFillColorDefault": ("#B3FFFFFF", "#0DFFFFFF"),
    "CardBackgroundFillColorSecondary": ("#80F6F6F6", "#0BFFFFFF"),
    "SubtleFillColorSecondary": ("#09000000", "#0FFFFFFF"),
    "SubtleFillColorTertiary": ("#06000000", "#0BFFFFFF"),
    "TextFillColorPrimary": ("#E4000000", "#FFFFFFFF"),
    "TextFillColorSecondary": ("#9E000000", "#C5FFFFFF"),
    "TextFillColorDisabled": ("#5C000000", "#5DFFFFFF"),
    "ControlStrokeColorDefault": ("#0F000000", "#12FFFFFF"),
    "DividerStrokeColorDefault": ("#0F000000", "#15FFFFFF"),
    "SystemFillColorCritical": ("#C42B1C", "#FF99A4"),
    # Fill for a destructive *button*, which needs white text on it in both
    # themes. The critical token above is tuned for text, not for a fill.
    "DestructiveFillColor": ("#C42B1C", "#B4291B"),
    "DestructiveFillColorHover": ("#B12719", "#C43325"),
    "SystemFillColorSuccess": ("#0F7B0F", "#6CCB5F"),
    "SystemFillColorCaution": ("#9D5D00", "#FCE100"),
}

# Type ramp: role -> (point size, weight). Semibold for emphasis, never Bold.
TYPE_RAMP = {
    "caption": (9, QFont.Weight.Normal),
    "body": (10, QFont.Weight.Normal),
    "body_strong": (10, QFont.Weight.DemiBold),
    "body_large": (13, QFont.Weight.Normal),
    "subtitle": (15, QFont.Weight.DemiBold),
    "title": (21, QFont.Weight.DemiBold),
}

# Metrics from section 0.3.
CONTROL_HEIGHT = 32
ROW_HEIGHT = 40
PAGE_MARGIN = 16
GROUP_GAP = 8
CONTROL_RADIUS = 4
OVERLAY_RADIUS = 8
RAIL_WIDTH = 40
NAV_WIDTH = 248
TILE_SIZE = 132
# Windows default accent ("blue"); the real app reads this from the system.
FALLBACK_ACCENT = "#0067C0"


def tokens_is_dark() -> bool:
    """Report whether the current system palette is dark.

    Returns True when the window background is darker than its text, which is
    how the mock follows the OS theme without a Windows-only API.
    """
    palette = QGuiApplication.palette()
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


def tokens_color(name: str, dark: bool | None = None) -> QColor:
    """Resolve a design token to a color for the active theme.

    name: a key of ``TOKENS``.
    dark: force a theme; None follows the system.
    Returns the QColor for that token, including its alpha channel.
    """
    if dark is None:
        dark = tokens_is_dark()
    light_value, dark_value = TOKENS[name]
    value = dark_value if dark else light_value
    if len(value) == 9:
        # #AARRGGBB -> QColor wants the alpha supplied separately.
        alpha = int(value[1:3], 16)
        color = QColor(f"#{value[3:]}")
        color.setAlpha(alpha)
        return color
    return QColor(value)


def tokens_css(name: str, dark: bool | None = None) -> str:
    """Return a token as a CSS ``rgba(...)`` string usable in QSS.

    name: a key of ``TOKENS``.
    dark: force a theme; None follows the system.
    Returns the color formatted for a stylesheet.
    """
    color = tokens_color(name, dark)
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alphaF():.3f})"


def tokens_accent() -> QColor:
    """Return the user's accent color.

    Uses the system highlight color, which on Windows is the accent the user
    picked, and falls back to the Windows default blue when unavailable.
    """
    accent = QGuiApplication.palette().color(QPalette.ColorRole.Highlight)
    if not accent.isValid():
        accent = QColor(FALLBACK_ACCENT)
    return accent


def tokens_font(role: str) -> QFont:
    """Build a font for a type-ramp role.

    role: a key of ``TYPE_RAMP``.
    Returns a QFont using Segoe UI Variable when present, else Segoe UI.
    """
    size, weight = TYPE_RAMP[role]
    font = QFont("Segoe UI Variable Text")
    font.setStyleHint(QFont.StyleHint.SansSerif)
    # Families are tried in order, so non-Windows hosts still render sensibly.
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Selawik", "Inter", "Sans Serif"])
    font.setPointSize(size)
    font.setWeight(weight)
    if sys.platform != "win32":
        # Windows uses ClearType subpixel antialiasing, which is correct there.
        # Off-Windows the same setting produces heavy color fringes on thin
        # strokes, so grayscale antialiasing is used for the mock and captures.
        font.setStyleStrategy(QFont.StyleStrategy.NoSubpixelAntialias)
    return font


def tokens_stylesheet() -> str:
    """Build the scoped QSS applied on top of the native Windows 11 style.

    Returns stylesheet text. Deliberately targets named surfaces and never uses
    a blanket ``QWidget`` rule, which would strip the native rendering that
    section 0.1 depends on.
    """
    dark = tokens_is_dark()
    accent = tokens_accent()
    accent_css = f"rgb({accent.red()}, {accent.green()}, {accent.blue()})"
    text = tokens_css("TextFillColorPrimary", dark)
    secondary = tokens_css("TextFillColorSecondary", dark)
    card = tokens_css("CardBackgroundFillColorDefault", dark)
    layer = tokens_css("LayerFillColorDefault", dark)
    stroke = tokens_css("ControlStrokeColorDefault", dark)
    divider = tokens_css("DividerStrokeColorDefault", dark)
    subtle = tokens_css("SubtleFillColorSecondary", dark)
    base = tokens_css("SolidBackgroundFillColorBase", dark)
    critical = tokens_css("SystemFillColorCritical", dark)
    return f"""
    #MockRoot {{ background: transparent; }}
    #NavPane {{ background: transparent; border: none; }}
    #ContentLayer {{
        background: {layer};
        border: 1px solid {stroke};
        border-top-left-radius: {OVERLAY_RADIUS}px;
        border-bottom-left-radius: 0px;
    }}
    #CommandBar, #Card {{
        background: {card};
        border: 1px solid {stroke};
        border-radius: {OVERLAY_RADIUS}px;
    }}
    #StatusBar {{
        background: transparent;
        border-top: 1px solid {divider};
        color: {secondary};
    }}
    QLabel {{ color: {text}; background: transparent; }}
    QLabel[role="secondary"] {{ color: {secondary}; }}
    QLabel[role="critical"] {{ color: {critical}; }}
    #SectionHeader {{ color: {secondary}; padding: 12px 12px 4px 12px; }}
    QPushButton#Command {{
        background: transparent;
        border: none;
        border-radius: {CONTROL_RADIUS}px;
        padding: 6px 12px;
        color: {text};
        text-align: left;
    }}
    QPushButton#Command:hover {{ background: {subtle}; }}
    QPushButton#Command:disabled {{ color: {tokens_css("TextFillColorDisabled", dark)}; }}
    QPushButton#Accent {{
        background: {accent_css};
        color: white;
        border: none;
        border-radius: {CONTROL_RADIUS}px;
        padding: 6px 16px;
        min-height: 20px;
    }}
    QPushButton#Accent:disabled {{
        background: {subtle};
        color: {tokens_css("TextFillColorDisabled", dark)};
    }}
    QPushButton#Destructive {{
        background: {tokens_css("DestructiveFillColor", dark)};
        color: white;
        border: none;
        border-radius: {CONTROL_RADIUS}px;
        padding: 6px 16px;
    }}
    QPushButton#Destructive:hover {{
        background: {tokens_css("DestructiveFillColorHover", dark)};
    }}
    QPushButton#Destructive:disabled {{
        background: {subtle};
        color: {tokens_css("TextFillColorDisabled", dark)};
    }}
    QPushButton#Standard {{
        background: {card};
        color: {text};
        border: 1px solid {stroke};
        border-radius: {CONTROL_RADIUS}px;
        padding: 6px 16px;
        min-height: 20px;
    }}
    QPushButton#Standard:hover {{ background: {subtle}; }}
    #NavList {{ background: transparent; border: none; outline: none; }}
    #NavList::item {{ color: {text}; border: none; background: transparent; }}
    #CategoryList {{ background: transparent; border: none; outline: none; }}
    #CategoryList::item {{
        color: {text};
        border-radius: {CONTROL_RADIUS}px;
        padding: 6px 10px;
        margin: 1px 0px;
    }}
    #CategoryList::item:hover {{ background: {subtle}; }}
    #CategoryList::item:selected {{
        background: {card};
        color: {text};
        border: 1px solid {stroke};
    }}
    #Dialog {{ background: {base}; border-radius: {OVERLAY_RADIUS}px; }}
    QLineEdit {{
        border-radius: {CONTROL_RADIUS}px;
        padding: 5px 8px;
        min-height: 20px;
    }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    {tokens_scrollbar_css(dark)}
    """


def tokens_scrollbar_css(dark: bool) -> str:
    """Return scrollbar QSS for non-Windows hosts only.

    dark: whether the dark theme is active.
    Returns stylesheet text. On Windows the native windows11 style already draws
    Fluent scrollbars, so styling them there would override real native
    rendering; this exists purely so the mock reviews cleanly off-Windows.
    """
    if sys.platform == "win32":
        return ""
    handle = "rgba(255,255,255,0.28)" if dark else "rgba(0,0,0,0.30)"
    handle_hover = "rgba(255,255,255,0.45)" if dark else "rgba(0,0,0,0.45)"
    return f"""
    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
    QScrollBar::handle:vertical {{
        background: {handle};
        border-radius: 3px;
        min-height: 28px;
        margin: 0px 4px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {handle_hover}; margin: 0px 3px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
    QScrollBar::handle:horizontal {{
        background: {handle};
        border-radius: 3px;
        min-width: 28px;
        margin: 4px 0px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
    """
