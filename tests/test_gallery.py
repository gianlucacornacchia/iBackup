"""Tests for browsing the archive by album and recycle-bin state."""

from __future__ import annotations

import pytest

from iphone_archive import config
from iphone_archive.browse import gallery
from iphone_archive.catalog import database, repository
from iphone_archive.core import importer, recycle
from iphone_archive.device.fake_device import FakeDevice


@pytest.fixture
def archive(tmp_path):
    """An initialized archive with an open catalog connection."""
    paths = config.config_initialize_archive(tmp_path / "archive")
    connection = database.database_connect(paths.catalog_path)
    database.database_initialize(connection)
    yield paths, connection
    connection.close()


def test_list_all_assets(archive):
    """All active assets are listed with their stored paths."""
    paths, connection = archive
    importer.importer_run(
        connection, paths, FakeDevice({"/DCIM/A.HEIC": b"a", "/DCIM/B.JPG": b"b"})
    )

    views = gallery.gallery_list_assets(connection)

    assert len(views) == 2
    assert all(view.paths for view in views)
    assert gallery.gallery_count_assets(connection) == 2


def test_filter_by_album(archive):
    """Listing can be restricted to a single album."""
    paths, connection = archive
    device = FakeDevice(
        {"/DCIM/A.HEIC": b"a", "/DCIM/B.HEIC": b"b"},
        album_map={"/DCIM/A.HEIC": ["Trip"]},
    )
    importer.importer_run(connection, paths, device)
    album_id = repository.repository_list_albums(connection)[0].album_id

    views = gallery.gallery_list_assets(connection, album_id=album_id)

    assert len(views) == 1
    assert views[0].original_name == "A.HEIC"


def test_unsorted_listing(archive):
    """Album-less assets are listed separately."""
    paths, connection = archive
    device = FakeDevice(
        {"/DCIM/A.HEIC": b"a", "/DCIM/B.HEIC": b"b"},
        album_map={"/DCIM/A.HEIC": ["Trip"]},
    )
    importer.importer_run(connection, paths, device)

    views = gallery.gallery_list_unsorted(connection)

    assert [view.original_name for view in views] == ["B.HEIC"]


def test_recycled_excluded_by_default(archive):
    """Recycled assets disappear from normal browsing but remain findable."""
    paths, connection = archive
    importer.importer_run(connection, paths, FakeDevice({"/DCIM/A.HEIC": b"a"}))
    asset_id = repository.repository_all_asset_files(connection)[0].asset_id
    recycle.recycle_move_to_deleted(connection, paths, [asset_id])

    assert gallery.gallery_list_assets(connection) == []
    assert len(gallery.gallery_list_assets(connection, include_deleted=True)) == 1
    assert len(gallery.gallery_list_recycled(connection)) == 1


def test_paging_for_large_libraries(archive):
    """Limit and offset support virtualized grids."""
    paths, connection = archive
    items = {f"/DCIM/IMG_{index:03d}.HEIC": bytes([index]) for index in range(10)}
    importer.importer_run(connection, paths, FakeDevice(items))

    first_page = gallery.gallery_list_assets(connection, limit=4, offset=0)
    second_page = gallery.gallery_list_assets(connection, limit=4, offset=4)

    assert len(first_page) == 4
    assert len(second_page) == 4
    assert {view.asset_id for view in first_page}.isdisjoint(
        {view.asset_id for view in second_page}
    )


def test_absolute_path_resolution(archive):
    """Stored paths resolve to real files for viewing."""
    paths, connection = archive
    importer.importer_run(connection, paths, FakeDevice({"/DCIM/A.HEIC": b"a"}))
    view = gallery.gallery_list_assets(connection)[0]

    absolute = gallery.gallery_absolute_path(paths, view.paths[0])

    assert view.paths[0] in absolute.replace("\\", "/")
    assert (paths.root / view.paths[0]).is_file()


def test_empty_archive_lists_nothing(archive):
    """An empty archive returns empty listings."""
    paths, connection = archive
    assert gallery.gallery_list_assets(connection) == []
    assert gallery.gallery_count_assets(connection) == 0
