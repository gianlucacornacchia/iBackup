"""Copy-scoped, recoverable recycle, restore and confirmed purge operations."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..catalog import repository
from ..catalog.models import FileLocation
from ..config import ArchivePaths
from . import file_operations, name_safety


@dataclass
class RecycleResult:
    """Asset counts affected by a copy-scoped recycle-bin operation."""

    moved_count: int = 0
    restored_count: int = 0
    purged_count: int = 0
    skipped_count: int = 0
    errors: list[str] = field(default_factory=list)


def recycle_deleted_path_for(paths: ArchivePaths, stored_path: str) -> Path:
    """Map a validated Photos path into Deleted, preserving its album subpath."""
    source = file_operations.file_operations_path(paths, stored_path)
    return paths.deleted_dir / source.relative_to(paths.photos_dir)


def recycle_restored_path_for(paths: ArchivePaths, stored_path: str) -> Path:
    """Map a validated Deleted path into Photos, preserving its album subpath."""
    source = file_operations.file_operations_path(paths, stored_path)
    return paths.photos_dir / source.relative_to(paths.deleted_dir)


def recycle_unique_destination(destination: Path) -> Path:
    """Return a portable destination that avoids case-insensitive disk collisions."""
    existing = (
        {entry.name.lower() for entry in destination.parent.iterdir()}
        if destination.parent.is_dir()
        else set()
    )
    return destination.with_name(
        name_safety.name_safety_resolve_collision(
            name_safety.name_safety_safe_file_name(destination.name), existing
        )
    )


def recycle_apply(
    connection: sqlite3.Connection,
    paths: ArchivePaths,
    asset_ids: list[int],
    operation: str,
    file_ids: list[int] | None = None,
    update: Callable[[], None] | None = None,
    recycled_only: bool = False,
) -> RecycleResult:
    """Preflight and execute the entire copy selection with one catalog commit."""
    file_operations.file_operations_recover(connection, paths)
    identifiers = file_operations.file_operations_ids(asset_ids)
    location = {
        "recycle": "photos",
        "restore": "deleted",
        "purge": "deleted" if recycled_only else None,
    }[operation]
    selected = file_operations.file_operations_select(
        connection, paths, identifiers, location, file_ids
    )
    changes = []
    reserved = {stored.path for stored in repository.repository_all_asset_files(connection)}
    for stored in selected:
        asset = repository.repository_get_asset(connection, stored.asset_id)
        assert asset is not None and stored.file_id is not None
        destination = ""
        target_location = None
        if operation != "purge":
            desired = (
                recycle_deleted_path_for(paths, stored.path)
                if operation == "recycle"
                else recycle_restored_path_for(paths, stored.path)
            )
            destination = file_operations.file_operations_destination(paths, desired, reserved)
            target_location = (
                FileLocation.DELETED.value if operation == "recycle" else FileLocation.PHOTOS.value
            )
        changes.append(
            file_operations.FileChange(
                stored.file_id,
                stored.asset_id,
                stored.path,
                destination,
                target_location,
                stored.album_id,
                asset.sha256,
            )
        )
    file_operations.file_operations_execute(connection, paths, changes, update)
    affected_count = len({change.asset_id for change in changes})
    result = RecycleResult(skipped_count=len(identifiers) - affected_count)
    if operation == "recycle":
        result.moved_count = affected_count
    elif operation == "restore":
        result.restored_count = affected_count
    else:
        result.purged_count = affected_count
    return result


def recycle_move_to_deleted(
    connection: sqlite3.Connection,
    paths: ArchivePaths,
    asset_ids: list[int],
    *,
    file_ids: list[int] | None = None,
    update: Callable[[], None] | None = None,
) -> RecycleResult:
    """Recycle active copies, optionally scoped by file_ids; update joins the commit."""
    return recycle_apply(connection, paths, asset_ids, "recycle", file_ids, update)


def recycle_restore(
    connection: sqlite3.Connection,
    paths: ArchivePaths,
    asset_ids: list[int],
    *,
    file_ids: list[int] | None = None,
) -> RecycleResult:
    """Restore deleted copies, including partially recycled assets, without overwrite."""
    return recycle_apply(connection, paths, asset_ids, "restore", file_ids)


def recycle_purge(
    connection: sqlite3.Connection,
    paths: ArchivePaths,
    asset_ids: list[int],
    confirmed: bool = False,
    *,
    file_ids: list[int] | None = None,
    update: Callable[[], None] | None = None,
    recycled_only: bool = False,
) -> RecycleResult:
    """Purge selected copies after confirmation; recycled_only excludes Photos."""
    if not confirmed:
        return RecycleResult(skipped_count=len(file_operations.file_operations_ids(asset_ids)))
    return recycle_apply(connection, paths, asset_ids, "purge", file_ids, update, recycled_only)


def recycle_list_deleted(connection: sqlite3.Connection) -> list[int]:
    """List assets having at least one deleted copy, including mixed-state assets."""
    rows = connection.execute(
        "SELECT DISTINCT asset_id FROM asset_files WHERE location = 'deleted' ORDER BY asset_id"
    ).fetchall()
    return [int(row["asset_id"]) for row in rows]
