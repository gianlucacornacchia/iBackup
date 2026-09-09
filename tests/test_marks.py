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


def test_move_selection_rejects_missing_files(service):
    """Missing bytes abort the batch explicitly rather than mutating the catalog."""
    service.app_service_import(FakeDevice({"/DCIM/A.HEIC": b"a"}))
    connection, paths = service.app_service_require()
    view = service.app_service_list_assets()[0]
    (paths.root / view.paths[0]).unlink()

    with pytest.raises(FileNotFoundError):
        service.app_service_move_selection([view.asset_id], "Elsewhere")
    assert (
        repository.repository_list_asset_files(connection, view.asset_id)[0].path == view.paths[0]
    )


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


@pytest.mark.parametrize("purge", [False, True])
def test_shared_album_mark_only_removes_album_copy(service, purge):
    """US-G5 keeps the other album's copy and the shared asset alive."""
    service.app_service_import(
        FakeDevice({"/DCIM/A.HEIC": b"shared"}, album_map={"/DCIM/A.HEIC": ["Trip", "Family"]})
    )
    connection, paths = service.app_service_require()
    asset_id = service.app_service_list_assets()[0].asset_id
    album_id = next(
        album.album_id
        for album in repository.repository_list_albums(connection)
        if album.name == "Trip"
    )
    marks.marks_add(connection, marks.TARGET_ALBUM, album_id)
    result = marks.marks_commit(connection, True, paths=paths, purge=purge)
    assert result.committed_count == 1
    assert len(result.file_ids) == 1
    asset = repository.repository_get_asset(connection, asset_id)
    assert asset.archive_state.value == "active"
    files = repository.repository_list_asset_files(connection, asset_id)
    active = [stored for stored in files if stored.location.value == "photos"]
    assert len(active) == 1
    assert "Family" in active[0].path
    assert (paths.root / active[0].path).read_bytes() == b"shared"
    assert marks.marks_list_pending(connection) == []


def test_mark_failure_remains_pending_for_retry(service, monkeypatch):
    """Filesystem failure rolls back deletion and leaves marks retryable."""
    from iphone_archive.core import file_operations

    service.app_service_import(FakeDevice({"/DCIM/A.HEIC": b"first", "/DCIM/B.HEIC": b"second"}))
    connection, paths = service.app_service_require()
    asset_ids = [view.asset_id for view in service.app_service_list_assets()]
    marks.marks_add_many(connection, asset_ids)
    original = file_operations.file_operations_copy
    calls = 0

    def fail_second(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated disk failure")
        original(source, destination)

    monkeypatch.setattr(file_operations, "file_operations_copy", fail_second)
    with pytest.raises(OSError, match="simulated"):
        marks.marks_commit(connection, True, paths=paths)
    assert len(marks.marks_list_pending(connection)) == 2
    assert all(
        (paths.root / stored.path).is_file()
        for stored in repository.repository_all_asset_files(connection)
    )
    monkeypatch.setattr(file_operations, "file_operations_copy", original)
    assert marks.marks_commit(connection, True, paths=paths).recycle_result.moved_count == 2


def test_mark_many_validates_all_before_staging(service):
    """A bad final selection id does not leave a partial mark queue."""
    service.app_service_import(FakeDevice({"/DCIM/A.HEIC": b"a"}))
    connection, _ = service.app_service_require()
    asset_id = service.app_service_list_assets()[0].asset_id
    with pytest.raises(ValueError, match="Unknown asset"):
        marks.marks_add_many(connection, [asset_id, 99999])
    assert marks.marks_list_pending(connection) == []


def test_file_mark_keeps_other_album_copy(service):
    """US-G4 can target just the picture copy shown in the current album."""
    service.app_service_import(
        FakeDevice({"/DCIM/A.HEIC": b"a"}, album_map={"/DCIM/A.HEIC": ["Trip", "Family"]})
    )
    connection, paths = service.app_service_require()
    files = repository.repository_all_asset_files(connection)
    marks.marks_add(connection, marks.TARGET_FILE, files[0].file_id)
    marks.marks_commit(connection, True, paths=paths, purge=True)
    assert [stored.file_id for stored in repository.repository_all_asset_files(connection)] == [
        files[1].file_id
    ]
