"""Tests for deleted-from-phone detection, the recycle bin, and reclamation."""

from __future__ import annotations

import pytest

from iphone_archive import config
from iphone_archive.catalog import database, repository
from iphone_archive.catalog.models import ArchiveState, FileLocation
from iphone_archive.core import importer, phone_diff, reclaim, recycle
from iphone_archive.device.fake_device import FakeDevice


@pytest.fixture
def archive(tmp_path):
    """An initialized archive with an open catalog connection."""
    paths = config.config_initialize_archive(tmp_path / "archive")
    connection = database.database_connect(paths.catalog_path)
    database.database_initialize(connection)
    yield paths, connection
    connection.close()


def import_two(paths, connection):
    """Import two assets and return the device that held them."""
    device = FakeDevice({"/DCIM/A.HEIC": b"aaa", "/DCIM/B.JPG": b"bbb"})
    importer.importer_run(connection, paths, device)
    return device


def test_detects_asset_removed_from_phone(archive):
    """An asset missing from a later scan is reported, read-only."""
    paths, connection = archive
    import_two(paths, connection)

    phone_diff.phone_diff_scan_presence(
        connection, FakeDevice({"/DCIM/A.HEIC": b"aaa"}), "2026-09-07T00:00:00"
    )
    result = phone_diff.phone_diff_list(connection, paths)

    assert result.count == 1
    assert result.items[0].original_name == "B.JPG"
    assert result.items[0].paths
    assert (paths.root / result.items[0].paths[0]).is_file()


def test_present_assets_not_reported(archive):
    """Assets still on the phone are not listed."""
    paths, connection = archive
    device = import_two(paths, connection)

    phone_diff.phone_diff_scan_presence(connection, device, "2026-09-07T00:00:00")

    assert phone_diff.phone_diff_list(connection, paths).count == 0


def test_detection_changes_no_files(archive):
    """Detection never modifies the archive."""
    paths, connection = archive
    import_two(paths, connection)
    before = {f.path for f in repository.repository_all_asset_files(connection)}

    phone_diff.phone_diff_scan_presence(connection, FakeDevice({}), "2026-09-07T00:00:00")
    phone_diff.phone_diff_list(connection, paths)

    after = {f.path for f in repository.repository_all_asset_files(connection)}
    assert after == before
    for path in after:
        assert (paths.root / path).is_file()


def test_still_on_phone_helper(archive):
    """The per-asset presence helper reflects the latest scan."""
    paths, connection = archive
    import_two(paths, connection)
    phone_diff.phone_diff_scan_presence(
        connection, FakeDevice({"/DCIM/A.HEIC": b"aaa"}), "2026-09-07T00:00:00"
    )
    gone = phone_diff.phone_diff_list(connection, paths).items[0]
    assert not phone_diff.phone_diff_asset_still_on_phone(connection, gone.asset_id)


def test_move_to_deleted_preserves_album_subpath(archive):
    """Recycling moves files under Deleted/ keeping the album folder."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/IMG.HEIC": b"x"}, album_map={"/DCIM/IMG.HEIC": ["Trip"]})
    importer.importer_run(connection, paths, device)
    asset_id = repository.repository_all_asset_files(connection)[0].asset_id

    result = recycle.recycle_move_to_deleted(connection, paths, [asset_id])

    assert result.moved_count == 1
    stored = repository.repository_list_asset_files(connection, asset_id)[0]
    assert stored.path.startswith("Deleted/Trip/")
    assert (paths.root / stored.path).is_file()
    assert stored.location is FileLocation.DELETED


def test_recycled_asset_marked_deleted_and_excluded(archive):
    """A recycled asset is no longer reported as deleted-from-phone."""
    paths, connection = archive
    import_two(paths, connection)
    phone_diff.phone_diff_scan_presence(connection, FakeDevice({}), "2026-09-07T00:00:00")
    gone = phone_diff.phone_diff_list(connection, paths)
    asset_ids = [item.asset_id for item in gone.items]

    recycle.recycle_move_to_deleted(connection, paths, asset_ids)

    assert phone_diff.phone_diff_list(connection, paths).count == 0
    assert sorted(recycle.recycle_list_deleted(connection)) == sorted(asset_ids)


def test_restore_returns_to_photos(archive):
    """Restoring a recycled asset puts it back under Photos/."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/IMG.HEIC": b"x"}, album_map={"/DCIM/IMG.HEIC": ["Trip"]})
    importer.importer_run(connection, paths, device)
    asset_id = repository.repository_all_asset_files(connection)[0].asset_id
    recycle.recycle_move_to_deleted(connection, paths, [asset_id])

    result = recycle.recycle_restore(connection, paths, [asset_id])

    assert result.restored_count == 1
    stored = repository.repository_list_asset_files(connection, asset_id)[0]
    assert stored.path.startswith("Photos/Trip/")
    assert (paths.root / stored.path).read_bytes() == b"x"
    row = connection.execute("SELECT archive_state FROM assets WHERE id = ?", (asset_id,))
    assert row.fetchone()["archive_state"] == ArchiveState.ACTIVE.value


def test_purge_requires_confirmation(archive):
    """Without confirmation, purge removes nothing."""
    paths, connection = archive
    import_two(paths, connection)
    asset_id = repository.repository_all_asset_files(connection)[0].asset_id

    result = recycle.recycle_purge(connection, paths, [asset_id], confirmed=False)

    assert result.purged_count == 0
    assert result.skipped_count == 1
    assert repository.repository_list_asset_files(connection, asset_id)


def test_purge_removes_files_and_catalog_rows(archive):
    """Confirmed purge deletes files, sidecar, and catalog rows."""
    paths, connection = archive
    import_two(paths, connection)
    stored = repository.repository_all_asset_files(connection)[0]
    asset_id = stored.asset_id
    file_path = paths.root / stored.path

    result = recycle.recycle_purge(connection, paths, [asset_id], confirmed=True)

    assert result.purged_count == 1
    assert not file_path.exists()
    assert repository.repository_list_asset_files(connection, asset_id) == []


def test_reclaim_dry_run_deletes_nothing(archive):
    """The default dry run reports candidates without touching the phone."""
    paths, connection = archive
    device = import_two(paths, connection)

    result = reclaim.reclaim_run(connection, paths, device)

    assert result.dry_run
    assert len(result.candidates) == 2
    assert result.deleted_count == 0
    assert device.deleted_paths == []
    assert result.reclaimable_bytes == 6


def test_reclaim_confirmed_deletes_only_phone_files(archive):
    """Confirmed reclamation deletes phone files and leaves the archive intact."""
    paths, connection = archive
    device = import_two(paths, connection)
    archived = {f.path for f in repository.repository_all_asset_files(connection)}

    result = reclaim.reclaim_run(connection, paths, device, confirmed=True)

    assert result.deleted_count == 2
    assert sorted(device.deleted_paths) == ["/DCIM/A.HEIC", "/DCIM/B.JPG"]
    for path in archived:
        assert (paths.root / path).is_file()


def test_reclaim_requires_verified_archive_copy(archive):
    """An asset whose archived file is corrupt is not a deletion candidate."""
    paths, connection = archive
    device = import_two(paths, connection)
    stored = repository.repository_all_asset_files(connection)[0]
    (paths.root / stored.path).write_bytes(b"corrupted")

    result = reclaim.reclaim_run(connection, paths, device)

    assert len(result.candidates) == 1


def test_reclaim_skips_unarchived_items(archive):
    """Items never imported are never offered for deletion."""
    paths, connection = archive
    import_two(paths, connection)
    device = FakeDevice({"/DCIM/NEW.HEIC": b"never-imported"})

    result = reclaim.reclaim_run(connection, paths, device)

    assert result.candidates == []


def test_reclaim_missing_archive_file_blocks_deletion(archive):
    """A missing archive copy disqualifies the phone file from deletion."""
    paths, connection = archive
    device = import_two(paths, connection)
    stored = repository.repository_all_asset_files(connection)[0]
    (paths.root / stored.path).unlink()

    result = reclaim.reclaim_run(connection, paths, device, confirmed=True)

    assert result.deleted_count == 1
    assert len(device.deleted_paths) == 1
