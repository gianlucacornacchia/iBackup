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
from collections.abc import Callable, Collection
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal, Slot
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..browse import thumbnails
from ..browse.gallery import AssetView
from ..config import ArchivePaths
from ..core.trip import TRIP_MODES, TripSegment
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
# Console messages with this prefix are travel-mode edits: ``<leg>:<mode|none>``.
MODE_CHANGE_PREFIX = "ibackup-mode:"
# Console messages with this prefix ignore or re-include a point: ``<index>:<0|1>``.
IGNORE_CHANGE_PREFIX = "ibackup-ignore:"
POPUP_PHOTO_SIZE = 320
# How each travel mode is drawn: the leg's colour and dash pattern, plus a badge.
# Plane and boat legs are dashed because the straight line is not the route.
MODE_STYLES: dict[str, dict[str, str | None]] = {
    "car": {"label": "Car", "emoji": "\U0001f697", "color": "#d9822b", "dash": None},
    "plane": {"label": "Plane", "emoji": "\u2708\ufe0f", "color": "#7b4fd6", "dash": "8 8"},
    "foot": {"label": "On foot", "emoji": "\U0001f6b6", "color": "#2e9e4a", "dash": "2 6"},
    "bike": {"label": "Bike", "emoji": "\U0001f6b2", "color": "#1a9bb0", "dash": None},
    "tuktuk": {"label": "Tuk-tuk", "emoji": "\U0001f6fa", "color": "#c9a000", "dash": None},
    "bus": {"label": "Bus", "emoji": "\U0001f68c", "color": "#c83c3c", "dash": None},
    "taxi": {"label": "Taxi", "emoji": "\U0001f695", "color": "#8a6d00", "dash": "12 4"},
    "boat": {"label": "Boat", "emoji": "\u26f4\ufe0f", "color": "#1f6fd1", "dash": "10 5"},
}
assert tuple(MODE_STYLES) == TRIP_MODES, "every travel mode needs a map style"


@dataclass(frozen=True)
class MapPoint:
    """One plotted location, in capture order."""

    latitude: float
    longitude: float
    label: str
    captured_at: str | None = None
    note: str | None = None
    # How the user travelled from this point to the next one, when known.
    mode: str | None = None
    # The user chose to leave this photo out of the trip (greyed, not connected).
    ignored: bool = False


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


def mapview_points(
    assets: list[AssetView],
    segments: list[TripSegment] | None = None,
    ignored: Collection[int] | None = None,
) -> list[MapPoint]:
    """Extract plottable points from asset views, preserving their order.

    assets: ``AssetView`` rows, expected ordered oldest capture first.
    segments: stored travel modes; a mode applies only to the exact
        consecutive pair it was saved for.
    ignored: asset ids the user left out of this view's trip.
    Returns one ``MapPoint`` per asset that actually carries coordinates.
    """
    modes = {(item.from_asset_id, item.to_asset_id): item.mode for item in segments or []}
    skipped = set(ignored or ())
    located = mapview_located(assets)
    points: list[MapPoint] = []
    for index, asset in enumerate(located):
        assert asset.latitude is not None and asset.longitude is not None
        when = asset.captured_at[:16].replace("T", " ") if asset.captured_at else None
        following = located[index + 1].asset_id if index + 1 < len(located) else None
        points.append(
            MapPoint(
                asset.latitude,
                asset.longitude,
                asset.original_name,
                when,
                mapview_note(asset),
                modes.get((asset.asset_id, following)) if following is not None else None,
                asset.asset_id in skipped,
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
            "mode": point.mode,
            "ignored": point.ignored,
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
  .trip-mode {
    position: absolute; left: 14px; top: -14px; font-size: 16px; line-height: 1;
    background: #fff; border-radius: 9px; padding: 1px 2px; box-shadow: 0 1px 3px rgba(0,0,0,.4);
  }
  .trip-legs { font: 12px "Segoe UI", sans-serif; }
  .trip-mode-grid {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; margin-top: 6px;
  }
  .trip-mode-button {
    font: 12px "Segoe UI", sans-serif; padding: 4px 6px; border: 1px solid #ccc;
    border-radius: 4px; background: #fafafa; cursor: pointer; text-align: left;
  }
  .trip-mode-button:hover { background: #eef3fb; }
  .trip-mode-button.selected { border-color: #1f4f9c; background: #dde8f8; font-weight: 600; }
  .trip-popup { width: 320px; font: 12px "Segoe UI", sans-serif; }
  .trip-photo {
    min-height: 120px; display: flex; align-items: center; justify-content: center;
    background: #f0f0f0; color: #666; border-radius: 4px; overflow: hidden;
  }
  .trip-photo img { max-width: 320px; max-height: 320px; display: block; }
  .trip-name { font-weight: 600; margin-top: 6px; word-break: break-all; }
  .trip-meta, .trip-note { color: #666; margin-top: 2px; }
  .trip-ignore-button {
    font: 12px "Segoe UI", sans-serif; margin-top: 6px; padding: 4px 8px; border: 1px solid #ccc;
    border-radius: 4px; background: #fafafa; cursor: pointer;
  }
  .trip-ignore-button:hover { background: #eef3fb; }
"""

# The page script. Plain string (not an f-string) so the JavaScript braces stay
# readable. ``mapLoad(data)`` plots the points; ``__LOAD__`` is either a call
# with the points inlined or empty, when Python pushes them after the page has
# loaded (see ``WebMapWidget``), because ``setHtml()`` caps a page at 2 MB.
MAP_SCRIPT = """
  var map = L.map('map', {preferCanvas: true});
  L.tileLayer(__TILE_URL__, {maxZoom: 19, attribution: __ATTRIBUTION__}).addTo(map);
  L.control.scale({metric: true, imperial: true}).addTo(map);
  var points = [];
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
    var toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'trip-ignore-button';
    toggle.textContent = p.ignored ? 'Include this point' : 'Ignore this point';
    toggle.onclick = function () {
      mapSetIgnored(i, !points[i].ignored, true);
      map.closePopup();
    };
    box.appendChild(toggle);
    return box;
  }

  var markers = [];
  var segments = [];
  var pins = [];
  var current = null;
  var arrowLayer = L.layerGroup().addTo(map);
  var modes = __MODES__;
  var latlngs = [];
  var crs = L.CRS.EPSG3857;

  function mapLineStyle(mode) {
    var style = mode ? modes[mode] : null;
    if (!style) { return {color: '#5a8cdc', weight: 3, dashArray: null}; }
    return {color: style.color, weight: 4, dashArray: style.dash};
  }

  function mapArrowIcon(angle, mode) {
    var style = mode ? modes[mode] : null;
    var color = style ? style.color : '#1f4f9c';
    var badge = style ? '<span class="trip-mode">' + style.emoji + '</span>' : '';
    return L.divIcon({
      className: 'trip-arrow',
      iconSize: [16, 16],
      iconAnchor: [8, 8],
      html: badge + '<svg width="16" height="16" viewBox="0 0 16 16" style="transform: rotate(' +
        angle + 'deg)"><path d="M3 2 L14 8 L3 14 L6 8 Z" fill="' + color + '"/></svg>'
    });
  }

  // Applies a mode locally; ``report`` tells Python to save it. A leg can span
  // ignored photos, so the mode is saved for every consecutive pair it covers.
  function mapSetMode(leg, mode, report) {
    leg.mode = mode;
    leg.line.setStyle(mapLineStyle(mode));
    leg.marker.setIcon(mapArrowIcon(leg.angle, mode));
    leg.hit.setTooltipContent(mapLegTooltip(leg));
    for (var k = leg.fromIndex; k < leg.toIndex; k++) {
      points[k].mode = mode;
      if (report) { console.log(__MODE_PREFIX__ + k + ':' + (mode || 'none')); }
    }
  }

  function mapLegTooltip(leg) {
    var style = leg.mode ? modes[leg.mode] : null;
    return (style ? style.emoji + ' ' + style.label + ' \u00b7 ' : '') +
      'Click to set how you travelled';
  }

  function mapLegPopup(leg) {
    var box = document.createElement('div');
    box.className = 'trip-legs';
    var title = document.createElement('div');
    title.className = 'trip-name';
    title.textContent = 'How did you travel from photo ' + (leg.fromIndex + 1) + ' to ' +
      (leg.toIndex + 1) + '?';
    box.appendChild(title);
    var grid = document.createElement('div');
    grid.className = 'trip-mode-grid';
    Object.keys(modes).concat([null]).forEach(function (mode) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'trip-mode-button' + (mode === leg.mode ? ' selected' : '');
      button.dataset.mode = mode || 'none';
      button.textContent = mode ? modes[mode].emoji + ' ' + modes[mode].label : 'Clear';
      button.onclick = function () {
        mapSetMode(leg, mode, true);
        map.closePopup();
      };
      grid.appendChild(button);
    });
    box.appendChild(grid);
    return box;
  }

  function mapBindLeg(leg) {
    leg.hit.bindTooltip(mapLegTooltip(leg), {sticky: true});
    leg.hit.on('click', function (event) {
      L.popup({minWidth: 260}).setLatLng(event.latlng).setContent(mapLegPopup(leg)).openOn(map);
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

  // Ignored photos stay on the map, greyed, but are not part of the trip.
  function mapActive() {
    var active = [];
    points.forEach(function (p, i) { if (!p.ignored) { active.push(i); } });
    return active;
  }

  function mapMarkerStyle(i, first, last) {
    if (points[i].ignored) {
      return {radius: 5, color: '#777', weight: 1, fillColor: '#ccc', fillOpacity: 0.6,
              dashArray: '2 3'};
    }
    var isStart = i === first;
    var isEnd = i === last;
    return {
      radius: (isStart || isEnd) ? 8 : 5, color: '#28508f', weight: 1, dashArray: null,
      fillColor: isStart ? '#3cbe5a' : (isEnd ? '#dc4646' : '#3c78dc'), fillOpacity: 0.9
    };
  }

  // Draws the trip line, pins and marker colours from the photos not ignored.
  function mapRedraw() {
    segments.forEach(function (s) { map.removeLayer(s.line); map.removeLayer(s.hit); });
    segments.length = 0;
    pins.forEach(function (pin) { map.removeLayer(pin); });
    pins.length = 0;
    var active = mapActive();
    var first = active.length ? active[0] : -1;
    var last = active.length ? active[active.length - 1] : -1;
    for (var k = 1; k < active.length; k++) {
      var a = active[k - 1];
      var b = active[k];
      var pa = crs.latLngToPoint(latlngs[a], 0);
      var pb = crs.latLngToPoint(latlngs[b], 0);
      // An ignored photo between the two breaks the line: no leg bridges it.
      if (b - a > 1) { continue; }
      // Consecutive photos at the same spot have no leg to draw or tag.
      if (pa.distanceTo(pb) === 0) { continue; }
      // Web Mercator is conformal, so the on-screen angle is the same at every
      // zoom level and can be computed once.
      var angle = Math.atan2(pb.y - pa.y, pb.x - pa.x) * 180 / Math.PI;
      var mid = crs.pointToLatLng(pa.add(pb).divideBy(2), 0);
      var leg = {
        fromIndex: a, toIndex: b, from: latlngs[a], to: latlngs[b], angle: angle,
        mode: points[a].mode || null
      };
      leg.line = L.polyline([leg.from, leg.to], mapLineStyle(leg.mode)).addTo(map);
      leg.marker = L.marker(mid, {icon: mapArrowIcon(angle, leg.mode), interactive: false,
                                  keyboard: false});
      // A wide invisible twin makes a thin leg easy to click.
      leg.hit = L.polyline([leg.from, leg.to], {weight: 16, opacity: 0}).addTo(map);
      mapBindLeg(leg);
      segments.push(leg);
    }
    markers.forEach(function (marker, i) {
      marker.setStyle(mapMarkerStyle(i, first, last));
      marker.bringToFront();
    });
    if (active.length > 0) {
      pins.push(mapEndpoint(latlngs[first], active.length === 1 ? 'Start / End' : 'Start', 'start')
        .on('click', function () { markers[first].openPopup(); }));
    }
    if (active.length > 1) {
      pins.push(mapEndpoint(latlngs[last], 'End', 'end')
        .on('click', function () { markers[last].openPopup(); }));
    }
    mapUpdateArrows();
  }

  // Applies the choice locally; ``report`` tells Python to save it.
  function mapSetIgnored(i, ignored, report) {
    points[i].ignored = ignored;
    if (boxes[i]) {
      var toggle = boxes[i].querySelector('.trip-ignore-button');
      if (toggle) { toggle.textContent = ignored ? 'Include this point' : 'Ignore this point'; }
    }
    mapRedraw();
    if (report) { console.log(__IGNORE_PREFIX__ + i + ':' + (ignored ? 1 : 0)); }
  }

  function mapGoTo(i) {
    current = i;
    map.panTo(latlngs[i]);
    markers[i].openPopup();
  }

  // Moves to the next (step > 0) or previous point that is not ignored,
  // wrapping around at the ends. Called from the Previous/Next buttons.
  function mapStep(step) {
    var active = mapActive();
    if (active.length === 0) { return; }
    var target;
    if (current === null) {
      target = step > 0 ? active[0] : active[active.length - 1];
    } else if (step > 0) {
      target = active.find(function (i) { return i > current; });
      if (target === undefined) { target = active[0]; }
    } else {
      for (var k = active.length - 1; k >= 0; k--) {
        if (active[k] < current) { target = active[k]; break; }
      }
      if (target === undefined) { target = active[active.length - 1]; }
    }
    mapGoTo(target);
  }

  // Plots the trip once; called inline or from Python with the points array.
  function mapLoad(data) {
    points = data;
    latlngs = points.map(function (p) { return L.latLng(p.lat, p.lon); });
    if (points.length === 0) {
      map.setView([20, 0], 2);
      return;
    }
    points.forEach(function (p, i) {
      var marker = L.circleMarker(latlngs[i], {radius: 5}).addTo(map);
      marker.bindPopup(function () {
        if (!boxes[i]) { boxes[i] = mapPopup(p, i); }
        return boxes[i];
      }, {maxWidth: 340, minWidth: 320});
      marker.on('popupopen', function () {
        current = i;
        if (photos[i]) { mapRenderPhoto(i); } else { console.log(__PREFIX__ + i); }
      });
      markers.push(marker);
    });
    map.on('zoomend', mapUpdateArrows);
    map.fitBounds(L.latLngBounds(latlngs).pad(0.15));
    mapRedraw();
  }
  __LOAD__
"""


def mapview_build_html(points: list[MapPoint], inline_points: bool = True) -> str:
    """Build the full, self-contained HTML page for the trip map.

    points: the locations to plot, in capture order (oldest first).
    inline_points: when False the page plots nothing until the caller runs
        ``mapview_load_script(points)`` in it, which keeps a large trip under
        ``setHtml()``'s 2 MB page limit; ``points`` is then ignored here.
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
        .replace("__MODE_PREFIX__", json.dumps(MODE_CHANGE_PREFIX))
        .replace("__IGNORE_PREFIX__", json.dumps(IGNORE_CHANGE_PREFIX))
        .replace("__MODES__", json.dumps(MODE_STYLES))
        .replace("__LOAD__", mapview_load_script(points) if inline_points else "")
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


def mapview_load_script(points: list[MapPoint]) -> str:
    """Return the JavaScript statement that plots ``points`` on a loaded map page.

    points: the locations to plot, in capture order.
    Returns ``mapLoad([...]);`` with script-safe JSON, for inlining or for
    ``QWebEnginePage.runJavaScript`` (which has no page-size limit).
    """
    return f"mapLoad({mapview_points_json(points)});"


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


def mapview_parse_mode_change(message: str, count: int) -> tuple[int, str | None] | None:
    """Decode a travel-mode edit logged by the page.

    message: one JavaScript console message, ``ibackup-mode:<leg>:<mode|none>``.
    count: how many points the page plots (legs are ``0 .. count - 2``).
    Returns ``(leg, mode)`` with ``mode`` None for "clear", or None for any
    other message, an unknown mode or an out-of-range leg.
    """
    if not message.startswith(MODE_CHANGE_PREFIX):
        return None
    leg_text, _, mode_text = message[len(MODE_CHANGE_PREFIX) :].partition(":")
    if not leg_text.isdigit() or int(leg_text) >= count - 1:
        return None
    if mode_text == "none":
        return int(leg_text), None
    if mode_text not in TRIP_MODES:
        return None
    return int(leg_text), mode_text


def mapview_parse_ignore_change(message: str, count: int) -> tuple[int, bool] | None:
    """Decode an ignore/include edit logged by the page.

    message: one JavaScript console message, ``ibackup-ignore:<index>:<0|1>``.
    count: how many points the page plots.
    Returns ``(index, ignored)``, or None for any other message or an
    out-of-range index.
    """
    if not message.startswith(IGNORE_CHANGE_PREFIX):
        return None
    index_text, _, flag = message[len(IGNORE_CHANGE_PREFIX) :].partition(":")
    if not index_text.isdigit() or int(index_text) >= count or flag not in ("0", "1"):
        return None
    return int(index_text), flag == "1"


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
    mode_changed = Signal(str)
    ignore_changed = Signal(str)

    def javaScriptConsoleMessage(
        self,
        level: QWebEnginePage.JavaScriptConsoleMessageLevel,
        message: str,
        line_number: int,
        source_id: str,
    ) -> None:
        """Forward photo requests and map edits; ignore other messages."""
        if message.startswith(PHOTO_REQUEST_PREFIX):
            self.photo_requested.emit(message)
        elif message.startswith(MODE_CHANGE_PREFIX):
            self.mode_changed.emit(message)
        elif message.startswith(IGNORE_CHANGE_PREFIX):
            self.ignore_changed.emit(message)


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

    # A leg's travel mode was edited: (from_asset_id, to_asset_id, mode or None).
    mode_changed = Signal(int, int, object)
    # A point was ignored or included again: (asset_id, ignored).
    ignore_changed = Signal(int, bool)

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
        self.previous_button = QPushButton("\u25c0 Previous point", self)
        self.next_button = QPushButton("Next point \u25b6", self)
        self.previous_button.clicked.connect(lambda: self.mapview_step(-1))
        self.next_button.clicked.connect(lambda: self.mapview_step(1))
        header = QHBoxLayout()
        header.setSpacing(GROUP_GAP)
        header.addWidget(self.caption, 1)
        header.addWidget(self.previous_button)
        header.addWidget(self.next_button)
        self.ignored: set[int] = set()
        self.view = QWebEngineView(self)
        self.page = MapPage(mapview_tile_profile(), self.view)
        self.page.photo_requested.connect(self.mapview_photo_requested)
        self.page.mode_changed.connect(self.mapview_mode_message)
        self.page.ignore_changed.connect(self.mapview_ignore_message)
        self.view.setPage(self.page)
        # The points of the page being loaded; pushed once it has finished.
        self.pending_load: str | None = None
        self.view.loadFinished.connect(self.mapview_page_loaded)
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.view.setMinimumSize(320, 240)
        layout.addLayout(header)
        layout.addWidget(self.view, 1)
        self.bridge = MapPhotoBridge(self)
        self.bridge.finished.connect(self.mapview_photo_ready)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)

    def mapview_set_assets(
        self,
        assets: list[AssetView],
        segments: list[TripSegment] | None = None,
        ignored: Collection[int] | None = None,
    ) -> None:
        """Plot every located asset, oldest first, as the trip path.

        assets: ``AssetView`` rows, already ordered by capture time.
        segments: saved travel modes for the legs between them.
        ignored: asset ids the user left out of this view's trip.
        Returns None.
        """
        self.located = mapview_located(assets)
        self.requested.clear()
        self.ignored = {asset.asset_id for asset in self.located} & set(ignored or ())
        points = mapview_points(assets, segments, self.ignored)
        self.mapview_update_caption()
        # The page carries Leaflet and the script only; the points follow via
        # runJavaScript, so a large library never exceeds setHtml's 2 MB cap
        # (which would leave the map blank). The tile origin stays the base URL.
        self.pending_load = mapview_load_script(points)
        self.view.setHtml(
            mapview_build_html(points, inline_points=False),
            QUrl("https://tile.openstreetmap.org/"),
        )

    def mapview_page_loaded(self, ok: bool) -> None:
        """Plot the pending points once their page has loaded.

        ok: whether the page loaded; the points are pushed only on success.
        Returns None.
        """
        script, self.pending_load = self.pending_load, None
        if ok and script is not None:
            self.page.runJavaScript(script)

    def mapview_update_caption(self) -> None:
        """Describe the plotted trip and enable stepping when a point is left to visit."""
        total = len(self.located)
        active = total - len(self.ignored)
        skipped = f" ({len(self.ignored)} ignored)" if self.ignored else ""
        if not total:
            self.caption.setText("No photos in this view have location data.")
        elif total == 1:
            self.caption.setText(
                f"1 located photo{skipped} (no trip path to draw). Click it to see it."
            )
        else:
            self.caption.setText(
                f"{total} located photos{skipped}, plotted in capture order from Start to End. "
                "Click a point to see its photo, or a line to set how you travelled."
            )
        self.previous_button.setEnabled(active > 0)
        self.next_button.setEnabled(active > 0)

    @Slot(int)
    def mapview_step(self, step: int) -> None:
        """Move to the next (1) or previous (-1) point that is not ignored.

        step: 1 or -1. Returns None. The page pans to the point and opens its
        photo popup, wrapping around at either end.
        """
        self.page.runJavaScript(f"mapStep({1 if step > 0 else -1});")

    @Slot(str)
    def mapview_ignore_message(self, message: str) -> None:
        """Turn a page edit into ``ignore_changed`` with the photo's asset id.

        message: the page's ``ibackup-ignore:<index>:<0|1>`` console message.
        Returns None. Malformed or out-of-range edits are ignored.
        """
        change = mapview_parse_ignore_change(message, len(self.located))
        if change is None:
            return
        index, ignored = change
        asset_id = self.located[index].asset_id
        if ignored:
            self.ignored.add(asset_id)
        else:
            self.ignored.discard(asset_id)
        self.mapview_update_caption()
        self.ignore_changed.emit(asset_id, ignored)

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

    @Slot(str)
    def mapview_mode_message(self, message: str) -> None:
        """Turn a page edit into ``mode_changed`` with the leg's two asset ids.

        message: the page's ``ibackup-mode:<leg>:<mode|none>`` console message.
        Returns None. Malformed or out-of-range edits are ignored.
        """
        change = mapview_parse_mode_change(message, len(self.located))
        if change is None:
            return
        leg, mode = change
        self.mode_changed.emit(self.located[leg].asset_id, self.located[leg + 1].asset_id, mode)

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
        segments: list[TripSegment] | None = None,
        on_mode_changed: Callable[[int, int, str | None], None] | None = None,
        ignored: Collection[int] | None = None,
        on_point_ignored: Callable[[int, bool], None] | None = None,
    ) -> None:
        """Build the dialog and plot ``assets`` immediately.

        title: the dialog's window title (the library/album name).
        assets: the located assets to plot, already ordered by capture time.
        parent: optional parent widget.
        archive_root: the open archive popup pictures are rendered from.
        segments: saved travel modes for the legs between the assets.
        on_mode_changed: called with ``(from_asset_id, to_asset_id, mode)``
            whenever the user sets or clears a leg's travel mode, to save it.
        ignored: asset ids the user left out of this view's trip.
        on_point_ignored: called with ``(asset_id, ignored)`` whenever the
            user ignores or includes a point, to save it.
        """
        super().__init__(parent)
        self.setWindowTitle(f"Map — {title}")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self.setSizeGripEnabled(True)
        self.resize(900, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        layout.setSpacing(GROUP_GAP)
        self.widget = WebMapWidget(self, archive_root)
        if on_mode_changed is not None:
            self.widget.mode_changed.connect(on_mode_changed)
        if on_point_ignored is not None:
            self.widget.ignore_changed.connect(on_point_ignored)
        self.widget.mapview_set_assets(assets, segments, ignored)
        layout.addWidget(self.widget, 1)
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)
        self.finished.connect(lambda _result: self.widget.mapview_shutdown())
