"""A lightweight, offline trip map for one album/library view.

Plots every located photo in a view using a simple equirectangular projection
fitted to the bounding box of the points shown, and connects them in capture
order so the sequence traces the path taken between them ("trip steps"). This
deliberately never fetches map tiles from the internet or any other online
service: nothing else in the app makes a network call on the user's behalf,
and a map feature is not worth breaking that guarantee.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..browse.gallery import AssetView
from .theme import GROUP_GAP, PAGE_MARGIN, theme_font

MARGIN = 28.0
POINT_RADIUS = 4.0
ENDPOINT_RADIUS = 6.0
LINE_COLOR = QColor(90, 140, 220)
POINT_COLOR = QColor(60, 120, 220)
POINT_BORDER = QColor(40, 80, 160)
START_COLOR = QColor(60, 190, 90)
END_COLOR = QColor(220, 70, 70)


@dataclass(frozen=True)
class MapPoint:
    """One plotted location."""

    latitude: float
    longitude: float
    label: str


def mapview_points(assets: list[AssetView]) -> list[MapPoint]:
    """Extract plottable points from asset views, preserving their order.

    assets: ``AssetView`` rows, expected ordered oldest capture first.
    Returns one ``MapPoint`` per asset that actually carries coordinates.
    """
    return [
        MapPoint(asset.latitude, asset.longitude, asset.original_name)
        for asset in assets
        if asset.latitude is not None and asset.longitude is not None
    ]


class TripMapCanvas(QWidget):
    """Custom-painted canvas: one marker per photo plus a chronological trip line."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create an empty canvas; points are supplied later via ``mapview_set_points``."""
        super().__init__(parent)
        self.points: list[MapPoint] = []
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def mapview_set_points(self, points: list[MapPoint]) -> None:
        """Replace the plotted points and repaint.

        points: the locations to plot, in capture order.
        Returns None.
        """
        self.points = points
        self.update()

    def mapview_project(self, rect: QRectF) -> list[QPointF]:
        """Fit every point's latitude/longitude into ``rect``, north-up.

        rect: the drawable area, already inset by the margin.
        Returns one screen point per plotted point, in the same order as
        ``self.points``.
        """
        if not self.points:
            return []
        lats = [point.latitude for point in self.points]
        lons = [point.longitude for point in self.points]
        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)
        lat_span = max(max_lat - min_lat, 1e-6)
        lon_span = max(max_lon - min_lon, 1e-6)
        # A degree of longitude covers less ground the further from the
        # equator, so it is scaled by the cosine of the mean latitude: without
        # this, a tight cluster of nearby photos would be stretched sideways.
        mean_lat_rad = math.radians((min_lat + max_lat) / 2.0)
        lon_scale = max(math.cos(mean_lat_rad), 0.05)
        aspect = (lon_span * lon_scale) / lat_span
        width, height = rect.width(), rect.height()
        available_aspect = (width / height) if height else aspect
        if aspect > available_aspect:
            draw_width = width
            draw_height = (width / aspect) if aspect else height
        else:
            draw_height = height
            draw_width = height * aspect
        x_offset = rect.left() + (width - draw_width) / 2.0
        y_offset = rect.top() + (height - draw_height) / 2.0
        screen_points = []
        for point in self.points:
            x_ratio = (point.longitude - min_lon) / lon_span
            y_ratio = (point.latitude - min_lat) / lat_span
            screen_points.append(
                QPointF(
                    x_offset + x_ratio * draw_width,
                    # North is up: a higher latitude draws nearer the top.
                    y_offset + (1.0 - y_ratio) * draw_height,
                )
            )
        return screen_points

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the chronological trip line and one marker per located photo."""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
        screen_points = self.mapview_project(rect)
        if screen_points:
            painter.setPen(QPen(LINE_COLOR, 2))
            for start, end in zip(screen_points, screen_points[1:], strict=False):
                painter.drawLine(start, end)
            painter.setPen(QPen(POINT_BORDER, 1))
            painter.setBrush(POINT_COLOR)
            for screen_point in screen_points:
                painter.drawEllipse(screen_point, POINT_RADIUS, POINT_RADIUS)
            # The trip's start and end are marked distinctly from the rest.
            painter.setBrush(START_COLOR)
            painter.drawEllipse(screen_points[0], ENDPOINT_RADIUS, ENDPOINT_RADIUS)
            if len(screen_points) > 1:
                painter.setBrush(END_COLOR)
                painter.drawEllipse(screen_points[-1], ENDPOINT_RADIUS, ENDPOINT_RADIUS)
        painter.end()


class TripMapWidget(QWidget):
    """A map canvas with a caption describing what is plotted."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the caption label above the drawing canvas."""
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GROUP_GAP)
        self.caption = QLabel("", self)
        self.caption.setFont(theme_font("caption"))
        self.caption.setProperty("role", "secondary")
        self.canvas = TripMapCanvas(self)
        layout.addWidget(self.caption)
        layout.addWidget(self.canvas, 1)

    def mapview_set_assets(self, assets: list[AssetView]) -> None:
        """Plot every located asset, oldest first, as the trip path.

        assets: ``AssetView`` rows, already ordered by capture time.
        Returns None.
        """
        points = mapview_points(assets)
        self.canvas.mapview_set_points(points)
        if not points:
            self.caption.setText("No photos in this view have location data.")
        elif len(points) == 1:
            self.caption.setText("1 located photo (no trip path to draw).")
        else:
            self.caption.setText(f"{len(points)} located photos, plotted in capture order.")


class MapDialog(QDialog):
    """A standalone window showing one view's trip map."""

    def __init__(self, title: str, assets: list[AssetView], parent: QWidget | None = None) -> None:
        """Build the dialog and plot ``assets`` immediately.

        title: the dialog's window title (the library/album name).
        assets: the located assets to plot, already ordered by capture time.
        parent: optional parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle(f"Map — {title}")
        self.resize(640, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        layout.setSpacing(GROUP_GAP)
        self.widget = TripMapWidget(self)
        self.widget.mapview_set_assets(assets)
        layout.addWidget(self.widget, 1)
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)
