"""Incremental, append-only import of phone media into the archive.

Implements the specified two-pass workflow: a metadata-only **fast-skip pass**
that recognizes already-archived items by phone identity without transferring
bytes, then an **import pass** that streams only new content, verifies its hash,
places it atomically into album folders, writes a sidecar, and commits the
catalog rows. The run is idempotent, so an interrupted import resumes cleanly.
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from ..catalog import repository
from ..catalog.models import (
    Album,
    Asset,
    AssetFile,
    FileLocation,
    ImportSession,
    PhoneItem,
)
from ..catalog.sidecar import sidecar_from_catalog, sidecar_path_for, sidecar_write
from ..config import ArchivePaths
from ..device.interface import DeviceError, MediaSource
from ..service.progress import ProgressHandle
from . import archive_layout, exif, hashing, name_safety
from .file_operations import file_operations_path, file_operations_write_journal

OPERATION_NAME = "import"


@dataclass
class ImportResult:
    """Summary of a completed import run."""

    added_count: int = 0
    skipped_count: int = 0
    duplicate_count: int = 0
    upgraded_count: int = 0
    error_count: int = 0
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)
    added_hashes: list[str] = field(default_factory=list)
    seen_sources: list[tuple[str, int]] = field(default_factory=list, repr=False)


class ImportJournal:
    """Durable per-item file intent paired with an atomic catalog commit marker."""

    def __init__(self, paths: ArchivePaths) -> None:
        """Initialize a unique journal under the archive's internal directory."""
        self.paths = paths
        self.identifier = uuid4().hex
        self.path = paths.internal_dir / "import-journals" / f"{self.identifier}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.staging = paths.internal_dir / "import-staging" / self.identifier
        file_operations_path(paths, self.staging.relative_to(paths.root).as_posix())
        self.staging.parent.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(mode=0o700)
        identity = self.staging.stat()
        self.staging_identity = [identity.st_dev, identity.st_ino]
        self.created: dict[str, list[int] | None] = {}
        self.records: dict[str, Path] = {}
        self.sidecars: dict[str, str | None] = {}
        try:
            archive_layout.archive_layout_sync(paths.internal_dir)
            archive_layout.archive_layout_sync(self.staging.parent)
            self.persist()
        except Exception:
            self.path.with_suffix(".pending").unlink(missing_ok=True)
            self.path.unlink(missing_ok=True)
            archive_layout.archive_layout_sync(self.path.parent)
            self.staging.rmdir()
            raise

    def persist(self) -> None:
        """Persist namespace ownership before any files can be created within it."""
        file_operations_write_journal(
            self.path,
            {
                "created": {},
                "sidecars": self.sidecars,
                "staging": {
                    "path": self.staging.relative_to(self.paths.root).as_posix(),
                    "identity": self.staging_identity,
                },
            },
        )

    def record(self, path: Path) -> None:
        """Record a new file that must disappear if the catalog rolls back."""
        if path.parent == self.staging:
            return
        relative = path.relative_to(self.paths.root).as_posix()
        file_operations_path(self.paths, relative)
        self.created[relative] = None
        self.write_ownership(relative)

    def write_ownership(self, relative: str) -> None:
        """Flush one bounded ownership record without rewriting the growing file set."""
        record = self.records.setdefault(relative, self.staging / f"{uuid4().hex}.owner")
        file_operations_write_journal(
            record, {"path": relative, "identity": self.created[relative]}
        )

    def prepare_publication(self, source: Path, destination: Path) -> None:
        """Identify a complete private inode durably before publishing its final name."""
        if source.parent != self.staging:
            raise RuntimeError("import publication requires the owned private staging namespace")
        relative = destination.relative_to(self.paths.root).as_posix()
        file_operations_path(self.paths, relative)
        identity = source.stat()
        self.created[relative] = [identity.st_dev, identity.st_ino]
        self.write_ownership(relative)

    def claim(self, path: Path, created: bool) -> None:
        """Record file identity after exclusive creation; never claim a colliding file."""
        if path.parent == self.staging:
            return
        relative = path.relative_to(self.paths.root).as_posix()
        if created:
            raise RuntimeError("public file ownership must be recorded before publication")
        else:
            self.created.pop(relative, None)
            record = self.records.pop(relative, None)
            if record is not None:
                record.unlink(missing_ok=True)
                archive_layout.archive_layout_sync(self.staging)

    def protect_sidecar(self, sha256: str) -> None:
        """Persist the original sidecar bytes before replacing its metadata."""
        target = sidecar_path_for(self.paths.sidecars_dir, sha256)
        relative = target.relative_to(self.paths.root).as_posix()
        file_operations_path(self.paths, relative)
        self.sidecars[relative] = (
            base64.b64encode(target.read_bytes()).decode("ascii") if target.exists() else None
        )
        self.persist()


def importer_recover(connection: sqlite3.Connection, paths: ArchivePaths) -> None:
    """Recover interrupted imports under the archive writer lock; never hide failures."""
    if connection.in_transaction:
        raise RuntimeError("Finish or roll back the current catalog transaction before recovery")
    directory = paths.internal_dir / "import-journals"
    for journal in sorted(directory.glob("*.json")):
        payload = json.loads(journal.read_text(encoding="utf-8"))
        staging: Path | None = None
        if "staging" in payload:
            staging = file_operations_path(paths, payload["staging"]["path"])
            if staging.exists():
                identity = staging.stat()
                if payload["staging"]["identity"] != [identity.st_dev, identity.st_ino]:
                    raise RuntimeError(f"import recovery staging namespace changed: {staging}")
                for record in sorted(staging.glob("*.owner")):
                    file_operations_path(paths, record.relative_to(paths.root).as_posix())
                    ownership = json.loads(record.read_text(encoding="utf-8"))
                    payload["created"][ownership["path"]] = ownership["identity"]
            else:
                raise RuntimeError(f"import recovery staging namespace missing: {staging}")
        committed = connection.execute(
            "SELECT 1 FROM import_commits WHERE journal_id = ?", (journal.stem,)
        ).fetchone()
        if committed is None:
            for relative in reversed(payload["created"]):
                target = file_operations_path(paths, relative)
                if target.exists():
                    ownership = payload["created"][relative]
                    info = target.stat()
                    if ownership != [info.st_dev, info.st_ino]:
                        raise RuntimeError(f"import recovery cannot establish ownership: {target}")
                    target.unlink()
                if target.parent.exists():
                    archive_layout.archive_layout_sync(target.parent)
            for relative, original in payload["sidecars"].items():
                target = file_operations_path(paths, relative)
                if original is None:
                    target.unlink(missing_ok=True)
                else:
                    with target.open("wb") as handle:
                        handle.write(base64.b64decode(original))
                        handle.flush()
                        os.fsync(handle.fileno())
                archive_layout.archive_layout_sync(target.parent)
        if staging is not None and staging.exists():
            for entry in staging.iterdir():
                file_operations_path(paths, entry.relative_to(paths.root).as_posix())
                if not entry.is_file() or entry.suffix not in {".partial", ".owner", ".pending"}:
                    raise RuntimeError(f"unexpected file in private import staging: {entry}")
                entry.unlink()
        journal.unlink()
        journal.with_suffix(".pending").unlink(missing_ok=True)
        archive_layout.archive_layout_sync(directory)
        if staging is not None:
            staging.rmdir()
            archive_layout.archive_layout_sync(staging.parent)
        connection.execute("DELETE FROM import_commits WHERE journal_id = ?", (journal.stem,))
        connection.commit()


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
    importer_recover(connection, paths)

    session = ImportSession(device_udid=source.device_udid(), started_at=scanned_at)
    session.session_id = repository.repository_create_import_session(connection, session)
    connection.commit()
    items = list(source.device_enumerate())
    total = len(items)

    for index, item in enumerate(items, start=1):
        if handle.progress_is_cancelled():
            result.cancelled = True
            break
        handle.progress_report(OPERATION_NAME, index, total, item.original_name)
        journal = ImportJournal(paths)
        token = archive_layout.placement_recorder.set(journal.record)
        claim_token = archive_layout.placement_claimer.set(journal.claim)
        staging_token = archive_layout.placement_staging_dir.set(journal.staging)
        prepare_token = archive_layout.placement_preparer.set(journal.prepare_publication)
        item_result = ImportResult()
        connection.execute("BEGIN")
        connection.execute("SAVEPOINT import_item")
        try:
            importer_process_item(
                connection, paths, source, item, scanned_at, link_mode, item_result, journal
            )
            connection.execute(
                "INSERT INTO import_commits(journal_id) VALUES (?)", (journal.identifier,)
            )
            connection.execute("RELEASE SAVEPOINT import_item")
            connection.commit()
        except Exception as error:
            connection.rollback()
            importer_recover(connection, paths)
            if not isinstance(error, (DeviceError, OSError, sqlite3.Error, ValueError)):
                raise
            result.error_count += 1
            result.errors.append(f"{item.phone_path}: {error}")
        else:
            importer_recover(connection, paths)
            result.added_count += item_result.added_count
            result.skipped_count += item_result.skipped_count
            result.duplicate_count += item_result.duplicate_count
            result.upgraded_count += item_result.upgraded_count
            result.added_hashes.extend(item_result.added_hashes)
            result.seen_sources.extend(item_result.seen_sources)
        finally:
            archive_layout.placement_recorder.reset(token)
            archive_layout.placement_claimer.reset(claim_token)
            archive_layout.placement_staging_dir.reset(staging_token)
            archive_layout.placement_preparer.reset(prepare_token)

    if handle.progress_is_cancelled():
        result.cancelled = True
    if not result.cancelled and not result.errors:
        repository.repository_publish_presence(
            connection, session.device_udid, result.seen_sources, scanned_at
        )

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
    journal: ImportJournal | None = None,
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
        connection,
        item.phone_asset_id,
        item.phone_path,
        item.size,
        source.device_udid(),
        item.modified_at,
    )
    if (
        known is not None
        and known.asset_id is not None
        and importer_has_valid_copy(connection, paths, known)
    ):
        # Fast-skip pass: identity match means the bytes are already archived, so
        # nothing is transferred; only newly discovered albums are reconciled.
        importer_backfill_metadata(connection, paths, known, item)
        importer_sync_albums(connection, paths, known.asset_id, item, link_mode)
        importer_update_sidecar(connection, paths, known.asset_id, journal)
        result.seen_sources.append((item.phone_path, known.asset_id))
        result.skipped_count += 1
        return

    upgrade_target: Asset | None = None
    if not item.is_offloaded_preview:
        # The real original may have been re-downloaded to the phone since a
        # previous import only found its cached low-resolution preview at this
        # same album path. Upgrade that preview in place instead of archiving a
        # duplicate second copy of the same photo.
        upgrade_target = repository.repository_find_offloaded_preview_by_original_path(
            connection, item.phone_path
        )

    with source.device_open(item.phone_path) as stream:
        target_dir = importer_target_dir(paths, item)
        placed = archive_layout.archive_layout_store_stream(
            paths, stream, target_dir, item.original_name
        )
    if placed.size != item.size:
        raise DeviceError(f"source size changed during import: {item.phone_path}")

    if upgrade_target is not None and upgrade_target.asset_id is not None:
        importer_upgrade_offloaded_preview(
            connection, paths, source, upgrade_target.asset_id, item, placed, link_mode, result
        )
        importer_update_sidecar(connection, paths, upgrade_target.asset_id, journal)
        return

    existing = repository.repository_get_asset_by_hash(connection, placed.sha256)
    if existing is not None and existing.asset_id is not None:
        placed_relative = archive_layout.archive_layout_relative_path(paths, placed.path)
        restored_recorded_copy = any(
            stored.path == placed_relative
            for stored in repository.repository_list_asset_files(connection, existing.asset_id)
        )
        importer_backfill_metadata(connection, paths, existing, item, file_path=placed.path)
        # Placement may have restored a missing catalogued path. Do not mistake
        # that newly restored file for a pre-existing duplicate and unlink it.
        if not restored_recorded_copy and importer_has_valid_copy(connection, paths, existing):
            placed.path.unlink()
        elif not restored_recorded_copy:
            primary_album_id = importer_album_id(connection, item, index=0)
            repository.repository_insert_asset_file(
                connection,
                AssetFile(
                    asset_id=existing.asset_id,
                    path=placed_relative,
                    album_id=primary_album_id,
                    link_mode=placed.link_mode,
                    location=FileLocation.PHOTOS,
                ),
            )
            if primary_album_id is not None:
                repository.repository_link_asset_album(
                    connection, existing.asset_id, primary_album_id
                )
        repository.repository_record_source(
            connection, existing.asset_id, source.device_udid(), item
        )
        importer_sync_albums(connection, paths, existing.asset_id, item, link_mode)
        importer_update_sidecar(connection, paths, existing.asset_id, journal)
        result.seen_sources.append((item.phone_path, existing.asset_id))
        result.duplicate_count += 1
        result.skipped_count += 1
        return

    exif_metadata = exif.exif_read_metadata(placed.path)
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
        is_offloaded_preview=item.is_offloaded_preview,
        offloaded_original_path=item.offloaded_original_path,
        # The phone database is the primary GPS source; a file's own EXIF is
        # only consulted when the phone had no location for this item.
        latitude=item.latitude if item.latitude is not None else exif_metadata.latitude,
        longitude=item.longitude if item.longitude is not None else exif_metadata.longitude,
        camera_model=exif_metadata.camera_model,
        lens_model=exif_metadata.lens_model,
        iso=exif_metadata.iso,
        aperture=exif_metadata.aperture,
        focal_length_mm=exif_metadata.focal_length_mm,
    )
    asset_id = repository.repository_insert_asset(connection, asset)
    repository.repository_record_source(connection, asset_id, source.device_udid(), item)

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

    importer_update_sidecar(connection, paths, asset_id, journal)
    result.added_count += 1
    result.added_hashes.append(placed.sha256)
    result.seen_sources.append((item.phone_path, asset_id))


def importer_upgrade_offloaded_preview(
    connection: sqlite3.Connection,
    paths: ArchivePaths,
    source: MediaSource,
    asset_id: int,
    item: PhoneItem,
    placed: archive_layout.PlacedFile,
    link_mode: str,
    result: ImportResult,
) -> None:
    """Replace a previously-imported offloaded preview with its real original.

    connection: an open catalog connection.
    paths: resolved archive paths.
    source: the media source being imported from.
    asset_id: the existing preview asset to upgrade in place.
    item: the real, full-resolution phone item just downloaded.
    placed: the already-stored full-resolution file.
    link_mode: ``copy`` or ``hardlink`` for extra album copies.
    result: the running result summary, updated in place.
    Returns None. Deletes the old low-resolution preview copy (never valuable
    on its own) and rewrites the asset's content/phone identity, so the
    catalog ends up with exactly one entry for the photo instead of a
    duplicate, and every previously-linked album/mark keeps pointing at the
    same asset id.
    """
    for stored in repository.repository_list_asset_files(connection, asset_id):
        file_operations_path(paths, stored.path).unlink(missing_ok=True)
        repository.repository_delete_asset_file(connection, stored.file_id)

    exif_metadata = exif.exif_read_metadata(placed.path)
    repository.repository_upgrade_offloaded_asset(
        connection,
        asset_id,
        sha256=placed.sha256,
        size=placed.size,
        original_name=item.original_name,
        media_type=item.media_type,
        phone_path=item.phone_path,
        phone_size=item.size,
        phone_modified_at=item.modified_at,
        verified_at=importer_now(),
        latitude=item.latitude if item.latitude is not None else exif_metadata.latitude,
        longitude=item.longitude if item.longitude is not None else exif_metadata.longitude,
        camera_model=exif_metadata.camera_model,
        lens_model=exif_metadata.lens_model,
        iso=exif_metadata.iso,
        aperture=exif_metadata.aperture,
        focal_length_mm=exif_metadata.focal_length_mm,
    )
    repository.repository_record_source(connection, asset_id, source.device_udid(), item)

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

    result.upgraded_count += 1
    result.added_hashes.append(placed.sha256)
    result.seen_sources.append((item.phone_path, asset_id))


def importer_has_valid_copy(
    connection: sqlite3.Connection, paths: ArchivePaths, asset: Asset
) -> bool:
    """Require a present, byte-valid archive copy before trusting an import shortcut."""
    if asset.asset_id is None:
        return False
    for stored in repository.repository_list_asset_files(connection, asset.asset_id):
        target = file_operations_path(paths, stored.path)
        if target.is_file() and target.stat().st_size == asset.size:
            if hashing.hashing_sha256_file(target) == asset.sha256:
                return True
    return False


def importer_backfill_metadata(
    connection: sqlite3.Connection,
    paths: ArchivePaths,
    asset: Asset,
    item: PhoneItem,
    file_path: Path | None = None,
) -> None:
    """Fill in GPS/camera facts for an asset archived before this data existed.

    connection: an open catalog connection.
    paths: resolved archive paths.
    asset: the already-archived asset, as read from the catalog.
    item: the just-enumerated phone item standing in for the same content.
    file_path: an already-open copy of the file to read EXIF from, when one
        is available (e.g. a freshly downloaded duplicate, before it is
        unlinked). When None, the asset's first recorded archive copy is
        used instead, so a purely local repair never re-contacts the phone.
    Returns None. A no-op whenever the asset already has every field this
    import could discover, so repeat imports cost nothing once backfilled.
    Existing values are never overwritten, only missing ones are filled in.
    """
    if asset.asset_id is None:
        return
    latitude, longitude = asset.latitude, asset.longitude
    camera_model = asset.camera_model
    lens_model = asset.lens_model
    iso = asset.iso
    aperture = asset.aperture
    focal_length_mm = asset.focal_length_mm
    needs_update = False

    if latitude is None and item.latitude is not None:
        latitude, longitude = item.latitude, item.longitude
        needs_update = True

    if camera_model is None:
        target = file_path
        if target is None:
            stored_files = repository.repository_list_asset_files(connection, asset.asset_id)
            stored = next(iter(stored_files), None)
            target = file_operations_path(paths, stored.path) if stored is not None else None
        if target is not None and target.is_file():
            metadata = exif.exif_read_metadata(target)
            if any(
                value is not None
                for value in (
                    metadata.camera_model,
                    metadata.lens_model,
                    metadata.iso,
                    metadata.aperture,
                    metadata.focal_length_mm,
                )
            ):
                camera_model = metadata.camera_model
                lens_model = metadata.lens_model
                iso = metadata.iso
                aperture = metadata.aperture
                focal_length_mm = metadata.focal_length_mm
                needs_update = True
            if latitude is None and metadata.latitude is not None:
                latitude, longitude = metadata.latitude, metadata.longitude
                needs_update = True

    if needs_update:
        repository.repository_backfill_asset_metadata(
            connection,
            asset.asset_id,
            latitude=latitude,
            longitude=longitude,
            camera_model=camera_model,
            lens_model=lens_model,
            iso=iso,
            aperture=aperture,
            focal_length_mm=focal_length_mm,
        )


def importer_update_sidecar(
    connection: sqlite3.Connection,
    paths: ArchivePaths,
    asset_id: int,
    journal: ImportJournal | None,
) -> None:
    """Write accurate catalog-derived metadata, protecting the prior sidecar."""
    data = sidecar_from_catalog(connection, asset_id)
    if journal is not None:
        journal.protect_sidecar(data.sha256)
    sidecar_write(paths.sidecars_dir, data)


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
    """Make an asset's archived copies match its current phone album membership.

    connection: an open catalog connection.
    paths: resolved archive paths.
    asset_id: the already-archived asset.
    item: the phone item carrying current album membership.
    link_mode: ``copy`` or ``hardlink``.
    Returns None. Adds a copy for every album newly discovered on the phone
    (a photo can belong to several albums at once, and each keeps its own
    copy), and removes any existing copy for an album the asset no longer
    belongs to there (including a stale ``_Unsorted`` copy once a photo gains
    its first album), so moving a photo between albums on the phone never
    leaves a duplicate behind. Recycle-bin copies are a separate, user-driven
    lifecycle and are never touched here. New copies are always created
    before any stale ones are removed, so a crash mid-reconciliation can
    never drop the asset below one valid, on-disk copy.
    """
    existing_files = [
        stored
        for stored in repository.repository_list_asset_files(connection, asset_id)
        if stored.location == FileLocation.PHOTOS
    ]
    if not existing_files:
        return
    existing_album_ids = {stored.album_id for stored in existing_files}
    asset = repository.repository_get_asset(connection, asset_id)
    source_path: Path | None = None
    for stored in existing_files:
        candidate = file_operations_path(paths, stored.path)
        if candidate.is_file() and asset is not None:
            if hashing.hashing_sha256_file(candidate) == asset.sha256:
                source_path = candidate
                break
    if source_path is None:
        raise OSError(f"no valid archive copy for album reconciliation: {asset_id}")

    def place_copy(target_dir: Path, album_id: int | None) -> None:
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
        if album_id is not None:
            repository.repository_link_asset_album(connection, asset_id, album_id)

    desired_album_ids: set[int | None] = set()
    for index in range(len(item.album_names)):
        album_id = importer_album_id(connection, item, index)
        desired_album_ids.add(album_id)
        if album_id is None or album_id in existing_album_ids:
            continue
        target_dir = archive_layout.archive_layout_album_dir(paths, item.album_names[index])
        place_copy(target_dir, album_id)
        existing_album_ids.add(album_id)

    if not item.album_names:
        # No album membership at all: the asset belongs in _Unsorted. Give it
        # a copy there if it does not already have one.
        desired_album_ids.add(None)
        if None not in existing_album_ids:
            place_copy(archive_layout.archive_layout_unsorted_dir(paths, item.captured_at), None)

    for stored in existing_files:
        if stored.album_id in desired_album_ids:
            continue
        # This copy's album is no longer part of the phone's current
        # membership (or the asset gained its first real album, retiring its
        # old _Unsorted placeholder): remove it now that a desired copy is
        # already guaranteed to exist.
        file_operations_path(paths, stored.path).unlink(missing_ok=True)
        repository.repository_delete_asset_file(connection, stored.file_id)
        if stored.album_id is not None:
            repository.repository_unlink_asset_album(connection, asset_id, stored.album_id)
