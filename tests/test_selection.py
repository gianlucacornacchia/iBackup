"""Copy-scoped batch moves and recoverable filesystem/catalog agreement."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from iphone_archive.catalog import database, repository
from iphone_archive.catalog.models import AssetFile
from iphone_archive.catalog.sidecar import sidecar_read
from iphone_archive.core import file_operations
from iphone_archive.device.fake_device import FakeDevice
from iphone_archive.service import selection
from iphone_archive.service.app_service import AppService


@pytest.fixture
def archive(tmp_path):
    """Create two assets with shared album copies for scoped batch tests."""
    service = AppService(tmp_path / "archive")
    service.app_service_initialize()
    service.app_service_import(
        FakeDevice(
            {"/DCIM/A.HEIC": b"a", "/DCIM/B.HEIC": b"b"},
            album_map={"/DCIM/A.HEIC": ["Trip", "Family"], "/DCIM/B.HEIC": ["Trip"]},
        )
    )
    yield service
    service.app_service_close()


def test_partial_move_preserves_other_album_and_sidecar(archive):
    connection, paths = archive.app_service_require()
    album_id = next(
        album.album_id
        for album in repository.repository_list_albums(connection)
        if album.name == "Trip"
    )
    asset_id = selection.selection_asset_ids_in_album(connection, album_id)[0]
    result = selection.selection_move_to_album(
        connection, paths, [asset_id, asset_id], "Sorted", source_album_id=album_id
    )
    assert result.affected_count == 1
    files = repository.repository_list_asset_files(connection, asset_id)
    assert {stored.path.split("/")[1] for stored in files} == {"Family", "Sorted"}
    asset = repository.repository_get_asset(connection, asset_id)
    metadata = sidecar_read(paths.sidecars_dir, asset.sha256)
    assert set(metadata.albums) == {"Family", "Sorted"}
    assert {entry["path"] for entry in metadata.files} == {stored.path for stored in files}


def test_default_move_relocates_all_active_copies_without_losing_bytes(archive):
    connection, paths = archive.app_service_require()
    asset_id = repository.repository_all_asset_files(connection)[0].asset_id
    before = repository.repository_list_asset_files(connection, asset_id)
    selection.selection_move_to_album(connection, paths, [asset_id], "Sorted")
    after = repository.repository_list_asset_files(connection, asset_id)
    assert len(after) == len(before) == 2
    assert len({stored.path.lower() for stored in after}) == 2
    assert all(stored.path.startswith("Photos/Sorted/") for stored in after)
    assert all((paths.root / stored.path).read_bytes() == b"a" for stored in after)


def test_explicit_file_move_preserves_unselected_files(archive):
    connection, paths = archive.app_service_require()
    selected = repository.repository_all_asset_files(connection)[0]
    unrelated = repository.repository_list_asset_files(connection, selected.asset_id)[1]
    selection.selection_move_to_album(
        connection, paths, [selected.asset_id], "Sorted", file_ids=[selected.file_id]
    )
    assert (paths.root / unrelated.path).read_bytes() == b"a"


def test_batch_preflight_missing_second_asset_keeps_first_unchanged(archive):
    connection, paths = archive.app_service_require()
    files = repository.repository_all_asset_files(connection)
    last = files[-1]
    (paths.root / last.path).unlink()
    before = [stored.path for stored in files]
    with pytest.raises(FileNotFoundError):
        selection.selection_move_to_album(
            connection, paths, [files[0].asset_id, last.asset_id], "Sorted"
        )
    assert [stored.path for stored in repository.repository_all_asset_files(connection)] == before
    assert not (paths.photos_dir / "Sorted").exists()


def test_move_failure_after_first_copy_rolls_back_whole_batch(archive, monkeypatch):
    connection, paths = archive.app_service_require()
    files = repository.repository_all_asset_files(connection)
    original = file_operations.file_operations_copy
    calls = 0

    def fail_second(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("copy failed")
        original(source, destination)

    monkeypatch.setattr(file_operations, "file_operations_copy", fail_second)
    with pytest.raises(OSError, match="copy failed"):
        selection.selection_move_to_album(
            connection, paths, [stored.asset_id for stored in files], "Sorted"
        )
    assert repository.repository_all_asset_files(connection) == files
    assert all((paths.root / stored.path).is_file() for stored in files)
    assert not list((paths.photos_dir / "Sorted").glob("*"))
    assert not list((paths.internal_dir / "operations").glob("*.json"))


def test_restart_rolls_back_interrupted_batch(archive, monkeypatch):
    connection, paths = archive.app_service_require()
    files = repository.repository_all_asset_files(connection)
    original = file_operations.file_operations_copy
    calls = 0

    def crash_second(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt("process death")
        original(source, destination)

    monkeypatch.setattr(file_operations, "file_operations_copy", crash_second)
    with pytest.raises(KeyboardInterrupt):
        selection.selection_move_to_album(
            connection, paths, [stored.asset_id for stored in files], "Sorted"
        )
    archive.app_service_close()
    reopened = database.database_connect(paths.catalog_path)
    try:
        file_operations.file_operations_recover(reopened, paths)
        assert repository.repository_all_asset_files(reopened) == files
        assert all((paths.root / stored.path).is_file() for stored in files)
        assert not list((paths.photos_dir / "Sorted").glob("*"))
        file_operations.file_operations_recover(reopened, paths)
    finally:
        reopened.close()


def test_real_process_exit_after_first_copy_is_recoverable(archive):
    """os._exit bypasses Python cleanup and leaves SQLite/journal recovery to reopen."""
    connection, paths = archive.app_service_require()
    before = repository.repository_all_asset_files(connection)
    archive.app_service_close()
    program = """
import os
import sys
from pathlib import Path
from iphone_archive.catalog import repository
from iphone_archive.core import file_operations
from iphone_archive.service import selection
from iphone_archive.service.app_service import AppService
service = AppService(Path(sys.argv[1]))
connection, paths = service.app_service_require()
original = file_operations.file_operations_copy
calls = 0
def crash_second(source, destination):
    global calls
    calls += 1
    if calls == 2:
        os._exit(42)
    original(source, destination)
file_operations.file_operations_copy = crash_second
identifiers = [stored.asset_id for stored in repository.repository_all_asset_files(connection)]
selection.selection_move_to_album(connection, paths, identifiers, "Sorted")
"""
    process = subprocess.run(
        [sys.executable, "-c", program, str(paths.root)], capture_output=True, check=False
    )
    assert process.returncode == 42, process.stderr.decode()
    connection = database.database_connect(paths.catalog_path)
    try:
        file_operations.file_operations_recover(connection, paths)
        assert repository.repository_all_asset_files(connection) == before
        assert all((paths.root / stored.path).is_file() for stored in before)
        assert not list((paths.photos_dir / "Sorted").glob("*"))
    finally:
        connection.close()


def test_album_and_filename_case_collisions_are_never_overwritten(archive):
    connection, paths = archive.app_service_require()
    asset_id = repository.repository_all_asset_files(connection)[0].asset_id
    directory = paths.photos_dir / "sorted"
    directory.mkdir()
    external = directory / "A.HEIC"
    external.write_bytes(b"unrelated")
    selection.selection_move_to_album(connection, paths, [asset_id], "Sorted")
    assert external.read_bytes() == b"unrelated"
    assert all(
        stored.path.startswith("Photos/Sorted-1/")
        for stored in repository.repository_list_asset_files(connection, asset_id)
    )


@pytest.mark.parametrize("bad_ids", [[True], [0], [-1], [99999]])
def test_invalid_selection_ids_rejected_without_changes(archive, bad_ids):
    connection, paths = archive.app_service_require()
    before = repository.repository_all_asset_files(connection)
    with pytest.raises(ValueError):
        selection.selection_move_to_album(connection, paths, bad_ids, "Sorted")
    assert repository.repository_all_asset_files(connection) == before


def test_journal_bytes_scale_linearly_with_batch_size(archive, monkeypatch):
    """Measure actual UTF-8 bytes sent to journal writers, not elapsed runtime."""
    connection, paths = archive.app_service_require()
    reference = repository.repository_all_asset_files(connection)[0]
    original_dump = json.dump
    samples = []
    writes = []

    def measured_dump(payload, handle, *args, **kwargs):
        length = 0

        class MeasuredWriter:
            def write(self, text):
                nonlocal length
                length += len(text.encode("utf-8"))
                return handle.write(text)

        result = original_dump(payload, MeasuredWriter(), *args, **kwargs)
        writes.append((Path(handle.name), length))
        return result

    monkeypatch.setattr(json, "dump", measured_dump)
    for count in (32, 64):
        selected = []
        for index in range(count):
            relative = f"Photos/Trip/batch-{count}-{index}.heic"
            (paths.root / relative).write_bytes(b"a")
            selected.append(
                repository.repository_insert_asset_file(
                    connection,
                    AssetFile(
                        asset_id=reference.asset_id, path=relative, album_id=reference.album_id
                    ),
                )
            )
        connection.commit()
        writes.clear()
        selection.selection_move_to_album(
            connection, paths, [reference.asset_id], f"Batch{count}", file_ids=selected
        )
        operations = paths.internal_dir / "operations"
        bounded_records = [length for path, length in writes if path.parent.parent == operations]
        intent_and_completion = [length for path, length in writes if path.parent == operations]
        assert len(bounded_records) == count
        assert max(bounded_records) < 256
        assert len(intent_and_completion) == 2
        total = sum(length for _, length in writes)
        assert total < 1000 * count
        samples.append(total)
    assert samples[0] < samples[1] < 2.2 * samples[0]
