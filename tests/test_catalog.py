"""Tests for the SQLite catalog schema, migrations, and repository queries."""

from __future__ import annotations

import sqlite3

import pytest

from iphone_archive.catalog import database, repository
from iphone_archive.catalog.models import (
    Album,
    ArchiveState,
    Asset,
    AssetFile,
    DeletionMark,
    FileLocation,
    ImportSession,
)


def make_asset(sha256: str = "a" * 64, **overrides) -> Asset:
    """Build a minimal asset for tests."""
    values = {
        "sha256": sha256,
        "size": 1024,
        "original_name": "IMG_0001.HEIC",
        "media_type": "image",
    }
    values.update(overrides)
    return Asset(**values)


def test_schema_created_and_version_recorded(catalog_connection):
    """Initialization creates tables and records the schema version."""
    assert database.database_read_version(catalog_connection) == database.SCHEMA_VERSION
    tables = {
        row["name"]
        for row in catalog_connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for expected in {
        "assets",
        "albums",
        "asset_files",
        "asset_albums",
        "import_sessions",
        "deletion_marks",
    }:
        assert expected in tables


def test_initialize_is_idempotent(catalog_connection):
    """Re-initializing an existing catalog is safe."""
    database.database_initialize(catalog_connection)
    assert database.database_read_version(catalog_connection) == database.SCHEMA_VERSION


def test_asset_file_indexes_cover_hot_queries(catalog_connection):
    """Fresh catalogs index per-asset sidecar refreshes and active-album file lookups."""
    cases = (
        ("SELECT * FROM asset_files WHERE asset_id = ?", (1,), "idx_asset_files_asset"),
        (
            "SELECT * FROM asset_files WHERE album_id = ? AND location = ?",
            (1, "photos"),
            "idx_asset_files_album_location",
        ),
        (
            "SELECT id FROM assets WHERE EXISTS "
            "(SELECT 1 FROM source_identities WHERE asset_id = assets.id AND present = 1)",
            (),
            "idx_sources_asset_present",
        ),
    )
    for query, parameters, expected_index in cases:
        plan = catalog_connection.execute(f"EXPLAIN QUERY PLAN {query}", parameters).fetchall()
        assert any(expected_index in row["detail"] for row in plan)


@pytest.mark.parametrize("stored_version", [1, database.SCHEMA_VERSION])
def test_existing_catalog_initialization_adds_file_indexes(catalog_connection, stored_version):
    """Both v1 migration and reopening v2 add missing indexes without changing file rows."""
    connection = catalog_connection
    asset_id = repository.repository_insert_asset(connection, make_asset())
    repository.repository_insert_asset_file(
        connection, AssetFile(asset_id=asset_id, path="Photos/Album/A.JPG")
    )
    existing_files = repository.repository_list_asset_files(connection, asset_id)
    connection.execute("DROP INDEX idx_asset_files_asset")
    connection.execute("DROP INDEX idx_asset_files_album_location")
    connection.execute("DROP INDEX idx_sources_asset_present")
    database.database_write_version(connection, stored_version)
    connection.commit()

    database.database_initialize(connection)
    database.database_initialize(connection)

    assert database.database_read_version(connection) == database.SCHEMA_VERSION
    assert repository.repository_list_asset_files(connection, asset_id) == existing_files
    columns = {
        index: [row["name"] for row in connection.execute(f"PRAGMA index_info({index})").fetchall()]
        for index in (
            "idx_asset_files_asset",
            "idx_asset_files_album_location",
            "idx_sources_asset_present",
        )
    }
    assert columns == {
        "idx_asset_files_asset": ["asset_id"],
        "idx_asset_files_album_location": ["album_id", "location"],
        "idx_sources_asset_present": ["asset_id", "present"],
    }


def test_old_catalog_upgrades(tmp_path):
    """A catalog recorded at an older version is migrated to the current one."""
    path = tmp_path / ".ibackup" / "catalog.sqlite"
    connection = database.database_connect(path)
    database.database_initialize(connection)
    database.database_write_version(connection, 0)
    connection.commit()
    connection.close()

    reopened = database.database_connect(path)
    database.database_initialize(reopened)
    assert database.database_read_version(reopened) == database.SCHEMA_VERSION
    reopened.close()


def test_v1_migration_does_not_invent_device_provenance(catalog_connection):
    """Old content remains indexed, but legacy identities cannot authorize a fast skip."""
    connection = catalog_connection
    asset_id = repository.repository_insert_asset(
        connection,
        make_asset(
            phone_path="/DCIM/A.JPG",
            phone_size=1024,
            phone_modified_at="old",
            phone_asset_id="legacy",
        ),
    )
    connection.execute("DROP TABLE source_identities")
    connection.execute("DROP TABLE import_commits")
    database.database_write_version(connection, 1)
    connection.commit()
    database.database_initialize(connection)
    assert repository.repository_get_asset(connection, asset_id) is not None
    assert connection.execute("SELECT COUNT(*) FROM source_identities").fetchone()[0] == 0
    assert (
        repository.repository_find_by_phone_identity(
            connection, "legacy", "/DCIM/A.JPG", 1024, "phone", "old"
        )
        is None
    )


def test_future_schema_is_rejected_before_mutation(catalog_connection):
    """A newer catalog is not silently opened with an older schema contract."""
    database.database_write_version(catalog_connection, database.SCHEMA_VERSION + 1)
    catalog_connection.commit()
    with pytest.raises(ValueError, match="unsupported catalog schema"):
        database.database_initialize(catalog_connection)


def test_insert_and_lookup_by_hash(catalog_connection):
    """An inserted asset is retrievable by its content hash."""
    asset_id = repository.repository_insert_asset(catalog_connection, make_asset())
    found = repository.repository_get_asset_by_hash(catalog_connection, "a" * 64)
    assert found is not None
    assert found.asset_id == asset_id
    assert found.archive_state is ArchiveState.ACTIVE


def test_hash_is_unique(catalog_connection):
    """The sha256 column rejects duplicates."""
    repository.repository_insert_asset(catalog_connection, make_asset())
    with pytest.raises(sqlite3.IntegrityError):
        repository.repository_insert_asset(catalog_connection, make_asset())


def test_find_by_phone_identity_asset_id(catalog_connection):
    """Legacy asset ids without device and modification metadata are untrusted."""
    repository.repository_insert_asset(catalog_connection, make_asset(phone_asset_id="PH-1"))
    found = repository.repository_find_by_phone_identity(catalog_connection, "PH-1", None, None)
    assert found is None


def test_find_by_phone_identity_path_and_size(catalog_connection):
    """Legacy path and size pairs are not sufficient for a fast skip."""
    repository.repository_insert_asset(
        catalog_connection, make_asset(phone_path="/DCIM/IMG_0001.HEIC", phone_size=1024)
    )
    found = repository.repository_find_by_phone_identity(
        catalog_connection, None, "/DCIM/IMG_0001.HEIC", 1024
    )
    assert found is None
    missing = repository.repository_find_by_phone_identity(
        catalog_connection, None, "/DCIM/IMG_0001.HEIC", 999
    )
    assert missing is None


def test_asset_files_and_albums(catalog_connection):
    """Files and album membership are stored and queryable."""
    asset_id = repository.repository_insert_asset(catalog_connection, make_asset())
    album_id = repository.repository_upsert_album(
        catalog_connection, Album(name="Family Trip", safe_name="Family Trip")
    )
    repository.repository_link_asset_album(catalog_connection, asset_id, album_id)
    repository.repository_insert_asset_file(
        catalog_connection,
        AssetFile(asset_id=asset_id, path="Photos/Family Trip/IMG_0001.heic", album_id=album_id),
    )

    files = repository.repository_list_asset_files(catalog_connection, asset_id)
    assert len(files) == 1
    assert files[0].location is FileLocation.PHOTOS
    assert len(repository.repository_list_albums(catalog_connection)) == 1


def test_upsert_album_is_idempotent(catalog_connection):
    """Upserting the same album twice returns the same id."""
    first = repository.repository_upsert_album(
        catalog_connection, Album(name="Trip", safe_name="Trip")
    )
    second = repository.repository_upsert_album(
        catalog_connection, Album(name="Trip", safe_name="Trip")
    )
    assert first == second


def test_presence_tracking_and_deleted_from_phone(catalog_connection):
    """Assets not seen in the latest scan surface as deleted-from-phone."""
    kept = repository.repository_insert_asset(catalog_connection, make_asset("a" * 64))
    gone = repository.repository_insert_asset(catalog_connection, make_asset("b" * 64))

    repository.repository_mark_all_absent(catalog_connection)
    repository.repository_mark_present(catalog_connection, kept, "2026-09-07T00:00:00")

    absent = repository.repository_list_deleted_from_phone(catalog_connection)
    assert [asset.asset_id for asset in absent] == [gone]


def test_archive_state_excludes_from_deleted_list(catalog_connection):
    """Assets already moved to Deleted/ are not re-reported."""
    asset_id = repository.repository_insert_asset(catalog_connection, make_asset())
    repository.repository_mark_all_absent(catalog_connection)
    repository.repository_set_archive_state(catalog_connection, asset_id, ArchiveState.DELETED)
    assert repository.repository_list_deleted_from_phone(catalog_connection) == []


def test_update_asset_file_path(catalog_connection):
    """Moving a file updates its path and location."""
    asset_id = repository.repository_insert_asset(catalog_connection, make_asset())
    file_id = repository.repository_insert_asset_file(
        catalog_connection, AssetFile(asset_id=asset_id, path="Photos/Trip/IMG.heic")
    )
    repository.repository_update_asset_file_path(
        catalog_connection, file_id, "Deleted/Trip/IMG.heic", FileLocation.DELETED
    )
    files = repository.repository_list_asset_files(catalog_connection, asset_id)
    assert files[0].path == "Deleted/Trip/IMG.heic"
    assert files[0].location is FileLocation.DELETED


def test_delete_asset_cascades(catalog_connection):
    """Deleting an asset removes its file rows."""
    asset_id = repository.repository_insert_asset(catalog_connection, make_asset())
    repository.repository_insert_asset_file(
        catalog_connection, AssetFile(asset_id=asset_id, path="Photos/Trip/IMG.heic")
    )
    repository.repository_delete_asset(catalog_connection, asset_id)
    assert repository.repository_all_asset_files(catalog_connection) == []


def test_import_session_lifecycle(catalog_connection):
    """An import session can be created and finalized with counts."""
    session = ImportSession(device_udid="UDID", started_at="2026-09-07T00:00:00")
    session.session_id = repository.repository_create_import_session(catalog_connection, session)
    session.finished_at = "2026-09-07T00:10:00"
    session.added_count = 5
    session.skipped_count = 2
    repository.repository_finish_import_session(catalog_connection, session)

    row = catalog_connection.execute(
        "SELECT * FROM import_sessions WHERE id = ?", (session.session_id,)
    ).fetchone()
    assert row["added_count"] == 5
    assert row["skipped_count"] == 2


def test_deletion_marks_stage_then_commit(catalog_connection):
    """Marks are staged as pending until explicitly committed."""
    asset_id = repository.repository_insert_asset(catalog_connection, make_asset())
    mark_id = repository.repository_add_deletion_mark(
        catalog_connection,
        DeletionMark(target_type="asset", target_id=asset_id, marked_at="2026-09-07T00:00:00"),
    )
    assert len(repository.repository_list_pending_marks(catalog_connection)) == 1
    repository.repository_commit_mark(catalog_connection, mark_id, "2026-09-07T00:05:00")
    assert repository.repository_list_pending_marks(catalog_connection) == []


def test_set_verified_at(catalog_connection):
    """Verification time is recorded on the asset."""
    asset_id = repository.repository_insert_asset(catalog_connection, make_asset())
    repository.repository_set_verified_at(catalog_connection, asset_id, "2026-09-07T01:00:00")
    found = repository.repository_get_asset_by_hash(catalog_connection, "a" * 64)
    assert found is not None
    assert found.verified_at == "2026-09-07T01:00:00"
