"""End-to-end tests over the full pipeline with the fake device.

These are the tests that protect the product promises: byte-for-byte
preservation, append-only behaviour, idempotent incremental imports, and safe
recovery from an interrupted run. They exercise the real service, core, and
catalog layers together — only the phone is faked.
"""

from __future__ import annotations

import hashlib

import pytest

from iphone_archive.catalog import repository, sidecar
from iphone_archive.core import importer
from iphone_archive.device.fake_device import FakeDevice
from iphone_archive.service.app_service import AppService

MEDIA = {
    "/DCIM/IMG_0001.HEIC": b"first-photo-bytes",
    "/DCIM/IMG_0002.HEIC": b"second-photo-bytes",
    "/DCIM/IMG_0003.MOV": b"a-little-video",
}
ALBUMS = {
    "/DCIM/IMG_0001.HEIC": ["Trip 2024"],
    "/DCIM/IMG_0002.HEIC": ["Trip 2024", "Favourites"],
}


def helper_device() -> FakeDevice:
    """Build the standard fake phone used by these tests."""
    device = FakeDevice(dict(MEDIA), album_map={k: list(v) for k, v in ALBUMS.items()})
    device.metadata = {path: {"modified_at": "2026-01-01T12:00:00"} for path in MEDIA}
    return device


def helper_archive_files(service: AppService) -> dict[str, bytes]:
    """Snapshot every stored media file as archive-relative path to content."""
    _, paths = service.app_service_require()
    snapshot = {}
    for stored in paths.photos_dir.rglob("*"):
        if stored.is_file():
            snapshot[stored.relative_to(paths.root).as_posix()] = stored.read_bytes()
    return snapshot


@pytest.fixture
def service(tmp_path):
    """A service bound to a freshly initialized archive."""
    instance = AppService(tmp_path / "archive")
    instance.app_service_initialize()
    yield instance
    instance.app_service_close()


def test_golden_end_to_end(service, tmp_path):
    """A full lifecycle keeps every archive invariant intact."""
    device = helper_device()

    first = service.app_service_import(device)
    assert (first.added_count, first.error_count) == (3, 0)

    # Byte-for-byte preservation of every original.
    stored = helper_archive_files(service)
    stored_hashes = {hashlib.sha256(content).hexdigest() for content in stored.values()}
    source_hashes = {hashlib.sha256(content).hexdigest() for content in MEDIA.values()}
    assert source_hashes == stored_hashes

    # Album folders are real, self-contained directories; album-less goes to _Unsorted.
    _, paths = service.app_service_require()
    assert sorted(entry.name for entry in paths.photos_dir.iterdir()) == [
        "Favourites",
        "Trip 2024",
        "_Unsorted",
    ]
    assert any("_Unsorted" in path for path in stored)

    # No symlinks anywhere, so the archive survives a copy to another filesystem.
    assert not any(entry.is_symlink() for entry in paths.root.rglob("*"))

    assert service.app_service_verify().passed

    # A second import transfers nothing.
    second = service.app_service_import(device)
    assert (second.added_count, second.duplicate_count) == (0, 0)
    assert second.skipped_count == 3
    assert helper_archive_files(service) == stored

    # Deleting on the phone never touches the archive.
    device.items.pop("/DCIM/IMG_0002.HEIC")
    service.app_service_scan_phone(device)
    review = service.app_service_deleted_on_phone()
    assert review.count == 1
    assert helper_archive_files(service) == stored

    # The user chooses the recycle bin; content is preserved, browsing excludes it.
    target = review.items[0].asset_id
    service.app_service_move_to_deleted([target])
    assert len(service.app_service_list_recycled()) == 1
    recycled_files = list(paths.deleted_dir.rglob("*.heic"))
    assert recycled_files and recycled_files[0].read_bytes() == MEDIA["/DCIM/IMG_0002.HEIC"]

    # Or purges permanently, but only with confirmation.
    assert service.app_service_purge([target]).purged_count == 0
    assert service.app_service_purge([target], confirmed=True).purged_count == 1
    assert list(paths.deleted_dir.rglob("*.heic")) == []

    # Reclaim frees phone space only for verified assets, never the archive.
    before = helper_archive_files(service)
    reclaimed = service.app_service_reclaim(device, confirmed=True)
    assert reclaimed.deleted_count == 2
    assert device.items == {}
    assert helper_archive_files(service) == before


def test_catalog_and_sidecars_stay_consistent(service):
    """Every asset has a unique hash, stored files, and a matching sidecar."""
    service.app_service_import(helper_device())
    connection, paths = service.app_service_require()

    hashes = [row["sha256"] for row in connection.execute("SELECT sha256 FROM assets")]
    assert len(hashes) == len(set(hashes)) == 3

    for asset_hash in hashes:
        record = sidecar.sidecar_read(paths.sidecars_dir, asset_hash)
        assert record.sha256 == asset_hash
        assert record.size > 0

    for stored in repository.repository_all_asset_files(connection):
        assert (paths.root / stored.path).is_file()


def test_album_added_later_is_appended(service):
    """Adding an album on the phone adds a copy without moving existing files."""
    device = FakeDevice({"/DCIM/IMG_0001.HEIC": b"first-photo-bytes"})
    service.app_service_import(device)
    before = helper_archive_files(service)

    device.albums["/DCIM/IMG_0001.HEIC"] = ["Later Album"]
    service.app_service_import(device)

    after = helper_archive_files(service)
    assert set(before).issubset(set(after))
    assert len(after) == len(before) + 1
    assert any("Later Album" in path for path in after)


def test_crash_mid_import_leaves_no_partial_state(service, monkeypatch, tmp_path):
    """An import that dies mid-asset commits nothing partial and resumes cleanly."""
    device = helper_device()
    real_process = importer.importer_process_item
    calls = {"count": 0}

    def failing_process(*args, **kwargs):
        """Fail while storing the third asset, simulating a crash."""
        calls["count"] += 1
        if calls["count"] == 3:
            raise OSError("simulated crash")
        return real_process(*args, **kwargs)

    monkeypatch.setattr(importer, "importer_process_item", failing_process)
    crashed = service.app_service_import(device)
    assert crashed.error_count == 1
    assert crashed.added_count == 2

    _, paths = service.app_service_require()
    # No staged temp file and no committed partial copy survive the failure.
    assert list(paths.temp_dir.iterdir()) == []
    connection, _ = service.app_service_require()
    for stored in repository.repository_all_asset_files(connection):
        assert (paths.root / stored.path).is_file()

    monkeypatch.setattr(importer, "importer_process_item", real_process)
    resumed = service.app_service_import(device)
    assert resumed.added_count == 1
    assert resumed.error_count == 0
    assert service.app_service_verify().passed

    # The resumed archive equals an uninterrupted one.
    reference = AppService(tmp_path / "reference")
    reference.app_service_initialize()
    reference.app_service_import(helper_device())
    assert helper_archive_files(service) == helper_archive_files(reference)
    reference.app_service_close()


def test_interrupted_import_is_idempotent_on_hashes(service):
    """Re-running after any interruption never duplicates catalog rows."""
    device = helper_device()
    service.app_service_import(device)
    service.app_service_import(device)
    service.app_service_import(device)

    connection, _ = service.app_service_require()
    rows = connection.execute("SELECT COUNT(*) AS total FROM assets").fetchone()
    assert rows["total"] == 3
