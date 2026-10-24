"""Tests for the incremental import workflow, including album reconciliation."""

from __future__ import annotations

import io

import pytest

from iphone_archive import config
from iphone_archive.catalog import database, repository
from iphone_archive.catalog.models import PhoneItem
from iphone_archive.core import importer
from iphone_archive.device.fake_device import FakeDevice
from iphone_archive.service.progress import ProgressHandle


@pytest.fixture
def archive(tmp_path):
    """An initialized archive with an open catalog connection."""
    paths = config.config_initialize_archive(tmp_path / "archive")
    connection = database.database_connect(paths.catalog_path)
    database.database_initialize(connection)
    yield paths, connection
    connection.close()


def test_imports_new_assets(archive):
    """New items are copied, hashed, and committed to the catalog."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/IMG_0001.HEIC": b"one", "/DCIM/IMG_0002.JPG": b"two"})

    result = importer.importer_run(connection, paths, device)

    assert result.added_count == 2
    assert result.error_count == 0
    assert len(repository.repository_all_asset_files(connection)) == 2


def test_file_content_preserved_byte_for_byte(archive):
    """The archived file matches the source content exactly."""
    paths, connection = archive
    payload = b"original-bytes" * 100
    device = FakeDevice({"/DCIM/IMG_0001.HEIC": payload})

    importer.importer_run(connection, paths, device)

    stored = repository.repository_all_asset_files(connection)[0]
    assert (paths.root / stored.path).read_bytes() == payload


def test_second_run_skips_without_transfer(archive):
    """The fast-skip pass recognizes archived items without re-importing."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/IMG_0001.HEIC": b"one"})
    importer.importer_run(connection, paths, device)

    result = importer.importer_run(connection, paths, device)

    assert result.added_count == 0
    assert result.skipped_count == 1
    assert len(repository.repository_all_asset_files(connection)) == 1


def test_duplicate_content_under_new_identity_not_restored(archive):
    """Identical content at a new phone path is detected as a duplicate."""
    paths, connection = archive
    importer.importer_run(connection, paths, FakeDevice({"/DCIM/IMG_A.HEIC": b"same"}))

    result = importer.importer_run(connection, paths, FakeDevice({"/DCIM/IMG_B.HEIC": b"same"}))

    assert result.duplicate_count == 1
    assert result.added_count == 0
    assert len(repository.repository_all_asset_files(connection)) == 1


def test_album_less_asset_goes_to_unsorted(archive):
    """An asset with no album lands under _Unsorted."""
    paths, connection = archive
    importer.importer_run(connection, paths, FakeDevice({"/DCIM/IMG.HEIC": b"x"}))

    stored = repository.repository_all_asset_files(connection)[0]
    assert stored.path.startswith("Photos/_Unsorted/")


def test_multi_album_asset_placed_in_each_album(archive):
    """A photo in two albums exists as a real file in both folders."""
    paths, connection = archive
    device = FakeDevice(
        {"/DCIM/IMG.HEIC": b"shared"},
        album_map={"/DCIM/IMG.HEIC": ["Trip", "Favorites"]},
    )

    importer.importer_run(connection, paths, device)

    files = repository.repository_all_asset_files(connection)
    assert len(files) == 2
    folders = {stored.path.split("/")[1] for stored in files}
    assert folders == {"Trip", "Favorites"}
    for stored in files:
        assert (paths.root / stored.path).read_bytes() == b"shared"
        assert not (paths.root / stored.path).is_symlink()


def test_album_growth_is_append_only(archive):
    """A newly discovered album adds a copy without moving existing ones."""
    paths, connection = archive
    first = FakeDevice({"/DCIM/IMG.HEIC": b"x"}, album_map={"/DCIM/IMG.HEIC": ["Trip"]})
    importer.importer_run(connection, paths, first)
    original_paths = {f.path for f in repository.repository_all_asset_files(connection)}

    second = FakeDevice(
        {"/DCIM/IMG.HEIC": b"x"}, album_map={"/DCIM/IMG.HEIC": ["Trip", "Favorites"]}
    )
    importer.importer_run(connection, paths, second)

    new_paths = {f.path for f in repository.repository_all_asset_files(connection)}
    assert original_paths.issubset(new_paths)
    assert len(new_paths) == 2


def test_album_move_removes_stale_copy(archive):
    """Moving a photo to a different album on the phone drops the old copy."""
    paths, connection = archive
    first = FakeDevice({"/DCIM/IMG.HEIC": b"x"}, album_map={"/DCIM/IMG.HEIC": ["Trip"]})
    importer.importer_run(connection, paths, first)

    second = FakeDevice({"/DCIM/IMG.HEIC": b"x"}, album_map={"/DCIM/IMG.HEIC": ["Favorites"]})
    importer.importer_run(connection, paths, second)

    files = repository.repository_all_asset_files(connection)
    assert len(files) == 1
    assert "Favorites" in files[0].path
    assert not any("Trip" in f.path for f in files)
    assert all((paths.root / f.path).is_file() for f in files)


def test_album_removed_on_phone_falls_back_to_unsorted(archive):
    """Removing a photo from its only album returns it to _Unsorted, not a copy."""
    paths, connection = archive
    first = FakeDevice({"/DCIM/IMG.HEIC": b"x"}, album_map={"/DCIM/IMG.HEIC": ["Trip"]})
    importer.importer_run(connection, paths, first)

    second = FakeDevice({"/DCIM/IMG.HEIC": b"x"}, album_map={})
    importer.importer_run(connection, paths, second)

    files = repository.repository_all_asset_files(connection)
    assert len(files) == 1
    assert "_Unsorted" in files[0].path
    assert (paths.root / files[0].path).is_file()


def test_album_move_rolled_back_keeps_the_stale_copy(archive, monkeypatch):
    """A failure after reconciliation must not delete the asset's only archived copy.

    The new album copy is rolled back, so the old one has to survive on disk.
    """
    paths, connection = archive
    first = FakeDevice({"/DCIM/IMG.HEIC": b"x"}, album_map={"/DCIM/IMG.HEIC": ["Trip"]})
    importer.importer_run(connection, paths, first)

    def disk_full(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(importer, "sidecar_write", disk_full)
    second = FakeDevice({"/DCIM/IMG.HEIC": b"x"}, album_map={"/DCIM/IMG.HEIC": ["Favorites"]})
    result = importer.importer_run(connection, paths, second)

    assert result.error_count == 1
    files = repository.repository_all_asset_files(connection)
    assert [f.path for f in files] == ["Photos/Trip/IMG.heic"]
    assert (paths.root / files[0].path).read_bytes() == b"x"
    assert not list(paths.photos_dir.glob("Favorites/*"))


def test_stale_copy_removed_by_recovery_after_commit(archive, monkeypatch):
    """A stale copy retired by a committed item is deleted when recovery next runs."""
    paths, connection = archive
    first = FakeDevice({"/DCIM/IMG.HEIC": b"x"}, album_map={"/DCIM/IMG.HEIC": ["Trip"]})
    importer.importer_run(connection, paths, first)
    stale = paths.photos_dir / "Trip" / "IMG.heic"

    real_recover = importer.importer_recover
    monkeypatch.setattr(importer, "importer_recover", lambda connection, paths: None)
    second = FakeDevice({"/DCIM/IMG.HEIC": b"x"}, album_map={"/DCIM/IMG.HEIC": ["Favorites"]})
    importer.importer_run(connection, paths, second)
    # Committed, but the process "died" before post-commit cleanup.
    assert stale.is_file()
    assert [f.path for f in repository.repository_all_asset_files(connection)] == [
        "Photos/Favorites/IMG.heic"
    ]

    real_recover(connection, paths)

    assert not stale.exists()
    assert (paths.photos_dir / "Favorites" / "IMG.heic").read_bytes() == b"x"
    assert not list((paths.internal_dir / "import-journals").glob("*.json"))


def test_unreadable_album_metadata_keeps_album_copies(archive):
    """Without readable album data an empty list is unknown, not "no album".

    Reconciling would otherwise move every album copy into _Unsorted.
    """
    paths, connection = archive
    first = FakeDevice({"/DCIM/IMG.HEIC": b"x"}, album_map={"/DCIM/IMG.HEIC": ["Trip"]})
    importer.importer_run(connection, paths, first)

    blind = FakeDevice(
        {"/DCIM/IMG.HEIC": b"x", "/DCIM/NEW.HEIC": b"y"}, album_membership_known=False
    )
    result = importer.importer_run(connection, paths, blind)

    assert result.error_count == 0
    stored = {f.path for f in repository.repository_all_asset_files(connection)}
    assert "Photos/Trip/IMG.heic" in stored
    assert not any(path.endswith("IMG.heic") and "_Unsorted" in path for path in stored)
    # A new asset still lands in _Unsorted, as before.
    assert any(
        path.startswith("Photos/_Unsorted/") and path.endswith("NEW.heic") for path in stored
    )
    assert len(stored) == 2
    assert (paths.photos_dir / "Trip" / "IMG.heic").is_file()


def test_fast_skip_reads_each_unchanged_asset_once(archive, monkeypatch):
    """A known, unchanged item is byte-verified once, not again for reconciliation."""
    from iphone_archive.core import hashing

    paths, connection = archive
    device = FakeDevice({"/DCIM/A.JPG": b"content"}, album_map={"/DCIM/A.JPG": ["Trip"]})
    device.metadata["/DCIM/A.JPG"] = {"modified_at": "known"}
    importer.importer_run(connection, paths, device)

    hashed = []
    real_hash = hashing.hashing_sha256_file

    def counting(path, *args, **kwargs):
        if "Photos" in str(path):
            hashed.append(path)
        return real_hash(path, *args, **kwargs)

    monkeypatch.setattr(hashing, "hashing_sha256_file", counting)
    result = importer.importer_run(connection, paths, device)

    assert result.skipped_count == 1
    assert len(hashed) == 1


def test_reconciliation_never_removes_the_only_valid_copy(archive):
    """When the copy that would be kept is corrupt, the stale valid copy stays."""
    paths, connection = archive
    both = FakeDevice({"/DCIM/A.JPG": b"original"}, album_map={"/DCIM/A.JPG": ["Trip", "Fav"]})
    both.metadata["/DCIM/A.JPG"] = {"modified_at": "known"}
    importer.importer_run(connection, paths, both)
    (paths.photos_dir / "Fav" / "A.jpg").write_bytes(b"damaged!")

    only_fav = FakeDevice({"/DCIM/A.JPG": b"original"}, album_map={"/DCIM/A.JPG": ["Fav"]})
    only_fav.metadata["/DCIM/A.JPG"] = {"modified_at": "known"}
    result = importer.importer_run(connection, paths, only_fav)

    assert result.error_count == 1
    assert (paths.photos_dir / "Trip" / "A.jpg").read_bytes() == b"original"
    assert "Photos/Trip/A.jpg" in {
        f.path for f in repository.repository_all_asset_files(connection)
    }


def test_sidecar_written_for_each_asset(archive):
    """Every imported asset gets a sidecar JSON file."""
    paths, connection = archive
    importer.importer_run(connection, paths, FakeDevice({"/DCIM/IMG.HEIC": b"x"}))
    assert len(list(paths.sidecars_dir.glob("*.json"))) == 1


def test_import_session_recorded(archive):
    """An import session summary is persisted."""
    paths, connection = archive
    importer.importer_run(connection, paths, FakeDevice({"/DCIM/IMG.HEIC": b"x"}))

    row = connection.execute("SELECT * FROM import_sessions").fetchone()
    assert row["added_count"] == 1
    assert row["finished_at"] is not None


def test_presence_tracking_marks_missing_assets(archive):
    """Items absent from a later scan are flagged as gone from the phone."""
    paths, connection = archive
    importer.importer_run(
        connection, paths, FakeDevice({"/DCIM/A.HEIC": b"a", "/DCIM/B.HEIC": b"b"})
    )

    importer.importer_run(connection, paths, FakeDevice({"/DCIM/A.HEIC": b"a"}))

    absent = repository.repository_list_deleted_from_phone(connection)
    assert len(absent) == 1
    assert absent[0].original_name == "B.HEIC"


def test_archive_is_append_only_on_phone_deletion(archive):
    """Removing a photo from the phone never removes it from the archive."""
    paths, connection = archive
    importer.importer_run(connection, paths, FakeDevice({"/DCIM/A.HEIC": b"a"}))
    stored = repository.repository_all_asset_files(connection)[0]

    importer.importer_run(connection, paths, FakeDevice({}))

    assert (paths.root / stored.path).is_file()


def test_progress_reported(archive):
    """Progress events are emitted for each item."""
    paths, connection = archive
    handle = ProgressHandle()

    importer.importer_run(
        connection, paths, FakeDevice({"/DCIM/A.HEIC": b"a", "/DCIM/B.HEIC": b"b"}), handle
    )

    assert len(handle.events) == 2
    assert handle.events[-1].fraction == 1.0


def test_cancellation_stops_safely(archive):
    """A cancelled import stops without corrupting the archive."""
    paths, connection = archive
    handle = ProgressHandle()
    handle.progress_cancel()

    result = importer.importer_run(connection, paths, FakeDevice({"/DCIM/A.HEIC": b"a"}), handle)

    assert result.cancelled
    assert result.added_count == 0
    assert list(paths.temp_dir.glob("*")) == []


def test_read_error_counted_not_fatal(archive):
    """A failing item is recorded as an error while others still import."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/GOOD.HEIC": b"good", "/DCIM/BAD.HEIC": b"bad"})
    original_open = device.device_open

    def failing_open(phone_path):
        if phone_path.endswith("BAD.HEIC"):
            raise OSError("simulated read failure")
        return original_open(phone_path)

    device.device_open = failing_open

    result = importer.importer_run(connection, paths, device)

    assert result.added_count == 1
    assert result.error_count == 1


def test_interrupted_import_resumes_idempotently(archive):
    """After a mid-run failure, re-running yields the complete archive once."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/A.HEIC": b"a", "/DCIM/B.HEIC": b"b"})
    original_open = device.device_open

    def failing_open(phone_path):
        if phone_path.endswith("B.HEIC"):
            raise OSError("interrupted")
        return original_open(phone_path)

    device.device_open = failing_open
    first = importer.importer_run(connection, paths, device)
    assert first.added_count == 1

    device.device_open = original_open
    second = importer.importer_run(connection, paths, device)

    assert second.added_count == 1
    assert second.skipped_count == 1
    assert len(repository.repository_all_asset_files(connection)) == 2
    third = importer.importer_run(connection, paths, device)
    assert third.added_count == 0


def test_same_size_replacement_is_imported(archive):
    """Same path and size never suppress changed bytes with changed/unknown mtime."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/A.JPG": b"old"})
    importer.importer_run(connection, paths, device)
    device.items["/DCIM/A.JPG"] = b"new"
    result = importer.importer_run(connection, paths, device)
    assert result.added_count == 1
    assert len(repository.repository_all_asset_files(connection)) == 2


def test_device_scope_and_duplicate_source_identities(archive):
    """Shared content retains distinct source identities without cross-device skipping."""
    paths, connection = archive
    first = FakeDevice({"/DCIM/A.JPG": b"same", "/DCIM/B.JPG": b"same"}, udid="first")
    second = FakeDevice({"/DCIM/A.JPG": b"else"}, udid="second")
    for device in (first, second):
        device.metadata = {path: {"modified_at": "1"} for path in device.items}
        importer.importer_run(connection, paths, device)
    assert connection.execute("SELECT COUNT(*) FROM source_identities").fetchone()[0] == 3
    assert len(repository.repository_all_asset_files(connection)) == 2
    first.device_open = lambda path: pytest.fail("known metadata should fast-skip")
    assert importer.importer_run(connection, paths, first).skipped_count == 2
    importer.importer_run(connection, paths, FakeDevice({}, udid="second"))
    assert len(repository.repository_list_deleted_from_phone(connection, "second")) == 1
    assert repository.repository_list_deleted_from_phone(connection, "first") == []


@pytest.mark.parametrize("failure", ["cancel", "read", "enumerate"])
def test_failed_scan_never_publishes_absence(archive, failure):
    """Partial imports retain the previous complete presence snapshot."""
    paths, connection = archive
    importer.importer_run(connection, paths, FakeDevice({"/DCIM/A.JPG": b"a", "/DCIM/B.JPG": b"b"}))
    device = FakeDevice({"/DCIM/A.JPG": b"a"})
    handle = ProgressHandle()
    if failure == "cancel":
        handle.progress_cancel()
    elif failure == "read":

        def failed_open(path):
            raise OSError("lost connection")

        device.device_open = failed_open
    else:

        def failed_enumerate():
            yield next(iter(FakeDevice({"/DCIM/A.JPG": b"a"}).device_enumerate()))
            raise OSError("incomplete enumeration")

        device.device_enumerate = failed_enumerate
    if failure == "enumerate":
        with pytest.raises(OSError):
            importer.importer_run(connection, paths, device, handle)
    else:
        importer.importer_run(connection, paths, device, handle)
    assert repository.repository_list_deleted_from_phone(connection) == []


@pytest.mark.parametrize("point", ["placement", "extra", "sidecar"])
def test_mutation_failure_compensates_files_catalog_and_sidecar(archive, monkeypatch, point):
    """Faults after filesystem mutations leave no orphan file or partial catalog row."""
    from iphone_archive.core import archive_layout

    paths, connection = archive
    device = FakeDevice({"/DCIM/A.JPG": b"a"}, album_map={"/DCIM/A.JPG": ["One", "Two"]})
    owner, name = {
        "placement": (archive_layout, "archive_layout_store_stream"),
        "extra": (archive_layout, "archive_layout_duplicate_file"),
        "sidecar": (importer, "sidecar_write"),
    }[point]
    original = getattr(owner, name)

    def fail_after(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("fault after mutation")

    monkeypatch.setattr(owner, name, fail_after)
    result = importer.importer_run(connection, paths, device)
    assert result.error_count == 1
    assert repository.repository_all_asset_files(connection) == []
    assert not [path for path in paths.photos_dir.rglob("*") if path.is_file()]
    assert not list(paths.sidecars_dir.glob("*.json"))
    monkeypatch.setattr(owner, name, original)
    assert importer.importer_run(connection, paths, device).added_count == 1


def test_sidecar_failure_restores_existing_album_metadata(archive, monkeypatch):
    """Failed album growth restores both the old JSON and original catalog/copies."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/A.JPG": b"a"}, album_map={"/DCIM/A.JPG": ["One"]})
    importer.importer_run(connection, paths, device)
    sidecar = next(paths.sidecars_dir.glob("*.json"))
    original_bytes = sidecar.read_bytes()
    original_write = importer.sidecar_write

    def fail_after(*args, **kwargs):
        original_write(*args, **kwargs)
        raise OSError("write failed after replacement")

    monkeypatch.setattr(importer, "sidecar_write", fail_after)
    device.albums["/DCIM/A.JPG"].append("Two")
    assert importer.importer_run(connection, paths, device).error_count == 1
    assert sidecar.read_bytes() == original_bytes
    assert len(repository.repository_all_asset_files(connection)) == 1
    assert len([path for path in paths.photos_dir.rglob("*") if path.is_file()]) == 1


@pytest.mark.parametrize("point", ["placement", "extra", "sidecar"])
def test_process_death_after_mutation_recovers_on_restart(archive, point):
    """A real subprocess exit after mutation leaves durable intent for restart recovery."""
    import subprocess
    import sys

    paths, connection = archive
    script = """
import os, sys
from pathlib import Path
from iphone_archive import config
from iphone_archive.catalog import database
from iphone_archive.core import importer, archive_layout
from iphone_archive.device.fake_device import FakeDevice
paths = config.config_initialize_archive(Path(sys.argv[1]))
connection = database.database_connect(paths.catalog_path)
database.database_initialize(connection)
owner, name = {
    "placement": (archive_layout, "archive_layout_store_stream"),
    "extra": (archive_layout, "archive_layout_duplicate_file"),
    "sidecar": (importer, "sidecar_write"),
}[sys.argv[2]]
original = getattr(owner, name)
def exit_after(*args, **kwargs):
    original(*args, **kwargs)
    os._exit(61)
setattr(owner, name, exit_after)
device = FakeDevice({"/DCIM/A.JPG": b"a"}, album_map={"/DCIM/A.JPG": ["One", "Two"]})
importer.importer_run(connection, paths, device)
"""
    completed = subprocess.run([sys.executable, "-c", script, str(paths.root), point], check=False)
    assert completed.returncode == 61
    assert list((paths.internal_dir / "import-journals").glob("*.json"))
    importer.importer_recover(connection, paths)
    assert repository.repository_all_asset_files(connection) == []
    assert not [path for path in paths.photos_dir.rglob("*") if path.is_file()]
    assert not list(paths.sidecars_dir.glob("*.json"))
    result = importer.importer_run(connection, paths, FakeDevice({"/DCIM/A.JPG": b"a"}))
    assert result.added_count == 1


def test_recovery_refuses_to_delete_replaced_unowned_file(archive):
    """Recovery never removes an unrelated file now occupying an import destination."""
    paths, connection = archive
    journal = importer.ImportJournal(paths)
    target = paths.photos_dir / "unowned.JPG"
    journal.record(target)
    target.write_bytes(b"external content")
    with pytest.raises(RuntimeError, match="cannot establish ownership"):
        importer.importer_recover(connection, paths)
    assert target.read_bytes() == b"external content"
    assert journal.path.exists()


def test_import_size_mismatch_rolls_back(archive):
    """Stale enumeration sizes cannot be committed as accurate archive metadata."""
    import io

    paths, connection = archive
    device = FakeDevice({"/DCIM/A.JPG": b"original"})
    device.device_open = lambda path: io.BytesIO(b"short")
    result = importer.importer_run(connection, paths, device)
    assert result.error_count == 1
    assert repository.repository_all_asset_files(connection) == []


def test_fast_skip_requires_known_mtime_and_valid_local_copy(archive):
    """Known device metadata skips transfer, but damaged local bytes force reimport."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/A.JPG": b"content"})
    device.metadata["/DCIM/A.JPG"] = {"modified_at": "known"}
    importer.importer_run(connection, paths, device)
    original = device.device_open
    device.device_open = lambda path: pytest.fail("unnecessary phone transfer")
    assert importer.importer_run(connection, paths, device).skipped_count == 1
    stored = repository.repository_all_asset_files(connection)[0]
    (paths.root / stored.path).write_bytes(b"damaged")
    device.device_open = original
    result = importer.importer_run(connection, paths, device)
    assert result.error_count == 0
    assert any(
        (paths.root / entry.path).read_bytes() == b"content"
        for entry in repository.repository_all_asset_files(connection)
    )


@pytest.mark.parametrize("failure", ["exception", "exit"])
def test_post_commit_failure_keeps_journal_and_committed_files(archive, failure):
    """A failure after SQL commit must retain intent and never roll back committed media."""
    import subprocess
    import sys

    paths, connection = archive
    script = """
import os, sys
from pathlib import Path
from iphone_archive import config
from iphone_archive.catalog import database
from iphone_archive.core import importer
from iphone_archive.device.fake_device import FakeDevice
paths = config.config_initialize_archive(Path(sys.argv[1]))
connection = database.database_connect(paths.catalog_path)
database.database_initialize(connection)
original = importer.importer_recover
def fail_after_commit(connection, paths):
    if connection.execute("SELECT 1 FROM import_commits").fetchone():
        if sys.argv[2] == "exit":
            os._exit(61)
        raise OSError("failure after catalog commit")
    original(connection, paths)
importer.importer_recover = fail_after_commit
importer.importer_run(connection, paths, FakeDevice({"/DCIM/A.JPG": b"preserved"}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(paths.root), failure],
        check=False,
        capture_output=True,
    )
    assert completed.returncode == (61 if failure == "exit" else 1)
    assert list((paths.internal_dir / "import-journals").glob("*.json"))
    stored = repository.repository_all_asset_files(connection)
    assert len(stored) == 1
    importer.importer_recover(connection, paths)
    assert (paths.root / stored[0].path).read_bytes() == b"preserved"
    assert len(list(paths.sidecars_dir.glob("*.json"))) == 1
    assert repository.repository_all_asset_files(connection) == stored
    assert not list((paths.internal_dir / "import-journals").glob("*.json"))


def test_recovery_refuses_an_uncommitted_catalog_transaction(archive):
    """An uncommitted marker must never be mistaken for durable import completion."""
    paths, connection = archive
    connection.execute("BEGIN")
    with pytest.raises(RuntimeError, match="current catalog transaction"):
        importer.importer_recover(connection, paths)
    connection.rollback()


@pytest.mark.parametrize("publication", [1, 2])
def test_ownership_record_enospc_rolls_back_automatically(archive, monkeypatch, publication):
    """Disk-full ownership writes occur before publication and never block future imports."""
    import errno

    paths, connection = archive
    device = FakeDevice({"/DCIM/A.JPG": b"content"}, album_map={"/DCIM/A.JPG": ["One", "Two"]})
    original = importer.file_operations_write_journal
    prepared = 0

    def disk_full_on_ownership(path, payload):
        nonlocal prepared
        if path.suffix == ".owner" and payload["identity"] is not None:
            prepared += 1
            if prepared == publication:
                path.with_suffix(".pending").write_bytes(b"incomplete ownership record")
                raise OSError(errno.ENOSPC, "simulated full disk")
        original(path, payload)

    monkeypatch.setattr(importer, "file_operations_write_journal", disk_full_on_ownership)
    result = importer.importer_run(connection, paths, device)
    assert result.error_count == 1
    assert repository.repository_all_asset_files(connection) == []
    assert not [entry for entry in paths.photos_dir.rglob("*") if entry.is_file()]
    assert not list((paths.internal_dir / "import-journals").glob("*.json"))
    assert not list((paths.internal_dir / "import-staging").iterdir())
    monkeypatch.setattr(importer, "file_operations_write_journal", original)
    assert importer.importer_run(connection, paths, device).added_count == 1
    assert len(repository.repository_all_asset_files(connection)) == 2


@pytest.mark.parametrize(
    "point", ["primary-created", "extra-created", "primary-published", "extra-published"]
)
def test_process_death_in_creation_window_recovers_automatically(archive, point):
    """Private creation and final publication have no unowned-file recovery window."""
    import subprocess
    import sys

    paths, connection = archive
    unrelated = paths.photos_dir / "unrelated.jpg"
    unrelated.write_bytes(b"unrelated preserved content")
    script = """
import os, sys
from pathlib import Path
from iphone_archive import config
from iphone_archive.catalog import database
from iphone_archive.core import importer, archive_layout
from iphone_archive.device.fake_device import FakeDevice
paths = config.config_initialize_archive(Path(sys.argv[1]))
connection = database.database_connect(paths.catalog_path)
database.database_initialize(connection)
point = sys.argv[2]
target = 1 if point.startswith("primary") else 2
count = 0
original_claim = archive_layout.archive_layout_claim
original_publish = archive_layout.file_operations_publish
def stop_after_creation(path, created=True):
    global count
    if point.endswith("created") and path.suffix == ".partial" and created:
        count += 1
        if count == target:
            os._exit(61)
    original_claim(path, created)
def stop_after_publication(source, destination):
    global count
    original_publish(source, destination)
    if point.endswith("published"):
        count += 1
        if count == target:
            os._exit(61)
archive_layout.archive_layout_claim = stop_after_creation
archive_layout.file_operations_publish = stop_after_publication
device = FakeDevice({"/DCIM/A.JPG": b"content"}, album_map={"/DCIM/A.JPG": ["One", "Two"]})
importer.importer_run(connection, paths, device)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(paths.root), point],
        check=False,
        capture_output=True,
    )
    assert completed.returncode == 61, completed.stderr.decode()
    importer.importer_recover(connection, paths)
    assert repository.repository_all_asset_files(connection) == []
    assert [entry for entry in paths.photos_dir.rglob("*") if entry.is_file()] == [unrelated]
    assert unrelated.read_bytes() == b"unrelated preserved content"
    assert not list((paths.internal_dir / "import-staging").iterdir())
    assert not list((paths.internal_dir / "import-journals").glob("*.json"))
    assert (
        importer.importer_run(
            connection, paths, FakeDevice({"/DCIM/A.JPG": b"content"})
        ).added_count
        == 1
    )


def test_import_ownership_records_are_bounded_per_file(archive, monkeypatch):
    """Adding albums does not rewrite a growing aggregate ownership list."""
    paths, connection = archive
    payloads = []
    original = importer.file_operations_write_journal

    def capture_record(path, payload):
        payloads.append((path, payload))
        original(path, payload)

    monkeypatch.setattr(importer, "file_operations_write_journal", capture_record)
    device = FakeDevice(
        {"/DCIM/A.JPG": b"content"},
        album_map={"/DCIM/A.JPG": [f"Album-{index}" for index in range(12)]},
    )
    assert importer.importer_run(connection, paths, device).added_count == 1
    base_records = [payload for path, payload in payloads if path.suffix == ".json"]
    ownership = [payload for path, payload in payloads if path.suffix == ".owner"]
    assert len(base_records) == 2
    assert all(payload["created"] == {} for payload in base_records)
    assert len(ownership) == 24
    assert all(set(payload) == {"path", "identity"} for payload in ownership)


def test_recovery_still_preserves_externally_replaced_destination(archive):
    """Recording ownership before publication never authorizes deleting a replacement."""
    paths, connection = archive
    journal = importer.ImportJournal(paths)
    staged = journal.staging / "owned.partial"
    staged.write_bytes(b"owned content")
    target = paths.photos_dir / "A.JPG"
    journal.record(target)
    journal.prepare_publication(staged, target)
    target.write_bytes(b"external replacement")
    with pytest.raises(RuntimeError, match="cannot establish ownership"):
        importer.importer_recover(connection, paths)
    assert target.read_bytes() == b"external replacement"
    assert journal.path.exists()


def test_initial_journal_flush_failure_leaves_no_recovery_blocker(archive, monkeypatch):
    """A journal fsync failure after namespace creation is compensated before any media write."""
    import errno

    paths, connection = archive
    original = importer.file_operations_write_journal

    def fail_after_initial_write(path, payload):
        original(path, payload)
        raise OSError(errno.EIO, "initial journal flush failed")

    monkeypatch.setattr(importer, "file_operations_write_journal", fail_after_initial_write)
    with pytest.raises(OSError, match="initial journal flush"):
        importer.importer_run(connection, paths, FakeDevice({"/DCIM/A.JPG": b"content"}))
    assert not list((paths.internal_dir / "import-staging").iterdir())
    assert not list((paths.internal_dir / "import-journals").iterdir())
    monkeypatch.setattr(importer, "file_operations_write_journal", original)
    importer.importer_recover(connection, paths)
    assert (
        importer.importer_run(
            connection, paths, FakeDevice({"/DCIM/A.JPG": b"content"})
        ).added_count
        == 1
    )


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_repair_copy_keeps_its_primary_album(archive, damage):
    """A replacement remains selectable by its containing album and in its sidecar."""
    from iphone_archive.browse import gallery
    from iphone_archive.catalog.sidecar import sidecar_read

    paths, connection = archive
    device = FakeDevice({"/DCIM/A.JPG": b"original"}, album_map={"/DCIM/A.JPG": ["Trip"]})
    assert importer.importer_run(connection, paths, device).added_count == 1
    original = repository.repository_all_asset_files(connection)[0]
    target = paths.root / original.path
    if damage == "missing":
        target.unlink()
    else:
        target.write_bytes(b"damaged!")

    result = importer.importer_run(connection, paths, device)

    assert result.error_count == 0
    files = repository.repository_all_asset_files(connection)
    repaired = (
        next(stored for stored in files if stored.file_id == original.file_id)
        if damage == "missing"
        else next(stored for stored in files if stored.file_id != original.file_id)
    )
    assert (paths.root / repaired.path).read_bytes() == b"original"
    assert repaired.album_id == original.album_id
    view = gallery.gallery_list_assets(connection, album_id=original.album_id)[0]
    assert repaired.file_id in view.file_ids
    sidecar = sidecar_read(paths.sidecars_dir, view.sha256)
    assert any(
        stored["path"] == repaired.path and stored["album_id"] == original.album_id
        for stored in sidecar.files
    )


def test_missing_private_namespace_fails_closed(archive):
    """Removing an active private namespace externally cannot erase ownership evidence silently."""
    paths, connection = archive
    journal = importer.ImportJournal(paths)
    journal.staging.rmdir()
    with pytest.raises(RuntimeError, match="staging namespace missing"):
        importer.importer_recover(connection, paths)
    assert journal.path.exists()


def test_publication_io_failure_after_create_recovers_automatically(archive, monkeypatch):
    """An I/O error after the final name appears already has durable inode ownership."""
    import errno

    from iphone_archive.core import archive_layout

    paths, connection = archive
    original = archive_layout.file_operations_publish

    def fail_after_publication(source, destination):
        original(source, destination)
        raise OSError(errno.EIO, "publication directory flush failed")

    monkeypatch.setattr(archive_layout, "file_operations_publish", fail_after_publication)
    result = importer.importer_run(connection, paths, FakeDevice({"/DCIM/A.JPG": b"content"}))
    assert result.error_count == 1
    assert repository.repository_all_asset_files(connection) == []
    assert not [entry for entry in paths.photos_dir.rglob("*") if entry.is_file()]
    assert not list((paths.internal_dir / "import-journals").iterdir())
    assert not list((paths.internal_dir / "import-staging").iterdir())


class ScriptedPreviewThenOriginalDevice:
    """A device that first reports only an offloaded preview, then the real original."""

    def __init__(self, udid: str = "FAKE-UDID") -> None:
        self.phase = "preview"
        self.udid = udid

    def device_udid(self) -> str:
        return self.udid

    def device_enumerate(self):
        if self.phase == "preview":
            yield PhoneItem(
                phone_path="/PhotoData/Thumbnails/V2/DCIM/100APPLE/IMG_0001.JPG",
                size=len(b"low-res-preview"),
                original_name="IMG_0001 (offloaded preview).JPG",
                media_type="image",
                is_offloaded_preview=True,
                offloaded_original_path="/DCIM/100APPLE/IMG_0001.HEIC",
                album_names=["Vacation"],
                latitude=45.07,
                longitude=7.69,
            )
        else:
            yield PhoneItem(
                phone_path="/DCIM/100APPLE/IMG_0001.HEIC",
                size=len(b"full-resolution-original"),
                original_name="IMG_0001.HEIC",
                media_type="image",
                album_names=["Vacation"],
                latitude=48.85,
                longitude=2.35,
            )

    def device_open(self, phone_path: str):
        content = b"low-res-preview" if self.phase == "preview" else b"full-resolution-original"
        return io.BytesIO(content)

    def device_delete(self, phone_path: str) -> None:
        raise NotImplementedError

    def device_album_map(self) -> dict[str, list[str]]:
        return {"/DCIM/100APPLE/IMG_0001.HEIC": ["Vacation"]}


def test_offloaded_preview_upgraded_in_place_once_original_reappears(archive):
    """Re-importing after the real original returns to the phone upgrades the preview.

    Rather than archiving a second, duplicate asset, the existing preview row is
    replaced in place: same asset id (so album links/marks survive), real content,
    and the old low-resolution file removed from disk.
    """
    paths, connection = archive
    device = ScriptedPreviewThenOriginalDevice()

    first = importer.importer_run(connection, paths, device)
    assert first.added_count == 1
    rows = connection.execute("SELECT * FROM assets").fetchall()
    assert len(rows) == 1
    assert bool(rows[0]["is_offloaded_preview"]) is True
    asset_id = rows[0]["id"]
    preview_files = repository.repository_list_asset_files(connection, asset_id)
    assert len(preview_files) == 1
    preview_path = paths.root / preview_files[0].path
    assert preview_path.read_bytes() == b"low-res-preview"

    device.phase = "original"
    second = importer.importer_run(connection, paths, device)

    assert second.upgraded_count == 1
    assert second.added_count == 0
    assert second.duplicate_count == 0
    rows_after = connection.execute("SELECT * FROM assets").fetchall()
    assert len(rows_after) == 1
    assert rows_after[0]["id"] == asset_id
    assert bool(rows_after[0]["is_offloaded_preview"]) is False
    assert rows_after[0]["offloaded_original_path"] is None
    assert rows_after[0]["original_name"] == "IMG_0001.HEIC"
    assert not preview_path.exists()

    final_files = repository.repository_list_asset_files(connection, asset_id)
    assert len(final_files) == 1
    assert (paths.root / final_files[0].path).read_bytes() == b"full-resolution-original"


def test_new_asset_stores_location_from_phone_item(archive):
    """A phone item's GPS coordinates are copied onto the new catalog asset."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/A.HEIC": b"a"}, locations={"/DCIM/A.HEIC": (45.07, 7.69)})

    importer.importer_run(connection, paths, device)

    asset = repository.repository_get_asset(
        connection, repository.repository_all_asset_files(connection)[0].asset_id
    )
    assert (asset.latitude, asset.longitude) == (45.07, 7.69)


def test_new_asset_stores_camera_metadata_from_exif(archive):
    """Camera/lens/ISO/aperture/focal-length are read from the archived file's own EXIF."""
    from tests.test_core_exif import make_jpeg_with_exif

    paths, connection = archive
    device = FakeDevice({"/DCIM/A.JPG": make_jpeg_with_exif()})

    importer.importer_run(connection, paths, device)

    asset = repository.repository_get_asset(
        connection, repository.repository_all_asset_files(connection)[0].asset_id
    )
    assert asset.camera_model == "Apple iPhone 12"
    assert asset.lens_model == "iPhone 12 back camera 4.2mm f/1.6"
    assert asset.iso == 64
    assert asset.aperture == 1.6
    assert asset.focal_length_mm == 4.2


def test_exif_gps_used_only_when_phone_gps_absent(archive):
    """Phone-sourced GPS wins; EXIF GPS is only a fallback when the phone had none."""
    from tests.test_core_exif import make_jpeg_with_exif

    paths, connection = archive
    device = FakeDevice(
        {
            "/DCIM/A.JPG": make_jpeg_with_exif(latitude=10.0, longitude=20.0),
            "/DCIM/B.JPG": make_jpeg_with_exif(latitude=10.0, longitude=20.0, iso=100),
        },
        locations={"/DCIM/A.JPG": (45.07, 7.69)},
    )

    importer.importer_run(connection, paths, device)

    assets = {
        asset.original_name.upper(): asset
        for asset in (
            repository.repository_get_asset(connection, file.asset_id)
            for file in repository.repository_all_asset_files(connection)
        )
    }
    asset_a = assets["A.JPG"]
    asset_b = assets["B.JPG"]
    assert (asset_a.latitude, asset_a.longitude) == (45.07, 7.69)
    assert (asset_b.latitude, asset_b.longitude) == pytest.approx((10.0, 20.0), abs=0.01)


def test_reimport_backfills_location_and_camera_metadata_on_existing_asset(archive):
    """Assets archived before GPS/EXIF support existed gain that data on the next import.

    Simulates an asset imported by an older version of the app (no latitude/
    longitude/camera columns populated), then re-imported once the phone
    reports a location for that same item: the fast-skip pass must backfill
    the existing row in place rather than leaving it permanently blank.
    """
    from tests.test_core_exif import make_jpeg_with_exif

    paths, connection = archive
    content = make_jpeg_with_exif(latitude=44.4, longitude=12.2)
    device = FakeDevice({"/DCIM/A.JPG": content}, locations={"/DCIM/A.JPG": (44.4, 12.2)})

    importer.importer_run(connection, paths, device)
    asset_id = repository.repository_all_asset_files(connection)[0].asset_id
    # Roll back the asset to what an old, pre-GPS/EXIF import would have recorded.
    connection.execute(
        "UPDATE assets SET latitude=NULL, longitude=NULL, camera_model=NULL, "
        "lens_model=NULL, iso=NULL, aperture=NULL, focal_length_mm=NULL WHERE id=?",
        (asset_id,),
    )
    connection.commit()
    blanked = repository.repository_get_asset(connection, asset_id)
    assert blanked.latitude is None
    assert blanked.camera_model is None

    result = importer.importer_run(connection, paths, device)

    assert result.skipped_count == 1
    assert result.added_count == 0
    backfilled = repository.repository_get_asset(connection, asset_id)
    assert (backfilled.latitude, backfilled.longitude) == pytest.approx((44.4, 12.2), abs=0.01)
    assert backfilled.camera_model == "Apple iPhone 12"
    assert backfilled.iso == 64


def test_reimport_never_overwrites_already_recorded_metadata(archive):
    """A later import cannot clobber GPS/camera data an earlier import already found."""
    from tests.test_core_exif import make_jpeg_with_exif

    paths, connection = archive
    content = make_jpeg_with_exif(latitude=44.4, longitude=12.2)
    device = FakeDevice({"/DCIM/A.JPG": content}, locations={"/DCIM/A.JPG": (1.0, 2.0)})

    importer.importer_run(connection, paths, device)
    asset_id = repository.repository_all_asset_files(connection)[0].asset_id
    first_pass = repository.repository_get_asset(connection, asset_id)
    assert (first_pass.latitude, first_pass.longitude) == (1.0, 2.0)

    # A second scan with a different (bogus) phone location must not override
    # the value already recorded; only a currently-missing field may be filled.
    device.locations["/DCIM/A.JPG"] = (99.0, 99.0)
    importer.importer_run(connection, paths, device)

    unchanged = repository.repository_get_asset(connection, asset_id)
    assert (unchanged.latitude, unchanged.longitude) == (1.0, 2.0)


def test_offloaded_preview_upgrade_replaces_location(archive):
    """Upgrading an offloaded preview replaces its coordinates with the original's."""
    paths, connection = archive
    device = ScriptedPreviewThenOriginalDevice()

    importer.importer_run(connection, paths, device)
    asset_id = connection.execute("SELECT id FROM assets").fetchone()["id"]
    preview_asset = repository.repository_get_asset(connection, asset_id)
    assert (preview_asset.latitude, preview_asset.longitude) == (45.07, 7.69)

    device.phase = "original"
    importer.importer_run(connection, paths, device)

    upgraded_asset = repository.repository_get_asset(connection, asset_id)
    assert (upgraded_asset.latitude, upgraded_asset.longitude) == (48.85, 2.35)


def test_offloaded_preview_not_upgraded_by_another_device(archive):
    """A different phone's photo at the same /DCIM path must not replace the preview."""
    paths, connection = archive
    phone_a = ScriptedPreviewThenOriginalDevice(udid="PHONE-A")
    importer.importer_run(connection, paths, phone_a)
    preview = repository.repository_all_asset_files(connection)[0]

    phone_b = ScriptedPreviewThenOriginalDevice(udid="PHONE-B")
    phone_b.phase = "original"
    result = importer.importer_run(connection, paths, phone_b)

    assert result.upgraded_count == 0
    assert result.added_count == 1
    rows = connection.execute("SELECT is_offloaded_preview FROM assets ORDER BY id").fetchall()
    assert [bool(row[0]) for row in rows] == [True, False]
    assert (paths.root / preview.path).read_bytes() == b"low-res-preview"


def test_offloaded_preview_kept_when_original_already_archived(archive):
    """An original whose bytes are already archived is a duplicate, not an upgrade.

    Upgrading would hit UNIQUE(sha256) and fail on every import, which would
    also stop presence (deleted-from-phone) from ever being published again.
    """
    paths, connection = archive
    other = FakeDevice({"/DCIM/COPY.HEIC": b"full-resolution-original"}, udid="OTHER")
    importer.importer_run(connection, paths, other)
    device = ScriptedPreviewThenOriginalDevice()
    importer.importer_run(connection, paths, device)

    device.phase = "original"
    result = importer.importer_run(connection, paths, device)

    assert result.error_count == 0
    assert result.upgraded_count == 0
    assert result.duplicate_count == 1
    rows = connection.execute("SELECT is_offloaded_preview FROM assets ORDER BY id").fetchall()
    assert [bool(row[0]) for row in rows] == [False, True]
