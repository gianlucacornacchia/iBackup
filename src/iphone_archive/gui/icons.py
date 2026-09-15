"""Line-art icons drawn in code.

The sketch uses Fluent-style icon rows, but shipping an icon font or a PNG set
would add a redistribution obligation and a packaging step for a handful of
16-pixel glyphs. Drawing them with QPainter keeps the executable self-contained
and lets every glyph take the caller's colour, so icons follow light, dark and
high-contrast themes without a second asset set.

Colours come from the caller (normally a palette role) rather than from the
theme module, so widgets stay usable when the palette is overridden.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

ICON_SIZE = 16
STROKE_WIDTH = 1.4
GLYPH_NAMES = frozenset(
    {
        "photos",
        "album",
        "unsorted",
        "phone",
        "recycle",
        "mark",
        "settings",
        "import",
        "verify",
        "scan",
        "broom",
        "more",
        "hamburger",
        "search",
        "folder",
        "close",
    }
)


def icons_draw(painter: QPainter, rect: QRect, glyph: str, color: QColor) -> None:
    """Draw one glyph inside a square area using the caller's colour.

    painter: an active painter, ideally with antialiasing enabled.
    rect: the square area to draw inside.
    glyph: a name from ``GLYPH_NAMES``.
    color: the stroke colour, normally a palette role.
    Returns None. Raises ``ValueError`` for an unknown glyph, because a silently
    blank icon is far harder to notice than a failing test.
    """
    if glyph not in GLYPH_NAMES:
        raise ValueError(f"Unknown icon glyph: {glyph}")
    pen = QPen(color, STROKE_WIDTH)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    box = rect.adjusted(3, 3, -3, -3)
    left, top, right, bottom = box.left(), box.top(), box.right(), box.bottom()
    middle_x, middle_y = box.center().x(), box.center().y()

    if glyph == "photos":
        painter.drawRoundedRect(box, 2, 2)
        painter.drawEllipse(QPoint(left + 4, top + 4), 1, 1)
        painter.drawPolyline(
            [QPoint(left, bottom - 3), QPoint(middle_x, middle_y), QPoint(right, bottom)]
        )
    elif glyph in {"album", "folder"}:
        painter.drawRoundedRect(QRect(left, top + 2, box.width() - 3, box.height() - 2), 2, 2)
        painter.drawLine(left + 3, top, right, top)
    elif glyph == "unsorted":
        painter.drawRoundedRect(box, 2, 2)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, "?")
    elif glyph == "phone":
        painter.drawRoundedRect(QRect(left + 2, top, box.width() - 4, box.height()), 2, 2)
        painter.drawLine(middle_x - 2, bottom - 2, middle_x + 2, bottom - 2)
    elif glyph == "recycle":
        painter.drawLine(left, top + 2, right, top + 2)
        painter.drawPolyline(
            [
                QPoint(left + 2, top + 2),
                QPoint(left + 3, bottom),
                QPoint(right - 3, bottom),
                QPoint(right - 2, top + 2),
            ]
        )
    elif glyph == "mark":
        painter.drawLine(middle_x, top, middle_x, bottom - 4)
        painter.drawEllipse(QPoint(middle_x, bottom - 1), 1, 1)
    elif glyph == "settings":
        painter.drawEllipse(box.center(), 3, 3)
        for offset in (-1, 1):
            painter.drawLine(middle_x + offset * 6, middle_y, middle_x + offset * 4, middle_y)
            painter.drawLine(middle_x, middle_y + offset * 6, middle_x, middle_y + offset * 4)
    elif glyph == "import":
        painter.drawLine(middle_x, top, middle_x, bottom - 3)
        painter.drawPolyline(
            [
                QPoint(middle_x - 3, bottom - 6),
                QPoint(middle_x, bottom - 3),
                QPoint(middle_x + 3, bottom - 6),
            ]
        )
        painter.drawLine(left, bottom, right, bottom)
    elif glyph == "verify":
        painter.drawPolyline(
            [QPoint(left, middle_y), QPoint(middle_x - 1, bottom - 2), QPoint(right, top)]
        )
    elif glyph == "scan":
        painter.drawEllipse(box.adjusted(1, 1, -3, -3))
        painter.drawLine(right - 3, bottom - 3, right, bottom)
    elif glyph == "broom":
        painter.drawLine(right - 1, top, middle_x - 1, middle_y)
        painter.drawPolygon(
            [
                QPoint(middle_x - 4, middle_y - 2),
                QPoint(middle_x + 3, middle_y + 4),
                QPoint(left, bottom),
            ]
        )
    elif glyph == "more":
        for offset in (-5, 0, 5):
            painter.drawEllipse(QPoint(middle_x + offset, middle_y), 1, 1)
    elif glyph == "hamburger":
        for offset in (-4, 0, 4):
            painter.drawLine(left, middle_y + offset, right, middle_y + offset)
    elif glyph == "search":
        painter.drawEllipse(QPoint(middle_x - 1, middle_y - 1), 4, 4)
        painter.drawLine(middle_x + 2, middle_y + 2, right, bottom)
    else:
        painter.drawLine(left, top, right, bottom)
        painter.drawLine(right, top, left, bottom)


def icons_pixmap(glyph: str, color: QColor, size: int = ICON_SIZE) -> QPixmap:
    """Render a glyph into a transparent pixmap.

    glyph: a name from ``GLYPH_NAMES``.
    color: the stroke colour.
    size: edge length in pixels.
    Returns the rendered pixmap. Raises ``ValueError`` for an unusable size.
    """
    if not isinstance(size, int) or isinstance(size, bool) or not 8 <= size <= 256:
        raise ValueError("Icon size must be an integer between 8 and 256")
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        icons_draw(painter, QRect(0, 0, size, size), glyph, color)
    finally:
        painter.end()
    return pixmap


def icons_get(glyph: str, color: QColor, size: int = ICON_SIZE) -> QIcon:
    """Build a themed icon for a glyph name.

    glyph: a name from ``GLYPH_NAMES``.
    color: the stroke colour, normally a palette role.
    size: edge length in pixels.
    Returns a QIcon holding the drawn pixmap.
    """
    return QIcon(icons_pixmap(glyph, color, size))
