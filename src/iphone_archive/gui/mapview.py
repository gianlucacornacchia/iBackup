"""A real, zoomable trip map for one album/library view.

Renders located photos on an interactive Leaflet.js map (OpenStreetMap tiles)
embedded in a ``QWebEngineView``, with full pan/zoom, a trip line connecting
the photos in capture order, and distinct start/end markers. This is the one
feature in the app that makes network calls on the user's behalf: it fetches
map tiles from the OpenStreetMap tile servers on demand, caching them to disk
(via a dedicated, named ``QWebEngineProfile``) so re-viewing the same area
later needs the network again only for tiles that were never seen before.
Leaflet itself (``webassets/leaflet/``) is vendored locally, so only the
tile imagery requires network access — the map UI and controls work the
same offline, just without imagery.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
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

WEBASSETS_DIR = Path(__file__).parent / "webassets" / "leaflet"
TILE_PROFILE_NAME = "ibackup-map-tiles"
TILE_CACHE_MAX_BYTES = 200 * 1024 * 1024  # 200MB of OpenStreetMap tiles.
TILE_URL_TEMPLATE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_ATTRIBUTION = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
)
USER_AGENT = "ibackup-photo-archive/1.0 (personal desktop app; non-commercial)"


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


@lru_cache(maxsize=1)
def mapview_leaflet_css() -> str:
    """Return the vendored Leaflet stylesheet (read once, then cached)."""
    return (WEBASSETS_DIR / "leaflet.css").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def mapview_leaflet_js() -> str:
    """Return the vendored Leaflet script (read once, then cached)."""
    return (WEBASSETS_DIR / "leaflet.js").read_text(encoding="utf-8")


def mapview_points_json(points: list[MapPoint]) -> str:
    """Serialize points to JSON safe for embedding inside an inline ``<script>``.

    points: the locations to plot, in capture order.
    Returns a JSON array of ``{lat, lon, label}`` objects with any
    ``</script>``-like substring escaped so it cannot break out of the
    surrounding script tag.
    """
    payload = [
        {"lat": point.latitude, "lon": point.longitude, "label": point.label} for point in points
    ]
    return json.dumps(payload).replace("</", "<\\/")


def mapview_build_html(points: list[MapPoint]) -> str:
    """Build the full, self-contained HTML page for the trip map.

    points: the locations to plot, in capture order (oldest first).
    Returns an HTML document with Leaflet inlined (no external file:// or
    http:// references except the OpenStreetMap tile requests themselves),
    showing a trip line and start/end-highlighted markers when there are
    any points, or a world view when there are none.
    """
    points_json = mapview_points_json(points)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body, #map {{ height: 100%; margin: 0; padding: 0; }}
{mapview_leaflet_css()}
</style>
<script>
{mapview_leaflet_js()}
</script>
</head>
<body>
<div id="map"></div>
<script>
  var map = L.map('map');
  L.tileLayer({json.dumps(TILE_URL_TEMPLATE)}, {{
      maxZoom: 19,
      attribution: {json.dumps(TILE_ATTRIBUTION)}
  }}).addTo(map);
  L.control.scale({{metric: true, imperial: true}}).addTo(map);
  var points = {points_json};
  if (points.length > 0) {{
    var latlngs = points.map(function (p) {{ return [p.lat, p.lon]; }});
    L.polyline(latlngs, {{color: '#5a8cdc', weight: 3}}).addTo(map);
    points.forEach(function (p, i) {{
      var isEndpoint = (i === 0) || (i === points.length - 1);
      var fill = (i === 0) ? '#3cbe5a' : (i === points.length - 1 ? '#dc4646' : '#3c78dc');
      L.circleMarker([p.lat, p.lon], {{
        radius: isEndpoint ? 8 : 5,
        color: '#28508f',
        weight: 1,
        fillColor: fill,
        fillOpacity: 0.9
      }}).addTo(map).bindPopup(p.label);
    }});
    map.fitBounds(L.latLngBounds(latlngs).pad(0.15));
  }} else {{
    map.setView([20, 0], 2);
  }}
</script>
</body>
</html>
"""


@lru_cache(maxsize=1)
def mapview_tile_profile() -> QWebEngineProfile:
    """Return the app-wide, persistent profile used for every trip map view.

    A single named profile (rather than the WebEngine default one) keeps the
    on-disk tile cache in its own, clearly labelled storage area, isolated
    from anything else Qt WebEngine might ever be used for, while persisting
    across runs so previously-viewed areas redraw without the network.
    """
    profile = QWebEngineProfile(TILE_PROFILE_NAME)
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
    profile.setHttpCacheMaximumSize(TILE_CACHE_MAX_BYTES)
    profile.setHttpUserAgent(USER_AGENT)
    return profile


class WebMapWidget(QWidget):
    """A caption plus an interactive, zoomable Leaflet map."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the caption label above the embedded map view."""
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GROUP_GAP)
        self.caption = QLabel("", self)
        self.caption.setFont(theme_font("caption"))
        self.caption.setProperty("role", "secondary")
        self.view = QWebEngineView(self)
        self.view.setPage(QWebEnginePage(mapview_tile_profile(), self.view))
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.view.setMinimumSize(320, 240)
        layout.addWidget(self.caption)
        layout.addWidget(self.view, 1)

    def mapview_set_assets(self, assets: list[AssetView]) -> None:
        """Plot every located asset, oldest first, as the trip path.

        assets: ``AssetView`` rows, already ordered by capture time.
        Returns None.
        """
        points = mapview_points(assets)
        if not points:
            self.caption.setText("No photos in this view have location data.")
        elif len(points) == 1:
            self.caption.setText("1 located photo (no trip path to draw).")
        else:
            self.caption.setText(f"{len(points)} located photos, plotted in capture order.")
        self.view.setHtml(mapview_build_html(points), QUrl("https://tile.openstreetmap.org/"))


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
        self.widget = WebMapWidget(self)
        self.widget.mapview_set_assets(assets)
        layout.addWidget(self.widget, 1)
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)
