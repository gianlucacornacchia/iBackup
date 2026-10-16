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


def helper_device(names, times, previews=()):
    """A fake phone holding located photos; ``previews`` are offloaded thumbnails.

    names: photo letters, e.g. "ABC".
    times: capture day per letter (controls the trip order).
    previews: letters whose original is not on the phone yet.
    """
    from iphone_archive.catalog.models import PhoneItem

    class Phone(FakeDevice):
        def device_enumerate(self):
            for item in super().device_enumerate():
                letter = item.phone_path.split("/DCIM/")[1][0]
                if letter in previews:
                    item.is_offloaded_preview = True
                    item.offloaded_original_path = f"/DCIM/{letter}.JPG"
                    item.original_name = f"{letter} (offloaded preview).JPG"
                yield item

    files = {}
    for letter in names:
        path = (
            f"/PhotoData/Thumbnails/V2/DCIM/{letter}.JPG/5005.JPG"
            if letter in previews
            else f"/DCIM/{letter}.JPG"
        )
        files[path] = (b"thumb-" if letter in previews else b"full-") + letter.encode()
    device = Phone(
        files,
        album_map={path: ["Trip"] for path in files},
        locations={path: (40.0 + ord(path[-5]) % 10, 7.0) for path in files},
    )
    for path in files:
        letter = path.split("/DCIM/")[1][0]
        device.metadata[path] = {"captured_at": f"2024-01-{times[letter]:02d}T10:00:00"}
    assert all(isinstance(item, PhoneItem) for item in device.device_enumerate())
    return device


def helper_trip(service, scope="all", album_id=None):
    """Open the map's data the way the GUI does and return ``{"AB": mode}``."""
    located = service.app_service_list_locations(album_id=album_id)
    names = {asset.asset_id: asset.original_name[0] for asset in located}
    segments = service.app_service_trip_modes(scope, [asset.asset_id for asset in located])
    return {names[s.from_asset_id] + names[s.to_asset_id]: s.mode for s in segments}, {
        name: asset_id for asset_id, name in names.items()
    }


@pytest.fixture
def empty_service(tmp_path):
    """An open, empty archive."""
    service = AppService(tmp_path / "archive")
    service.app_service_initialize()
    yield service
    service.app_service_close()


def test_modes_survive_reimporting_the_same_photos(empty_service):
    """The same bytes are the same catalog asset, so a re-import changes nothing."""
    service = empty_service
    days = {"A": 1, "B": 2, "C": 3}
    service.app_service_import(helper_device("ABC", days))
    _, ids = helper_trip(service)
    service.app_service_set_trip_mode("all", ids["A"], ids["B"], "car")
    service.app_service_set_trip_mode("all", ids["B"], ids["C"], "plane")

    result = service.app_service_import(helper_device("ABC", days))

    assert result.added_count == 0
    modes, after = helper_trip(service)
    assert after == ids
    assert modes == {"AB": "car", "BC": "plane"}


def test_a_newly_imported_photo_in_the_middle_splits_the_leg(empty_service):
    """An import that adds X between B and C gives B→X and X→C the B→C mode."""
    service = empty_service
    service.app_service_import(helper_device("ABC", {"A": 1, "B": 2, "C": 4}))
    _, ids = helper_trip(service)
    service.app_service_set_trip_mode("all", ids["A"], ids["B"], "car")
    service.app_service_set_trip_mode("all", ids["B"], ids["C"], "boat")

    service.app_service_import(helper_device("ABXC", {"A": 1, "B": 2, "X": 3, "C": 4}))

    modes, _ = helper_trip(service)
    assert modes == {"AB": "car", "BX": "boat", "XC": "boat"}


def test_modes_survive_an_offloaded_preview_being_upgraded(empty_service):
    """When B's original comes back, its preview row is upgraded in place: same asset."""
    service = empty_service
    days = {"A": 1, "B": 2, "C": 3}
    service.app_service_import(helper_device("ABC", days, previews="B"))
    _, ids = helper_trip(service)
    service.app_service_set_trip_mode("all", ids["A"], ids["B"], "tuktuk")
    service.app_service_set_trip_mode("all", ids["B"], ids["C"], "bus")

    result = service.app_service_import(helper_device("ABC", days))

    assert result.upgraded_count == 1
    modes, after = helper_trip(service)
    assert after["B"] == ids["B"]
    assert modes == {"AB": "tuktuk", "BC": "bus"}


def test_album_map_modes_survive_reimport(empty_service):
    """An album keeps its catalog id across imports, so its map keeps its modes."""
    service = empty_service
    days = {"A": 1, "B": 2}
    service.app_service_import(helper_device("AB", days))
    album_id = service.app_service_list_albums()[0].album_id
    scope = f"album:{album_id}"
    _, ids = helper_trip(service, scope, album_id)
    service.app_service_set_trip_mode(scope, ids["A"], ids["B"], "foot")

    service.app_service_import(helper_device("AB", days))

    assert service.app_service_list_albums()[0].album_id == album_id
    assert helper_trip(service, scope, album_id)[0] == {"AB": "foot"}


def test_ignored_points_are_saved_per_view_and_survive_reopening(service):
    """Ignoring is stored in the catalog, per view, and never touches the modes."""
    ids = helper_ids(service)
    order = [ids[name] for name in "ABCDE"]
    service.app_service_set_trip_mode("all", ids["A"], ids["B"], "car")
    assert service.app_service_set_trip_ignored("all", ids["B"], True) is True
    service.app_service_set_trip_ignored("all", ids["D"], True)
    service.app_service_set_trip_ignored("album:1", ids["C"], True)
    service.app_service_close()

    service.app_service_open()
    assert service.app_service_trip_ignored("all", order) == [ids["B"], ids["D"]]
    assert service.app_service_trip_ignored("album:1", order) == [ids["C"]]
    assert service.app_service_trip_ignored("unsorted", order) == []
    assert helper_modes(service, "all", order) == {"AB": "car"}

    service.app_service_set_trip_ignored("all", ids["B"], False)
    service.app_service_set_trip_ignored("all", ids["B"], False)  # idempotent
    assert service.app_service_trip_ignored("all", order) == [ids["D"]]
    assert service.app_service_trip_ignored("all", [ids["A"], ids["B"]]) == []


def test_ignoring_twice_is_harmless_and_input_is_validated(service):
    ids = helper_ids(service)
    service.app_service_set_trip_ignored("all", ids["A"], True)
    service.app_service_set_trip_ignored("all", ids["A"], True)
    assert service.app_service_trip_ignored("all", [ids["A"]]) == [ids["A"]]
    with pytest.raises(ValueError):
        service.app_service_set_trip_ignored("all", 99999, True)
    with pytest.raises(ValueError):
        service.app_service_set_trip_ignored("", ids["A"], True)
    with pytest.raises(ValueError):
        service.app_service_set_trip_ignored("all", ids["A"], "yes")
    with pytest.raises(ValueError):
        service.app_service_trip_ignored("all", [1, 1])


def test_ignored_flag_goes_away_with_the_asset(service):
    """The table cascades, so a purged photo leaves no orphan row behind."""
    ids = helper_ids(service)
    service.app_service_set_trip_ignored("all", ids["A"], True)
    connection, _ = service.app_service_require()
    connection.execute("DELETE FROM assets WHERE id = ?", (ids["A"],))
    connection.commit()
    count = connection.execute("SELECT COUNT(*) FROM trip_ignored_points").fetchone()[0]
    assert count == 0
