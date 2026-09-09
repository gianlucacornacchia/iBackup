"""Browsing the archive: album listings and asset queries.

Supplies the read models that both the CLI and the future GUI use to present the
archive. Recycled assets (``Deleted/``) are excluded from normal album browsing
but remain queryable through the dedicated recycle-bin view.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from ..catalog.models import ArchiveState, FileLocation
from ..config import ArchivePaths


@dataclass
class AssetView:
    """A single asset as presented to a frontend."""

    asset_id: int
    sha256: str
    original_name: str
    media_type: str
    size: int
    captured_at: str | None
    present_on_phone: bool
    archive_state: str
    paths: list[str] = field(default_factory=list)
    file_ids: list[int] = field(default_factory=list)


def gallery_row_to_view(
    row: sqlite3.Row, paths: list[str], file_ids: list[int] | None = None
) -> AssetView:
    """Map an asset row plus its stored paths into a view model.

    row: a row from the ``assets`` table.
    paths: archive-relative paths of the asset's stored copies.
    file_ids: catalog ids corresponding to those paths for scoped editing.
    Returns the corresponding ``AssetView``.
    """
    return AssetView(
        asset_id=int(row["id"]),
        sha256=str(row["sha256"]),
        original_name=str(row["original_name"]),
        media_type=str(row["media_type"]),
        size=int(row["size"]),
        captured_at=row["captured_at"],
        present_on_phone=bool(row["present_on_phone"]),
        archive_state=str(row["archive_state"]),
        paths=paths,
        file_ids=file_ids if file_ids is not None else [],
    )


def gallery_collect_files(
    connection: sqlite3.Connection,
    asset_ids: list[int],
    location: FileLocation | None = None,
    album_id: int | None = None,
) -> dict[int, list[tuple[int, str]]]:
    """Fetch stored file ids and paths in bounded queries.

    connection: an open catalog connection.
    asset_ids: the assets whose paths to collect.
    location: restrict paths to Photos or Deleted when provided.
    album_id: restrict paths to one album when provided.
    Returns a mapping of asset id to its file-id/path pairs.
    """
    grouped: dict[int, list[tuple[int, str]]] = {}
    if not asset_ids:
        return grouped
    for offset in range(0, len(asset_ids), 500):
        batch = asset_ids[offset : offset + 500]
        placeholders = ",".join("?" for _ in batch)
        clauses = [f"asset_id IN ({placeholders})"]
        parameters: list[object] = list(batch)
        if location is not None:
            clauses.append("location = ?")
            parameters.append(location.value)
        if album_id is not None:
            clauses.append("album_id = ?")
            parameters.append(album_id)
        rows = connection.execute(
            f"SELECT id, asset_id, path FROM asset_files WHERE {' AND '.join(clauses)} ORDER BY id",
            parameters,
        ).fetchall()
        for row in rows:
            grouped.setdefault(int(row["asset_id"]), []).append((int(row["id"]), str(row["path"])))
    return grouped


def gallery_collect_paths(
    connection: sqlite3.Connection, asset_ids: list[int]
) -> dict[int, list[str]]:
    """Return archive-relative paths for the supplied asset ids."""
    return {
        asset_id: [path for _, path in files]
        for asset_id, files in gallery_collect_files(connection, asset_ids).items()
    }


def gallery_build_views(
    connection: sqlite3.Connection,
    rows: list[sqlite3.Row],
    location: FileLocation | None = None,
    album_id: int | None = None,
) -> list[AssetView]:
    """Attach matching file paths and scope ids to an ordered asset query result."""
    by_asset = gallery_collect_files(
        connection, [int(row["id"]) for row in rows], location, album_id
    )
    return [
        gallery_row_to_view(
            row,
            [path for _, path in by_asset.get(int(row["id"]), [])],
            [file_id for file_id, _ in by_asset.get(int(row["id"]), [])],
        )
        for row in rows
    ]


def gallery_list_assets(
    connection: sqlite3.Connection,
    album_id: int | None = None,
    include_deleted: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[AssetView]:
    """List archived assets, optionally filtered to one album.

    connection: an open catalog connection.
    album_id: restrict to this album, or None for all assets.
    include_deleted: when True, include assets held in the recycle bin.
    limit: maximum number of assets to return (None for all).
    offset: number of assets to skip, for paged/virtualized views.
    Returns a list of ``AssetView`` models ordered by capture time then name.
    """
    if offset < 0 or (limit is not None and limit < 0):
        raise ValueError("listing limit and offset must not be negative")
    clauses = []
    parameters: list[object] = []
    if not include_deleted:
        clauses.append("assets.archive_state = ?")
        parameters.append(ArchiveState.ACTIVE.value)
    if album_id is not None:
        membership = "SELECT asset_id FROM asset_files WHERE album_id = ?"
        parameters.append(album_id)
        if not include_deleted:
            membership += " AND location = ?"
            parameters.append(FileLocation.PHOTOS.value)
        clauses.append(f"assets.id IN ({membership})")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"SELECT * FROM assets {where} ORDER BY COALESCE(captured_at, ''), original_name, id"
    if limit is not None:
        query += " LIMIT ? OFFSET ?"
        parameters.extend([limit, offset])
    elif offset:
        query += " LIMIT -1 OFFSET ?"
        parameters.append(offset)

    rows = connection.execute(query, parameters).fetchall()
    return gallery_build_views(
        connection,
        rows,
        None if include_deleted else FileLocation.PHOTOS,
        album_id,
    )


def gallery_list_unsorted(connection: sqlite3.Connection) -> list[AssetView]:
    """List active assets that belong to no album.

    connection: an open catalog connection.
    Returns the album-less assets as view models.
    """
    rows = connection.execute(
        """
        SELECT * FROM assets
        WHERE archive_state = ?
          AND id NOT IN (SELECT asset_id FROM asset_albums)
        ORDER BY COALESCE(captured_at, ''), original_name
        """,
        (ArchiveState.ACTIVE.value,),
    ).fetchall()
    return gallery_build_views(connection, rows, FileLocation.PHOTOS)


def gallery_list_recycled(connection: sqlite3.Connection) -> list[AssetView]:
    """List assets currently held in the ``Deleted/`` recycle bin.

    connection: an open catalog connection.
    Returns the recycled assets as view models.
    """
    rows = connection.execute(
        "SELECT * FROM assets WHERE id IN "
        "(SELECT asset_id FROM asset_files WHERE location = ?) ORDER BY original_name, id",
        (FileLocation.DELETED.value,),
    ).fetchall()
    return gallery_build_views(connection, rows, FileLocation.DELETED)


def gallery_count_assets(connection: sqlite3.Connection, include_deleted: bool = False) -> int:
    """Count assets in the archive.

    connection: an open catalog connection.
    include_deleted: when True, count recycled assets too.
    Returns the number of matching assets.
    """
    if include_deleted:
        row = connection.execute("SELECT COUNT(*) AS total FROM assets").fetchone()
    else:
        row = connection.execute(
            "SELECT COUNT(*) AS total FROM assets WHERE archive_state = ?",
            (ArchiveState.ACTIVE.value,),
        ).fetchone()
    return int(row["total"]) if row is not None else 0


def gallery_absolute_path(paths: ArchivePaths, stored_path: str) -> str:
    """Resolve an archive-relative path to an absolute filesystem path.

    paths: resolved archive paths.
    stored_path: an archive-relative path from the catalog.
    Returns the absolute path as a string, for opening in a viewer.
    """
    return str(paths.root / stored_path)
