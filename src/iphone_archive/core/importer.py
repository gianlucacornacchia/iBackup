"""Incremental, append-only import of phone media into the archive.

Implements the specified two-pass workflow: a metadata-only **fast-skip pass**
that recognizes already-archived items by phone identity without transferring
bytes, then an **import pass** that streams only new content, verifies its hash,
places it atomically into album folders, writes a sidecar, and commits the
catalog rows. The run is idempotent, so an interrupted import resumes cleanly.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..catalog import repository
from ..catalog.models import (
    Album,
    Asset,
    AssetFile,
    FileLocation,
    ImportSession,
    PhoneItem,
)
from ..catalog.sidecar import SidecarData, sidecar_write
from ..config import ArchivePaths
from ..device.interface import DeviceError, MediaSource
from ..service.progress import ProgressHandle
from . import archive_layout, name_safety

OPERATION_NAME = "import"


@dataclass
class ImportResult:
    """Summary of a completed import run."""

    added_count: int = 0
    skipped_count: int = 0
    duplicate_count: int = 0
    error_count: int = 0
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)
    added_hashes: list[str] = field(default_factory=list)


def importer_now() -> str:
    """Return the current time as an ISO-8601 string.

    Returns the timestamp used for imported/seen/verified fields.
    """
    return datetime.now().isoformat(timespec="seconds")


def importer_run(
    connection: sqlite3.Connection,
    paths: ArchivePaths,
    source: MediaSource,
    progress: ProgressHandle | None = None,
    link_mode: str = archive_layout.LINK_MODE_COPY,
) -> ImportResult:
    """Import all new media from a source into the archive.

    connection: an open catalog connection.
    paths: resolved archive paths.
    source: the media source to import from (real device or fake).
    progress: optional progress/cancellation handle.
    link_mode: ``copy`` or ``hardlink`` for extra album copies.
    Returns an ``ImportResult`` summarizing the run.
    """
    handle = progress if progress is not None else ProgressHandle()
    result = ImportResult()
    scanned_at = importer_now()

    session = ImportSession(device_udid=source.device_udid(), started_at=scanned_at)
    session.session_id = repository.repository_create_import_session(connection, session)

    items = list(source.device_enumerate())
    repository.repository_mark_all_absent(connection)
    total = len(items)

    for index, item in enumerate(items, start=1):
        if handle.progress_is_cancelled():
            result.cancelled = True
            break
        handle.progress_report(OPERATION_NAME, index, total, item.original_name)
        try:
            importer_process_item(connection, paths, source, item, scanned_at, link_mode, result)
        except (DeviceError, OSError) as error:
            result.error_count += 1
            result.errors.append(f"{item.phone_path}: {error}")
        connection.commit()

    session.finished_at = importer_now()
    session.added_count = result.added_count
    session.skipped_count = result.skipped_count
    session.error_count = result.error_count
    repository.repository_finish_import_session(connection, session)
    connection.commit()
    return result


def importer_process_item(
    connection: sqlite3.Connection,
    paths: ArchivePaths,
    source: MediaSource,
    item: PhoneItem,
    scanned_at: str,
    link_mode: str,
    result: ImportResult,
) -> None:
    """Import a single enumerated item, skipping it when already archived.

    connection: an open catalog connection.
    paths: resolved archive paths.
    source: the media source being imported from.
    item: the enumerated phone item to process.
    scanned_at: ISO timestamp of the current scan.
    link_mode: ``copy`` or ``hardlink`` for extra album copies.
    result: the running result summary, updated in place.
    Returns None.
    """
    known = repository.repository_find_by_phone_identity(
        connection, item.phone_asset_id, item.phone_path, item.size
    )
    if known is not None and known.asset_id is not None:
        # Fast-skip pass: identity match means the bytes are already archived, so
        # nothing is transferred; only newly discovered albums are reconciled.
        repository.repository_mark_present(connection, known.asset_id, scanned_at)
        importer_sync_albums(connection, paths, known.asset_id, item, link_mode)
        result.skipped_count += 1
        return

    with source.device_open(item.phone_path) as stream:
        target_dir = importer_target_dir(paths, item)
        placed = archive_layout.archive_layout_store_stream(
            paths, stream, target_dir, item.original_name
        )

    existing = repository.repository_get_asset_by_hash(connection, placed.sha256)
    if existing is not None and existing.asset_id is not None:
        # Same content under a different phone identity: keep one stored copy and
        # discard the freshly staged duplicate.
        placed.path.unlink(missing_ok=True)
        repository.repository_mark_present(connection, existing.asset_id, scanned_at)
        importer_sync_albums(connection, paths, existing.asset_id, item, link_mode)
        result.duplicate_count += 1
        result.skipped_count += 1
        return

    asset = Asset(
        sha256=placed.sha256,
        size=placed.size,
        original_name=item.original_name,
        media_type=item.media_type,
        captured_at=item.captured_at,
        imported_at=scanned_at,
        verified_at=scanned_at,
        first_seen_on_phone_at=scanned_at,
        last_seen_on_phone_at=scanned_at,
        present_on_phone=True,
        phone_asset_id=item.phone_asset_id,
        phone_path=item.phone_path,
        phone_size=item.size,
        phone_modified_at=item.modified_at,
    )
    asset_id = repository.repository_insert_asset(connection, asset)

    primary_album_id = importer_album_id(connection, item, index=0)
    repository.repository_insert_asset_file(
        connection,
        AssetFile(
            asset_id=asset_id,
            path=archive_layout.archive_layout_relative_path(paths, placed.path),
            album_id=primary_album_id,
            link_mode=placed.link_mode,
            location=FileLocation.PHOTOS,
        ),
    )
    if primary_album_id is not None:
        repository.repository_link_asset_album(connection, asset_id, primary_album_id)

    importer_place_extra_albums(connection, paths, asset_id, item, placed.path, link_mode)

    sidecar_write(
        paths.sidecars_dir,
        SidecarData(
            sha256=placed.sha256,
            size=placed.size,
            original_name=item.original_name,
            media_type=item.media_type,
            source_phone_path=item.phone_path,
            captured_at=item.captured_at,
            imported_at=scanned_at,
            albums=list(item.album_names),
        ),
    )
    result.added_count += 1
    result.added_hashes.append(placed.sha256)


def importer_target_dir(paths: ArchivePaths, item: PhoneItem) -> Path:
    """Return the folder the item's primary copy belongs in.

    paths: resolved archive paths.
    item: the phone item being imported.
    Returns the first album's folder, or a dated _Unsorted folder.
    """
    if item.album_names:
        target = archive_layout.archive_layout_album_dir(paths, item.album_names[0])
    else:
        target = archive_layout.archive_layout_unsorted_dir(paths, item.captured_at)
    return target


def importer_album_id(connection: sqlite3.Connection, item: PhoneItem, index: int) -> int | None:
    """Return the catalog album id for one of an item's albums.

    connection: an open catalog connection.
    item: the phone item whose album to resolve.
    index: position within the item's album list.
    Returns the album id, or None when the item has no album at that position.
    """
    result: int | None = None
    if len(item.album_names) > index:
        name = item.album_names[index]
        result = repository.repository_upsert_album(
            connection,
            Album(
                name=name,
                safe_name=name_safety.name_safety_sanitize_component(name, fallback="Album"),
            ),
        )
    return result


def importer_place_extra_albums(
    connection: sqlite3.Connection,
    paths: ArchivePaths,
    asset_id: int,
    item: PhoneItem,
    source_path: Path,
    link_mode: str,
) -> None:
    """Place additional real copies for every album beyond the first.

    connection: an open catalog connection.
    paths: resolved archive paths.
    asset_id: the catalog id of the asset being placed.
    item: the phone item carrying album membership.
    source_path: the already-stored primary copy.
    link_mode: ``copy`` or ``hardlink``.
    Returns None.
    """
    for index in range(1, len(item.album_names)):
        album_id = importer_album_id(connection, item, index)
        if album_id is None:
            continue
        target_dir = archive_layout.archive_layout_album_dir(paths, item.album_names[index])
        duplicate = archive_layout.archive_layout_duplicate_file(
            source_path, target_dir, link_mode=link_mode
        )
        repository.repository_insert_asset_file(
            connection,
            AssetFile(
                asset_id=asset_id,
                path=archive_layout.archive_layout_relative_path(paths, duplicate.path),
                album_id=album_id,
                link_mode=duplicate.link_mode,
                location=FileLocation.PHOTOS,
            ),
        )
        repository.repository_link_asset_album(connection, asset_id, album_id)


def importer_sync_albums(
    connection: sqlite3.Connection,
    paths: ArchivePaths,
    asset_id: int,
    item: PhoneItem,
    link_mode: str,
) -> None:
    """Add copies for albums discovered after an asset was first imported.

    connection: an open catalog connection.
    paths: resolved archive paths.
    asset_id: the already-archived asset.
    item: the phone item carrying current album membership.
    link_mode: ``copy`` or ``hardlink``.
    Returns None. Album growth is append-only: existing copies are never moved
    or removed.
    """
    existing_files = repository.repository_list_asset_files(connection, asset_id)
    if not existing_files:
        return
    existing_album_ids = {
        stored.album_id for stored in existing_files if stored.album_id is not None
    }
    source_path = paths.root / existing_files[0].path
    if not source_path.is_file():
        return

    for index in range(len(item.album_names)):
        album_id = importer_album_id(connection, item, index)
        if album_id is None or album_id in existing_album_ids:
            continue
        target_dir = archive_layout.archive_layout_album_dir(paths, item.album_names[index])
        duplicate = archive_layout.archive_layout_duplicate_file(
            source_path, target_dir, link_mode=link_mode
        )
        repository.repository_insert_asset_file(
            connection,
            AssetFile(
                asset_id=asset_id,
                path=archive_layout.archive_layout_relative_path(paths, duplicate.path),
                album_id=album_id,
                link_mode=duplicate.link_mode,
                location=FileLocation.PHOTOS,
            ),
        )
        repository.repository_link_asset_album(connection, asset_id, album_id)
