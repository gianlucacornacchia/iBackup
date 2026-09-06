"""Album membership extraction and browsing.

Album information is read best-effort from the phone's ``Photos.sqlite``. When
that database is unavailable or unreadable, assets are filed under ``_Unsorted``
rather than failing the import — album data is a bonus, never a prerequisite.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..catalog import repository
from ..catalog.models import ArchiveState

# Candidate queries for the album tables across iOS Photos.sqlite versions.
ALBUM_QUERIES = (
    """
    SELECT album.ZTITLE AS album_name, asset.ZFILENAME AS file_name
    FROM ZGENERICALBUM AS album
    JOIN Z_28ASSETS AS link ON link.Z_28ALBUMS = album.Z_PK
    JOIN ZASSET AS asset ON asset.Z_PK = link.Z_3ASSETS
    WHERE album.ZTITLE IS NOT NULL
    """,
    """
    SELECT album.ZTITLE AS album_name, asset.ZFILENAME AS file_name
    FROM ZGENERICALBUM AS album
    JOIN ZASSET AS asset ON asset.ZMOMENT = album.Z_PK
    WHERE album.ZTITLE IS NOT NULL
    """,
)


@dataclass
class AlbumSummary:
    """An album and how many archived assets it contains."""

    album_id: int
    name: str
    safe_name: str
    asset_count: int


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
        for query in ALBUM_QUERIES:
            try:
                rows = connection.execute(query).fetchall()
            except sqlite3.Error:
                # Schema differs between iOS versions; try the next known shape.
                continue
            for row in rows:
                file_name = str(row["file_name"])
                album_name = str(row["album_name"])
                names = membership.setdefault(file_name, [])
                if album_name not in names:
                    names.append(album_name)
            if membership:
                break
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
            SELECT COUNT(*) AS total
            FROM asset_albums
            JOIN assets ON assets.id = asset_albums.asset_id
            WHERE asset_albums.album_id = ? AND assets.archive_state = ?
            """,
            (album.album_id, ArchiveState.ACTIVE.value),
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
