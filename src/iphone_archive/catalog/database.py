"""SQLite catalog: schema definition, connection management, and migrations.

The catalog is the source-of-truth index for the archive. It is created inside
the hidden ``.ibackup/`` folder. A simple integer ``schema_version`` stored in a
``meta`` table drives forward-only migrations so an old archive can be opened by
a newer build.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Current catalog schema version. Bump when adding a migration step.
SCHEMA_VERSION = 2

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sha256 TEXT NOT NULL UNIQUE,
        size INTEGER NOT NULL,
        original_name TEXT NOT NULL,
        media_type TEXT NOT NULL,
        captured_at TEXT,
        imported_at TEXT,
        verified_at TEXT,
        first_seen_on_phone_at TEXT,
        last_seen_on_phone_at TEXT,
        present_on_phone INTEGER NOT NULL DEFAULT 1,
        archive_state TEXT NOT NULL DEFAULT 'active',
        phone_asset_id TEXT,
        phone_path TEXT,
        phone_size INTEGER,
        phone_modified_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS albums (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone_album_id TEXT,
        name TEXT NOT NULL,
        safe_name TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'user'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS asset_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
        path TEXT NOT NULL UNIQUE,
        album_id INTEGER REFERENCES albums(id) ON DELETE SET NULL,
        link_mode TEXT NOT NULL DEFAULT 'copy',
        location TEXT NOT NULL DEFAULT 'photos'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS asset_albums (
        asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
        album_id INTEGER NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
        PRIMARY KEY (asset_id, album_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS import_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_udid TEXT,
        started_at TEXT,
        finished_at TEXT,
        added_count INTEGER NOT NULL DEFAULT 0,
        skipped_count INTEGER NOT NULL DEFAULT 0,
        error_count INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS deletion_marks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_type TEXT NOT NULL,
        target_id INTEGER NOT NULL,
        marked_at TEXT,
        reason TEXT,
        committed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_identities (
        device_udid TEXT NOT NULL,
        phone_path TEXT NOT NULL,
        asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
        phone_asset_id TEXT,
        phone_size INTEGER NOT NULL,
        phone_modified_at TEXT,
        present INTEGER NOT NULL DEFAULT 1,
        last_seen_at TEXT,
        PRIMARY KEY(device_udid, phone_path, asset_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS import_commits (
        journal_id TEXT PRIMARY KEY
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_assets_sha256 ON assets(sha256)",
    "CREATE INDEX IF NOT EXISTS idx_assets_present ON assets(present_on_phone)",
    "CREATE INDEX IF NOT EXISTS idx_assets_phone_id ON assets(phone_asset_id)",
    "CREATE INDEX IF NOT EXISTS idx_sources_asset_present ON source_identities(asset_id, present)",
    "CREATE INDEX IF NOT EXISTS idx_asset_albums_album ON asset_albums(album_id)",
    "CREATE INDEX IF NOT EXISTS idx_asset_files_path ON asset_files(path)",
    "CREATE INDEX IF NOT EXISTS idx_asset_files_asset ON asset_files(asset_id)",
    "CREATE INDEX IF NOT EXISTS idx_asset_files_album_location ON asset_files(album_id, location)",
    "CREATE INDEX IF NOT EXISTS idx_marks_committed ON deletion_marks(committed_at)",
]


def database_connect(catalog_path: Path) -> sqlite3.Connection:
    """Open (creating parent folders as needed) a catalog SQLite connection.

    catalog_path: filesystem path to the ``catalog.sqlite`` file.
    Returns a sqlite3 connection with row access by name and foreign keys on.
    """
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(catalog_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def database_initialize(connection: sqlite3.Connection) -> None:
    """Create the schema if missing and apply any pending migrations.

    connection: an open catalog connection.
    Returns None.
    """
    connection.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    current = database_read_version(connection)
    if current > SCHEMA_VERSION:
        raise ValueError(f"unsupported catalog schema version: {current}")
    for statement in SCHEMA_STATEMENTS:
        connection.execute(statement)
    if current == 0:
        database_write_version(connection, SCHEMA_VERSION)
    elif current < SCHEMA_VERSION:
        database_apply_migrations(connection, current)
    connection.commit()


def database_read_version(connection: sqlite3.Connection) -> int:
    """Return the stored schema version, or 0 when unset.

    connection: an open catalog connection.
    Returns the integer schema version currently recorded.
    """
    row = connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    version = int(row["value"]) if row is not None else 0
    return version


def database_write_version(connection: sqlite3.Connection, version: int) -> None:
    """Persist the schema version into the meta table.

    connection: an open catalog connection.
    version: the integer version to store.
    Returns None.
    """
    connection.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(version),),
    )


def database_apply_migrations(connection: sqlite3.Connection, from_version: int) -> None:
    """Apply forward-only migrations from a stored version to the current one.

    connection: an open catalog connection.
    from_version: the schema version currently stored in the catalog.
    Returns None. Future schema bumps add ordered steps here.
    """
    # V1 has no device provenance. Preserve its content rows, but never promote
    # legacy path/size pairs to trusted source identities without reading bytes.
    database_write_version(connection, SCHEMA_VERSION)
