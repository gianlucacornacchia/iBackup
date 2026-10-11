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
# ZKIND of an iCloud Shared Album (formerly "Shared Photo Stream"), whether the
# phone's owner created it or subscribed to someone else's.
SHARED_ALBUM_KIND = 1505
# Where iOS keeps the locally cached copies of shared-album media. These are
# separate files from the owner's DCIM originals (iOS re-encodes on upload), and
# Photos.sqlite records them with a ZDIRECTORY under this AFC-relative root.
SHARED_MEDIA_ROOT = "/PhotoData/PhotoCloudSharingData"
# Catalog ``albums.kind`` values.
ALBUM_KIND_USER = "user"
ALBUM_KIND_SHARED = "shared"


def albums_is_shared_path(phone_path: str) -> bool:
    """Return whether a phone path lies inside the shared-album media cache.

    phone_path: an absolute AFC path.
    Returns True for ``/PhotoData/PhotoCloudSharingData/...`` files.
    """
    return phone_path.startswith(f"{SHARED_MEDIA_ROOT}/")


@dataclass
class AlbumSummary:
    """An album and how many archived assets it contains."""

    album_id: int
    name: str
    safe_name: str
    asset_count: int
    kind: str = ALBUM_KIND_USER


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
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
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


def albums_asset_key_sql(connection: sqlite3.Connection, table: str) -> str:
    """Return the identity expression for the known asset table aliased as ``asset``.

    Modern schemas require a directory: a bare filename must never identify
    an offloaded original as a different local photo with a reused name.
    """
    if "ZDIRECTORY" in albums_table_columns(connection, table):
        return (
            "CASE WHEN TRIM(asset.ZDIRECTORY, '/') <> '' THEN "
            "'/' || TRIM(asset.ZDIRECTORY, '/') || '/' || asset.ZFILENAME END"
        )
    return "asset.ZFILENAME"


def albums_membership_query(
    connection: sqlite3.Connection, kind: int = USER_ALBUM_KIND
) -> str | None:
    """Build the album-membership query for the schema actually present.

    connection: an open photo-database connection.
    kind: the ``ZKIND`` to select, ``USER_ALBUM_KIND`` or ``SHARED_ALBUM_KIND``.
    Returns the SQL text, or None when the required tables are missing. Shared
    albums can only be told apart via ZKIND, so a schema without it yields None
    for them rather than mislabelling every album as shared.
    """
    if kind not in (USER_ALBUM_KIND, SHARED_ALBUM_KIND):
        raise ValueError(f"unsupported album kind: {kind}")
    join = albums_discover_join(connection)
    asset_table = albums_asset_table(connection)
    if join is None or asset_table is None:
        return None
    album_columns = albums_table_columns(connection, "ZGENERICALBUM")
    if "ZTITLE" not in album_columns:
        return None

    table, album_column, asset_column = join
    # Older schemas predate ZKIND; without it every titled album is accepted.
    kind_filter = ""
    if "ZKIND" in album_columns:
        kind_filter = f"AND album.ZKIND = {int(kind)}"
    elif kind == SHARED_ALBUM_KIND:
        return None

    path_expr = albums_asset_key_sql(connection, asset_table)
    # Count every asset, not only album members: an unassigned local photo can
    # share its filename with an offloaded album member.
    unique_filter = ""
    if "ZDIRECTORY" not in albums_table_columns(connection, asset_table):
        unique_filter = f"""
            AND asset.ZFILENAME IN (
                SELECT ZFILENAME FROM "{asset_table}"
                GROUP BY ZFILENAME HAVING COUNT(*) = 1
            )
        """

    return f"""
        SELECT album.ZTITLE AS album_name, {path_expr} AS asset_path
        FROM ZGENERICALBUM AS album
        JOIN "{table}" AS link ON link."{album_column}" = album.Z_PK
        JOIN "{asset_table}" AS asset ON asset.Z_PK = link."{asset_column}"
        WHERE album.ZTITLE IS NOT NULL AND TRIM(album.ZTITLE) <> ''
          AND ({path_expr}) IS NOT NULL AND TRIM(asset.ZFILENAME) <> ''
          {kind_filter}
          {unique_filter}
    """


def albums_parse_photos_database(
    database_path: Path, kind: int = USER_ALBUM_KIND
) -> dict[str, list[str]]:
    """Extract album membership from a phone ``Photos.sqlite`` file.

    database_path: path to a copy of the phone's photo database.
    kind: which albums to read; user-created albums by default, or
        ``SHARED_ALBUM_KIND`` for iCloud Shared Albums.
    Returns a mapping of AFC asset path (e.g. ``/DCIM/100APPLE/IMG_0001.HEIC``)
    to album names; empty when the database is missing or unreadable, so callers
    fall back to ``_Unsorted``. On older schemas without ZDIRECTORY, bare keys
    are emitted only for filenames unique across the entire asset table.
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
        query = albums_membership_query(connection, kind)
        if query is None:
            if kind == USER_ALBUM_KIND:
                logger.warning("no recognisable album tables in the photo database")
            return membership
        try:
            rows = connection.execute(query).fetchall()
        except sqlite3.Error as error:
            logger.warning("album membership query failed: %s", error)
            return membership
        for row in rows:
            asset_path = str(row["asset_path"])
            album_name = str(row["album_name"])
            names = membership.setdefault(asset_path, [])
            if album_name not in names:
                names.append(album_name)
    finally:
        connection.close()

    return membership


def albums_parse_shared_albums(database_path: Path) -> dict[str, list[str]]:
    """Extract iCloud Shared Album membership from a phone ``Photos.sqlite``.

    database_path: path to a copy of the phone's photo database.
    Returns a mapping of AFC path to shared-album names. Only paths inside
    ``SHARED_MEDIA_ROOT`` are kept: those are the files the phone actually
    caches for a shared album, and any other key could never be enumerated.
    Empty when the database is missing, unreadable or predates ZKIND.
    """
    membership = albums_parse_photos_database(database_path, SHARED_ALBUM_KIND)
    return {path: names for path, names in membership.items() if albums_is_shared_path(path)}


def albums_location_query(connection: sqlite3.Connection) -> str | None:
    """Build the GPS-coordinate query for the schema actually present.

    connection: an open photo-database connection.
    Returns the SQL text, or None when the asset table has no recognisable
    latitude/longitude columns. iOS stores "no location" as CoreLocation's
    invalid coordinate (-180, -180) rather than NULL, so those sentinel rows
    are excluded alongside genuinely missing values.
    """
    asset_table = albums_asset_table(connection)
    if asset_table is None:
        return None
    columns = albums_table_columns(connection, asset_table)
    if "ZLATITUDE" not in columns or "ZLONGITUDE" not in columns:
        return None

    path_expr = albums_asset_key_sql(connection, asset_table)
    return f"""
        SELECT {path_expr} AS asset_path,
            asset.ZLATITUDE AS latitude, asset.ZLONGITUDE AS longitude
        FROM "{asset_table}" AS asset
        WHERE ({path_expr}) IS NOT NULL
          AND asset.ZLATITUDE IS NOT NULL AND asset.ZLONGITUDE IS NOT NULL
          AND asset.ZLATITUDE <> -180.0 AND asset.ZLONGITUDE <> -180.0
    """


def albums_parse_location_data(database_path: Path) -> dict[str, tuple[float, float]]:
    """Extract GPS coordinates from a phone ``Photos.sqlite`` file.

    database_path: path to a copy of the phone's photo database.
    Returns a mapping of AFC asset path to ``(latitude, longitude)``; empty
    when the database is missing, unreadable, or exposes no recognisable
    location columns, so callers simply treat those assets as having no map
    position rather than failing the import.
    """
    locations: dict[str, tuple[float, float]] = {}
    if not database_path.is_file():
        return locations

    try:
        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return locations

    try:
        connection.row_factory = sqlite3.Row
        query = albums_location_query(connection)
        if query is None:
            return locations
        try:
            rows = connection.execute(query).fetchall()
        except sqlite3.Error as error:
            logger.warning("location query failed: %s", error)
            return locations
        for row in rows:
            try:
                locations[str(row["asset_path"])] = (
                    float(row["latitude"]),
                    float(row["longitude"]),
                )
            except (TypeError, ValueError):
                continue
    finally:
        connection.close()

    return locations


def albums_list(
    connection: sqlite3.Connection, limit: int | None = None, offset: int = 0
) -> list[AlbumSummary]:
    """List albums with their archived asset counts.

    connection: an open catalog connection.
    limit: maximum albums, or None for all.
    offset: rows to skip in deterministic safe-name/id order.
    Returns one ``AlbumSummary`` per album, excluding recycled assets. Each
    summary carries the album's ``kind`` so frontends can list iCloud Shared
    Albums separately from the user's own albums.
    """
    paging, parameters = repository.repository_page_clause(limit, offset)
    rows = connection.execute(
        """
        SELECT albums.id, albums.name, albums.safe_name, albums.kind,
            (SELECT COUNT(DISTINCT asset_id) FROM asset_files
             WHERE album_id = albums.id AND location = ?) AS asset_count
        FROM albums ORDER BY safe_name, id
        """
        + paging,
        [FileLocation.PHOTOS.value, *parameters],
    ).fetchall()
    return [
        AlbumSummary(
            album_id=int(row["id"]),
            name=str(row["name"]),
            safe_name=str(row["safe_name"]),
            asset_count=int(row["asset_count"]),
            kind=str(row["kind"] or ALBUM_KIND_USER),
        )
        for row in rows
    ]


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
