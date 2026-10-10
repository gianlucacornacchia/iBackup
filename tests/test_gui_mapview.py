"""Tests for the offline trip-map canvas: projection math and map-like chrome."""

from __future__ import annotations

import math
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QRectF  # noqa: E402

from iphone_archive.browse.gallery import AssetView  # noqa: E402
from iphone_archive.gui.mapview import (  # noqa: E402
    MapDialog,
    MapPoint,
    TripMapCanvas,
    mapview_graticule_step,
    mapview_haversine_km,
    mapview_points,
    mapview_scale_bar_km,
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


def test_graticule_step_picks_a_round_number_with_several_lines():
    """The chosen spacing always produces at least two grid lines across the span."""
    assert mapview_graticule_step(25.0) == 10.0
    assert mapview_graticule_step(3.0) == 1.0
    assert mapview_graticule_step(0.05) == 0.02
    # A span tighter than every step still returns the finest one, not zero.
    assert mapview_graticule_step(0.0001) == 0.001


def test_scale_bar_km_picks_a_round_number_that_fits():
    assert mapview_scale_bar_km(850.0) == 500.0
    assert mapview_scale_bar_km(3.0) == 2.0
    assert mapview_scale_bar_km(0.005) == 0.01


def test_haversine_known_distance_rome_to_milan():
    """A known real-world distance sanity-checks the formula (~480km, give or take)."""
    rome = (41.9028, 12.4964)
    milan = (45.4642, 9.1900)
    distance = mapview_haversine_km(*rome, *milan)
    assert 460 < distance < 500


def test_project_point_is_north_up_and_within_rect(qapp):
    """Higher latitude draws nearer the top; every projected point stays inside rect."""
    canvas = TripMapCanvas()
    canvas.mapview_set_points(
        [
            MapPoint(45.0, 7.0, "north"),
            MapPoint(40.0, 7.0, "south"),
        ]
    )
    rect = QRectF(0, 0, 400, 300)
    north = canvas.mapview_project_point(rect, 45.0, 7.0)
    south = canvas.mapview_project_point(rect, 40.0, 7.0)
    assert north.y() < south.y()
    for point in (north, south):
        assert rect.left() <= point.x() <= rect.right()
        assert rect.top() <= point.y() <= rect.bottom()


def test_project_point_handles_single_point_without_crashing(qapp):
    """A lone located photo still projects to a sane point instead of raising."""
    canvas = TripMapCanvas()
    canvas.mapview_set_points([MapPoint(45.0, 7.0, "solo")])
    rect = QRectF(0, 0, 400, 300)
    point = canvas.mapview_project_point(rect, 45.0, 7.0)
    assert math.isfinite(point.x())
    assert math.isfinite(point.y())


def test_canvas_paints_without_error_for_empty_and_populated_state(qapp, qtbot):
    """The canvas renders cleanly both with no located photos and with several."""
    canvas = TripMapCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(400, 300)
    canvas.mapview_set_points([])
    canvas.grab()  # forces a paintEvent synchronously; must not raise

    canvas.mapview_set_points(
        [
            MapPoint(45.0, 7.0, "a"),
            MapPoint(45.1, 7.2, "b"),
            MapPoint(45.2, 7.4, "c"),
        ]
    )
    canvas.grab()


def test_map_dialog_opens_with_located_assets(qapp, qtbot):
    """The dialog builds and plots assets without raising."""
    assets = [
        make_asset_view(original_name="A.JPG", latitude=45.0, longitude=7.0),
        make_asset_view(original_name="B.JPG", latitude=45.1, longitude=7.1),
    ]
    dialog = MapDialog("Vacation", assets)
    qtbot.addWidget(dialog)
    assert dialog.widget.canvas.points == mapview_points(assets)
    assert "2 located photos" in dialog.widget.caption.text()
