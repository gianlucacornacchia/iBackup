"""Tests for duplicate detection and multi-album storage reporting."""

from __future__ import annotations

import pytest

from iphone_archive import config
from iphone_archive.catalog import database, repository
from iphone_archive.core import dedup, importer
from iphone_archive.device.fake_device import FakeDevice


@pytest.fixture
def archive(tmp_path):
    """An initialized archive with an open catalog connection."""
    paths = config.config_initialize_archive(tmp_path / "archive")
    connection = database.database_connect(paths.catalog_path)
    database.database_initialize(connection)
    yield paths, connection
    connection.close()


def test_no_duplicates_reported_for_single_copies(archive):
    """Distinct single-copy assets produce no multi-copy groups."""
    paths, connection = archive
    importer.importer_run(
        connection, paths, FakeDevice({"/DCIM/A.HEIC": b"aaa", "/DCIM/B.JPG": b"bbb"})
    )

    result = dedup.dedup_report(connection, paths)

    assert result.asset_count == 2
    assert result.file_count == 2
    assert result.multi_copy_groups == []
    assert result.reclaimable_bytes == 0


def test_identical_content_stored_once(archive):
    """Two phone items with identical bytes yield a single asset."""
    paths, connection = archive
    importer.importer_run(
        connection, paths, FakeDevice({"/DCIM/A.HEIC": b"same", "/DCIM/B.HEIC": b"same"})
    )

    result = dedup.dedup_report(connection, paths)

    assert result.asset_count == 1
    assert result.file_count == 1


def test_multi_album_copies_reported(archive):
    """An asset in two albums is reported with its extra storage cost."""
    paths, connection = archive
    payload = b"x" * 100
    device = FakeDevice(
        {"/DCIM/IMG.HEIC": payload}, album_map={"/DCIM/IMG.HEIC": ["Trip", "Favorites"]}
    )
    importer.importer_run(connection, paths, device)

    result = dedup.dedup_report(connection, paths)

    assert len(result.multi_copy_groups) == 1
    group = result.multi_copy_groups[0]
    assert group.copy_count == 2
    assert group.extra_bytes == 100
    assert result.reclaimable_bytes == 100


def test_dedup_never_deletes_files(archive):
    """Reporting leaves every stored file in place."""
    paths, connection = archive
    device = FakeDevice(
        {"/DCIM/IMG.HEIC": b"x"}, album_map={"/DCIM/IMG.HEIC": ["Trip", "Favorites"]}
    )
    importer.importer_run(connection, paths, device)
    before = [f.path for f in repository.repository_all_asset_files(connection)]

    dedup.dedup_report(connection, paths)

    after = [f.path for f in repository.repository_all_asset_files(connection)]
    assert after == before
    for path in after:
        assert (paths.root / path).is_file()


def test_empty_archive_reports_zero(archive):
    """An empty archive produces an empty report."""
    paths, connection = archive
    result = dedup.dedup_report(connection, paths)
    assert result.asset_count == 0
    assert result.reclaimable_bytes == 0
