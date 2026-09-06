"""Browsing the archive: album listings and asset queries.

Supplies the read models that both the CLI and the future GUI use to present the
archive. Recycled assets (``Deleted/``) are excluded from normal album browsing
but remain queryable through the dedicated recycle-bin view.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from ..catalog.models import ArchiveState
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


def gallery_row_to_view(row: sqlite3.Row, paths: list[str]) -> AssetView:
    """Map an asset row plus its stored paths into a view model.

    row: a row from the ``assets`` table.
    paths: archive-relative paths of the asset's stored copies.
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
    )


def gallery_collect_paths(
    connection: sqlite3.Connection, asset_ids: list[int]
) -> dict[int, list[str]]:
    """Fetch stored paths for many assets in one query.

    connection: an open catalog connection.
    asset_ids: the assets whose paths to collect.
    Returns a mapping of asset id to its archive-relative paths.
    """
    grouped: dict[int, list[str]] = {}
    if not asset_ids:
        return grouped
    placeholders = ",".join("?" for _ in asset_ids)
    rows = connection.execute(
        f"SELECT asset_id, path FROM asset_files WHERE asset_id IN ({placeholders})",
        asset_ids,
    ).fetchall()
    for row in rows:
        grouped.setdefault(int(row["asset_id"]), []).append(str(row["path"]))
    return grouped


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
    clauses = []
    parameters: list[object] = []
    if not include_deleted:
        clauses.append("assets.archive_state = ?")
        parameters.append(ArchiveState.ACTIVE.value)
    if album_id is not None:
        clauses.append("assets.id IN (SELECT asset_id FROM asset_albums WHERE album_id = ?)")
        parameters.append(album_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"SELECT * FROM assets {where} ORDER BY COALESCE(captured_at, ''), original_name"
    if limit is not None:
        query += " LIMIT ? OFFSET ?"
        parameters.extend([limit, offset])

    rows = connection.execute(query, parameters).fetchall()
    paths_by_asset = gallery_collect_paths(connection, [int(row["id"]) for row in rows])
    return [gallery_row_to_view(row, paths_by_asset.get(int(row["id"]), [])) for row in rows]


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
    paths_by_asset = gallery_collect_paths(connection, [int(row["id"]) for row in rows])
    return [gallery_row_to_view(row, paths_by_asset.get(int(row["id"]), [])) for row in rows]


def gallery_list_recycled(connection: sqlite3.Connection) -> list[AssetView]:
    """List assets currently held in the ``Deleted/`` recycle bin.

    connection: an open catalog connection.
    Returns the recycled assets as view models.
    """
    rows = connection.execute(
        "SELECT * FROM assets WHERE archive_state = ? ORDER BY original_name",
        (ArchiveState.DELETED.value,),
    ).fetchall()
    paths_by_asset = gallery_collect_paths(connection, [int(row["id"]) for row in rows])
    return [gallery_row_to_view(row, paths_by_asset.get(int(row["id"]), [])) for row in rows]


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
