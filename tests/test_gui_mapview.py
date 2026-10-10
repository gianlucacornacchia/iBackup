"""Tests for the interactive (Leaflet/OpenStreetMap-backed) trip map."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtWebEngineCore import QWebEngineProfile  # noqa: E402

from iphone_archive.browse.gallery import AssetView  # noqa: E402
from iphone_archive.gui.mapview import (  # noqa: E402
    MapDialog,
    MapPoint,
    WebMapWidget,
    mapview_build_html,
    mapview_points,
    mapview_tile_profile,
)


def make_asset_view(**overrides) -> AssetView:
    """Build a minimal AssetView for mapview tests."""
    values = {
        "asset_id": 1,
        "sha256": "a" * 64,
        "original_name": "IMG_0001.HEIC",
        "media_type": "image",
        "size": 1024,
        "captured_at": None,
        "present_on_phone": True,
        "archive_state": "active",
        "latitude": None,
        "longitude": None,
    }
    values.update(overrides)
    return AssetView(**values)


def test_mapview_points_filters_out_assets_without_coordinates():
    """Only assets carrying both latitude and longitude are plotted."""
    assets = [
        make_asset_view(original_name="A.JPG", latitude=45.0, longitude=7.0),
        make_asset_view(original_name="B.JPG"),
        make_asset_view(original_name="C.JPG", latitude=10.0, longitude=20.0),
    ]
    points = mapview_points(assets)
    assert points == [
        MapPoint(45.0, 7.0, "A.JPG"),
        MapPoint(10.0, 20.0, "C.JPG"),
    ]


def test_build_html_embeds_leaflet_and_points():
    """The generated page inlines Leaflet and every point, with a trip line."""
    points = [MapPoint(45.0, 7.0, "a.jpg"), MapPoint(45.1, 7.1, "b.jpg")]
    html = mapview_build_html(points)
    assert "L.map(" in html
    assert "L.tileLayer(" in html
    assert "tile.openstreetmap.org" in html
    assert "OpenStreetMap" in html
    assert "L.polyline(" in html
    assert "L.circleMarker(" in html
    assert '"lat": 45.0' in html
    assert '"label": "a.jpg"' in html
    assert "fitBounds" in html


def test_build_html_falls_back_to_world_view_with_no_points():
    """With nothing to plot, the map still opens, centred on the whole world."""
    html = mapview_build_html([])
    assert "points.length > 0" in html
    assert "map.setView([20, 0], 2)" in html
    assert "var points = []" in html


def test_build_html_escapes_closing_script_tags_in_labels():
    """A filename containing '</script>' cannot break out of the inline script."""
    points = [MapPoint(45.0, 7.0, "</script><script>alert(1)</script>.jpg")]
    html = mapview_build_html(points)
    assert "</script><script>alert(1)" not in html
    assert "<\\/script>" in html


def test_tile_profile_is_a_single_persistent_disk_cached_profile(qapp):
    """The same named, disk-cached profile is reused across every map view."""
    profile = mapview_tile_profile()
    assert profile is mapview_tile_profile()
    assert profile.httpCacheType() == QWebEngineProfile.HttpCacheType.DiskHttpCache
    assert profile.httpCacheMaximumSize() > 0
    assert "ibackup" in profile.httpUserAgent()


def test_web_map_widget_plots_assets_without_crashing(qapp, qtbot):
    """The widget builds, updates its caption, and loads HTML without raising."""
    widget = WebMapWidget()
    qtbot.addWidget(widget)

    widget.mapview_set_assets([])
    assert "No photos" in widget.caption.text()

    assets = [
        make_asset_view(original_name="A.JPG", latitude=45.0, longitude=7.0),
        make_asset_view(original_name="B.JPG", latitude=45.1, longitude=7.1),
    ]
    widget.mapview_set_assets(assets)
    assert "2 located photos" in widget.caption.text()


def test_map_dialog_opens_with_located_assets(qapp, qtbot):
    """The dialog builds and plots assets without raising."""
    assets = [
        make_asset_view(original_name="A.JPG", latitude=45.0, longitude=7.0),
        make_asset_view(original_name="B.JPG", latitude=45.1, longitude=7.1),
    ]
    dialog = MapDialog("Vacation", assets)
    qtbot.addWidget(dialog)
    assert "2 located photos" in dialog.widget.caption.text()
