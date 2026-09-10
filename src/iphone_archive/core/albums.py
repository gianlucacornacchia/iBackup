"""Album membership extraction and browsing.

Album information is read best-effort from the phone's ``Photos.sqlite``. When
that database is unavailable or unreadable, assets are filed under ``_Unsorted``
rather than failing the import — album data is a bonus, never a prerequisite.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..catalog import repository
from ..catalog.models import ArchiveState, FileLocation

logger = logging.getLogger(__name__)

# iOS names the album/asset join table after a Core Data entity ordinal that
# changes between releases (Z_28ASSETS on iOS 14, Z_33ASSETS on iOS 26), so the
# table and its columns are discovered at runtime rather than hardcoded.
JOIN_TABLE_PATTERN = re.compile(r"^Z_\d+ASSETS$")
ALBUM_COLUMN_PATTERN = re.compile(r"^Z_\d+ALBUMS$")
ASSET_COLUMN_PATTERN = re.compile(r"^Z_\d+ASSETS$")
# Asset tables, newest schema first.
ASSET_TABLES = ("ZASSET", "ZGENERICASSET")
# ZKIND of a user-created album. Other kinds are smart albums, folders and
# internal bookkeeping such as the untitled system albums and 'progress-sync'.
USER_ALBUM_KIND = 2


@dataclass
class AlbumSummary:
    """An album and how many archived assets it contains."""

    album_id: int
    name: str
    safe_name: str
    asset_count: int


def albums_table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    """Return the column names of a table.

    connection: an open photo-database connection.
    table: the table to inspect; must already be a known-safe identifier.
    Returns the column names, or an empty list when the table is unreadable.
    """
    try:
        rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    except sqlite3.Error:
        return []
    return [str(row[1]) for row in rows]


def albums_discover_join(connection: sqlite3.Connection) -> tuple[str, str, str] | None:
    """Locate the album/asset join table and its two foreign-key columns.

    connection: an open photo-database connection.
    Returns ``(table, album_column, asset_column)``, or None when no join table
    matching the iOS naming convention is present.
    """
    try:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    except sqlite3.Error:
        return None

    found: tuple[str, str, str] | None = None
    for row in rows:
        table = str(row[0])
        if not JOIN_TABLE_PATTERN.match(table):
            continue
        columns = albums_table_columns(connection, table)
        album_column = next((name for name in columns if ALBUM_COLUMN_PATTERN.match(name)), None)
        asset_column = next((name for name in columns if ASSET_COLUMN_PATTERN.match(name)), None)
        if album_column is not None and asset_column is not None:
            found = (table, album_column, asset_column)
            break
    return found


def albums_asset_table(connection: sqlite3.Connection) -> str | None:
    """Return the name of the asset table for this schema version.

    connection: an open photo-database connection.
    Returns ``ZASSET`` or ``ZGENERICASSET``, or None when neither exists.
    """
    return next(
        (table for table in ASSET_TABLES if "ZFILENAME" in albums_table_columns(connection, table)),
        None,
    )


def albums_membership_query(connection: sqlite3.Connection) -> str | None:
    """Build the album-membership query for the schema actually present.

    connection: an open photo-database connection.
    Returns the SQL text, or None when the required tables are missing.
    """
    join = albums_discover_join(connection)
    asset_table = albums_asset_table(connection)
    if join is None or asset_table is None:
        return None
    if "ZTITLE" not in albums_table_columns(connection, "ZGENERICALBUM"):
        return None

    table, album_column, asset_column = join
    # Older schemas predate ZKIND; without it every titled album is accepted.
    kind_filter = ""
    if "ZKIND" in albums_table_columns(connection, "ZGENERICALBUM"):
        kind_filter = f"AND album.ZKIND = {USER_ALBUM_KIND}"
    return f"""
        SELECT album.ZTITLE AS album_name, asset.ZFILENAME AS file_name
        FROM ZGENERICALBUM AS album
        JOIN "{table}" AS link ON link."{album_column}" = album.Z_PK
        JOIN "{asset_table}" AS asset ON asset.Z_PK = link."{asset_column}"
        WHERE album.ZTITLE IS NOT NULL AND TRIM(album.ZTITLE) <> ''
          AND asset.ZFILENAME IS NOT NULL
          {kind_filter}
    """


def albums_parse_photos_database(database_path: Path) -> dict[str, list[str]]:
    """Extract album membership from a phone ``Photos.sqlite`` file.

    database_path: path to a copy of the phone's photo database.
    Returns a mapping of file name to album names; empty when the database is
    missing or unreadable, so callers fall back to ``_Unsorted``.
    """
    membership: dict[str, list[str]] = {}
    if not database_path.is_file():
        return membership

    try:
        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return membership

    try:
        connection.row_factory = sqlite3.Row
        query = albums_membership_query(connection)
        if query is None:
            logger.warning("no recognisable album tables in the photo database")
            return membership
        try:
            rows = connection.execute(query).fetchall()
        except sqlite3.Error as error:
            logger.warning("album membership query failed: %s", error)
            return membership
        for row in rows:
            file_name = str(row["file_name"])
            album_name = str(row["album_name"])
            names = membership.setdefault(file_name, [])
            if album_name not in names:
                names.append(album_name)
    finally:
        connection.close()

    return membership


def albums_list(connection: sqlite3.Connection) -> list[AlbumSummary]:
    """List albums with their archived asset counts.

    connection: an open catalog connection.
    Returns one ``AlbumSummary`` per album, excluding recycled assets.
    """
    summaries: list[AlbumSummary] = []
    for album in repository.repository_list_albums(connection):
        if album.album_id is None:
            continue
        row = connection.execute(
            """
            SELECT COUNT(DISTINCT asset_id) AS total
            FROM asset_files
            WHERE album_id = ? AND location = ?
            """,
            (album.album_id, FileLocation.PHOTOS.value),
        ).fetchone()
        summaries.append(
            AlbumSummary(
                album_id=album.album_id,
                name=album.name,
                safe_name=album.safe_name,
                asset_count=int(row["total"]) if row is not None else 0,
            )
        )
    return summaries


def albums_unsorted_count(connection: sqlite3.Connection) -> int:
    """Count active assets that belong to no album.

    connection: an open catalog connection.
    Returns the number of album-less, non-recycled assets.
    """
    row = connection.execute(
        """
        SELECT COUNT(*) AS total
        FROM assets
        WHERE archive_state = ?
          AND id NOT IN (SELECT asset_id FROM asset_albums)
        """,
        (ArchiveState.ACTIVE.value,),
    ).fetchone()
    return int(row["total"]) if row is not None else 0
