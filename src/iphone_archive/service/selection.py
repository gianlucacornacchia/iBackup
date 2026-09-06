"""Multi-select operations on assets.

Supports the GUI's batch actions — move a selection to another album, mark a
selection for deletion, or recycle a selection — while guaranteeing the archive's
append-only rules. Moving changes only album placement, never content.
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass, field

from ..catalog import repository
from ..catalog.models import Album, FileLocation
from ..config import ArchivePaths
from ..core import archive_layout, name_safety


@dataclass
class SelectionResult:
    """Outcome of a batch operation over selected assets."""

    affected_count: int = 0
    skipped_count: int = 0
    errors: list[str] = field(default_factory=list)


def selection_move_to_album(
    connection: sqlite3.Connection,
    paths: ArchivePaths,
    asset_ids: list[int],
    album_name: str,
) -> SelectionResult:
    """Move selected assets into another album folder.

    connection: an open catalog connection.
    paths: resolved archive paths.
    asset_ids: the assets to move.
    album_name: destination album display name.
    Returns a ``SelectionResult``. File content is never modified.
    """
    result = SelectionResult()
    safe_name = name_safety.name_safety_sanitize_component(album_name, fallback="Album")
    album_id = repository.repository_upsert_album(
        connection, Album(name=album_name, safe_name=safe_name)
    )
    target_dir = archive_layout.archive_layout_album_dir(paths, album_name)

    for asset_id in asset_ids:
        stored_files = repository.repository_list_asset_files(connection, asset_id)
        active = [
            stored
            for stored in stored_files
            if stored.location is FileLocation.PHOTOS and stored.file_id is not None
        ]
        if not active:
            result.skipped_count += 1
            continue

        primary = active[0]
        source = paths.root / primary.path
        if not source.is_file():
            result.skipped_count += 1
            continue

        target_dir.mkdir(parents=True, exist_ok=True)
        destination = archive_layout.archive_layout_unique_target(target_dir, source.name)
        shutil.move(str(source), str(destination))
        repository.repository_update_asset_file_path(
            connection,
            primary.file_id if primary.file_id is not None else 0,
            archive_layout.archive_layout_relative_path(paths, destination),
            FileLocation.PHOTOS,
        )
        connection.execute(
            "UPDATE asset_files SET album_id = ? WHERE id = ?", (album_id, primary.file_id)
        )
        connection.execute("DELETE FROM asset_albums WHERE asset_id = ?", (asset_id,))
        repository.repository_link_asset_album(connection, asset_id, album_id)
        result.affected_count += 1

    connection.commit()
    return result


def selection_asset_ids_in_album(connection: sqlite3.Connection, album_id: int) -> list[int]:
    """List the assets belonging to an album.

    connection: an open catalog connection.
    album_id: the album to expand.
    Returns the ids of its member assets.
    """
    rows = connection.execute(
        "SELECT asset_id FROM asset_albums WHERE album_id = ?", (album_id,)
    ).fetchall()
    return [int(row["asset_id"]) for row in rows]


def selection_total_size(connection: sqlite3.Connection, asset_ids: list[int]) -> int:
    """Sum the stored size of a selection.

    connection: an open catalog connection.
    asset_ids: the selected assets.
    Returns the total byte size of those assets.
    """
    if not asset_ids:
        return 0
    placeholders = ",".join("?" for _ in asset_ids)
    row = connection.execute(
        f"SELECT COALESCE(SUM(size), 0) AS total FROM assets WHERE id IN ({placeholders})",
        asset_ids,
    ).fetchone()
    return int(row["total"]) if row is not None else 0
