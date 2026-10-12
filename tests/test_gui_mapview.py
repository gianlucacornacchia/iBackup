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
    MapPage,
    MapPoint,
    WebMapWidget,
    mapview_build_html,
    mapview_parse_request,
    mapview_points,
    mapview_render_photo,
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


def test_mapview_points_carry_time_and_preview_notes():
    """Popups show the capture time and say when the picture is only a preview."""
    assets = [
        make_asset_view(
            original_name="IMG_1 (offloaded preview).JPG",
            captured_at="2024-03-12T14:05:33+00:00",
            latitude=1.0,
            longitude=2.0,
        ),
        make_asset_view(original_name="V.MOV", media_type="video", latitude=1.0, longitude=2.0),
    ]
    first, second = mapview_points(assets)
    assert first.captured_at == "2024-03-12 14:05"
    assert "Low-resolution preview" in (first.note or "")
    assert second.note == "Video (poster frame)"


def test_build_html_marks_start_end_and_draws_direction_arrows():
    """Start/End get labelled pins and each segment gets a chronological arrow."""
    html = mapview_build_html([MapPoint(45.0, 7.0, "a"), MapPoint(45.1, 7.1, "b")])
    assert "'Start'" in html and "'End'" in html
    assert "trip-pin" in html
    assert "trip-arrow" in html and "Math.atan2" in html
    assert "mapUpdateArrows" in html
    assert "ibackup-photo:" in html


def test_parse_request_accepts_only_in_range_photo_indices():
    """Page content can only ask for one of the plotted points."""
    assert mapview_parse_request("ibackup-photo:2", 3) == 2
    assert mapview_parse_request("ibackup-photo:3", 3) is None
    assert mapview_parse_request("ibackup-photo:-1", 3) is None
    assert mapview_parse_request("ibackup-photo:1;x", 3) is None
    assert mapview_parse_request("hello", 3) is None


def make_archived_photo(tmp_path, name="A.JPG"):
    """Archive one real JPEG and return ``(archive_root, AssetView)``."""
    from PIL import Image

    root = tmp_path / "archive"
    (root / "Photos" / "Trip").mkdir(parents=True)
    Image.new("RGB", (64, 48), (200, 30, 30)).save(root / "Photos" / "Trip" / name)
    view = make_asset_view(
        original_name=name, paths=[f"Photos/Trip/{name}"], latitude=45.0, longitude=7.0
    )
    return root, view


def test_render_photo_returns_a_data_uri_from_the_archived_copy(tmp_path):
    """The popup picture comes from the archive, never from the phone."""
    root, view = make_archived_photo(tmp_path)
    uri, message = mapview_render_photo(root, view, 128)
    assert uri is not None and uri.startswith("data:image/jpeg;base64,")
    assert message == ""
    missing = make_asset_view(sha256="b" * 64, paths=["Photos/Trip/missing.JPG"])
    assert mapview_render_photo(root, missing, 128)[0] is None
    assert mapview_render_photo(root, make_asset_view(), 128) == (None, "No archived copy")


def test_clicked_point_receives_its_photo(qapp, qtbot, tmp_path):
    """End to end: a photo request from the page is rendered and pushed back."""
    root, view = make_archived_photo(tmp_path)
    widget = WebMapWidget(archive_root=root)
    qtbot.addWidget(widget)
    pushed = []
    widget.page.runJavaScript = lambda script, *args: pushed.append(script)
    widget.mapview_set_assets([view])

    widget.mapview_photo_requested("ibackup-photo:0")
    qtbot.waitUntil(lambda: bool(pushed), timeout=10000)
    assert pushed[0].startswith('mapShowPhoto(0, "data:image/jpeg;base64,')
    widget.mapview_photo_requested("ibackup-photo:0")  # answered once per plot
    widget.mapview_shutdown()
    assert len(pushed) == 1


def test_photo_request_without_archive_reports_why(qapp, qtbot):
    """Without an open archive the popup says so instead of spinning forever."""
    widget = WebMapWidget()
    qtbot.addWidget(widget)
    pushed = []
    widget.page.runJavaScript = lambda script, *args: pushed.append(script)
    widget.mapview_set_assets([make_asset_view(latitude=1.0, longitude=2.0)])
    widget.mapview_photo_requested("ibackup-photo:0")
    assert pushed == ['mapShowPhoto(0, null, "No archive open");']


def test_page_forwards_only_photo_requests(qapp):
    """Ordinary console output from Leaflet is ignored."""
    page = MapPage(mapview_tile_profile())
    seen = []
    page.photo_requested.connect(seen.append)
    level = page.JavaScriptConsoleMessageLevel.InfoMessageLevel
    page.javaScriptConsoleMessage(level, "ibackup-photo:4", 1, "")
    page.javaScriptConsoleMessage(level, "some leaflet log", 1, "")
    assert seen == ["ibackup-photo:4"]
    page.deleteLater()


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


def test_page_script_runs_and_builds_pins_arrows_and_popups(qapp, qtbot):
    """The real page script executes in WebEngine without errors."""
    widget = WebMapWidget()
    widget.resize(800, 600)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.view.loadFinished, timeout=20000):
        widget.mapview_set_assets(
            [
                make_asset_view(original_name="A", latitude=45.0, longitude=7.0),
                make_asset_view(original_name="B", latitude=46.0, longitude=8.0),
                make_asset_view(original_name="C", latitude=46.0, longitude=8.0),
                make_asset_view(original_name="D", latitude=47.0, longitude=7.0),
            ]
        )
    result = []
    widget.page.runJavaScript(
        "JSON.stringify([markers.length, segments.length,"
        " document.querySelectorAll('.trip-pin').length])",
        0,
        result.append,
    )
    qtbot.waitUntil(lambda: bool(result), timeout=10000)
    # Four points, three segments minus one zero-length duplicate, two pins.
    assert result[0] == "[4,2,2]"
    requests = []
    widget.page.photo_requested.connect(requests.append)
    widget.page.runJavaScript("markers[1].openPopup();")
    qtbot.waitUntil(lambda: bool(requests), timeout=10000)
    assert requests == ["ibackup-photo:1"]


def test_popup_shows_the_rendered_photo_end_to_end(qapp, qtbot, tmp_path):
    """Opening a popup in the real page ends with the picture inside it.

    Regression: Leaflet re-runs a popup content function on ``update()``, which
    replaced the freshly inserted picture with "Loading preview" again.
    """
    root, view = make_archived_photo(tmp_path)
    widget = WebMapWidget(archive_root=root)
    widget.resize(800, 600)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.view.loadFinished, timeout=20000):
        widget.mapview_set_assets([view])
    widget.page.runJavaScript("markers[0].openPopup();")
    shown = []

    def poll():
        widget.page.runJavaScript(
            "!!document.querySelector('.leaflet-popup .trip-photo img')", 0, shown.append
        )
        return bool(shown) and shown[-1] is True

    qtbot.waitUntil(poll, timeout=15000)
    widget.mapview_shutdown()


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
