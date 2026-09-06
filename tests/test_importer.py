"""Tests for the incremental, append-only import workflow."""

from __future__ import annotations

import pytest

from iphone_archive import config
from iphone_archive.catalog import database, repository
from iphone_archive.core import importer
from iphone_archive.device.fake_device import FakeDevice
from iphone_archive.service.progress import ProgressHandle


@pytest.fixture
def archive(tmp_path):
    """An initialized archive with an open catalog connection."""
    paths = config.config_initialize_archive(tmp_path / "archive")
    connection = database.database_connect(paths.catalog_path)
    database.database_initialize(connection)
    yield paths, connection
    connection.close()


def test_imports_new_assets(archive):
    """New items are copied, hashed, and committed to the catalog."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/IMG_0001.HEIC": b"one", "/DCIM/IMG_0002.JPG": b"two"})

    result = importer.importer_run(connection, paths, device)

    assert result.added_count == 2
    assert result.error_count == 0
    assert len(repository.repository_all_asset_files(connection)) == 2


def test_file_content_preserved_byte_for_byte(archive):
    """The archived file matches the source content exactly."""
    paths, connection = archive
    payload = b"original-bytes" * 100
    device = FakeDevice({"/DCIM/IMG_0001.HEIC": payload})

    importer.importer_run(connection, paths, device)

    stored = repository.repository_all_asset_files(connection)[0]
    assert (paths.root / stored.path).read_bytes() == payload


def test_second_run_skips_without_transfer(archive):
    """The fast-skip pass recognizes archived items without re-importing."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/IMG_0001.HEIC": b"one"})
    importer.importer_run(connection, paths, device)

    result = importer.importer_run(connection, paths, device)

    assert result.added_count == 0
    assert result.skipped_count == 1
    assert len(repository.repository_all_asset_files(connection)) == 1


def test_duplicate_content_under_new_identity_not_restored(archive):
    """Identical content at a new phone path is detected as a duplicate."""
    paths, connection = archive
    importer.importer_run(connection, paths, FakeDevice({"/DCIM/IMG_A.HEIC": b"same"}))

    result = importer.importer_run(connection, paths, FakeDevice({"/DCIM/IMG_B.HEIC": b"same"}))

    assert result.duplicate_count == 1
    assert result.added_count == 0
    assert len(repository.repository_all_asset_files(connection)) == 1


def test_album_less_asset_goes_to_unsorted(archive):
    """An asset with no album lands under _Unsorted."""
    paths, connection = archive
    importer.importer_run(connection, paths, FakeDevice({"/DCIM/IMG.HEIC": b"x"}))

    stored = repository.repository_all_asset_files(connection)[0]
    assert stored.path.startswith("Photos/_Unsorted/")


def test_multi_album_asset_placed_in_each_album(archive):
    """A photo in two albums exists as a real file in both folders."""
    paths, connection = archive
    device = FakeDevice(
        {"/DCIM/IMG.HEIC": b"shared"},
        album_map={"/DCIM/IMG.HEIC": ["Trip", "Favorites"]},
    )

    importer.importer_run(connection, paths, device)

    files = repository.repository_all_asset_files(connection)
    assert len(files) == 2
    folders = {stored.path.split("/")[1] for stored in files}
    assert folders == {"Trip", "Favorites"}
    for stored in files:
        assert (paths.root / stored.path).read_bytes() == b"shared"
        assert not (paths.root / stored.path).is_symlink()


def test_album_growth_is_append_only(archive):
    """A newly discovered album adds a copy without moving existing ones."""
    paths, connection = archive
    first = FakeDevice({"/DCIM/IMG.HEIC": b"x"}, album_map={"/DCIM/IMG.HEIC": ["Trip"]})
    importer.importer_run(connection, paths, first)
    original_paths = {f.path for f in repository.repository_all_asset_files(connection)}

    second = FakeDevice(
        {"/DCIM/IMG.HEIC": b"x"}, album_map={"/DCIM/IMG.HEIC": ["Trip", "Favorites"]}
    )
    importer.importer_run(connection, paths, second)

    new_paths = {f.path for f in repository.repository_all_asset_files(connection)}
    assert original_paths.issubset(new_paths)
    assert len(new_paths) == 2


def test_sidecar_written_for_each_asset(archive):
    """Every imported asset gets a sidecar JSON file."""
    paths, connection = archive
    importer.importer_run(connection, paths, FakeDevice({"/DCIM/IMG.HEIC": b"x"}))
    assert len(list(paths.sidecars_dir.glob("*.json"))) == 1


def test_import_session_recorded(archive):
    """An import session summary is persisted."""
    paths, connection = archive
    importer.importer_run(connection, paths, FakeDevice({"/DCIM/IMG.HEIC": b"x"}))

    row = connection.execute("SELECT * FROM import_sessions").fetchone()
    assert row["added_count"] == 1
    assert row["finished_at"] is not None


def test_presence_tracking_marks_missing_assets(archive):
    """Items absent from a later scan are flagged as gone from the phone."""
    paths, connection = archive
    importer.importer_run(
        connection, paths, FakeDevice({"/DCIM/A.HEIC": b"a", "/DCIM/B.HEIC": b"b"})
    )

    importer.importer_run(connection, paths, FakeDevice({"/DCIM/A.HEIC": b"a"}))

    absent = repository.repository_list_deleted_from_phone(connection)
    assert len(absent) == 1
    assert absent[0].original_name == "B.HEIC"


def test_archive_is_append_only_on_phone_deletion(archive):
    """Removing a photo from the phone never removes it from the archive."""
    paths, connection = archive
    importer.importer_run(connection, paths, FakeDevice({"/DCIM/A.HEIC": b"a"}))
    stored = repository.repository_all_asset_files(connection)[0]

    importer.importer_run(connection, paths, FakeDevice({}))

    assert (paths.root / stored.path).is_file()


def test_progress_reported(archive):
    """Progress events are emitted for each item."""
    paths, connection = archive
    handle = ProgressHandle()

    importer.importer_run(
        connection, paths, FakeDevice({"/DCIM/A.HEIC": b"a", "/DCIM/B.HEIC": b"b"}), handle
    )

    assert len(handle.events) == 2
    assert handle.events[-1].fraction == 1.0


def test_cancellation_stops_safely(archive):
    """A cancelled import stops without corrupting the archive."""
    paths, connection = archive
    handle = ProgressHandle()
    handle.progress_cancel()

    result = importer.importer_run(connection, paths, FakeDevice({"/DCIM/A.HEIC": b"a"}), handle)

    assert result.cancelled
    assert result.added_count == 0
    assert list(paths.temp_dir.glob("*")) == []


def test_read_error_counted_not_fatal(archive):
    """A failing item is recorded as an error while others still import."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/GOOD.HEIC": b"good", "/DCIM/BAD.HEIC": b"bad"})
    original_open = device.device_open

    def failing_open(phone_path):
        if phone_path.endswith("BAD.HEIC"):
            raise OSError("simulated read failure")
        return original_open(phone_path)

    device.device_open = failing_open

    result = importer.importer_run(connection, paths, device)

    assert result.added_count == 1
    assert result.error_count == 1


def test_interrupted_import_resumes_idempotently(archive):
    """After a mid-run failure, re-running yields the complete archive once."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/A.HEIC": b"a", "/DCIM/B.HEIC": b"b"})
    original_open = device.device_open

    def failing_open(phone_path):
        if phone_path.endswith("B.HEIC"):
            raise OSError("interrupted")
        return original_open(phone_path)

    device.device_open = failing_open
    first = importer.importer_run(connection, paths, device)
    assert first.added_count == 1

    device.device_open = original_open
    second = importer.importer_run(connection, paths, device)

    assert second.added_count == 1
    assert second.skipped_count == 1
    assert len(repository.repository_all_asset_files(connection)) == 2
    third = importer.importer_run(connection, paths, device)
    assert third.added_count == 0
