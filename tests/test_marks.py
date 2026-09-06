"""Tests for mark-for-delete staging and multi-select operations."""

from __future__ import annotations

import pytest

from iphone_archive.catalog import repository
from iphone_archive.device.fake_device import FakeDevice
from iphone_archive.service import marks, selection
from iphone_archive.service.app_service import AppService


@pytest.fixture
def service(tmp_path):
    """A service bound to a freshly initialized archive."""
    instance = AppService(tmp_path / "archive")
    instance.app_service_initialize()
    yield instance
    instance.app_service_close()


def test_mark_album_expands_to_members(service):
    """Marking an album stages all of its assets for deletion."""
    device = FakeDevice(
        {"/DCIM/A.HEIC": b"a", "/DCIM/B.HEIC": b"b"},
        album_map={"/DCIM/A.HEIC": ["Trip"], "/DCIM/B.HEIC": ["Trip"]},
    )
    service.app_service_import(device)
    connection, _ = service.app_service_require()
    album_id = repository.repository_list_albums(connection)[0].album_id

    service.app_service_mark(marks.TARGET_ALBUM, album_id)

    assert len(marks.marks_resolve_asset_ids(connection)) == 2


def test_marks_are_deduplicated(service):
    """Marking the same asset twice yields one target."""
    service.app_service_import(FakeDevice({"/DCIM/A.HEIC": b"a"}))
    connection, _ = service.app_service_require()
    asset_id = service.app_service_list_assets()[0].asset_id

    service.app_service_mark_many([asset_id])
    service.app_service_mark_many([asset_id])

    assert marks.marks_resolve_asset_ids(connection) == [asset_id]


def test_clear_removes_all_marks(service):
    """Clearing removes every staged mark."""
    service.app_service_import(FakeDevice({"/DCIM/A.HEIC": b"a"}))
    connection, _ = service.app_service_require()
    service.app_service_mark_many([service.app_service_list_assets()[0].asset_id])

    removed = marks.marks_clear(connection)

    assert removed == 1
    assert marks.marks_list_pending(connection) == []


def test_commit_marks_can_purge(service):
    """Committing with purge permanently removes the marked assets."""
    service.app_service_import(FakeDevice({"/DCIM/A.HEIC": b"a"}))
    asset_id = service.app_service_list_assets()[0].asset_id
    service.app_service_mark_many([asset_id])

    result = service.app_service_commit_marks(confirmed=True, purge=True)

    assert result.purged_count == 1
    assert service.app_service_list_assets(include_deleted=True) == []


def test_move_selection_applies_to_all(service):
    """A batch move affects every selected asset."""
    service.app_service_import(FakeDevice({"/DCIM/A.HEIC": b"a", "/DCIM/B.HEIC": b"b"}))
    asset_ids = [view.asset_id for view in service.app_service_list_assets()]

    result = service.app_service_move_selection(asset_ids, "Sorted")

    assert result.affected_count == 2
    for view in service.app_service_list_assets():
        assert any("Sorted" in path for path in view.paths)


def test_move_selection_preserves_content(service):
    """Moving changes placement but never file content."""
    service.app_service_import(FakeDevice({"/DCIM/A.HEIC": b"exact-bytes"}))
    view = service.app_service_list_assets()[0]

    service.app_service_move_selection([view.asset_id], "Elsewhere")

    connection, paths = service.app_service_require()
    moved = service.app_service_list_assets()[0]
    assert (paths.root / moved.paths[0]).read_bytes() == b"exact-bytes"


def test_move_selection_skips_missing_files(service):
    """An asset whose file is gone is skipped, not crashed on."""
    service.app_service_import(FakeDevice({"/DCIM/A.HEIC": b"a"}))
    connection, paths = service.app_service_require()
    view = service.app_service_list_assets()[0]
    (paths.root / view.paths[0]).unlink()

    result = service.app_service_move_selection([view.asset_id], "Elsewhere")

    assert result.skipped_count == 1
    assert result.affected_count == 0


def test_selection_helpers(service):
    """Selection helpers expose album membership and total size."""
    device = FakeDevice({"/DCIM/A.HEIC": b"12345"}, album_map={"/DCIM/A.HEIC": ["Trip"]})
    service.app_service_import(device)
    connection, _ = service.app_service_require()
    album_id = repository.repository_list_albums(connection)[0].album_id

    asset_ids = selection.selection_asset_ids_in_album(connection, album_id)

    assert len(asset_ids) == 1
    assert selection.selection_total_size(connection, asset_ids) == 5
    assert selection.selection_total_size(connection, []) == 0
