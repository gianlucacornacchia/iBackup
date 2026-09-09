"""Partial lifecycle, preflight and crash-recovery tests for archive deletion."""

from __future__ import annotations

import errno
import json
import os
import stat
import subprocess
import sys

import pytest

from iphone_archive.catalog import database, repository, sidecar
from iphone_archive.core import file_operations, recycle
from iphone_archive.device.fake_device import FakeDevice
from iphone_archive.service.app_service import AppService


@pytest.fixture
def archive(tmp_path):
    """Import one shared asset and return a live service."""
    service = AppService(tmp_path / "archive")
    service.app_service_initialize()
    service.app_service_import(
        FakeDevice({"/DCIM/A.HEIC": b"shared"}, album_map={"/DCIM/A.HEIC": ["Trip", "Family"]})
    )
    yield service
    service.app_service_close()


def test_partial_recycle_restore_updates_state_memberships_and_sidecar(archive):
    connection, paths = archive.app_service_require()
    files = repository.repository_all_asset_files(connection)
    asset_id = files[0].asset_id
    recycle.recycle_move_to_deleted(connection, paths, [asset_id], file_ids=[files[0].file_id])
    asset = repository.repository_get_asset(connection, asset_id)
    assert asset.archive_state.value == "active"
    assert recycle.recycle_list_deleted(connection) == [asset_id]
    metadata = sidecar.sidecar_read(paths.sidecars_dir, asset.sha256)
    assert metadata.archive_state == "active"
    assert metadata.albums == ["Family"]
    assert {entry["location"] for entry in metadata.files} == {"photos", "deleted"}
    restored = recycle.recycle_restore(connection, paths, [asset_id])
    assert restored.restored_count == 1
    assert recycle.recycle_list_deleted(connection) == []
    assert set(sidecar.sidecar_read(paths.sidecars_dir, asset.sha256).albums) == {"Trip", "Family"}


def test_partial_purge_keeps_shared_asset_and_metadata(archive):
    connection, paths = archive.app_service_require()
    files = repository.repository_all_asset_files(connection)
    asset_id = files[0].asset_id
    recycle.recycle_purge(connection, paths, [asset_id], True, file_ids=[files[0].file_id])
    asset = repository.repository_get_asset(connection, asset_id)
    assert asset is not None
    assert len(repository.repository_list_asset_files(connection, asset_id)) == 1
    assert sidecar.sidecar_read(paths.sidecars_dir, asset.sha256).files[0]["path"] == files[1].path
    recycle.recycle_purge(connection, paths, [asset_id], True)
    assert repository.repository_get_asset(connection, asset_id) is None
    assert not sidecar.sidecar_path_for(paths.sidecars_dir, asset.sha256).exists()


def test_recycled_only_purge_retains_surviving_photos_copy(archive):
    connection, paths = archive.app_service_require()
    files = repository.repository_all_asset_files(connection)
    asset_id = files[0].asset_id
    recycle.recycle_move_to_deleted(connection, paths, [asset_id], file_ids=[files[0].file_id])
    result = recycle.recycle_purge(
        connection, paths, [asset_id], confirmed=True, recycled_only=True
    )
    assert result.purged_count == 1
    remaining = repository.repository_list_asset_files(connection, asset_id)
    assert [stored.file_id for stored in remaining] == [files[1].file_id]
    assert (paths.root / remaining[0].path).read_bytes() == b"shared"
    assert repository.repository_get_asset(connection, asset_id).archive_state.value == "active"


def test_recycled_only_purge_rejects_explicit_photos_file_scope(archive):
    connection, paths = archive.app_service_require()
    files = repository.repository_all_asset_files(connection)
    with pytest.raises(ValueError, match="Selected file ids"):
        recycle.recycle_purge(
            connection,
            paths,
            [files[0].asset_id],
            confirmed=True,
            file_ids=[files[0].file_id],
            recycled_only=True,
        )
    assert repository.repository_all_asset_files(connection) == files


@pytest.mark.parametrize("operation", ["recycle", "restore", "purge"])
def test_missing_copy_aborts_every_operation(archive, operation):
    connection, paths = archive.app_service_require()
    asset_id = repository.repository_all_asset_files(connection)[0].asset_id
    if operation == "restore":
        recycle.recycle_move_to_deleted(connection, paths, [asset_id])
    files = repository.repository_all_asset_files(connection)
    (paths.root / files[-1].path).unlink()
    with pytest.raises(FileNotFoundError):
        recycle.recycle_apply(connection, paths, [asset_id], operation)
    assert repository.repository_all_asset_files(connection) == files
    assert (paths.root / files[0].path).is_file()


def test_purge_failure_retains_originals_and_catalog(archive, monkeypatch):
    connection, paths = archive.app_service_require()
    files = repository.repository_all_asset_files(connection)
    original = file_operations.file_operations_copy
    calls = 0

    def fail_second(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk full")
        original(source, destination)

    monkeypatch.setattr(file_operations, "file_operations_copy", fail_second)
    with pytest.raises(OSError, match="disk full"):
        recycle.recycle_purge(connection, paths, [files[0].asset_id], True)
    assert repository.repository_all_asset_files(connection) == files
    assert all((paths.root / stored.path).read_bytes() == b"shared" for stored in files)


def test_unowned_identical_destination_is_never_deleted_on_rollback(archive, monkeypatch):
    """Matching bytes alone do not establish ownership of a colliding path."""
    connection, paths = archive.app_service_require()
    files = repository.repository_all_asset_files(connection)
    original = file_operations.file_operations_publish
    collisions = []

    def collide_before_publication(source, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        collisions.append(destination)
        original(source, destination)

    monkeypatch.setattr(file_operations, "file_operations_publish", collide_before_publication)
    with pytest.raises(RuntimeError, match="destination ownership"):
        recycle.recycle_move_to_deleted(connection, paths, [files[0].asset_id])
    assert repository.repository_all_asset_files(connection) == files
    assert all((paths.root / stored.path).read_bytes() == b"shared" for stored in files)
    assert collisions[0].read_bytes() == b"shared"
    with pytest.raises(RuntimeError, match="destination ownership"):
        file_operations.file_operations_recover(connection, paths)
    assert collisions[0].read_bytes() == b"shared"
    collisions[0].unlink()
    file_operations.file_operations_recover(connection, paths)


def test_partial_owned_copy_is_preserved_outside_browsable_folders(archive, monkeypatch):
    """Disk failure inside copying rolls back and preserves partial bytes for inspection."""
    connection, paths = archive.app_service_require()
    files = repository.repository_all_asset_files(connection)

    def partial_copy(reader, writer):
        writer.write(reader.read(1))
        writer.flush()
        raise OSError("interrupted write")

    monkeypatch.setattr(file_operations.shutil, "copyfileobj", partial_copy)
    with pytest.raises(OSError, match="interrupted write"):
        recycle.recycle_move_to_deleted(connection, paths, [files[0].asset_id])
    assert repository.repository_all_asset_files(connection) == files
    assert all((paths.root / stored.path).read_bytes() == b"shared" for stored in files)
    conflicts = list((paths.internal_dir / "operation_conflicts").glob("*/*"))
    assert len(conflicts) == 1
    assert conflicts[0].read_bytes() == b"s"
    assert not list(paths.deleted_dir.rglob("*.heic"))


@pytest.mark.parametrize("operation", ["recycle", "restore", "purge"])
@pytest.mark.parametrize("phase", ["write", "file_fsync", "directory_fsync"])
@pytest.mark.parametrize("claim_number", [1, 2])
def test_ownership_persistence_failure_rolls_back_and_reopens(
    archive, monkeypatch, operation, phase, claim_number
):
    """No final path is exposed until the staged inode has durable ownership."""
    if phase == "directory_fsync" and os.name == "nt":
        pytest.skip("Windows does not expose directory fsync")
    connection, paths = archive.app_service_require()
    asset_id = repository.repository_all_asset_files(connection)[0].asset_id
    if operation == "restore":
        recycle.recycle_move_to_deleted(connection, paths, [asset_id])
    before = repository.repository_all_asset_files(connection)
    original_write = file_operations.file_operations_write_journal
    original_fsync = os.fsync
    claiming = False
    claims = 0

    def failing_write(journal, payload):
        nonlocal claiming, claims
        if journal.suffix == ".owner":
            claims += 1
        claiming = journal.suffix == ".owner" and claims == claim_number
        try:
            if claiming and phase == "write":
                raise OSError(errno.ENOSPC, "ownership write failed")
            original_write(journal, payload)
        finally:
            claiming = False

    def failing_fsync(descriptor):
        directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
        if claiming and (
            (phase == "file_fsync" and not directory) or (phase == "directory_fsync" and directory)
        ):
            raise OSError(errno.ENOSPC, "ownership fsync failed")
        original_fsync(descriptor)

    monkeypatch.setattr(file_operations, "file_operations_write_journal", failing_write)
    monkeypatch.setattr(os, "fsync", failing_fsync)
    with pytest.raises(OSError, match="ownership"):
        recycle.recycle_apply(connection, paths, [asset_id], operation)
    assert repository.repository_all_asset_files(connection) == before
    archive.app_service_close()
    archive.app_service_open()
    connection, paths = archive.app_service_require()
    assert repository.repository_all_asset_files(connection) == before
    assert all((paths.root / stored.path).read_bytes() == b"shared" for stored in before)
    assert not list((paths.internal_dir / "operations").glob("*.json"))


def test_persistent_journal_failure_recovers_after_disk_becomes_writable(archive, monkeypatch):
    """Even failed immediate housekeeping cannot turn private staging into an orphan."""
    connection, paths = archive.app_service_require()
    before = repository.repository_all_asset_files(connection)
    original_write = file_operations.file_operations_write_journal
    disk_full = False

    def failing_write(journal, payload):
        nonlocal disk_full
        disk_full = disk_full or journal.suffix == ".owner"
        if disk_full:
            raise OSError(errno.ENOSPC, "disk full")
        original_write(journal, payload)

    monkeypatch.setattr(file_operations, "file_operations_write_journal", failing_write)
    with pytest.raises(OSError, match="disk full"):
        recycle.recycle_move_to_deleted(connection, paths, [before[0].asset_id])
    assert list((paths.internal_dir / "operations").glob("*.json"))
    archive.app_service_close()
    monkeypatch.setattr(file_operations, "file_operations_write_journal", original_write)
    archive.app_service_open()
    connection, paths = archive.app_service_require()
    assert repository.repository_all_asset_files(connection) == before
    assert all((paths.root / stored.path).read_bytes() == b"shared" for stored in before)
    assert not list((paths.internal_dir / "operations").glob("*.json"))


@pytest.mark.parametrize("operation", ["recycle", "restore", "purge"])
@pytest.mark.parametrize("checkpoint", ["created", "published", "stage_removed"])
def test_process_death_in_staging_and_publication_windows(archive, operation, checkpoint):
    """Bypass every finally block at the creation gap, publication and housekeeping."""
    if operation == "purge" and checkpoint == "published":
        pytest.skip("Purge does not publish a final media name")
    connection, paths = archive.app_service_require()
    asset_id = repository.repository_all_asset_files(connection)[0].asset_id
    if operation == "restore":
        recycle.recycle_move_to_deleted(connection, paths, [asset_id])
    before = repository.repository_all_asset_files(connection)
    archive.app_service_close()
    program = """
import os
import sys
from pathlib import Path
from iphone_archive.catalog import repository
from iphone_archive.core import file_operations, recycle
from iphone_archive.service.app_service import AppService
service = AppService(Path(sys.argv[1]))
connection, paths = service.app_service_require()
checkpoint = sys.argv[3]
if checkpoint == "created":
    original = Path.open
    def crash_after_create(path, mode="r", *args, **kwargs):
        handle = original(path, mode, *args, **kwargs)
        if mode == "xb" and path.suffix == ".data":
            os._exit(72)
        return handle
    Path.open = crash_after_create
elif checkpoint == "published":
    original = file_operations.file_operations_publish
    def crash_after_publish(staged, destination):
        original(staged, destination)
        os._exit(72)
    file_operations.file_operations_publish = crash_after_publish
else:
    original = file_operations.file_operations_remove_stage
    def crash_after_cleanup(stage, count):
        original(stage, count)
        os._exit(72)
    file_operations.file_operations_remove_stage = crash_after_cleanup
asset_id = repository.repository_all_asset_files(connection)[0].asset_id
recycle.recycle_apply(connection, paths, [asset_id], sys.argv[2])
"""
    process = subprocess.run(
        [sys.executable, "-c", program, str(paths.root), operation, checkpoint],
        capture_output=True,
        check=False,
    )
    assert process.returncode == 72, process.stderr.decode()
    assert list((paths.internal_dir / "operations").glob("*.json"))
    if checkpoint == "created":
        assert list((paths.internal_dir / "operations").glob("*/*.data"))
        assert not list((paths.internal_dir / "operations").glob("*/*.owner"))
    archive.app_service_open()
    connection, paths = archive.app_service_require()
    if checkpoint != "stage_removed":
        assert repository.repository_all_asset_files(connection) == before
        assert all((paths.root / stored.path).read_bytes() == b"shared" for stored in before)
    else:
        assert all(not (paths.root / stored.path).exists() for stored in before)
        if operation == "purge":
            assert repository.repository_get_asset(connection, asset_id) is None
        else:
            assert all(
                (paths.root / stored.path).read_bytes() == b"shared"
                for stored in repository.repository_all_asset_files(connection)
            )
    assert not list((paths.internal_dir / "operations").glob("*.json"))
    assert not list((paths.internal_dir / "operations").glob("*.done"))


@pytest.mark.skipif(os.name == "nt", reason="Windows uses no-clobber rename instead")
def test_unsupported_atomic_publication_rolls_back_without_copy_fallback(archive, monkeypatch):
    connection, paths = archive.app_service_require()
    before = repository.repository_all_asset_files(connection)

    def unsupported_link(source, destination):
        raise OSError(errno.EOPNOTSUPP, "atomic hardlink publication unavailable")

    monkeypatch.setattr(os, "link", unsupported_link)
    with pytest.raises(OSError, match="publication unavailable"):
        recycle.recycle_move_to_deleted(connection, paths, [before[0].asset_id])
    assert repository.repository_all_asset_files(connection) == before
    assert all((paths.root / stored.path).read_bytes() == b"shared" for stored in before)
    assert not list((paths.internal_dir / "operations").glob("*.json"))


@pytest.mark.parametrize("operation", ["recycle", "restore", "purge"])
def test_restart_finalizes_catalog_committed_before_cleanup(archive, monkeypatch, operation):
    connection, paths = archive.app_service_require()
    asset_id = repository.repository_all_asset_files(connection)[0].asset_id
    if operation == "restore":
        recycle.recycle_move_to_deleted(connection, paths, [asset_id])
    before = repository.repository_all_asset_files(connection)
    asset = repository.repository_get_asset(connection, asset_id)
    original = file_operations.file_operations_finish

    def crash_cleanup(connection, paths, journal):
        raise KeyboardInterrupt("power loss")

    monkeypatch.setattr(file_operations, "file_operations_finish", crash_cleanup)
    with pytest.raises(KeyboardInterrupt):
        recycle.recycle_apply(connection, paths, [asset_id], operation)
    assert all((paths.root / stored.path).is_file() for stored in before)
    journals = list((paths.internal_dir / "operations").glob("*.json"))
    assert len(journals) == 1
    payload = json.loads(journals[0].read_text())
    assert all((paths.root / entry["destination"]).is_file() for entry in payload["changes"])
    archive.app_service_close()
    monkeypatch.setattr(file_operations, "file_operations_finish", original)
    reopened = database.database_connect(paths.catalog_path)
    try:
        file_operations.file_operations_recover(reopened, paths)
        assert all(not (paths.root / stored.path).exists() for stored in before)
        if operation == "purge":
            assert repository.repository_get_asset(reopened, asset_id) is None
            assert not sidecar.sidecar_path_for(paths.sidecars_dir, asset.sha256).exists()
        else:
            after = repository.repository_list_asset_files(reopened, asset_id)
            assert all((paths.root / stored.path).read_bytes() == b"shared" for stored in after)
            metadata = sidecar.sidecar_read(paths.sidecars_dir, asset.sha256)
            assert {entry["path"] for entry in metadata.files} == {stored.path for stored in after}
        assert not list((paths.internal_dir / "operations").glob("*.json"))
        file_operations.file_operations_recover(reopened, paths)
    finally:
        reopened.close()


def test_restore_avoids_case_insensitive_existing_file(archive):
    connection, paths = archive.app_service_require()
    files = repository.repository_all_asset_files(connection)
    recycle.recycle_move_to_deleted(connection, paths, [files[0].asset_id])
    external = (paths.root / files[0].path).with_name("A.HEIC")
    external.write_bytes(b"do not overwrite")
    recycle.recycle_restore(connection, paths, [files[0].asset_id])
    assert external.read_bytes() == b"do not overwrite"
    assert all(
        (paths.root / stored.path).read_bytes() == b"shared"
        for stored in repository.repository_all_asset_files(connection)
    )


def test_sidecar_failure_after_commit_is_repaired_on_recovery(archive, monkeypatch):
    connection, paths = archive.app_service_require()
    asset_id = repository.repository_all_asset_files(connection)[0].asset_id
    original = sidecar.sidecar_write

    def fail_sidecar(directory, metadata):
        raise OSError("sidecar disk failure")

    monkeypatch.setattr(sidecar, "sidecar_write", fail_sidecar)
    with pytest.raises(OSError, match="sidecar disk failure"):
        recycle.recycle_move_to_deleted(connection, paths, [asset_id])
    assert list((paths.internal_dir / "operations").glob("*.json"))
    assert repository.repository_get_asset(connection, asset_id).archive_state.value == "deleted"
    monkeypatch.setattr(sidecar, "sidecar_write", original)
    file_operations.file_operations_recover(connection, paths)
    asset = repository.repository_get_asset(connection, asset_id)
    metadata = sidecar.sidecar_read(paths.sidecars_dir, asset.sha256)
    assert metadata.archive_state == "deleted"
    assert metadata.albums == []
    assert all(entry["location"] == "deleted" for entry in metadata.files)
    assert not list((paths.internal_dir / "operations").glob("*.json"))


def test_purge_without_confirmation_preserves_every_copy(archive):
    connection, paths = archive.app_service_require()
    before = repository.repository_all_asset_files(connection)
    result = recycle.recycle_purge(connection, paths, [before[0].asset_id])
    assert result.purged_count == 0
    assert repository.repository_all_asset_files(connection) == before
    assert all((paths.root / stored.path).is_file() for stored in before)


def test_explicit_scope_cannot_silently_include_unknown_file(archive):
    connection, paths = archive.app_service_require()
    before = repository.repository_all_asset_files(connection)
    with pytest.raises(ValueError, match="Selected file ids"):
        recycle.recycle_move_to_deleted(
            connection, paths, [before[0].asset_id], file_ids=[before[0].file_id, 99999]
        )
    assert repository.repository_all_asset_files(connection) == before


@pytest.mark.parametrize(
    "unsafe", ["../escape", "/absolute", "Photos/../outside", "Photos/C:/secret", "Photos\\bad"]
)
def test_unsafe_catalog_paths_rejected(archive, unsafe):
    connection, paths = archive.app_service_require()
    stored = repository.repository_all_asset_files(connection)[0]
    connection.execute("UPDATE asset_files SET path = ? WHERE id = ?", (unsafe, stored.file_id))
    connection.commit()
    with pytest.raises(ValueError):
        recycle.recycle_move_to_deleted(connection, paths, [stored.asset_id])
