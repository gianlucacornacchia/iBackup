"""A real, zoomable trip map for one album/library view.

Renders located photos on an interactive Leaflet.js map (OpenStreetMap tiles)
embedded in a ``QWebEngineView``, with full pan/zoom, a trip line connecting
the photos in capture order with direction arrows, labelled Start/End pins,
and a photo popup on every point. This is the one
feature in the app that makes network calls on the user's behalf: it fetches
map tiles from the OpenStreetMap tile servers on demand, caching them to disk
(via a dedicated, named ``QWebEngineProfile``) so re-viewing the same area
later needs the network again only for tiles that were never seen before.
Leaflet itself (``webassets/leaflet/``) is vendored locally, so only the
tile imagery requires network access — the map UI and controls work the
same offline, just without imagery.

Photo popups never give the page file access. Clicking a point logs a
``ibackup-photo:<index>`` console message that ``MapPage`` intercepts; the
preview is rendered off the GUI thread from the archived copy (for an
offloaded photo that copy *is* the phone's low-resolution thumbnail) and
pushed back as a ``data:`` URI.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal, Slot
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

from ..browse import thumbnails
from ..browse.gallery import AssetView
from ..config import ArchivePaths
from ..device.afc_device import PREVIEW_NAME_MARKER
from .previews import previews_check_hash, previews_check_relative
from .theme import GROUP_GAP, PAGE_MARGIN, theme_font

LOGGER = logging.getLogger(__name__)
WEBASSETS_DIR = Path(__file__).parent / "webassets" / "leaflet"
TILE_PROFILE_NAME = "ibackup-map-tiles"
TILE_CACHE_MAX_BYTES = 200 * 1024 * 1024  # 200MB of OpenStreetMap tiles.
TILE_URL_TEMPLATE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_ATTRIBUTION = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
)
USER_AGENT = "ibackup-photo-archive/1.0 (personal desktop app; non-commercial)"
# Console messages with this prefix are photo requests from the page.
PHOTO_REQUEST_PREFIX = "ibackup-photo:"
POPUP_PHOTO_SIZE = 320


@dataclass(frozen=True)
class MapPoint:
    """One plotted location, in capture order."""

    latitude: float
    longitude: float
    label: str
    captured_at: str | None = None
    note: str | None = None


def mapview_note(asset: AssetView) -> str | None:
    """Describe what the popup picture is, when it is not the full photo.

    asset: the located asset.
    Returns a short caption for offloaded previews and videos, else None.
    """
    if PREVIEW_NAME_MARKER in asset.original_name:
        return "Low-resolution preview (original not on the phone)"
    if asset.media_type == "video":
        return "Video (poster frame)"
    return None


def mapview_located(assets: list[AssetView]) -> list[AssetView]:
    """Return the assets that carry coordinates, preserving their order."""
    return [asset for asset in assets if asset.latitude is not None and asset.longitude is not None]


def mapview_points(assets: list[AssetView]) -> list[MapPoint]:
    """Extract plottable points from asset views, preserving their order.

    assets: ``AssetView`` rows, expected ordered oldest capture first.
    Returns one ``MapPoint`` per asset that actually carries coordinates.
    """
    points: list[MapPoint] = []
    for asset in mapview_located(assets):
        assert asset.latitude is not None and asset.longitude is not None
        when = asset.captured_at[:16].replace("T", " ") if asset.captured_at else None
        points.append(
            MapPoint(
                asset.latitude, asset.longitude, asset.original_name, when, mapview_note(asset)
            )
        )
    return points


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
        {
            "lat": point.latitude,
            "lon": point.longitude,
            "label": point.label,
            "when": point.captured_at,
            "note": point.note,
        }
        for point in points
    ]
    return json.dumps(payload).replace("</", "<\\/")


MAP_CSS = """
  html, body, #map { height: 100%; margin: 0; padding: 0; }
  .trip-pin { background: transparent; border: none; }
  .trip-pin div {
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    border: 2px solid #fff; color: #fff; white-space: nowrap;
    font: 600 12px "Segoe UI", sans-serif; box-shadow: 0 1px 4px rgba(0,0,0,.45);
  }
  .trip-pin.start div { background: #2e9e4a; }
  .trip-pin.end div { background: #c83c3c; }
  .trip-arrow { background: transparent; border: none; pointer-events: none; }
  .trip-arrow svg { display: block; filter: drop-shadow(0 0 1px #fff); }
  .trip-popup { width: 320px; font: 12px "Segoe UI", sans-serif; }
  .trip-photo {
    min-height: 120px; display: flex; align-items: center; justify-content: center;
    background: #f0f0f0; color: #666; border-radius: 4px; overflow: hidden;
  }
  .trip-photo img { max-width: 320px; max-height: 320px; display: block; }
  .trip-name { font-weight: 600; margin-top: 6px; word-break: break-all; }
  .trip-meta, .trip-note { color: #666; margin-top: 2px; }
"""

# The page script. Plain string (not an f-string) so the JavaScript braces stay
# readable; the points array is spliced in where ``__POINTS__`` appears.
MAP_SCRIPT = """
  var map = L.map('map');
  L.tileLayer(__TILE_URL__, {maxZoom: 19, attribution: __ATTRIBUTION__}).addTo(map);
  L.control.scale({metric: true, imperial: true}).addTo(map);
  var points = __POINTS__;
  var photos = {};

  // Leaflet re-runs a popup content function on every update(), so each
  // popup's element is built once and kept, together with its picture.
  var boxes = {};
  function mapPhotoSlot(i) { return boxes[i] ? boxes[i].querySelector('.trip-photo') : null; }

  function mapRenderPhoto(i) {
    var slot = mapPhotoSlot(i);
    var entry = photos[i];
    if (!slot || !entry) { return; }
    slot.textContent = '';
    if (entry.uri) {
      var img = document.createElement('img');
      img.src = entry.uri;
      img.onload = function () { if (markers[i]) { markers[i].getPopup().update(); } };
      slot.appendChild(img);
    } else {
      slot.textContent = entry.message || 'No preview available';
    }
  }

  // Called from Python once a requested preview has been rendered.
  function mapShowPhoto(i, uri, message) {
    photos[i] = {uri: uri, message: message};
    mapRenderPhoto(i);
  }

  function mapPopup(p, i) {
    var box = document.createElement('div');
    box.className = 'trip-popup';
    var slot = document.createElement('div');
    slot.className = 'trip-photo';
    slot.id = 'trip-photo-' + i;
    slot.textContent = 'Loading preview\u2026';
    var name = document.createElement('div');
    name.className = 'trip-name';
    name.textContent = p.label;
    var meta = document.createElement('div');
    meta.className = 'trip-meta';
    meta.textContent = (p.when ? p.when + ' \u00b7 ' : '') + (i + 1) + ' of ' + points.length;
    box.appendChild(slot);
    box.appendChild(name);
    box.appendChild(meta);
    if (p.note) {
      var note = document.createElement('div');
      note.className = 'trip-note';
      note.textContent = p.note;
      box.appendChild(note);
    }
    return box;
  }

  var markers = [];
  var segments = [];
  var arrowLayer = L.layerGroup().addTo(map);

  function mapArrowIcon(angle) {
    return L.divIcon({
      className: 'trip-arrow',
      iconSize: [16, 16],
      iconAnchor: [8, 8],
      html: '<svg width="16" height="16" viewBox="0 0 16 16" style="transform: rotate(' +
        angle + 'deg)"><path d="M3 2 L14 8 L3 14 L6 8 Z" fill="#1f4f9c"/></svg>'
    });
  }

  // Only segments long enough on screen get an arrow, so a dense trip does not
  // turn into a smear of arrowheads; zooming in reveals the shorter ones.
  function mapUpdateArrows() {
    arrowLayer.clearLayers();
    segments.forEach(function (s) {
      var a = map.latLngToLayerPoint(s.from);
      var b = map.latLngToLayerPoint(s.to);
      if (a.distanceTo(b) >= 40) { arrowLayer.addLayer(s.marker); }
    });
  }

  function mapEndpoint(latlng, label, kind) {
    var width = 12 + label.length * 7;
    // Start sits above its point and End below it, so a round trip that ends
    // where it began still shows both labels.
    var anchor = kind === 'start' ? [width / 2, 30] : [width / 2, -10];
    return L.marker(latlng, {
      icon: L.divIcon({
        className: 'trip-pin ' + kind, iconSize: [width, 20], iconAnchor: anchor,
        html: '<div>' + label + '</div>'
      }),
      keyboard: false, zIndexOffset: 1000
    }).addTo(map);
  }

  if (points.length > 0) {
    var latlngs = points.map(function (p) { return L.latLng(p.lat, p.lon); });
    L.polyline(latlngs, {color: '#5a8cdc', weight: 3}).addTo(map);
    var crs = L.CRS.EPSG3857;
    for (var s = 1; s < latlngs.length; s++) {
      var pa = crs.latLngToPoint(latlngs[s - 1], 0);
      var pb = crs.latLngToPoint(latlngs[s], 0);
      if (pa.distanceTo(pb) === 0) { continue; }
      // Web Mercator is conformal, so the on-screen angle is the same at every
      // zoom level and can be computed once.
      var angle = Math.atan2(pb.y - pa.y, pb.x - pa.x) * 180 / Math.PI;
      var mid = crs.pointToLatLng(pa.add(pb).divideBy(2), 0);
      segments.push({
        from: latlngs[s - 1], to: latlngs[s],
        marker: L.marker(mid, {icon: mapArrowIcon(angle), interactive: false, keyboard: false})
      });
    }
    points.forEach(function (p, i) {
      var isStart = i === 0;
      var isEnd = i === points.length - 1;
      var fill = isStart ? '#3cbe5a' : (isEnd ? '#dc4646' : '#3c78dc');
      var marker = L.circleMarker(latlngs[i], {
        radius: (isStart || isEnd) ? 8 : 5,
        color: '#28508f', weight: 1, fillColor: fill, fillOpacity: 0.9
      }).addTo(map);
      marker.bindPopup(function () {
        if (!boxes[i]) { boxes[i] = mapPopup(p, i); }
        return boxes[i];
      }, {maxWidth: 340, minWidth: 320});
      marker.on('popupopen', function () {
        if (photos[i]) { mapRenderPhoto(i); } else { console.log(__PREFIX__ + i); }
      });
      markers.push(marker);
    });
    var startPin = mapEndpoint(latlngs[0], points.length === 1 ? 'Start / End' : 'Start', 'start');
    startPin.on('click', function () { markers[0].openPopup(); });
    if (points.length > 1) {
      var last = points.length - 1;
      mapEndpoint(latlngs[last], 'End', 'end').on('click', function () {
        markers[last].openPopup();
      });
    }
    map.on('zoomend', mapUpdateArrows);
    map.fitBounds(L.latLngBounds(latlngs).pad(0.15));
    mapUpdateArrows();
  } else {
    map.setView([20, 0], 2);
  }
"""


def mapview_build_html(points: list[MapPoint]) -> str:
    """Build the full, self-contained HTML page for the trip map.

    points: the locations to plot, in capture order (oldest first).
    Returns an HTML document with Leaflet inlined (no external file:// or
    http:// references except the OpenStreetMap tile requests themselves),
    showing a trip line with direction arrows, labelled Start/End pins and a
    photo popup per point when there are any points, or a world view when
    there are none.
    """
    script = (
        MAP_SCRIPT.replace("__TILE_URL__", json.dumps(TILE_URL_TEMPLATE))
        .replace("__ATTRIBUTION__", json.dumps(TILE_ATTRIBUTION).replace("</", "<\\/"))
        .replace("__PREFIX__", json.dumps(PHOTO_REQUEST_PREFIX))
        .replace("__POINTS__", mapview_points_json(points))
    )
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
{MAP_CSS}
{mapview_leaflet_css()}
</style>
<script>
{mapview_leaflet_js()}
</script>
</head>
<body>
<div id="map"></div>
<script>
{script}
</script>
</body>
</html>
"""


def mapview_parse_request(message: str, count: int) -> int | None:
    """Decode a photo request logged by the page.

    message: one JavaScript console message.
    count: how many points the page plots.
    Returns the requested point index, or None for any other message or an
    out-of-range index, so page content can never address another asset.
    """
    if not message.startswith(PHOTO_REQUEST_PREFIX):
        return None
    suffix = message[len(PHOTO_REQUEST_PREFIX) :]
    if not suffix.isdigit():
        return None
    index = int(suffix)
    return index if index < count else None


def mapview_render_photo(archive_root: Path, asset: AssetView, size: int) -> tuple[str | None, str]:
    """Render one popup picture from the archived copy, as a ``data:`` URI.

    archive_root: the open archive.
    asset: the located asset.
    size: the longest edge in pixels.
    Returns ``(uri, message)``; ``uri`` is None when no preview could be made.
    The archived copy of an offloaded photo is the phone's own thumbnail, so
    that thumbnail is what is shown; nothing is ever fetched from the phone.
    """
    if not asset.paths:
        return None, "No archived copy"
    sha256 = previews_check_hash(asset.sha256)
    relative = previews_check_relative(asset.paths[0])
    result = thumbnails.thumbnails_get(
        ArchivePaths(archive_root), sha256, archive_root / Path(relative), size
    )
    if result.path is None:
        return None, f"No preview available ({result.error or 'unknown error'})"
    encoded = base64.b64encode(result.path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}", ""


class MapPhotoBridge(QObject):
    """GUI-owned receiver; carries finished renders back to the GUI thread."""

    finished = Signal(int, object, str)


class MapPhotoTask(QRunnable):
    """Render one popup picture on the pool, from immutable inputs only."""

    def __init__(
        self, bridge: MapPhotoBridge, archive_root: Path, index: int, asset: AssetView
    ) -> None:
        """Capture the render inputs; no connection or widget crosses threads."""
        super().__init__()
        self.bridge = bridge
        self.archive_root = archive_root
        self.index = index
        self.asset = asset

    def run(self) -> None:
        """Render, then report exactly one outcome."""
        try:
            uri, message = mapview_render_photo(self.archive_root, self.asset, POPUP_PHOTO_SIZE)
        except Exception as error:  # a broken file must not kill the pool thread
            LOGGER.warning("map preview failed for %s: %s", self.asset.original_name, error)
            uri, message = None, "No preview available"
        try:
            self.bridge.finished.emit(self.index, uri, message)
        except RuntimeError:
            # The dialog was closed while rendering; nobody is waiting.
            pass


class MapPage(QWebEnginePage):
    """Web page that turns the map's photo-request console messages into a signal."""

    photo_requested = Signal(str)

    def javaScriptConsoleMessage(
        self,
        level: QWebEnginePage.JavaScriptConsoleMessageLevel,
        message: str,
        line_number: int,
        source_id: str,
    ) -> None:
        """Forward photo requests; ignore every other console message."""
        if message.startswith(PHOTO_REQUEST_PREFIX):
            self.photo_requested.emit(message)


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

    def __init__(self, parent: QWidget | None = None, archive_root: Path | None = None) -> None:
        """Build the caption label above the embedded map view.

        parent: optional parent widget.
        archive_root: the open archive popup pictures are rendered from, or
            None, in which case popups say no archive is open.
        """
        super().__init__(parent)
        self.archive_root = archive_root
        self.located: list[AssetView] = []
        self.requested: set[int] = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GROUP_GAP)
        self.caption = QLabel("", self)
        self.caption.setFont(theme_font("caption"))
        self.caption.setProperty("role", "secondary")
        self.view = QWebEngineView(self)
        self.page = MapPage(mapview_tile_profile(), self.view)
        self.page.photo_requested.connect(self.mapview_photo_requested)
        self.view.setPage(self.page)
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.view.setMinimumSize(320, 240)
        layout.addWidget(self.caption)
        layout.addWidget(self.view, 1)
        self.bridge = MapPhotoBridge(self)
        self.bridge.finished.connect(self.mapview_photo_ready)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)

    def mapview_set_assets(self, assets: list[AssetView]) -> None:
        """Plot every located asset, oldest first, as the trip path.

        assets: ``AssetView`` rows, already ordered by capture time.
        Returns None.
        """
        self.located = mapview_located(assets)
        self.requested.clear()
        points = mapview_points(assets)
        if not points:
            self.caption.setText("No photos in this view have location data.")
        elif len(points) == 1:
            self.caption.setText("1 located photo (no trip path to draw). Click it to see it.")
        else:
            self.caption.setText(
                f"{len(points)} located photos, plotted in capture order from Start to End. "
                "Click a point to see its photo."
            )
        self.view.setHtml(mapview_build_html(points), QUrl("https://tile.openstreetmap.org/"))

    @Slot(str)
    def mapview_photo_requested(self, message: str) -> None:
        """Render the clicked point's picture in the background.

        message: the page's ``ibackup-photo:<index>`` console message.
        Returns None. Each point is rendered at most once per plot; the page
        caches the answer for later clicks.
        """
        index = mapview_parse_request(message, len(self.located))
        if index is None or index in self.requested:
            return
        self.requested.add(index)
        if self.archive_root is None:
            self.mapview_photo_ready(index, None, "No archive open")
            return
        self.pool.start(MapPhotoTask(self.bridge, self.archive_root, index, self.located[index]))

    @Slot(int, object, str)
    def mapview_photo_ready(self, index: int, uri: object, message: str) -> None:
        """Push a rendered picture (or the reason there is none) into the page.

        index: the point index.
        uri: a ``data:`` URI, or None.
        message: the text shown when there is no picture.
        Returns None.
        """
        self.page.runJavaScript(
            f"mapShowPhoto({int(index)}, {json.dumps(uri)}, {json.dumps(message)});"
        )

    def mapview_shutdown(self, timeout_ms: int = 5000) -> None:
        """Wait for in-flight renders so none reports into a destroyed bridge."""
        self.pool.clear()
        self.pool.waitForDone(timeout_ms)


class MapDialog(QDialog):
    """A standalone window showing one view's trip map."""

    def __init__(
        self,
        title: str,
        assets: list[AssetView],
        parent: QWidget | None = None,
        archive_root: Path | None = None,
    ) -> None:
        """Build the dialog and plot ``assets`` immediately.

        title: the dialog's window title (the library/album name).
        assets: the located assets to plot, already ordered by capture time.
        parent: optional parent widget.
        archive_root: the open archive popup pictures are rendered from.
        """
        super().__init__(parent)
        self.setWindowTitle(f"Map — {title}")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(900, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        layout.setSpacing(GROUP_GAP)
        self.widget = WebMapWidget(self, archive_root)
        self.widget.mapview_set_assets(assets)
        layout.addWidget(self.widget, 1)
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)
        self.finished.connect(lambda _result: self.widget.mapview_shutdown())
