"""The ``Deleted/`` recycle bin: reversible removal from the browsable archive.

Moving an asset to ``Deleted/`` preserves its album subpath, keeps its files on
disk (so they still verify), and marks it ``archive_state=deleted`` so it no
longer appears when browsing albums. Restore returns it to its original place.
Purging is the only destructive operation and requires explicit confirmation.
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from ..catalog import repository
from ..catalog.models import ArchiveState, FileLocation
from ..catalog.sidecar import sidecar_path_for
from ..config import PHOTOS_DIR_NAME, ArchivePaths


@dataclass
class RecycleResult:
    """Summary of a recycle-bin operation."""

    moved_count: int = 0
    restored_count: int = 0
    purged_count: int = 0
    skipped_count: int = 0
    errors: list[str] = field(default_factory=list)


def recycle_deleted_path_for(paths: ArchivePaths, stored_path: str) -> Path:
    """Map an archived file path to its location inside ``Deleted/``.

    paths: resolved archive paths.
    stored_path: archive-relative path of the stored file.
    Returns the absolute destination path, preserving the album subpath.
    """
    relative = Path(stored_path)
    if relative.parts and relative.parts[0] == PHOTOS_DIR_NAME:
        relative = Path(*relative.parts[1:])
    return paths.deleted_dir / relative


def recycle_restored_path_for(paths: ArchivePaths, stored_path: str) -> Path:
    """Map a path inside ``Deleted/`` back to its original ``Photos/`` location.

    paths: resolved archive paths.
    stored_path: archive-relative path of the recycled file.
    Returns the absolute destination path under ``Photos/``.
    """
    relative = Path(stored_path)
    if relative.parts and relative.parts[0] == Path(paths.deleted_dir).name:
        relative = Path(*relative.parts[1:])
    return paths.photos_dir / relative


def recycle_unique_destination(destination: Path) -> Path:
    """Return a non-colliding destination path.

    destination: the desired absolute target path.
    Returns the path itself when free, otherwise a numbered variant.
    """
    result = destination
    counter = 1
    while result.exists():
        result = destination.with_name(f"{destination.stem}-{counter}{destination.suffix}")
        counter += 1
    return result


def recycle_move_to_deleted(
    connection: sqlite3.Connection, paths: ArchivePaths, asset_ids: list[int]
) -> RecycleResult:
    """Move assets into the ``Deleted/`` recycle bin (reversible).

    connection: an open catalog connection.
    paths: resolved archive paths.
    asset_ids: the assets to recycle.
    Returns a ``RecycleResult``. Files are moved, never destroyed.
    """
    result = RecycleResult()
    for asset_id in asset_ids:
        stored_files = repository.repository_list_asset_files(connection, asset_id)
        if not stored_files:
            result.skipped_count += 1
            continue
        for stored in stored_files:
            if stored.location is FileLocation.DELETED or stored.file_id is None:
                continue
            source = paths.root / stored.path
            destination = recycle_unique_destination(recycle_deleted_path_for(paths, stored.path))
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_file():
                shutil.move(str(source), str(destination))
            repository.repository_update_asset_file_path(
                connection,
                stored.file_id,
                destination.resolve().relative_to(paths.root).as_posix(),
                FileLocation.DELETED,
            )
        repository.repository_set_archive_state(connection, asset_id, ArchiveState.DELETED)
        result.moved_count += 1
    connection.commit()
    return result


def recycle_restore(
    connection: sqlite3.Connection, paths: ArchivePaths, asset_ids: list[int]
) -> RecycleResult:
    """Restore recycled assets back into the browsable ``Photos/`` tree.

    connection: an open catalog connection.
    paths: resolved archive paths.
    asset_ids: the assets to restore.
    Returns a ``RecycleResult``.
    """
    result = RecycleResult()
    for asset_id in asset_ids:
        stored_files = repository.repository_list_asset_files(connection, asset_id)
        if not stored_files:
            result.skipped_count += 1
            continue
        for stored in stored_files:
            if stored.location is not FileLocation.DELETED or stored.file_id is None:
                continue
            source = paths.root / stored.path
            destination = recycle_unique_destination(recycle_restored_path_for(paths, stored.path))
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_file():
                shutil.move(str(source), str(destination))
            repository.repository_update_asset_file_path(
                connection,
                stored.file_id,
                destination.resolve().relative_to(paths.root).as_posix(),
                FileLocation.PHOTOS,
            )
        repository.repository_set_archive_state(connection, asset_id, ArchiveState.ACTIVE)
        result.restored_count += 1
    connection.commit()
    return result


def recycle_purge(
    connection: sqlite3.Connection,
    paths: ArchivePaths,
    asset_ids: list[int],
    confirmed: bool = False,
) -> RecycleResult:
    """Permanently remove assets from the archive after explicit confirmation.

    connection: an open catalog connection.
    paths: resolved archive paths.
    asset_ids: the assets to permanently delete.
    confirmed: must be True; otherwise nothing is removed.
    Returns a ``RecycleResult``. This is the only destructive archive operation.
    """
    result = RecycleResult()
    if not confirmed:
        result.skipped_count = len(asset_ids)
        return result

    for asset_id in asset_ids:
        row = connection.execute("SELECT sha256 FROM assets WHERE id = ?", (asset_id,)).fetchone()
        if row is None:
            result.skipped_count += 1
            continue
        for stored in repository.repository_list_asset_files(connection, asset_id):
            absolute = paths.root / stored.path
            if absolute.is_file():
                absolute.unlink()
        sidecar = sidecar_path_for(paths.sidecars_dir, str(row["sha256"]))
        if sidecar.is_file():
            sidecar.unlink()
        repository.repository_delete_asset(connection, asset_id)
        result.purged_count += 1
    connection.commit()
    return result


def recycle_list_deleted(connection: sqlite3.Connection) -> list[int]:
    """List asset ids currently held in the recycle bin.

    connection: an open catalog connection.
    Returns the ids of assets whose archive state is ``deleted``.
    """
    rows = connection.execute(
        "SELECT id FROM assets WHERE archive_state = ?", (ArchiveState.DELETED.value,)
    ).fetchall()
    return [int(row["id"]) for row in rows]
