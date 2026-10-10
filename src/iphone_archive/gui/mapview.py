"""A lightweight, offline trip map for one album/library view.

Plots every located photo in a view using a simple equirectangular projection
fitted to the bounding box of the points shown, and connects them in capture
order so the sequence traces the path taken between them ("trip steps"). This
deliberately never fetches map tiles from the internet or any other online
service: nothing else in the app makes a network call on the user's behalf,
and a map feature is not worth breaking that guarantee. To still read like a
map rather than floating dots, a latitude/longitude graticule, a compass
arrow, and a distance scale bar are drawn entirely from the plotted
coordinates themselves — no bundled geographic data, no network.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPaintEvent, QPen, QPolygonF
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
BACKGROUND_COLOR = QColor(235, 241, 247)
GRATICULE_COLOR = QColor(200, 213, 224)
GRATICULE_LABEL_COLOR = QColor(120, 135, 150)
COMPASS_COLOR = QColor(110, 125, 140)
SCALE_BAR_COLOR = QColor(80, 95, 110)
EARTH_RADIUS_KM = 6371.0
# "Nice" graticule spacings in degrees, from coarse to fine, so a grid line
# lands on a round number regardless of how tightly the photos cluster.
GRATICULE_STEPS = (
    10.0, 5.0, 2.0, 1.0, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01, 0.005, 0.002, 0.001,
)
# "Nice" scale-bar lengths in kilometres, from coarse to fine.
SCALE_BAR_STEPS_KM = (
    2000.0, 1000.0, 500.0, 200.0, 100.0, 50.0, 20.0, 10.0, 5.0, 2.0, 1.0,
    0.5, 0.2, 0.1, 0.05, 0.02, 0.01,
)


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


def mapview_graticule_step(span: float) -> float:
    """Pick a round degree spacing that draws a handful of grid lines across ``span``.

    span: the latitude or longitude range being displayed, in degrees.
    Returns the largest step from ``GRATICULE_STEPS`` that still produces at
    least two grid lines across the span, falling back to the smallest step
    for a very tight cluster of photos.
    """
    for step in GRATICULE_STEPS:
        if span / step >= 2:
            return step
    return GRATICULE_STEPS[-1]


def mapview_scale_bar_km(max_km: float) -> float:
    """Pick a round real-world distance that fits within ``max_km``.

    max_km: the largest distance the scale bar may span.
    Returns the largest step from ``SCALE_BAR_STEPS_KM`` that still fits, or
    the smallest step when even that does not fit (an unrealistically tiny
    view).
    """
    for step in SCALE_BAR_STEPS_KM:
        if step <= max_km:
            return step
    return SCALE_BAR_STEPS_KM[-1]


def mapview_haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance between two coordinates, in kilometres."""
    lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


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

    def mapview_bounds(self) -> tuple[float, float, float, float, float]:
        """Compute the plotted bounding box and its mean-latitude longitude scale.

        Returns ``(min_lat, max_lat, min_lon, max_lon, lon_scale)``. Degenerate
        single-point spans are widened slightly so a grid/scale can still be
        drawn around a lone photo instead of collapsing to a point.
        """
        lats = [point.latitude for point in self.points]
        lons = [point.longitude for point in self.points]
        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)
        if max_lat - min_lat < 1e-4:
            min_lat -= 0.0005
            max_lat += 0.0005
        if max_lon - min_lon < 1e-4:
            min_lon -= 0.0005
            max_lon += 0.0005
        mean_lat_rad = math.radians((min_lat + max_lat) / 2.0)
        lon_scale = max(math.cos(mean_lat_rad), 0.05)
        return min_lat, max_lat, min_lon, max_lon, lon_scale

    def mapview_project_point(self, rect: QRectF, latitude: float, longitude: float) -> QPointF:
        """Project one arbitrary coordinate into ``rect`` using the plotted bounding box.

        rect: the drawable area, already inset by the margin.
        latitude, longitude: the coordinate to project; need not be one of
            the plotted points, so graticule lines and scale-bar endpoints
            share the exact same projection as the photo markers.
        Returns the corresponding screen point.
        """
        min_lat, max_lat, min_lon, max_lon, lon_scale = self.mapview_bounds()
        lat_span = max(max_lat - min_lat, 1e-6)
        lon_span = max(max_lon - min_lon, 1e-6)
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
        x_ratio = (longitude - min_lon) / lon_span
        y_ratio = (latitude - min_lat) / lat_span
        return QPointF(
            x_offset + x_ratio * draw_width,
            # North is up: a higher latitude draws nearer the top.
            y_offset + (1.0 - y_ratio) * draw_height,
        )

    def mapview_draw_graticule(self, painter: QPainter, rect: QRectF) -> None:
        """Draw latitude/longitude grid lines and degree labels across ``rect``.

        painter: the active painter.
        rect: the drawable area, already inset by the margin.
        Returns None. Gives the canvas map-like visual structure without any
        bundled geographic data or network access.
        """
        min_lat, max_lat, min_lon, max_lon, _lon_scale = self.mapview_bounds()
        lat_step = mapview_graticule_step(max_lat - min_lat)
        lon_step = mapview_graticule_step(max_lon - min_lon)
        painter.setPen(QPen(GRATICULE_COLOR, 1, Qt.PenStyle.DashLine))
        font_metrics = QFontMetricsF(painter.font())

        lat_value = math.ceil(min_lat / lat_step) * lat_step
        while lat_value <= max_lat:
            start = self.mapview_project_point(rect, lat_value, min_lon)
            end = self.mapview_project_point(rect, lat_value, max_lon)
            painter.drawLine(start, end)
            painter.setPen(QPen(GRATICULE_LABEL_COLOR))
            painter.drawText(
                QPointF(rect.left(), start.y() - font_metrics.descent() - 1),
                f"{lat_value:.4f}°",
            )
            painter.setPen(QPen(GRATICULE_COLOR, 1, Qt.PenStyle.DashLine))
            lat_value += lat_step

        lon_value = math.ceil(min_lon / lon_step) * lon_step
        while lon_value <= max_lon:
            start = self.mapview_project_point(rect, min_lat, lon_value)
            end = self.mapview_project_point(rect, max_lat, lon_value)
            painter.drawLine(start, end)
            painter.setPen(QPen(GRATICULE_LABEL_COLOR))
            painter.drawText(
                QPointF(start.x() + 2, rect.bottom() + font_metrics.ascent()),
                f"{lon_value:.4f}°",
            )
            painter.setPen(QPen(GRATICULE_COLOR, 1, Qt.PenStyle.DashLine))
            lon_value += lon_step

    def mapview_draw_compass(self, painter: QPainter, rect: QRectF) -> None:
        """Draw a simple north-pointing compass arrow in the top-right corner."""
        size = 16.0
        x = rect.right() - size
        y = rect.top() + size
        arrow = QPolygonF(
            [
                QPointF(x, y - size),
                QPointF(x - size * 0.4, y + size * 0.5),
                QPointF(x, y + size * 0.2),
                QPointF(x + size * 0.4, y + size * 0.5),
            ]
        )
        painter.setPen(QPen(COMPASS_COLOR, 1))
        painter.setBrush(COMPASS_COLOR)
        painter.drawPolygon(arrow)
        painter.drawText(QPointF(x - 4, y - size - 4), "N")

    def mapview_draw_scale_bar(self, painter: QPainter, rect: QRectF) -> None:
        """Draw a distance scale bar in the bottom-left corner.

        painter: the active painter.
        rect: the drawable area, already inset by the margin.
        Returns None. The bar's real-world length is derived with the
        haversine formula from the same bounding box used to project every
        point, so it stays accurate at any zoom level of the fitted view.
        """
        min_lat, max_lat, min_lon, max_lon, _lon_scale = self.mapview_bounds()
        mean_lat = (min_lat + max_lat) / 2.0
        full_width_km = mapview_haversine_km(mean_lat, min_lon, mean_lat, max_lon)
        if full_width_km <= 0:
            return
        bar_km = mapview_scale_bar_km(full_width_km * 0.4)
        bar_lon_span = (max_lon - min_lon) * (bar_km / full_width_km)
        left_point = self.mapview_project_point(rect, min_lat, min_lon)
        right_point = self.mapview_project_point(rect, min_lat, min_lon + bar_lon_span)
        y = rect.bottom() - 6
        painter.setPen(QPen(SCALE_BAR_COLOR, 2))
        painter.drawLine(QPointF(left_point.x(), y), QPointF(right_point.x(), y))
        painter.drawLine(QPointF(left_point.x(), y - 4), QPointF(left_point.x(), y + 4))
        painter.drawLine(QPointF(right_point.x(), y - 4), QPointF(right_point.x(), y + 4))
        label = f"{bar_km:g} km" if bar_km >= 1 else f"{bar_km * 1000:g} m"
        painter.drawText(QPointF(left_point.x(), y - 8), label)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the map background, graticule, trip line and photo markers."""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), BACKGROUND_COLOR)
        rect = QRectF(self.rect()).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
        if self.points:
            self.mapview_draw_graticule(painter, rect)
            self.mapview_draw_compass(painter, rect)
            self.mapview_draw_scale_bar(painter, rect)
        screen_points = [
            self.mapview_project_point(rect, point.latitude, point.longitude)
            for point in self.points
        ]
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
