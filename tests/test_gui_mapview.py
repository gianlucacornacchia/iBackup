"""Tests for the interactive (Leaflet/OpenStreetMap-backed) trip map."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtWebEngineCore import QWebEngineProfile  # noqa: E402

from iphone_archive.browse.gallery import AssetView  # noqa: E402
from iphone_archive.core.trip import TRIP_MODES, TripSegment  # noqa: E402
from iphone_archive.gui.mapview import (  # noqa: E402
    MODE_STYLES,
    MapDialog,
    MapPage,
    MapPoint,
    WebMapWidget,
    mapview_build_html,
    mapview_parse_ignore_change,
    mapview_parse_mode_change,
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


def test_parse_mode_change_accepts_only_known_modes_on_real_legs():
    """Legs run 0..count-2; only listed modes or "none" are accepted."""
    assert mapview_parse_mode_change("ibackup-mode:0:car", 3) == (0, "car")
    assert mapview_parse_mode_change("ibackup-mode:1:none", 3) == (1, None)
    assert mapview_parse_mode_change("ibackup-mode:2:car", 3) is None
    assert mapview_parse_mode_change("ibackup-mode:0:rocket", 3) is None
    assert mapview_parse_mode_change("ibackup-mode:x:car", 3) is None
    assert mapview_parse_mode_change("ibackup-photo:0", 3) is None


def test_points_carry_the_saved_mode_of_the_leg_they_start():
    """A saved mode applies only to the exact consecutive pair it was saved for."""
    assets = [
        make_asset_view(asset_id=index, latitude=float(index), longitude=1.0) for index in (1, 2, 3)
    ]
    segments = [TripSegment(1, 2, "plane"), TripSegment(1, 3, "car")]
    assert [point.mode for point in mapview_points(assets, segments)] == ["plane", None, None]
    assert '"mode": "plane"' in mapview_build_html(mapview_points(assets, segments))


def test_parse_ignore_change_accepts_only_real_points_and_flags():
    """Page messages can only ignore or include one of the plotted points."""
    assert mapview_parse_ignore_change("ibackup-ignore:1:1", 3) == (1, True)
    assert mapview_parse_ignore_change("ibackup-ignore:0:0", 3) == (0, False)
    assert mapview_parse_ignore_change("ibackup-ignore:3:1", 3) is None
    assert mapview_parse_ignore_change("ibackup-ignore:1:2", 3) is None
    assert mapview_parse_ignore_change("ibackup-ignore:x:1", 3) is None
    assert mapview_parse_ignore_change("ibackup-mode:0:car", 3) is None


def test_points_carry_the_ignored_flag():
    """Ignored photos are still plotted, flagged so the page greys them out."""
    assets = [
        make_asset_view(asset_id=index, latitude=float(index), longitude=1.0) for index in (1, 2, 3)
    ]
    points = mapview_points(assets, None, {2})
    assert [point.ignored for point in points] == [False, True, False]
    assert '"ignored": true' in mapview_build_html(points)


def make_trip_assets():
    """Four located photos A..D with distinct places."""
    return [
        make_asset_view(asset_id=11 + i, original_name=name, latitude=45.0 + i, longitude=7.0 + i)
        for i, name in enumerate("ABCD")
    ]


def helper_js(qtbot, page, script):
    """Run ``script`` in the page and return its (JSON string) result."""
    result = []
    page.runJavaScript(script, 0, result.append)
    qtbot.waitUntil(lambda: bool(result), timeout=10000)
    return result[0]


def test_ignoring_a_point_redraws_the_trip_without_it(qapp, qtbot):
    """The ignored point stays, greyed; the legs touching it vanish and none bridges it."""
    widget = WebMapWidget()
    widget.resize(800, 600)
    qtbot.addWidget(widget)
    assets = make_trip_assets()
    with qtbot.waitSignal(widget.view.loadFinished, timeout=20000):
        widget.mapview_set_assets(assets, [TripSegment(11, 12, "car")])
    page = widget.page
    legs = "JSON.stringify(segments.map(function (s) { return [s.fromIndex, s.toIndex, s.mode]; }))"
    assert helper_js(qtbot, page, legs) == '[[0,1,"car"],[1,2,null],[2,3,null]]'

    changes = []
    widget.ignore_changed.connect(lambda *change: changes.append(change))
    page.runJavaScript("markers[1].openPopup();")
    qtbot.waitUntil(
        lambda: helper_js(qtbot, page, "!!document.querySelector('.trip-ignore-button')") is True,
        timeout=10000,
    )
    page.runJavaScript("document.querySelector('.trip-ignore-button').click();")
    qtbot.waitUntil(lambda: changes == [(12, True)], timeout=10000)
    assert widget.ignored == {12}
    assert "1 ignored" in widget.caption.text()
    assert helper_js(qtbot, page, legs) == "[[2,3,null]]"
    assert helper_js(qtbot, page, "document.querySelectorAll('.trip-pin').length") == 2

    page.runJavaScript("mapSetIgnored(1, false, true);")
    qtbot.waitUntil(lambda: changes[-1] == (12, False), timeout=10000)
    assert widget.ignored == set()
    assert helper_js(qtbot, page, legs) == '[[0,1,"car"],[1,2,null],[2,3,null]]'


def test_initially_ignored_points_start_greyed_and_unconnected(qapp, qtbot):
    """Reopening a map restores which points were ignored."""
    widget = WebMapWidget()
    widget.resize(800, 600)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.view.loadFinished, timeout=20000):
        widget.mapview_set_assets(make_trip_assets(), None, [12, 14, 999])
    assert widget.ignored == {12, 14}
    legs = "JSON.stringify(segments.map(function (s) { return [s.fromIndex, s.toIndex]; }))"
    assert helper_js(qtbot, widget.page, legs) == "[]"
    fill = "JSON.stringify(markers.map(function (m) { return m.options.fillColor; }))"
    assert helper_js(qtbot, widget.page, fill) == '["#3cbe5a","#ccc","#dc4646","#ccc"]'


def test_no_leg_bridges_an_ignored_point(qapp, qtbot):
    """With B ignored, A and C are not joined; the legs after C still are."""
    widget = WebMapWidget()
    widget.resize(800, 600)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.view.loadFinished, timeout=20000):
        widget.mapview_set_assets(make_trip_assets(), None, [12])
    legs = "JSON.stringify(segments.map(function (s) { return [s.fromIndex, s.toIndex]; }))"
    assert helper_js(qtbot, widget.page, legs) == "[[2,3]]"


def test_next_and_previous_visit_points_and_skip_ignored_ones(qapp, qtbot):
    """Stepping opens each non-ignored point's popup in order, wrapping at the ends."""
    widget = WebMapWidget()
    widget.resize(800, 600)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.view.loadFinished, timeout=20000):
        widget.mapview_set_assets(make_trip_assets(), None, [13])

    def visit(step):
        before = helper_js(qtbot, widget.page, "current")
        widget.next_button.click() if step > 0 else widget.previous_button.click()
        qtbot.waitUntil(lambda: helper_js(qtbot, widget.page, "current") != before, timeout=10000)
        return helper_js(qtbot, widget.page, "current")

    # Nothing open yet: Next starts at the first point, Previous at the last.
    assert [visit(1), visit(1), visit(1), visit(1)] == [0, 1, 3, 0]
    assert visit(-1) == 3
    assert visit(-1) == 1
    assert helper_js(qtbot, widget.page, "!!map._popup") is True


def test_stepping_is_disabled_when_every_point_is_ignored(qapp, qtbot):
    """With nothing left to visit the buttons are disabled; no points disables them too."""
    widget = WebMapWidget()
    qtbot.addWidget(widget)
    widget.mapview_set_assets(make_trip_assets(), None, [11, 12, 13, 14])
    assert not widget.next_button.isEnabled() and not widget.previous_button.isEnabled()
    widget.mapview_set_assets(make_trip_assets())
    assert widget.next_button.isEnabled() and widget.previous_button.isEnabled()
    widget.mapview_set_assets([])
    assert not widget.next_button.isEnabled()


def test_every_trip_mode_has_a_map_style():
    assert tuple(MODE_STYLES) == TRIP_MODES
    assert all(style["emoji"] and style["label"] for style in MODE_STYLES.values())


def test_mode_edit_in_the_page_is_saved_with_the_leg_asset_ids(qapp, qtbot):
    """Picking a mode on a leg reports the two photos' ids and redraws the leg."""
    saved = []
    assets = [
        make_asset_view(asset_id=11, original_name="A", latitude=45.0, longitude=7.0),
        make_asset_view(asset_id=12, original_name="B", latitude=46.0, longitude=8.0),
        make_asset_view(asset_id=13, original_name="C", latitude=47.0, longitude=7.0),
    ]
    dialog = MapDialog(
        "Trip",
        assets,
        segments=[TripSegment(11, 12, "plane")],
        on_mode_changed=lambda *change: saved.append(change),
    )
    qtbot.addWidget(dialog)
    page = dialog.widget.page
    with qtbot.waitSignal(dialog.widget.view.loadFinished, timeout=20000):
        dialog.widget.mapview_set_assets(assets, [TripSegment(11, 12, "plane")])
    state = []
    page.runJavaScript(
        "JSON.stringify(segments.map(function (s) { return s.mode; }))", 0, state.append
    )
    qtbot.waitUntil(lambda: bool(state), timeout=10000)
    assert state[0] == '["plane",null]'

    page.runJavaScript(
        "segments[1].hit.fire('click', {latlng: segments[1].to});"
        "map._popup.getElement().querySelector('.trip-mode-button[data-mode=\"tuktuk\"]').click();"
    )
    qtbot.waitUntil(lambda: saved == [(12, 13, "tuktuk")], timeout=10000)
    state.clear()
    page.runJavaScript(
        "JSON.stringify([segments[1].mode, segments[1].line.options.color])", 0, state.append
    )
    qtbot.waitUntil(lambda: bool(state), timeout=10000)
    assert state[0] == f'["tuktuk","{MODE_STYLES["tuktuk"]["color"]}"]'

    page.runJavaScript(
        "segments[0].hit.fire('click', {latlng: segments[0].to});"
        "map._popup.getElement().querySelector('.trip-mode-button[data-mode=\"none\"]').click();"
    )
    qtbot.waitUntil(lambda: saved[-1] == (11, 12, None), timeout=10000)


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
    assert "points.length === 0" in html
    assert "map.setView([20, 0], 2)" in html
    assert "mapLoad([]);" in html


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


def test_a_map_larger_than_set_html_limit_still_plots_every_point(qapp, qtbot):
    """Qt's setHtml() caps a page at 2 MB; a big library must still draw its trip.

    20,000 located photos make a page of about 3 MB with the points inlined.
    """
    widget = WebMapWidget()
    widget.resize(800, 600)
    qtbot.addWidget(widget)
    assets = [
        make_asset_view(
            asset_id=index + 1,
            original_name=f"IMG_{index:05d}.HEIC",
            captured_at=f"2024-08-01T12:{index // 60 % 60:02d}:{index % 60:02d}",
            latitude=45.0 + index * 1e-5,
            longitude=7.0 + index * 1e-5,
        )
        for index in range(20000)
    ]
    assert len(mapview_build_html(mapview_points(assets)).encode()) > 2 * 1024 * 1024
    with qtbot.waitSignal(widget.view.loadFinished, timeout=60000):
        widget.mapview_set_assets(assets)
    plotted = -1
    for _ in range(60):
        plotted = helper_js(qtbot, widget.page, "markers.length")
        if plotted == 20000:
            break
        qtbot.wait(1000)
    assert plotted == 20000
