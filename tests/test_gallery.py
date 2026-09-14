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


def test_partial_recycle_filters_paths_and_album_counts(archive):
    """A shared asset can be active in one album and recycled in another."""
    from iphone_archive.core.albums import albums_list

    paths, connection = archive
    importer.importer_run(
        connection,
        paths,
        FakeDevice({"/DCIM/A.HEIC": b"a"}, album_map={"/DCIM/A.HEIC": ["Trip", "Family"]}),
    )
    connection.execute(
        "UPDATE asset_files SET location = 'deleted', path = replace(path, 'Photos/', 'Deleted/') "
        "WHERE album_id = (SELECT id FROM albums WHERE name = 'Trip')"
    )
    connection.commit()
    active = gallery.gallery_list_assets(connection)
    deleted = gallery.gallery_list_recycled(connection)
    assert len(active) == len(deleted) == 1
    assert all(path.startswith("Photos/Family/") for path in active[0].paths)
    assert all(path.startswith("Deleted/Trip/") for path in deleted[0].paths)
    summaries = {album.name: album.asset_count for album in albums_list(connection)}
    assert summaries == {"Family": 1, "Trip": 0}


def test_offset_without_limit_and_negative_paging(archive):
    """Paging always honors its offset and rejects invalid bounds."""
    paths, connection = archive
    importer.importer_run(
        connection, paths, FakeDevice({"/DCIM/A.HEIC": b"a", "/DCIM/B.HEIC": b"b"})
    )
    assert len(gallery.gallery_list_assets(connection, offset=1)) == 1
    with pytest.raises(ValueError):
        gallery.gallery_list_assets(connection, limit=-1)


@pytest.mark.parametrize("listing", [gallery.gallery_list_unsorted, gallery.gallery_list_recycled])
def test_special_scopes_have_stable_bounded_pages(archive, listing):
    paths, connection = archive
    importer.importer_run(
        connection,
        paths,
        FakeDevice({f"/DCIM/{index}/same.jpg": bytes([index]) for index in range(5)}),
    )
    if listing is gallery.gallery_list_recycled:
        identifiers = [view.asset_id for view in gallery.gallery_list_assets(connection)]
        recycle.recycle_move_to_deleted(connection, paths, identifiers)
    whole = listing(connection)
    pages = [view for offset in (0, 2, 4) for view in listing(connection, limit=2, offset=offset)]
    assert [view.asset_id for view in pages] == [view.asset_id for view in whole]
    assert len({view.asset_id for view in pages}) == 5
    assert listing(connection, limit=0) == []
    assert listing(connection, offset=2) == whole[2:]
    for limit, offset in [(-1, 0), (None, -1), (True, 0), (1, 0.5)]:
        with pytest.raises(ValueError):
            listing(connection, limit=limit, offset=offset)
