"""Multi-select operations on assets.

Supports the GUI's batch actions — move a selection to another album, mark a
selection for deletion, or recycle a selection — while guaranteeing the archive's
append-only rules. Moving changes only album placement, never content.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from ..catalog import repository
from ..catalog.models import Album, FileLocation
from ..config import ArchivePaths
from ..core import file_operations, name_safety


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
    *,
    source_album_id: int | None = None,
    file_ids: list[int] | None = None,
) -> SelectionResult:
    """Move selected assets into another album folder.

    connection: an open catalog connection.
    paths: resolved archive paths.
    asset_ids: the assets to move.
    album_name: destination album display name.
    source_album_id: restrict moves to copies in this album, when given.
    file_ids: optionally restrict the exact copies, belonging to asset_ids.
    Returns a ``SelectionResult``. Without scope, all active copies move; no
    content is discarded and unrelated recycled copies remain restorable.
    """
    file_operations.file_operations_recover(connection, paths)
    identifiers = file_operations.file_operations_ids(asset_ids)
    if not isinstance(album_name, str) or not album_name.strip():
        raise ValueError("Destination album name must not be empty")
    if source_album_id is not None:
        file_operations.file_operations_ids([source_album_id])
        if (
            connection.execute("SELECT id FROM albums WHERE id = ?", (source_album_id,)).fetchone()
            is None
        ):
            raise ValueError(f"Unknown source album: {source_album_id}")
    active = file_operations.file_operations_select(
        connection, paths, identifiers, FileLocation.PHOTOS.value, file_ids, source_album_id
    )
    selected_ids = {stored.asset_id for stored in active}
    if selected_ids != set(identifiers):
        raise ValueError("Every selected asset must have an active copy in the source scope")
    if not active:
        return SelectionResult()
    safe_name = name_safety.name_safety_sanitize_component(album_name, fallback="Album")
    albums = repository.repository_list_albums(connection)
    target_album = next((album for album in albums if album.name == album_name), None)
    if target_album is None:
        taken = {album.safe_name.lower() for album in albums}
        taken.update(entry.name.lower() for entry in paths.photos_dir.iterdir())
        safe_name = name_safety.name_safety_resolve_collision(safe_name, taken)
    else:
        safe_name = target_album.safe_name
    target_dir = paths.photos_dir / safe_name
    reserved = {stored.path for stored in repository.repository_all_asset_files(connection)}
    changes = []
    try:
        album_id = repository.repository_upsert_album(
            connection, Album(name=album_name, safe_name=safe_name)
        )
        for stored in active:
            if stored.album_id == album_id:
                continue
            asset = repository.repository_get_asset(connection, stored.asset_id)
            assert asset is not None and stored.file_id is not None
            destination = file_operations.file_operations_destination(
                paths, target_dir / (paths.root / stored.path).name, reserved
            )
            changes.append(
                file_operations.FileChange(
                    stored.file_id,
                    stored.asset_id,
                    stored.path,
                    destination,
                    FileLocation.PHOTOS.value,
                    album_id,
                    asset.sha256,
                )
            )
        file_operations.file_operations_execute(connection, paths, changes)
    except Exception:
        connection.rollback()
        raise
    affected = {change.asset_id for change in changes}
    return SelectionResult(
        affected_count=len(affected),
        skipped_count=len(identifiers) - len(affected),
    )


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
    asset_ids = file_operations.file_operations_ids(asset_ids)
    if not asset_ids:
        return 0
    placeholders = ",".join("?" for _ in asset_ids)
    row = connection.execute(
        f"SELECT COALESCE(SUM(size), 0) AS total FROM assets WHERE id IN ({placeholders})",
        asset_ids,
    ).fetchone()
    return int(row["total"]) if row is not None else 0
