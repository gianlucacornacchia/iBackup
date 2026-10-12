"""Tests for trip travel modes: storage, reconciliation and the service API."""

from __future__ import annotations

import pytest

from iphone_archive.core import trip
from iphone_archive.device.fake_device import FakeDevice
from iphone_archive.service.app_service import AppService


@pytest.fixture
def service(tmp_path):
    """An open archive holding five located photos A..E, in capture order."""
    service = AppService(tmp_path / "archive")
    service.app_service_initialize()
    files = {f"/DCIM/{name}.JPG": name.encode() for name in "ABCDE"}
    device = FakeDevice(
        files, locations={path: (45.0 + i, 7.0 + i) for i, path in enumerate(sorted(files))}
    )
    for i, path in enumerate(sorted(files)):
        device.metadata[path] = {"captured_at": f"2024-01-0{i + 1}T10:00:00"}
    service.app_service_import(device)
    yield service
    service.app_service_close()


def helper_ids(service):
    """Return the located asset ids keyed by name, in capture order."""
    return {
        asset.original_name[0]: asset.asset_id for asset in service.app_service_list_locations()
    }


def helper_modes(service, scope, ids):
    """Return the reconciled modes as ``{"AB": "car"}``."""
    names = {asset_id: name for name, asset_id in helper_ids(service).items()}
    return {
        names[segment.from_asset_id] + names[segment.to_asset_id]: segment.mode
        for segment in service.app_service_trip_modes(scope, ids)
    }


def test_modes_are_saved_and_survive_reopening(service, tmp_path):
    """A chosen travel mode is stored in the catalog, not only in the page."""
    ids = helper_ids(service)
    order = [ids[name] for name in "ABCDE"]
    service.app_service_set_trip_mode("all", ids["A"], ids["B"], "plane")
    service.app_service_set_trip_mode("all", ids["B"], ids["C"], "tuktuk")
    service.app_service_close()

    service.app_service_open()
    assert helper_modes(service, "all", order) == {"AB": "plane", "BC": "tuktuk"}
    service.app_service_set_trip_mode("all", ids["A"], ids["B"], None)
    assert helper_modes(service, "all", order) == {"BC": "tuktuk"}


def test_modes_are_per_view(service):
    """The same pair of photos can be travelled differently in another album's map."""
    ids = helper_ids(service)
    order = [ids[name] for name in "ABCDE"]
    service.app_service_set_trip_mode("all", ids["A"], ids["B"], "car")
    assert helper_modes(service, "album:7", order) == {}


def test_removed_photo_drops_the_modes_touching_it(service):
    """Removing B forgets A→B and B→C; the new A→C leg starts untagged."""
    ids = helper_ids(service)
    service.app_service_set_trip_mode("all", ids["A"], ids["B"], "car")
    service.app_service_set_trip_mode("all", ids["B"], ids["C"], "bus")
    service.app_service_set_trip_mode("all", ids["C"], ids["D"], "foot")

    without_b = [ids[name] for name in "ACDE"]
    assert helper_modes(service, "all", without_b) == {"CD": "foot"}
    # The forgotten modes do not come back when B returns.
    assert helper_modes(service, "all", [ids[name] for name in "ABCDE"]) == {"CD": "foot"}


def test_inserted_photo_splits_a_leg_into_two_with_the_same_mode(service):
    """Adding B between A and C gives A→B and B→C the mode A→C had."""
    ids = helper_ids(service)
    without_b = [ids[name] for name in "ACDE"]
    service.app_service_trip_modes("all", without_b)
    service.app_service_set_trip_mode("all", ids["A"], ids["C"], "boat")

    assert helper_modes(service, "all", [ids[name] for name in "ABCDE"]) == {
        "AB": "boat",
        "BC": "boat",
    }
    # The split is persistent, not recomputed each time.
    assert helper_modes(service, "all", [ids[name] for name in "ABCDE"]) == {
        "AB": "boat",
        "BC": "boat",
    }


def test_several_inserted_photos_all_inherit_the_mode(service):
    """Two photos inserted inside one leg tag all three resulting legs."""
    ids = helper_ids(service)
    service.app_service_set_trip_mode("all", ids["A"], ids["D"], "bike")
    assert helper_modes(service, "all", [ids[name] for name in "ABCD"]) == {
        "AB": "bike",
        "BC": "bike",
        "CD": "bike",
    }


def test_an_explicit_mode_wins_over_an_inherited_one(service):
    """Inheritance only fills legs the user has not tagged themselves."""
    ids = helper_ids(service)
    service.app_service_set_trip_mode("all", ids["A"], ids["C"], "plane")
    service.app_service_set_trip_mode("all", ids["B"], ids["C"], "taxi")
    assert helper_modes(service, "all", [ids[name] for name in "ABC"]) == {
        "AB": "plane",
        "BC": "taxi",
    }


def test_purged_photo_removes_its_segments(service):
    """Deleting the asset row cascades to every stored segment touching it."""
    ids = helper_ids(service)
    service.app_service_set_trip_mode("all", ids["A"], ids["B"], "car")
    service.app_service_purge([ids["B"]], confirmed=True)
    connection, _ = service.app_service_require()
    assert trip.trip_stored(connection, "all") == {}


@pytest.mark.parametrize(
    ("scope", "from_id", "to_id", "mode"),
    [
        ("", 1, 2, "car"),
        ("all", 1, 2, "rocket"),
        ("all", 1, 1, "car"),
        ("all", 0, 2, "car"),
        ("all", 1, 9999, "car"),
    ],
)
def test_invalid_mode_edits_are_refused(service, scope, from_id, to_id, mode):
    """Only known modes on real, distinct assets can be saved."""
    with pytest.raises(ValueError):
        service.app_service_set_trip_mode(scope, from_id, to_id, mode)


def test_reconcile_rejects_malformed_asset_lists(service):
    with pytest.raises(ValueError):
        service.app_service_trip_modes("all", [1, 1])
    with pytest.raises(ValueError):
        service.app_service_trip_modes("all", [1, "2"])


def test_every_required_mode_is_offered():
    assert trip.TRIP_MODES == ("car", "plane", "foot", "bike", "tuktuk", "bus", "taxi", "boat")
