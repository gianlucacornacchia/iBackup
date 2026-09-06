"""Tests for integrity verification."""

from __future__ import annotations

import pytest

from iphone_archive import config
from iphone_archive.catalog import database, repository
from iphone_archive.core import importer, verifier
from iphone_archive.device.fake_device import FakeDevice
from iphone_archive.service.progress import ProgressHandle


@pytest.fixture
def populated(tmp_path):
    """An archive containing two imported assets."""
    paths = config.config_initialize_archive(tmp_path / "archive")
    connection = database.database_connect(paths.catalog_path)
    database.database_initialize(connection)
    importer.importer_run(
        connection, paths, FakeDevice({"/DCIM/A.HEIC": b"aaa", "/DCIM/B.JPG": b"bbb"})
    )
    yield paths, connection
    connection.close()


def test_intact_archive_passes(populated):
    """Verification succeeds on an untouched archive."""
    paths, connection = populated
    result = verifier.verifier_run(connection, paths)
    assert result.passed
    assert result.checked_count == 2
    assert result.ok_count == 2


def test_detects_modified_file(populated):
    """A file whose bytes changed is reported as a mismatch."""
    paths, connection = populated
    stored = repository.repository_all_asset_files(connection)[0]
    (paths.root / stored.path).write_bytes(b"tampered")

    result = verifier.verifier_run(connection, paths)

    assert not result.passed
    assert result.mismatch_count == 1
    assert result.issues[0].status == verifier.STATUS_MISMATCH
    assert result.issues[0].actual_sha256 != result.issues[0].expected_sha256


def test_detects_missing_file(populated):
    """A deleted file is reported as missing."""
    paths, connection = populated
    stored = repository.repository_all_asset_files(connection)[0]
    (paths.root / stored.path).unlink()

    result = verifier.verifier_run(connection, paths)

    assert result.missing_count == 1
    assert result.issues[0].status == verifier.STATUS_MISSING


def test_verification_records_timestamp(populated):
    """A successful check records verified_at on the asset."""
    paths, connection = populated
    verifier.verifier_run(connection, paths)
    row = connection.execute("SELECT verified_at FROM assets LIMIT 1").fetchone()
    assert row["verified_at"] is not None


def test_limit_checks_subset(populated):
    """A limited run checks only part of the archive."""
    paths, connection = populated
    result = verifier.verifier_run(connection, paths, limit=1)
    assert result.checked_count == 1


def test_verification_is_read_only(populated):
    """Verification never modifies file content."""
    paths, connection = populated
    stored = repository.repository_all_asset_files(connection)[0]
    before = (paths.root / stored.path).read_bytes()

    verifier.verifier_run(connection, paths)

    assert (paths.root / stored.path).read_bytes() == before


def test_progress_and_cancel(populated):
    """Progress is emitted and cancellation stops the run."""
    paths, connection = populated
    handle = ProgressHandle()
    verifier.verifier_run(connection, paths, handle)
    assert len(handle.events) == 2

    cancelled = ProgressHandle()
    cancelled.progress_cancel()
    result = verifier.verifier_run(connection, paths, cancelled)
    assert result.cancelled
    assert result.checked_count == 0


def test_asset_is_verified_helper(populated):
    """The per-asset helper reflects on-disk truth."""
    paths, connection = populated
    asset_id = repository.repository_all_asset_files(connection)[0].asset_id
    assert verifier.verifier_asset_is_verified(connection, paths, asset_id)

    stored = repository.repository_list_asset_files(connection, asset_id)[0]
    (paths.root / stored.path).unlink()
    assert not verifier.verifier_asset_is_verified(connection, paths, asset_id)


def test_asset_is_verified_unknown_asset(populated):
    """An unknown asset id is never considered verified."""
    paths, connection = populated
    assert not verifier.verifier_asset_is_verified(connection, paths, 9999)
