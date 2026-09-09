"""Tests for the headless service facade shared by the CLI and GUI."""

from __future__ import annotations

import pytest

from iphone_archive.device.fake_device import FakeDevice
from iphone_archive.service.app_service import AppService, ArchiveNotFoundError
from iphone_archive.service.progress import ProgressHandle


@pytest.fixture
def service(tmp_path):
    """A service bound to a freshly initialized archive."""
    instance = AppService(tmp_path / "archive")
    instance.app_service_initialize()
    yield instance
    instance.app_service_close()


def test_open_missing_archive_raises(tmp_path):
    """Opening a non-archive folder fails clearly."""
    with pytest.raises(ArchiveNotFoundError):
        AppService(tmp_path / "nope").app_service_open()


def test_initialize_then_open(tmp_path):
    """An initialized archive can be reopened."""
    first = AppService(tmp_path / "archive")
    first.app_service_initialize()
    first.app_service_close()

    second = AppService(tmp_path / "archive")
    assert second.app_service_open().internal_dir.is_dir()
    second.app_service_close()


def test_import_and_stats(service):
    """Import runs through the facade and is reflected in stats."""
    result = service.app_service_import(FakeDevice({"/DCIM/A.HEIC": b"a"}))
    assert result.added_count == 1

    stats = service.app_service_stats()
    assert stats["assets"] == 1
    assert stats["files"] == 1
    assert stats["unsorted"] == 1


def test_verify_through_facade(service):
    """Verification is available from the facade."""
    service.app_service_import(FakeDevice({"/DCIM/A.HEIC": b"a"}))
    assert service.app_service_verify().passed


def test_dedup_report_through_facade(service):
    """Dedup reporting is available from the facade."""
    device = FakeDevice({"/DCIM/A.HEIC": b"a"}, album_map={"/DCIM/A.HEIC": ["X", "Y"]})
    service.app_service_import(device)
    assert len(service.app_service_dedup_report().multi_copy_groups) == 1


def test_browse_albums_and_assets(service):
    """Album and asset browsing is available from the facade."""
    device = FakeDevice({"/DCIM/A.HEIC": b"a"}, album_map={"/DCIM/A.HEIC": ["Trip"]})
    service.app_service_import(device)

    album_list = service.app_service_list_albums()
    assert album_list[0].name == "Trip"
    assert len(service.app_service_list_assets(album_id=album_list[0].album_id)) == 1


def test_deleted_on_phone_workflow(service):
    """Scan, review, and recycle the deleted-from-phone assets."""
    service.app_service_import(FakeDevice({"/DCIM/A.HEIC": b"a", "/DCIM/B.HEIC": b"b"}))
    service.app_service_scan_phone(FakeDevice({"/DCIM/A.HEIC": b"a"}))

    review = service.app_service_deleted_on_phone()
    assert review.count == 1

    service.app_service_move_to_deleted([review.items[0].asset_id])
    assert len(service.app_service_list_recycled()) == 1
    assert service.app_service_deleted_on_phone().count == 0


def test_restore_from_recycle_bin(service):
    """Recycled assets can be restored through the facade."""
    service.app_service_import(FakeDevice({"/DCIM/A.HEIC": b"a"}))
    asset_id = service.app_service_list_assets()[0].asset_id
    service.app_service_move_to_deleted([asset_id])

    service.app_service_restore([asset_id])

    assert service.app_service_list_recycled() == []
    assert len(service.app_service_list_assets()) == 1


def test_purge_requires_confirmation(service):
    """Purge through the facade is confirmation-gated."""
    service.app_service_import(FakeDevice({"/DCIM/A.HEIC": b"a"}))
    asset_id = service.app_service_list_assets()[0].asset_id

    assert service.app_service_purge([asset_id]).purged_count == 0
    assert service.app_service_purge([asset_id], confirmed=True).purged_count == 1
    assert service.app_service_list_assets() == []


def test_reclaim_dry_run_and_confirm(service):
    """Reclaim defaults to a dry run and deletes only when confirmed."""
    device = FakeDevice({"/DCIM/A.HEIC": b"a"})
    service.app_service_import(device)

    dry = service.app_service_reclaim(device)
    assert dry.dry_run and device.deleted_paths == []

    confirmed = service.app_service_reclaim(device, confirmed=True)
    assert confirmed.deleted_count == 1
    assert device.deleted_paths == ["/DCIM/A.HEIC"]


def test_mark_then_commit_recycles(service):
    """Marks stage without deleting, then commit recycles the assets."""
    service.app_service_import(FakeDevice({"/DCIM/A.HEIC": b"a"}))
    asset_id = service.app_service_list_assets()[0].asset_id

    service.app_service_mark_many([asset_id], reason="blurry")
    assert len(service.app_service_list_marks()) == 1
    assert len(service.app_service_list_assets()) == 1

    service.app_service_commit_marks(confirmed=True)

    assert service.app_service_list_marks() == []
    assert len(service.app_service_list_recycled()) == 1


def test_commit_without_confirmation_does_nothing(service):
    """An unconfirmed commit leaves marks and files untouched."""
    service.app_service_import(FakeDevice({"/DCIM/A.HEIC": b"a"}))
    asset_id = service.app_service_list_assets()[0].asset_id
    service.app_service_mark_many([asset_id])

    service.app_service_commit_marks(confirmed=False)

    assert len(service.app_service_list_marks()) == 1
    assert len(service.app_service_list_assets()) == 1


def test_unmark_cancels_intent(service):
    """A staged mark can be cancelled."""
    service.app_service_import(FakeDevice({"/DCIM/A.HEIC": b"a"}))
    asset_id = service.app_service_list_assets()[0].asset_id
    mark_id = service.app_service_mark("asset", asset_id)

    service.app_service_unmark(mark_id)

    assert service.app_service_list_marks() == []


def test_move_selection_between_albums(service):
    """A multi-selection moves to another album without changing content."""
    device = FakeDevice({"/DCIM/A.HEIC": b"payload"}, album_map={"/DCIM/A.HEIC": ["Trip"]})
    service.app_service_import(device)
    asset_id = service.app_service_list_assets()[0].asset_id

    result = service.app_service_move_selection([asset_id], "Favorites")

    assert result.affected_count == 1
    view = service.app_service_list_assets()[0]
    assert any("Favorites" in path for path in view.paths)
    _, paths = service.app_service_require()
    assert (paths.root / view.paths[0]).read_bytes() == b"payload"


def test_progress_handle_shared_by_operations(service):
    """Operations report progress through the shared handle."""
    handle = ProgressHandle()
    service.app_service_import(FakeDevice({"/DCIM/A.HEIC": b"a"}), progress=handle)
    assert handle.events


def test_facade_exposes_every_operation():
    """The facade covers all product operations, guaranteeing CLI/GUI parity."""
    expected = {
        "app_service_initialize",
        "app_service_open",
        "app_service_import",
        "app_service_verify",
        "app_service_dedup_report",
        "app_service_list_albums",
        "app_service_list_assets",
        "app_service_list_unsorted",
        "app_service_list_recycled",
        "app_service_scan_phone",
        "app_service_deleted_on_phone",
        "app_service_move_to_deleted",
        "app_service_restore",
        "app_service_purge",
        "app_service_reclaim",
        "app_service_mark",
        "app_service_mark_many",
        "app_service_list_marks",
        "app_service_unmark",
        "app_service_commit_marks",
        "app_service_move_selection",
        "app_service_stats",
    }
    assert expected.issubset(set(dir(AppService)))


def test_archive_session_is_exclusive_and_released(service):
    """A second process/service cannot mutate files during the owner's transaction."""
    from iphone_archive.service.archive_lock import ArchiveBusyError

    competing = AppService(service.archive_root)
    with pytest.raises(ArchiveBusyError):
        competing.app_service_open()
    service.app_service_close()
    competing.app_service_open()
    competing.app_service_close()


def test_cross_thread_service_access_is_rejected_before_sqlite(service):
    """A GUI must marshal work instead of sharing a connection with its workers."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as executor:
        with pytest.raises(RuntimeError, match="owning worker thread"):
            executor.submit(service.app_service_stats).result()
    assert service.app_service_stats()["assets"] == 0
